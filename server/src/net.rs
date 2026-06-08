use std::{
    fs,
    path::{Component, Path, PathBuf},
    sync::{Arc, Mutex, RwLock},
};

use anyhow::{anyhow, Context};
use p2p_core::{PeerInfo, PeerType, NodeAddr, JoinForm, NetId, Password};
use serde::{Deserialize, Serialize};

use crate::utils::{TripleBufWriter, TripleBufReader};
use crate::sim::{UserIn, SimFrame};

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

    let _ = collect_model_files(folder, folder, &mut files);

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
    // 사용자명에 한글/일본어/중국어 등 unicode 문자가 들어와도 폴더명으로 보존한다.
    // 차단 대상은 OS 파일시스템에서 위험한 문자(Windows 예약 + 제어문자)만.
    let s: String = name
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '_' || c == '-' { c }
            else if c.is_control() { '_' }
            else if matches!(c, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*') { '_' }
            else if c.is_alphabetic() || c.is_numeric() { c }   // 한글 등 통과
            else { '_' }
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
    // 매 file conn마다 serve_file에 넘길 폴더. notice_sim_online이 갱신.
    serve_folder: Arc<RwLock<Option<PathBuf>>>,
    // 현재 sim의 metadata.json SHA256(앞 16자). broadcast가 매 State frame에 함께 송신해
    // 클라가 model 변경을 자체 detect할 수 있게 한다.
    model_hash: Arc<RwLock<String>>,
}

impl Drop for NetThread {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(crate::qr_path());
    }
}

