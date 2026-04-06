mod h3_iroh;

use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::Instant,
};

use anyhow::Result;
use bytes::Bytes;
use iroh::{endpoint::presets, Endpoint, EndpointAddr, EndpointId};
use pbkdf2::pbkdf2_hmac;
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use tokio::sync::mpsc;

// ── 공개 타입 ────────────────────────────────────────────────────────────────

pub struct NetId(pub String);
pub struct Password(pub String);

pub type NodeAddr = EndpointAddr;

pub struct Node {
    endpoint: Endpoint,
    _accept_task: tokio::task::JoinHandle<()>,
}

impl Node {
    pub fn id(&self) -> EndpointId { self.endpoint.id() }
    pub fn addr(&self) -> NodeAddr { self.endpoint.addr() }
}

#[derive(Clone)]
pub struct Connection(iroh::endpoint::Connection);

impl Connection {
    pub async fn send(&self, data: &[u8]) -> Result<()> {
        let mut send = self.0.open_uni().await?;
        send.write_all(data).await?;
        send.finish()?;
        Ok(())
    }

    pub async fn recv(&self) -> Result<Vec<u8>> {
        let mut recv = self.0.accept_uni().await?;
        let data = recv.read_to_end(usize::MAX).await?;
        Ok(data)
    }

    pub fn remote_id(&self) -> EndpointId {
        self.0.remote_id()
    }
}

#[derive(Clone, Serialize, Deserialize)]
pub enum PeerType {
    SimServer,
    MidServer,
    ArClient { udp_port: u16 },
}

#[derive(Clone, Serialize, Deserialize)]
pub struct PeerInfo {
    pub addr: NodeAddr,
    pub name: String,
    pub peer_type: PeerType,
}

pub struct JoinForm {
    pub net_id: NetId,
    pub pw: Password,
    pub my_name: String,
    pub peer_type: PeerType,
}

// ── 공개 API ─────────────────────────────────────────────────────────────────

pub struct P2PNet {
    node: Node,
    peers: Peers,
    coord_conn: Option<iroh::endpoint::Connection>,
    data_rx: Arc<tokio::sync::Mutex<mpsc::Receiver<iroh::endpoint::Connection>>>,
    http_rx: Arc<tokio::sync::Mutex<mpsc::Receiver<iroh::endpoint::Connection>>>,
}

impl P2PNet {
    pub fn my_id(&self) -> EndpointId {
        self.node.id()
    }

    pub fn my_addr(&self) -> NodeAddr {
        self.node.addr()
    }

    pub fn get_peers(&self) -> Vec<PeerInfo> {
        match &self.peers {
            Peers::Coord(map) => peer_map_to_list(map),
            Peers::Peer(list) => list.lock().unwrap().clone(),
        }
    }

    pub async fn accept_data(&self) -> Option<Connection> {
        self.data_rx.lock().await.recv().await.map(Connection)
    }

    pub async fn accept_http_conn(&self) -> Option<iroh::endpoint::Connection> {
        self.http_rx.lock().await.recv().await
    }

    pub async fn connect_udp(&self, addr: NodeAddr) -> Result<Connection> {
        let conn = self.node.endpoint.connect(addr, DATA_ALPN).await?;
        Ok(Connection(conn))
    }

    pub async fn request_http(&self, addr: NodeAddr, path: &str) -> Result<Vec<u8>> {
        let conn = self.node.endpoint.connect(addr, HTTP_ALPN).await?;
        let h3_conn = h3_iroh::Connection::new(conn);
        let (mut driver, mut send_request) = h3::client::new(h3_conn).await?;
        tokio::spawn(async move { let _ = driver.wait_idle().await; });

        let req = http::Request::builder()
            .method(http::Method::GET)
            .uri(path)
            .body(())?;
        let mut stream = send_request.send_request(req).await?;
        stream.finish().await?;

        let _resp = stream.recv_response().await?;
        let mut body = Vec::new();
        while let Some(chunk) = stream.recv_data().await? {
            use bytes::Buf;
            body.extend_from_slice(chunk.chunk());
        }
        Ok(body)
    }

    pub async fn notice_sim_online(&self) -> Result<()> {
        match &self.peers {
            Peers::Coord(map) => {
                set_peer_type_and_broadcast(map, self.node.id(), PeerType::SimServer).await;
            }
            Peers::Peer(_) => {
                if let Some(conn) = &self.coord_conn {
                    send_to_coord(conn, &ToCoord::NoticeSimOnline).await?;
                }
            }
        }
        Ok(())
    }

    pub async fn notice_sim_offline(&self) -> Result<()> {
        match &self.peers {
            Peers::Coord(map) => {
                set_peer_type_and_broadcast(map, self.node.id(), PeerType::MidServer).await;
            }
            Peers::Peer(_) => {
                if let Some(conn) = &self.coord_conn {
                    send_to_coord(conn, &ToCoord::NoticeSimOffline).await?;
                }
            }
        }
        Ok(())
    }
}

