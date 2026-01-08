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

/// WebSocket 서버 초기화 및 시작
///
/// ## 인자
/// - `buffer`: 시뮬레이션 프레임 버퍼 (Arc<SimStateBuffer>)
pub async fn start_server(buffer: StateBuffer) -> Result<()> {
    let app = Router::new()
        // WebSocket 엔드포인트
        .route("/cadverse", get(websocket::websocket_handler))
        // 오브젝트 리스트 API
        .route("/cadverse/object", get(routes::get_object_list))
        // 메쉬 파일 다운로드 API
        .route("/cadverse/object/{name}", get(routes::get_object_mesh))
        // Axum state로 buffer 전달
        .with_state(buffer);

    let addr = SocketAddr::from(([127, 0, 0, 1], 3000));
    info!("Server listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
