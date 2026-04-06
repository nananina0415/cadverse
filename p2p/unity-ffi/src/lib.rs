use p2p_core::{Connection, JoinForm, NodeAddr, PeerInfo};

// tokio 런타임을 p2p_core::P2PNet과 함께 보관해 모든 async 작업이 같은 런타임에서 실행되도록 함
pub struct P2pNet {
    rt: tokio::runtime::Runtime,
    net: p2p_core::P2PNet,
}

impl P2pNet {
    pub fn my_addr(&self) -> NodeAddr {
        self.net.my_addr()
    }

    pub fn get_peers(&self) -> Vec<PeerInfo> {
        self.net.get_peers()
    }

    pub fn connect_udp(&self, addr: NodeAddr) -> anyhow::Result<Connection> {
        self.rt.block_on(self.net.connect_udp(addr))
    }

    pub fn request_http(&self, addr: NodeAddr, path: &str) -> anyhow::Result<Vec<u8>> {
        self.rt.block_on(self.net.request_http(addr, path))
    }
}

// FFI 진입점 - tokio 런타임 생성 후 join_p2p_net 실행
pub fn join_p2p_net(form: JoinForm) -> anyhow::Result<P2pNet> {
    let rt = tokio::runtime::Runtime::new()?;
    let net = rt.block_on(p2p_core::join_p2p_net(form))?;
    Ok(P2pNet { rt, net })
}