impl NetThread {
    pub fn new(
        setting: &NetSetting,
        userin_w: TripleBufWriter<Vec<UserIn>>,
        mut simout_r: triple_buffer::Output<SimFrame>,
        log: std::sync::mpsc::Sender<String>,
    ) -> anyhow::Result<NetThread> {
        let rt = tokio::runtime::Runtime::new()
            .expect("tokio 런타임 생성 실패");

        let net = Arc::new(rt.block_on(
            p2p_core::join_p2p_net(JoinForm {
                net_id:     NetId(setting.net_id.clone()),
                pw:         Password(setting.password.clone()),
                my_name:    setting.name.clone(),
                peer_type:  setting.peer_type.clone(),
            }, &log)
        )?);

        let my_peer_type = Arc::new(Mutex::new(setting.peer_type.clone()));
        let ar_clients: Arc<Mutex<Vec<p2p_core::Connection>>> = Arc::new(Mutex::new(Vec::new()));
        let (userin_tx, mut userin_rx) = tokio::sync::mpsc::channel::<UserIn>(32);

        // AR 클라이언트 연결 수락 → 연결별 수신 태스크 스폰 → 채널로 전달
        // 서버 username과 동일한 클라이언트의 입력만 시뮬에 forward한다.
        {
            let net = net.clone();
            let ar_clients = ar_clients.clone();
            let my_name = setting.name.clone();
            rt.spawn(async move {
                loop {
                    let Some(conn) = net.accept_data().await else {
                        eprintln!("[net] accept_data 종료");
                        break;
                    };
                    ar_clients.lock().expect("ar_clients mutex poisoned").push(conn.clone());
                    let userin_tx = userin_tx.clone();
                    let net = net.clone();
                    let my_name = my_name.clone();
                    let remote_id = conn.remote_id();
                    tokio::spawn(async move {
                        // peer 등록은 비동기이므로 짧게 retry 하며 name lookup.
                        let mut peer_name: Option<String> = None;
                        for _ in 0..10 {
                            if let Some(p) = net.get_peers().into_iter()
                                .find(|p| p.addr.id == remote_id)
                            {
                                peer_name = Some(p.name);
                                break;
                            }
                            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                        }

                        let Some(peer_name) = peer_name else {
                            eprintln!("[net] AR 클라 peer 조회 실패 → 입력 무시: id={remote_id:?}");
                            return;
                        };

                        if peer_name != my_name {
                            eprintln!(
                                "[net] AR 클라 username 불일치 → 입력 무시: server={my_name} client={peer_name}"
                            );
                            return;
                        }

                        eprintln!("[net] AR 클라 입력 수용 — username={peer_name}");

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
                eprintln!("[net] userin 채널 종료");
            });
        }

        // SimFrame 버퍼 읽기 → 모든 AR 클라이언트로 브로드캐스트
        let model_hash: Arc<RwLock<String>> = Arc::new(RwLock::new(String::new()));
        {
            let ar_clients = ar_clients.clone();
            let model_hash = model_hash.clone();
            rt.spawn(async move {
                let mut reload_sent = false;
                loop {
                    let data = match simout_r.read() {
                        SimFrame::State(out) => {
                            reload_sent = false;
                            // SimOut을 Value로 변환 후 metadataHash 필드 추가 (클라가 model 식별/캐시 키로 사용)
                            let mut v = match serde_json::to_value(out) {
                                Ok(v) => v,
                                Err(e) => {
                                    eprintln!("[broadcast] 직렬화 실패: {e}");
                                    tokio::time::sleep(std::time::Duration::from_millis(16)).await;
                                    continue;
                                }
                            };
                            if let Some(obj) = v.as_object_mut() {
                                let h = model_hash.read().expect("model_hash poisoned").clone();
                                obj.insert("metadataHash".to_string(), serde_json::Value::String(h));
                            }
                            match serde_json::to_vec(&v) {
                                Ok(d) => d,
                                Err(e) => {
                                    eprintln!("[broadcast] 직렬화 실패: {e}");
                                    tokio::time::sleep(std::time::Duration::from_millis(16)).await;
                                    continue;
                                }
                            }
                        }
                        SimFrame::Reload => {
                            if reload_sent {
                                tokio::time::sleep(std::time::Duration::from_millis(16)).await;
                                continue;
                            }
                            reload_sent = true;
                            let n = ar_clients.lock().expect("ar_clients mutex poisoned").len();
                            eprintln!("[broadcast] Reload → {n}개 클라");
                            br#"{"type":"reload"}"#.to_vec()
                        }
                    };
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
                eprintln!("[net] broadcast 루프 종료");
            });
        }

        if let Some(my_info) = net.get_peers().into_iter().find(|p| p.name == setting.name) {
            crate::save_local_sim_qr_txt(&my_info.addr);
        }

        // file conn accept-loop을 단 한 번만 spawn. 매 conn마다 serve_folder를 read해
        // 최신 폴더로 serve_file을 호출 → notice_sim_online 중복 호출에도 loop이 누적되지 않는다.
        let serve_folder: Arc<RwLock<Option<PathBuf>>> = Arc::new(RwLock::new(None));
        {
            let net = net.clone();
            let serve_folder = serve_folder.clone();
            rt.spawn(async move {
                loop {
                    let Some(conn) = net.accept_file_conn().await else {
                        eprintln!("[net] accept_file_conn 종료");
                        break;
                    };
                    let folder = serve_folder.read().expect("serve_folder poisoned").clone();
                    match folder {
                        Some(f) => {
                            tokio::spawn(async move {
                                if let Err(e) = serve_file(conn, &f).await {
                                    eprintln!("[net] serve_file 오류: {e}");
                                }
                            });
                        }
                        None => {
                            eprintln!("[net] file conn 도착했으나 serve_folder 미설정 → 무시");
                        }
                    }
                }
            });
        }

        Ok(NetThread { async_rt: rt, net, my_peer_type, ar_clients, serve_folder, model_hash })
    }

    /// 현재 sim의 metadata.json 해시(16자 hex)를 갱신. broadcast가 다음 state frame부터 이 hash를 함께 송신.
    pub fn set_model_hash(&self, hash: String) {
        *self.model_hash.write().expect("model_hash poisoned") = hash;
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
        // accept-loop은 new()에서 단 한 번 spawn됨. 여기서는 서비스할 폴더만 갱신.
        *self.serve_folder.write().expect("serve_folder poisoned") = Some(folder);

        self.async_rt.block_on(self.net.notice_sim_online())?;
        crate::save_local_sim_qr_txt(&self.net.my_addr());
        let mut t = self.my_peer_type.lock().expect("my_peer_type mutex poisoned");
        *t = PeerType::SimServer;
        Ok(())
    }

    pub fn notice_sim_offline(&self) -> anyhow::Result<()> {
        *self.serve_folder.write().expect("serve_folder poisoned") = None;
        self.async_rt.block_on(self.net.notice_sim_offline())?;
        let mut t = self.my_peer_type.lock().expect("my_peer_type mutex poisoned");
        *t = PeerType::MidServer;
        Ok(())
    }

    pub fn my_node_id(&self) -> Vec<u8> {
        self.net.my_addr().id.as_bytes().to_vec()
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

            if tmp_dir.exists() {
                fs::remove_dir_all(&tmp_dir)
                    .with_context(|| format!("임시 폴더 삭제 실패: {}", tmp_dir.display()))?;
            }

            fs::create_dir_all(&tmp_dir)
                .with_context(|| format!("임시 폴더 생성 실패: {}", tmp_dir.display()))?;

            for rel in manifest.files {
                if !is_safe_relative_path(&rel) { continue; }

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
    eprintln!("[serve_file] 요청: {path}");
    let file_path = if path == "/local_sim_qr.txt" {
        crate::qr_path()
    } else {
        folder.join(path.trim_start_matches('/'))
    };
    let data = if path == "/__cadverse_manifest.json" {
        let manifest = build_model_manifest(folder);
        eprintln!("[serve_file] manifest: {} 파일", manifest.files.len());
        serde_json::to_vec(&manifest).unwrap_or_default()
    } else {
        let d = std::fs::read(&file_path).unwrap_or_default();
        eprintln!("[serve_file] 응답: {} ({} bytes)", file_path.display(), d.len());
        d
    };
    let mut send = conn.open_uni().await?;
    send.write_all(&data).await?;
    send.finish()?;
    // conn을 즉시 드롭하면 CONNECTION_CLOSE가 먼저 도착해 클라이언트 read 실패
    let _ = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        conn.accept_uni(),
    ).await;
    Ok(())
}