pub async fn serve_h3_response<F>(conn: iroh::endpoint::Connection, body_fn: F) -> Result<()>
where
    F: FnOnce(&str) -> Bytes,
{
    let h3_conn = h3_iroh::Connection::new(conn);
    let mut h3_server: h3::server::Connection<_, Bytes> =
        h3::server::builder().build(h3_conn).await?;
    if let Some(resolver) = h3_server.accept().await? {
        let (req, mut stream) = resolver.resolve_request().await?;
        let path = req.uri().path();
        let body = body_fn(path);
        stream
            .send_response(http::Response::builder().status(200).body(())?)
            .await?;
        stream.send_data(body).await?;
        stream.finish().await?;
    }
    Ok(())
}

pub async fn join_p2p_net(form: JoinForm) -> Result<P2PNet> {
    let endpoint = create_endpoint().await?;
    endpoint.online().await;

    let keypair = derive_network_keypair(&form.net_id.0, &form.pw.0);

    let coord_id = if form.my_name == "A" {
        println!("[join] name is A, forcing coordinator role");
        None
    } else {
        read_coordinator_id(&keypair).await
    };

    let (data_tx, data_rx) = mpsc::channel(32);
    let (http_tx, http_rx) = mpsc::channel(32);

    match coord_id {
        None => {
            println!("[join] becoming coordinator");
            publish_coordinator_id(&keypair, endpoint.id()).await?;

            let my_info = PeerInfo {
                addr: endpoint.addr(),
                name: form.my_name,
                peer_type: form.peer_type,
            };

            let peers: PeerMap = Arc::new(Mutex::new(HashMap::new()));
            peers.lock().unwrap().insert(endpoint.id(), PeerSlot {
                info: my_info,
                conn: None,
                last_seen: None,
            });

            let accept_handle = tokio::spawn(accept_loop(
                endpoint.clone(), Some(peers.clone()), data_tx, http_tx,
            ));
            tokio::spawn(heartbeat_checker(peers.clone()));

            let node = Node { endpoint, _accept_task: accept_handle };
            Ok(P2PNet {
                node,
                peers: Peers::Coord(peers),
                coord_conn: None,
                data_rx: Arc::new(tokio::sync::Mutex::new(data_rx)),
                http_rx: Arc::new(tokio::sync::Mutex::new(http_rx)),
            })
        }
        Some(coord_id) => {
            println!("[join] coordinator found: {coord_id}");
            let coord_addr: NodeAddr = coord_id.into();
            let conn = endpoint.connect(coord_addr, COORD_ALPN).await?;

            let my_info = PeerInfo {
                addr: endpoint.addr(),
                name: form.my_name,
                peer_type: form.peer_type,
            };
            send_to_coord(&conn, &ToCoord::Register(my_info)).await?;

            let peers: Arc<Mutex<Vec<PeerInfo>>> = Arc::new(Mutex::new(Vec::new()));
            tokio::spawn(peer_recv_loop(conn.clone(), peers.clone()));
            tokio::spawn(peer_heartbeat_loop(conn.clone()));

            let accept_handle = tokio::spawn(accept_loop(
                endpoint.clone(), None, data_tx, http_tx,
            ));
            let node = Node { endpoint, _accept_task: accept_handle };
            Ok(P2PNet {
                node,
                peers: Peers::Peer(peers),
                coord_conn: Some(conn),
                data_rx: Arc::new(tokio::sync::Mutex::new(data_rx)),
                http_rx: Arc::new(tokio::sync::Mutex::new(http_rx)),
            })
        }
    }
}

// ── 비공개 구현 ───────────────────────────────────────────────────────────────

const COORD_ALPN: &[u8] = b"cv-coord/0";
pub const DATA_ALPN: &[u8] = b"cv-data/0";
const HTTP_ALPN: &[u8] = b"h3";
const PKARR_RELAY: &str = "https://dns.iroh.link/pkarr";

#[derive(Serialize, Deserialize)]
enum ToCoord {
    Register(PeerInfo),
    Heartbeat,
    NoticeSimOnline,
    NoticeSimOffline,
}

#[derive(Serialize, Deserialize)]
enum ToPeer {
    Ack(Vec<PeerInfo>),
    Broadcast(Vec<PeerInfo>),
}

struct PeerSlot {
    info: PeerInfo,
    conn: Option<iroh::endpoint::Connection>,
    last_seen: Option<Instant>,
}

type PeerMap = Arc<Mutex<HashMap<EndpointId, PeerSlot>>>;

enum Peers {
    Coord(PeerMap),
    Peer(Arc<Mutex<Vec<PeerInfo>>>),
}

