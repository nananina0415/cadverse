use std::{
    fs,
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex},
};

use anyhow::{anyhow, Context};
use p2p_core::{PeerInfo, PeerType, NodeAddr, JoinForm, NetId, Password};
use serde::{Deserialize, Serialize};

use crate::utils::{TripleBufWriter, TripleBufReader};
use crate::sim::{UserIn, SimOut};

pub struct NetSetting {
    pub net_id: String,
    pub password: String,
    pub name: String,
    pub peer_type: PeerType,
}

#[derive(Serialize, Deserialize)]
struct ModelManifest {
    files: Vec<String>,
}

fn collect_model_files(base: &Path, dir: &Path, out: &mut Vec<String>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_dir() {
            collect_model_files(base, &path, out)?;
        } else if path.is_file() {
            let rel = path
                .strip_prefix(base)
                .unwrap_or(&path)
                .to_string_lossy()
                .replace('\\', "/");

            out.push(rel);
        }
    }

    Ok(())
}

fn build_model_manifest(folder: &Path) -> ModelManifest {
    let mut files = Vec::new();

    if let Err(e) = collect_model_files(folder, folder, &mut files) {
        eprintln!("[manifest] 파일 목록 생성 실패: {e}");
    }

    ModelManifest { files }
}

fn is_safe_relative_path(path: &str) -> bool {
    let p = Path::new(path);

    !p.is_absolute()
        && p.components().all(|component| {
            matches!(component, Component::Normal(_))
        })
}

fn sanitize_folder_name(name: &str) -> String {
    let s: String = name
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
                c
            } else {
                '_'
            }
        })
        .collect();

    if s.is_empty() {
        "remote_model".to_string()
    } else {
        s
    }
}

pub struct NetThread {
    async_rt: tokio::runtime::Runtime,
    net: Arc<p2p_core::P2PNet>,
    my_peer_type: Arc<Mutex<PeerType>>,
    ar_clients: Arc<Mutex<Vec<p2p_core::Connection>>>,
}

impl NetThread {
    pub fn new(setting: &NetSetting, userin_w: TripleBufWriter<Vec<UserIn>>, simout_r: TripleBufReader<SimOut>) -> NetThread {
        let rt = tokio::runtime::Runtime::new()
            .expect("tokio 런타임 생성 실패");

        let net = Arc::new(rt.block_on(
            p2p_core::join_p2p_net(JoinForm {
                net_id:     NetId(setting.net_id.clone()),
                pw:         Password(setting.password.clone()),
                my_name:    setting.name.clone(),
                peer_type:  setting.peer_type.clone(),
            }
        )).expect("p2p 네트워크 참가 실패"));

        let my_peer_type = Arc::new(Mutex::new(setting.peer_type.clone()));
        let ar_clients: Arc<Mutex<Vec<p2p_core::Connection>>> = Arc::new(Mutex::new(Vec::new()));
        let (userin_tx, mut userin_rx) = tokio::sync::mpsc::channel::<UserIn>(32);

        // AR 클라이언트 연결 수락 → 연결별 수신 태스크 스폰 → 채널로 전달
        {
            let net = net.clone();
            let ar_clients = ar_clients.clone();
            rt.spawn(async move {
                loop {
                    let Some(conn) = net.accept_data().await else { break };
                    ar_clients.lock().expect("ar_clients mutex poisoned").push(conn.clone());
                    let userin_tx = userin_tx.clone();
                    tokio::spawn(async move {
                        loop {
                            let Ok(data) = conn.recv().await else { break };
                            if let Ok(msg) = serde_json::from_slice(&data) {
                                let _ = userin_tx.send(msg).await;
                            }
                        }
                    });
                }
            });
        }

        // 채널에서 수신 → 단일 writer로 UserIn 버퍼에 쓰기
        {
            let mut userin_w = userin_w;
            rt.spawn(async move {
                while let Some(msg) = userin_rx.recv().await {
                    userin_w.write().push(msg);
                }
            });
        }

        // SimOut 버퍼 읽기 → 모든 AR 클라이언트로 브로드캐스트
        {
            let ar_clients = ar_clients.clone();
            rt.spawn(async move {
                loop {
                    let data = serde_json::to_vec(simout_r.read()).expect("SimOut 직렬화 실패");
                    let clients = ar_clients.lock().expect("ar_clients mutex poisoned").clone();
                    let mut dead = vec![];
                    for (i, conn) in clients.iter().enumerate() {
                        if conn.send(&data).await.is_err() {
                            dead.push(i);
                        }
                    }
                    if !dead.is_empty() {
                        let mut clients = ar_clients.lock().expect("ar_clients mutex poisoned");
                        for i in dead.into_iter().rev() {
                            clients.remove(i);
                        }
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(16)).await;
                }
            });
        }

        NetThread { async_rt: rt, net, my_peer_type, ar_clients }
    }

    pub fn peer_list(&self) -> Vec<PeerInfo> {
        self.net.get_peers()
    }

    pub fn my_peer_type(&self) -> PeerType {
        self.my_peer_type
            .lock()
            .expect("my_peer_type mutex poisoned")
            .clone()
    }

