use std::sync::{Arc, Mutex};
use p2p_core::{PeerInfo, PeerType, NodeAddr, JoinForm, NetId, Password};
use crate::utils::{TripleBufWriter, TripleBufReader};
use crate::sim::{UserIn, SimOut};

pub struct NetSetting {
    pub net_id: String,
    pub password: String,
    pub name: String,
    pub peer_type: PeerType,
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
                let Some(conn) = net.accept_http_conn().await else { break };
                let folder = folder.clone();
                tokio::spawn(async move {
                    let _ = p2p_core::serve_h3_response(conn, |path| {
                        let file_path = folder.join(path.trim_start_matches('/'));
                        std::fs::read(&file_path).unwrap_or_default().into()
                    }).await;
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
}
