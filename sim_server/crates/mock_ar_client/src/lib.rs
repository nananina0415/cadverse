//! Mock AR Client - sim_server 통합 테스트용
//!
//! 실제 Unity AR 클라이언트가 서버와 주고받는 데이터 흐름을 재현합니다.
//!
//! ## 데이터 흐름
//!
//! ### 서버 → 클라 (HTTP)
//! - `GET /cadverse/qr`        → QR 패턴 (텍스트 0/1)
//! - `GET /cadverse/object`    → 오브젝트 이름 리스트 (JSON)
//! - `GET /cadverse/object/:n` → OBJ 메쉬 파일 (text/obj)
//!
//! ### 서버 ↔ 클라 (WebSocket /cadverse)
//! - 서버→클라: SimulationState (JSON) - 오브젝트 위치/회전
//! - 클라→서버: TouchRaycastInput (JSON) - 터치 입력

use std::sync::Arc;
use std::net::SocketAddr;

pub use server::models::*;
pub use server::{InputBuffer, TouchRaycastInput, ServerState, StateBuffer, build_router};

/// InputBuffer에 접근 가능한 테스트 서버 (클라→서버 입력 검증용)
pub struct TestServer {
    pub addr: SocketAddr,
    pub input_buffer: InputBuffer<TouchRaycastInput>,
}

impl TestServer {
    pub async fn spawn() -> Self {
        let state_buffer: StateBuffer = Arc::new(0u8);
        let input_buffer: InputBuffer<TouchRaycastInput> = InputBuffer::new();
        let input_buffer_clone = input_buffer.clone();

        let server_state = ServerState {
            state_buffer,
            input_buffer,
        };

        let app = build_router(server_state);

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();

        tokio::spawn(async move {
            axum::serve(
                listener,
                app.into_make_service_with_connect_info::<SocketAddr>(),
            )
            .await
            .unwrap();
        });

        Self {
            addr,
            input_buffer: input_buffer_clone,
        }
    }

    pub fn base_url(&self) -> String {
        format!("http://{}", self.addr)
    }

    pub fn ws_url(&self) -> String {
        format!("ws://{}/cadverse", self.addr)
    }
}

