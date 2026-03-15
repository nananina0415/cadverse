mod error;

pub use error::S2sError;
use mdns_sd::{ServiceDaemon, ServiceEvent, ServiceInfo};
use std::{
    collections::HashMap,
    net::{Ipv4Addr, UdpSocket},
    sync::{Arc, RwLock},
    thread::JoinHandle,
    time::{Duration, Instant},
};

const MDNS_SUFFIX_SERV_LOCAL: &str = "_cadverse._tcp.local.";
const HEALTH_PORT: u16 = 50507;

#[derive(Debug, Clone)]
pub struct ServerName(String);

impl ServerName {
    pub fn new(name: &str) -> Result<Self, S2sError> {
        if name.as_bytes().len() > 63 {
            return Err(S2sError::NameTooLong(name.as_bytes().len()));
        }
        if name.chars().any(|c| c.is_control()) {
            return Err(S2sError::NameHasControlChar);
        }
        Ok(Self(name.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone)]
pub struct IpPort {
    pub name: String, // 인스턴스명 (사용자가 지은 서버 이름)
    pub ip: Ipv4Addr,
    pub port: u16,
    pub health_port: u16,
    pub last_seen: Instant,
}

pub struct ServerToServer {
    my_name: ServerName,
    mdns: ServiceDaemon,
    peers: Arc<RwLock<HashMap<String, IpPort>>>, // key: fullname
    browse_thread: Option<JoinHandle<()>>,
    health_send_thread: Option<JoinHandle<()>>, // heartbeat 송신 + 타임아웃 제거
    health_recv_thread: Option<JoinHandle<()>>, // heartbeat 수신
}

impl ServerToServer {
    /// 생성 + mDNS 광고 + 백그라운드 탐색 시작
    pub fn new(my_name: ServerName, port: u16) -> Result<Self, S2sError> {
        let mdns = ServiceDaemon::new()?;
        let peers = Arc::new(RwLock::new(HashMap::new()));

        // 형식적으로 넘겨야하는 안 쓰이는 값
        let host_name = format!("{}.local.", my_name.as_str());
        let props = [("health_port", HEALTH_PORT.to_string())];

        let service = ServiceInfo::new(
            MDNS_SUFFIX_SERV_LOCAL,
            my_name.as_str(),
            &host_name,
            "", // IP 자동 감지
            port,
            &props[..],
        )?
        .enable_addr_auto(); // 호스트 IP 자동

        mdns.register(service)?;

        // 피어 탐색 백그라운드 스레드
        let receiver = mdns.browse(MDNS_SUFFIX_SERV_LOCAL)?;
        let peers_bg = Arc::clone(&peers);
        let my_fullname = format!("{}.{}", my_name.as_str(), MDNS_SUFFIX_SERV_LOCAL);

        let handle = std::thread::spawn(move || {
            while let Ok(event) = receiver.recv() {
                Self::handle_mdns_event(event, &my_fullname, &peers_bg);
            }
        });

        let peers_send = Arc::clone(&peers);
        let health_send_handle = std::thread::spawn(move || {
            let socket = match UdpSocket::bind("0.0.0.0:0") {
                Ok(s) => s,
                Err(_) => return,
            };
            loop {
                std::thread::sleep(Duration::from_secs(1));

                // heartbeat 송신
                peers_send.read().unwrap().values().for_each(|server| {
                    socket.send_to(b"hb", (server.ip, server.health_port)).ok();
                });

                // 타임아웃된 피어 제거
                peers_send
                    .write()
                    .unwrap()
                    .retain(|_, peer| peer.last_seen.elapsed() < Duration::from_secs(5));
            }
        });

        let peers_recv = Arc::clone(&peers);
        let health_recv_handle = std::thread::spawn(move || {
            let socket = match UdpSocket::bind(format!("0.0.0.0:{HEALTH_PORT}")) {
                Ok(s) => s,
                Err(_) => return,
            };
            let mut buf = [0; 32];
            loop {
                let Ok((_, addr)) = socket.recv_from(&mut buf) else {
                    continue;
                };
                let addr_v4 = match addr.ip() {
                    std::net::IpAddr::V4(v4) => v4,
                    _ => continue,
                };
                peers_recv
                    .write()
                    .unwrap()
                    .values_mut()
                    .filter(|peer| peer.ip == addr_v4)
                    .for_each(|peer| peer.last_seen = Instant::now());
            }
        });

        Ok(Self {
            my_name,
            mdns,
            peers,
            browse_thread: Some(handle),
            health_send_thread: Some(health_send_handle),
            health_recv_thread: Some(health_recv_handle),
        })
    }

    fn handle_mdns_event(
        event: ServiceEvent,
        my_fullname: &str,
        peers: &RwLock<HashMap<String, IpPort>>,
    ) {
        match event {
            ServiceEvent::ServiceResolved(info) => {
                if info.fullname == my_fullname {
                    return;
                }

                let Some(ip) = info.get_addresses_v4().iter().next().copied() else {
                    return;
                };

                let peer = IpPort {
                    name: info
                        .fullname
                        .split('.')
                        .next()
                        .unwrap_or("unknown")
                        .to_string(),
                    ip,
                    port: info.port,
                    health_port: HEALTH_PORT,
                    last_seen: Instant::now(),
                };

                peers.write().unwrap().insert(info.fullname, peer);
            }

            ServiceEvent::ServiceRemoved(_, fullname) => {
                peers.write().unwrap().remove(&fullname);
            }

            _ => {}
        }
    }

    /// 현재 발견된 피어 목록 스냅샷
    pub fn get_server_list(&self) -> Vec<IpPort> {
        self.peers.read().unwrap().values().cloned().collect()
    }

    /// 앱 종료 시 호출
    pub fn shutdown(mut self) -> Result<(), S2sError> {
        self.mdns.unregister(&format!(
            "{}.{}",
            self.my_name.as_str(),
            MDNS_SUFFIX_SERV_LOCAL
        ))?;
        self.mdns.shutdown()?;
        // 데몬 종료 후 receiver가 끊기면서 스레드가 자연히 종료됨
        if let Some(handle) = self.browse_thread.take() {
            let _ = handle.join();
        }
        if let Some(handle) = self.health_send_thread.take() {
            let _ = handle.join();
        }
        if let Some(handle) = self.health_recv_thread.take() {
            let _ = handle.join();
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use mdns_sd::{ServiceEvent, ServiceInfo};
    use std::collections::HashMap;
    use std::sync::RwLock;

    fn make_peers() -> RwLock<HashMap<String, IpPort>> {
        RwLock::new(HashMap::new())
    }

    /// ServiceResolved 이벤트 생성 헬퍼. ip가 ""이면 IPv4 주소 없음.
    fn make_resolved(name: &str, ip: &str, port: u16) -> ServiceEvent {
        let props = [("health_port", "50507")];
        let resolved = ServiceInfo::new(
            MDNS_SUFFIX_SERV_LOCAL,
            name,
            &format!("{name}.local."),
            ip,
            port,
            &props[..],
        )
        .unwrap()
        .as_resolved_service();
        ServiceEvent::ServiceResolved(Box::new(resolved))
    }

    // ─── ServerName ──────────────────────────────────────────────────────────

    #[test]
    fn server_name_valid() {
        assert!(ServerName::new("my-server").is_ok());
    }

    #[test]
    fn server_name_exactly_63_bytes_is_ok() {
        assert!(ServerName::new(&"a".repeat(63)).is_ok());
    }

    #[test]
    fn server_name_64_bytes_is_too_long() {
        assert!(matches!(
            ServerName::new(&"a".repeat(64)),
            Err(S2sError::NameTooLong(64))
        ));
    }

    #[test]
    fn server_name_control_chars_are_rejected() {
        for s in ["bad\nname", "bad\tname", "bad\0name"] {
            assert!(matches!(
                ServerName::new(s),
                Err(S2sError::NameHasControlChar)
            ));
        }
    }

    #[test]
    fn server_name_multibyte_over_63_bytes_is_too_long() {
        // 한글 1자 = 3바이트이므로 22자 = 66바이트
        assert!(matches!(
            ServerName::new(&"가".repeat(22)),
            Err(S2sError::NameTooLong(_))
        ));
    }

    #[test]
    fn server_name_as_str_returns_input() {
        assert_eq!(ServerName::new("hello").unwrap().as_str(), "hello");
    }

    // ─── ServerToServer::handle_mdns_event ───────────────────────────────────

    #[test]
    fn resolved_peer_is_added() {
        let peers = make_peers();
        ServerToServer::handle_mdns_event(
            make_resolved("peer1", "192.168.1.10", 8080),
            &format!("me.{MDNS_SUFFIX_SERV_LOCAL}"),
            &peers,
        );
        assert_eq!(peers.read().unwrap().len(), 1);
    }

    #[test]
    fn resolved_peer_name_is_instance_name() {
        let peers = make_peers();
        ServerToServer::handle_mdns_event(
            make_resolved("peer1", "192.168.1.10", 8080),
            &format!("me.{MDNS_SUFFIX_SERV_LOCAL}"),
            &peers,
        );
        let peer = peers.read().unwrap().values().next().unwrap().clone();
        assert_eq!(peer.name, "peer1");
        assert_eq!(peer.port, 8080);
    }

    #[test]
    fn resolved_self_is_ignored() {
        let peers = make_peers();
        ServerToServer::handle_mdns_event(
            make_resolved("me", "192.168.1.1", 8080),
            &format!("me.{MDNS_SUFFIX_SERV_LOCAL}"),
            &peers,
        );
        assert!(peers.read().unwrap().is_empty());
    }

    #[test]
    fn resolved_without_ipv4_is_ignored() {
        let peers = make_peers();
        ServerToServer::handle_mdns_event(
            make_resolved("peer2", "", 8080),
            &format!("me.{MDNS_SUFFIX_SERV_LOCAL}"),
            &peers,
        );
        assert!(peers.read().unwrap().is_empty());
    }

    #[test]
    fn removed_peer_is_deleted() {
        let peers = make_peers();
        let fullname = format!("peer1.{MDNS_SUFFIX_SERV_LOCAL}");
        peers.write().unwrap().insert(
            fullname.clone(),
            IpPort {
                name: "peer1".to_string(),
                ip: std::net::Ipv4Addr::new(192, 168, 1, 10),
                port: 8080,
                health_port: HEALTH_PORT,
                last_seen: Instant::now(),
            },
        );
        ServerToServer::handle_mdns_event(
            ServiceEvent::ServiceRemoved(MDNS_SUFFIX_SERV_LOCAL.to_string(), fullname),
            &format!("me.{MDNS_SUFFIX_SERV_LOCAL}"),
            &peers,
        );
        assert!(peers.read().unwrap().is_empty());
    }

    #[test]
    fn other_events_do_nothing() {
        let peers = make_peers();
        ServerToServer::handle_mdns_event(
            ServiceEvent::SearchStarted(MDNS_SUFFIX_SERV_LOCAL.to_string()),
            &format!("me.{MDNS_SUFFIX_SERV_LOCAL}"),
            &peers,
        );
        assert!(peers.read().unwrap().is_empty());
    }
}
