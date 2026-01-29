mod routes;
mod websocket;
pub mod models;

use anyhow::Result;
use axum::{
    Router,
    routing::get,
};
use std::net::SocketAddr;
use std::sync::Arc;
use tracing::info;

// SimStateBuffer를 외부에서 전달받기 위한 타입 재export
// (sim_state_buffer는 루트 크레이트에 있음)
pub type StateBuffer = Arc<dyn std::any::Any + Send + Sync>;

// 입력 버퍼 타입 재export
pub use sim_manager::InputBuffer;
pub use models::TouchRaycastInput;

/// 서버 상태 (StateBuffer + InputBuffer)
#[derive(Clone)]
pub struct ServerState {
    pub state_buffer: StateBuffer,
    pub input_buffer: InputBuffer<TouchRaycastInput>,
}

/// WebSocket 서버 초기화 및 시작
///
/// ## 인자
/// - `state_buffer`: 시뮬레이션 프레임 버퍼 (Arc<SimStateBuffer>)
/// - `input_buffer`: 입력 메시지 버퍼 (InputBuffer<TouchRaycastInput>)
pub async fn start_server(state_buffer: StateBuffer, input_buffer: InputBuffer<TouchRaycastInput>) -> Result<()> {
    let server_state = ServerState {
        state_buffer,
        input_buffer,
    };

    let app = Router::new()
        // WebSocket 엔드포인트
        .route("/cadverse", get(websocket::websocket_handler))
        // 오브젝트 리스트 API
        .route("/cadverse/object", get(routes::get_object_list))
        // 메쉬 파일 다운로드 API
        .route("/cadverse/object/{name}", get(routes::get_object_mesh))
        // QR 패턴 API
        .route("/cadverse/qr", get(routes::get_qr_pattern))
        // Axum state로 server_state 전달
        .with_state(server_state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 3000));
    info!("Server listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
