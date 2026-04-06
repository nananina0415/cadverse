use std::{io::{self, Write}, sync::Arc};
use p2p_core::{JoinForm, NetId, Password, PeerType};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let name = prompt("My name: ")?;
    let net_id = prompt("Network ID: ")?;
    let password = prompt("Password: ")?;
    let peer_type = prompt_peer_type()?;

    println!("Joining network...");
    let net = Arc::new(p2p_core::join_p2p_net(JoinForm {
        net_id: NetId(net_id),
        pw: Password(password),
        my_name: name.clone(),
        peer_type,
    }).await?);

    println!("Joined. My EndpointId: {}", net.my_id());

    // SimServer: DATA(udp) 및 HTTP 요청 처리
    if let PeerType::SimServer { .. } = net.get_peers()
        .iter()
        .find(|p| p.addr.id == net.my_id())
        .map(|p| &p.peer_type)
        .unwrap_or(&PeerType::MidServer)
    {
        let net_udp = net.clone();
        let name_udp = name.clone();
        tokio::spawn(async move {
            while let Some(conn) = net_udp.accept_data().await {
                let name = name_udp.clone();
                tokio::spawn(async move {
                    match conn.recv().await {
                        Ok(bytes) => {
                            println!("[udp] recv: {}", String::from_utf8_lossy(&bytes));
                            let resp = format!("hello udp, here {name}");
                            println!("[udp] send: {resp}");
                            if let Err(e) = conn.send(resp.as_bytes()).await {
                                eprintln!("[server] udp send error: {e}");
                            }
                        }
                        Err(e) => eprintln!("[server] udp recv error: {e}"),
                    }
                });
            }
        });

        let net_http = net.clone();
        let name_http = name.clone();
        tokio::spawn(async move {
            while let Some(conn) = net_http.accept_http_conn().await {
                let name = name_http.clone();
                tokio::spawn(async move {
                    if let Err(e) = p2p_core::serve_h3_response(conn, |_path| {
                        let body = format!("hello http, here {name}");
                        println!("[http] send: {body}");
                        bytes::Bytes::from(body)
                    }).await {
                        eprintln!("[server] http error: {e}");
                    }
                });
            }
        });

        println!("Server mode active. Waiting for requests...");
    }

    loop {
        let peers = net.get_peers();
        println!("--- peers ({}) ---", peers.len());
        for p in &peers {
            let type_str = match &p.peer_type {
                PeerType::SimServer => "SimServer".to_string(),
                PeerType::MidServer => "MidServer".to_string(),
                PeerType::ArClient { udp_port } => format!("ArClient udp={udp_port}"),
            };
            println!("  {} [{}]", p.name, type_str);
        }
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    }
}

fn prompt_peer_type() -> anyhow::Result<PeerType> {
    println!("Peer type: 1=SimServer  2=MidServer  3=ArClient");
    let choice = prompt("Choice: ")?;
    match choice.as_str() {
        "1" => Ok(PeerType::SimServer),
        "2" => Ok(PeerType::MidServer),
        "3" => {
            let udp_port: u16 = prompt("UDP port: ")?.parse()?;
            Ok(PeerType::ArClient { udp_port })
        }
        _ => anyhow::bail!("invalid choice"),
    }
}

fn prompt(msg: &str) -> anyhow::Result<String> {
    print!("{}", msg);
    io::stdout().flush()?;
    let mut input = String::new();
    io::stdin().read_line(&mut input)?;
    Ok(input.trim().to_string())
}