fn derive_network_keypair(net_id: &str, pw: &str) -> pkarr::Keypair {
    let mut secret = [0u8; 32];
    pbkdf2_hmac::<Sha256>(pw.as_bytes(), net_id.as_bytes(), 100_000, &mut secret);
    pkarr::Keypair::from_secret_key(&secret)
}

async fn read_coordinator_id(keypair: &pkarr::Keypair) -> Option<EndpointId> {
    let client = reqwest::Client::builder().build().ok()?;
    let z32 = keypair.public_key().to_z32();
    let url = format!("{PKARR_RELAY}/{z32}");

    let resp = client.get(&url).send().await.ok()?;
    if !resp.status().is_success() { return None; }

    let payload = resp.bytes().await.ok()?;
    let packet = pkarr::SignedPacket::from_relay_payload(&keypair.public_key(), &payload).ok()?;

    for record in packet.all_resource_records() {
        if let pkarr::dns::rdata::RData::TXT(txt) = &record.rdata {
            if let Ok(id_str) = String::try_from(txt.clone()) {
                if let Ok(id) = id_str.trim().parse::<EndpointId>() {
                    return Some(id);
                }
            }
        }
    }
    None
}

async fn publish_coordinator_id(keypair: &pkarr::Keypair, my_id: EndpointId) -> Result<()> {
    let client = reqwest::Client::builder().build()?;
    let z32 = keypair.public_key().to_z32();
    let url = format!("{PKARR_RELAY}/{z32}");
    let id_str = my_id.to_string();

    let txt = pkarr::dns::rdata::TXT::try_from(id_str.as_str())
        .map_err(|e| anyhow::anyhow!("TXT error: {e}"))?;
    let name = pkarr::dns::Name::new(".")
        .map_err(|e| anyhow::anyhow!("Name error: {e}"))?;

    let signed = pkarr::SignedPacket::builder()
        .txt(name, txt.into_owned(), 300)
        .sign(keypair)
        .map_err(|e| anyhow::anyhow!("sign error: {e}"))?;

    let payload: Bytes = signed.to_relay_payload();
    client
        .put(&url)
        .header("Content-Type", "application/octet-stream")
        .body(payload.to_vec())
        .send()
        .await?;

    Ok(())
}

async fn send_to_peer(conn: &iroh::endpoint::Connection, msg: &ToPeer) -> Result<()> {
    let data = serde_json::to_vec(msg)?;
    let mut send = conn.open_uni().await?;
    send.write_all(&data).await?;
    send.finish()?;
    Ok(())
}

async fn send_to_coord(conn: &iroh::endpoint::Connection, msg: &ToCoord) -> Result<()> {
    let data = serde_json::to_vec(msg)?;
    let mut send = conn.open_uni().await?;
    send.write_all(&data).await?;
    send.finish()?;
    Ok(())
}

fn peer_map_to_list(peers: &PeerMap) -> Vec<PeerInfo> {
    peers.lock().unwrap().values().map(|s| s.info.clone()).collect()
}

async fn broadcast_to_all_except(peers: &PeerMap, list: &[PeerInfo], except_id: Option<EndpointId>) {
    let conns: Vec<iroh::endpoint::Connection> = {
        let map = peers.lock().unwrap();
        map.iter()
            .filter(|(id, slot)| Some(**id) != except_id && slot.conn.is_some())
            .map(|(_, slot)| slot.conn.clone().unwrap())
            .collect()
    };
    for conn in conns {
        if let Err(e) = send_to_peer(&conn, &ToPeer::Broadcast(list.to_vec())).await {
            eprintln!("[coord] broadcast error: {e}");
        }
    }
}

async fn register_peer_and_ack(
    peers: &PeerMap,
    peer_id: EndpointId,
    info: PeerInfo,
    conn: &iroh::endpoint::Connection,
) {
    let list = {
        let mut map = peers.lock().unwrap();
        map.insert(peer_id, PeerSlot {
            info,
            conn: Some(conn.clone()),
            last_seen: Some(Instant::now()),
        });
        map.values().map(|s| s.info.clone()).collect::<Vec<_>>()
    };
    if let Err(e) = send_to_peer(conn, &ToPeer::Ack(list.clone())).await {
        eprintln!("[coord] ack error: {e}");
    }
    broadcast_to_all_except(peers, &list, Some(peer_id)).await;
}

async fn set_peer_type_and_broadcast(peers: &PeerMap, peer_id: EndpointId, new_type: PeerType) {
    let list = {
        let mut map = peers.lock().unwrap();
        if let Some(slot) = map.get_mut(&peer_id) {
            slot.info.peer_type = new_type;
        }
        map.values().map(|s| s.info.clone()).collect::<Vec<_>>()
    };
    broadcast_to_all_except(peers, &list, None).await;
}