    pub fn notice_sim_online(&self, folder: std::path::PathBuf) -> anyhow::Result<()> {
        let net = self.net.clone();

        self.async_rt.spawn(async move {
            loop {
                let Some(conn) = net.accept_file_conn().await else { break };
                println!("[file] connection accepted");
                let folder = folder.clone();

                tokio::spawn(async move {
                    if let Err(e) = serve_file(conn, &folder).await {
                        println!("[file] serve error: {e}");
                    }
                });
            }
        });

        self.async_rt.block_on(self.net.notice_sim_online())?;
        let mut t = self.my_peer_type.lock().expect("my_peer_type mutex poisoned");
        *t = PeerType::SimServer;
        Ok(())
    }

    pub fn notice_sim_offline(&self) -> anyhow::Result<()> {
        self.async_rt.block_on(self.net.notice_sim_offline())?;
        let mut t = self.my_peer_type.lock().expect("my_peer_type mutex poisoned");
        *t = PeerType::MidServer;
        Ok(())
    }

    pub fn sim_info(&self, name: &str) -> Option<NodeAddr> {
        self.net.get_peers().into_iter()
            .find(|p| p.name == name)
            .and_then(|p| match p.peer_type {
                PeerType::SimServer => Some(p.addr),
                _ => None,
            })
    }

    pub fn import_remote_model(&self, name: &str, import_root: PathBuf) -> anyhow::Result<PathBuf> {
        let peer = self.net
            .find_sim_server_by_name(name)
            .ok_or_else(|| anyhow!("그룹원이 존재하지 않거나 시뮬레이션이 실행 중이지 않습니다."))?;

        let safe_name = sanitize_folder_name(name);
        let target_dir = import_root.join(&safe_name);
        let tmp_dir = import_root.join(format!(".{}_tmp", safe_name));

        let net = self.net.clone();

        self.async_rt.block_on(async move {
            println!("원격 모델 파일 목록을 요청합니다. 대상: {}", peer.name);

            let manifest_bytes = match net
                .request_file(peer.addr.clone(), "/__cadverse_manifest.json")
                .await
            {
                Ok(bytes) => bytes,
                Err(_) => {
                    anyhow::bail!("대상의 시뮬레이션이 종료된 상태입니다");
                }
            };

            let manifest: ModelManifest = serde_json::from_slice(&manifest_bytes)
                .context("원격 모델 파일 목록 파싱 실패")?;

            if manifest.files.is_empty() {
                anyhow::bail!("대상의 시뮬레이션이 종료된 상태입니다");
            }

            println!("원격 모델 파일 {}개를 불러옵니다.", manifest.files.len());

            if tmp_dir.exists() {
                fs::remove_dir_all(&tmp_dir)
                    .with_context(|| format!("임시 폴더 삭제 실패: {}", tmp_dir.display()))?;
            }

            fs::create_dir_all(&tmp_dir)
                .with_context(|| format!("임시 폴더 생성 실패: {}", tmp_dir.display()))?;

            for rel in manifest.files {
                if !is_safe_relative_path(&rel) {
                    eprintln!("[remote import] 안전하지 않은 경로 생략: {rel}");
                    continue;
                }

                let request_path = format!("/{}", rel);

                let data = net
                    .request_file(peer.addr.clone(), &request_path)
                    .await
                    .with_context(|| format!("대상의 시뮬레이션이 종료된 상태입니다: {rel}"))?;

                if data.is_empty() {
                    anyhow::bail!("대상의 시뮬레이션이 종료된 상태입니다 또는 파일 데이터가 비어 있습니다: {rel}");
                }

                let out_path = tmp_dir.join(&rel);

                if let Some(parent) = out_path.parent() {
                    fs::create_dir_all(parent)
                        .with_context(|| format!("폴더 생성 실패: {}", parent.display()))?;
                }

                fs::write(&out_path, data)
                    .with_context(|| format!("파일 저장 실패: {}", out_path.display()))?;
            }

            if target_dir.exists() {
                fs::remove_dir_all(&target_dir)
                    .with_context(|| format!("기존 모델 폴더 삭제 실패: {}", target_dir.display()))?;
            }

            fs::rename(&tmp_dir, &target_dir)
                .with_context(|| {
                    format!(
                        "임시 폴더를 모델 폴더로 변경 실패: {} -> {}",
                        tmp_dir.display(),
                        target_dir.display()
                    )
                })?;

            Ok::<PathBuf, anyhow::Error>(target_dir)
        })
    }
}

async fn serve_file(conn: p2p_core::RawConn, folder: &std::path::Path) -> anyhow::Result<()> {
    let mut recv = conn.accept_uni().await?;
    let path_bytes = recv.read_to_end(1024).await?;
    let path = String::from_utf8(path_bytes)?;
    let file_path = if path == "/local_sim_qr.txt" {
        crate::qr_path()
    } else {
        folder.join(path.trim_start_matches('/'))
    };
    let data = if path == "/__cadverse_manifest.json" {
        let manifest = build_model_manifest(folder);
        serde_json::to_vec(&manifest).unwrap_or_default()
    } else {
        std::fs::read(&file_path).unwrap_or_default()
    };
    println!("[FILE] {path} ({} bytes)", data.len());
    let mut send = conn.open_uni().await?;
    send.write_all(&data).await?;
    send.finish()?;
    // 클라이언트가 데이터를 다 읽고 연결을 닫을 때까지 대기
    // (conn을 즉시 드롭하면 CONNECTION_CLOSE가 먼저 도착해 클라이언트 read 실패)
    let _ = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        conn.accept_uni(),
    ).await;
    println!("[FILE] done: {path}");
    Ok(())
}
