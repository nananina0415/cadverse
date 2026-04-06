use std::sync::Arc;
use p2p_core::{JoinForm, NetId, Password, PeerInfo, PeerType};

const NET_ID: &str = "1234";
const PASSWORD: &str = "1234";
const UDP_PORT: u16 = 44444;

#[unsafe(no_mangle)]
fn android_main(_app: android_activity::AndroidApp) {
    android_logger::init_once(
        android_logger::Config::default().with_max_level(log::LevelFilter::Info),
    );

    let name = {
        let t = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .subsec_millis();
        format!("{:03}", t % 1000)
    };

    log::info!("Starting as ArClient, name={name}");

    let rt = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => { log::error!("tokio error: {e}"); return; }
    };

    rt.block_on(run(name));
}

async fn run(name: String) {
    log::info!("[{}] Joining network...", name);

    let net = match p2p_core::join_p2p_net(JoinForm {
        net_id: NetId(NET_ID.to_string()),
        pw: Password(PASSWORD.to_string()),
        my_name: name.clone(),
        peer_type: PeerType::ArClient { udp_port: UDP_PORT },
    }).await {
        Ok(net) => { log::info!("[{}] Joined", name); Arc::new(net) }
        Err(e) => { log::error!("[{}] Join failed: {e}", name); return; }
    };

    let server_names = ["A", "B"];
    let mut target_idx: usize = 0;

    loop {
        let peers = net.get_peers();

        let servers: Vec<Option<PeerInfo>> = server_names.iter().map(|n| {
            peers.iter().find(|p| {
                p.name == *n && matches!(p.peer_type, PeerType::SimServer { .. })
            }).cloned()
        }).collect();

        // 현재 타겟 결정
        let peer = if servers[target_idx].is_some() {
            servers[target_idx].clone().unwrap()
        } else if servers[1 - target_idx].is_some() {
            target_idx = 1 - target_idx;
            servers[target_idx].clone().unwrap()
        } else {
            log::info!("[{}] No servers found, retry in 1s", name);
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            continue;
        };

        log::info!("[{}] Target: server {}", name, peer.name);

        // HTTP 요청
        match net.request_http(peer.addr.clone(), "/").await {
            Ok(body) => log::info!("[{}][http] <- {}: {}", name, peer.name, String::from_utf8_lossy(&body)),
            Err(e)   => log::warn!("[{}][http] {} error: {e}", name, peer.name),
        }

        // 1초마다 UDP x5 (총 5초)
        for i in 0..5u32 {
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            let msg = format!("hi from {name} #{i}");
            match net.connect_udp(peer.addr.clone()).await {
                Ok(conn) => {
                    log::info!("[{}][udp] -> {}: {msg}", name, peer.name);
                    if let Err(e) = conn.send(msg.as_bytes()).await {
                        log::warn!("[{}][udp] send error: {e}", name);
                    } else {
                        match conn.recv().await {
                            Ok(b)  => log::info!("[{}][udp] <- {}: {}", name, peer.name, String::from_utf8_lossy(&b)),
                            Err(e) => log::warn!("[{}][udp] recv error: {e}", name),
                        }
                    }
                }
                Err(e) => log::warn!("[{}][udp] connect error: {e}", name),
            }
        }

        // 5초 후 서버 교체
        target_idx = 1 - target_idx;
    }
}