async fn handle_coord_conn(conn: iroh::endpoint::Connection, peers: PeerMap) {
    let peer_id = conn.remote_id();

    loop {
        let mut recv = match conn.accept_uni().await {
            Ok(r) => r,
            Err(_) => break,
        };
        let data = match recv.read_to_end(64 * 1024).await {
            Ok(d) => d,
            Err(_) => break,
        };
        let msg: ToCoord = match serde_json::from_slice(&data) {
            Ok(m) => m,
            Err(e) => { eprintln!("[coord] parse error: {e}"); continue; }
        };

        match msg {
            ToCoord::Register(info) => {
                register_peer_and_ack(&peers, peer_id, info, &conn).await;
            }
            ToCoord::Heartbeat => {
                if let Some(slot) = peers.lock().unwrap().get_mut(&peer_id) {
                    slot.last_seen = Some(Instant::now());
                }
            }
            ToCoord::NoticeSimOnline => {
                set_peer_type_and_broadcast(&peers, peer_id, PeerType::SimServer).await;
            }
            ToCoord::NoticeSimOffline => {
                set_peer_type_and_broadcast(&peers, peer_id, PeerType::MidServer).await;
            }
        }
    }

    let removed = peers.lock().unwrap().remove(&peer_id).is_some();
    if removed {
        let list = peer_map_to_list(&peers);
        broadcast_to_all_except(&peers, &list, None).await;
    }
}

async fn accept_loop(
    endpoint: Endpoint,
    coord_peers: Option<PeerMap>,
    data_tx: mpsc::Sender<iroh::endpoint::Connection>,
    http_tx: mpsc::Sender<iroh::endpoint::Connection>,
) {
    loop {
        let Some(incoming) = endpoint.accept().await else { break };
        let coord_peers = coord_peers.clone();
        let data_tx = data_tx.clone();
        let http_tx = http_tx.clone();
        tokio::spawn(async move {
            let mut accepting = match incoming.accept() {
                Ok(a) => a,
                Err(e) => { eprintln!("[accept] error: {e}"); return; }
            };
            let alpn = match accepting.alpn().await {
                Ok(a) => a,
                Err(e) => { eprintln!("[accept] alpn error: {e}"); return; }
            };
            let conn = match accepting.await {
                Ok(c) => c,
                Err(e) => { eprintln!("[accept] conn error: {e}"); return; }
            };

            if alpn == COORD_ALPN {
                if let Some(peers) = coord_peers {
                    handle_coord_conn(conn, peers).await;
                }
            } else if alpn == DATA_ALPN {
                let _ = data_tx.send(conn).await;
            } else if alpn == HTTP_ALPN {
                let _ = http_tx.send(conn).await;
            }
        });
    }
}

async fn heartbeat_checker(peers: PeerMap) {
    loop {
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        let now = Instant::now();

        let timed_out: Vec<EndpointId> = {
            let map = peers.lock().unwrap();
            map.iter()
                .filter(|(_, slot)| {
                    slot.last_seen.map_or(false, |t| now.duration_since(t).as_secs() >= 5)
                })
                .map(|(id, _)| *id)
                .collect()
        };

        if !timed_out.is_empty() {
            {
                let mut map = peers.lock().unwrap();
                for id in &timed_out {
                    map.remove(id);
                }
            }
            let list = peer_map_to_list(&peers);
            broadcast_to_all_except(&peers, &list, None).await;
        }
    }
}

async fn peer_recv_loop(conn: iroh::endpoint::Connection, peers: Arc<Mutex<Vec<PeerInfo>>>) {
    loop {
        let mut recv = match conn.accept_uni().await {
            Ok(r) => r,
            Err(_) => break,
        };
        let data = match recv.read_to_end(64 * 1024).await {
            Ok(d) => d,
            Err(_) => break,
        };
        let msg: ToPeer = match serde_json::from_slice(&data) {
            Ok(m) => m,
            Err(e) => { eprintln!("[peer] parse error: {e}"); continue; }
        };
        let list = match msg {
            ToPeer::Ack(list) | ToPeer::Broadcast(list) => list,
        };
        *peers.lock().unwrap() = list;
    }
}

async fn peer_heartbeat_loop(conn: iroh::endpoint::Connection) {
    loop {
        tokio::time::sleep(std::time::Duration::from_secs(4)).await;
        if let Err(e) = send_to_coord(&conn, &ToCoord::Heartbeat).await {
            eprintln!("[peer] heartbeat error: {e}");
            break;
        }
    }
}

async fn create_endpoint() -> Result<Endpoint> {
    let endpoint = Endpoint::builder(presets::N0)
        .alpns(vec![COORD_ALPN.to_vec(), DATA_ALPN.to_vec(), HTTP_ALPN.to_vec()])
        .bind()
        .await?;
    Ok(endpoint)
}
