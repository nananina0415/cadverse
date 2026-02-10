mod routes;
mod websocket;
pub mod models;

use anyhow::Result;
use axum::{
    Router,
    routing::get,
    http::Request,
    body::Body,
};
use std::net::SocketAddr;
use std::sync::Arc;
use tower_http::trace::TraceLayer;
use tracing::{info, warn};

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

/// 서버 라우터 빌드 (테스트에서도 사용 가능)
pub fn build_router(server_state: ServerState) -> Router {
    Router::new()
        .route("/cadverse", get(websocket::websocket_handler))
        .route("/cadverse/object", get(routes::get_object_list))
        .route("/cadverse/object/{name}", get(routes::get_object_mesh))
        .route("/cadverse/qr", get(routes::get_qr_pattern))
        .with_state(server_state)
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(|request: &Request<Body>| {
                    tracing::info_span!(
                        "http_request",
                        method = %request.method(),
                        uri = %request.uri(),
                    )
                })
                .on_request(|request: &Request<Body>, _span: &tracing::Span| {
                    info!("→ {} {}", request.method(), request.uri());
                })
                .on_response(|response: &axum::http::Response<Body>, latency: std::time::Duration, _span: &tracing::Span| {
                    info!("← {} ({:?})", response.status(), latency);
                })
                .on_failure(|error: tower_http::classify::ServerErrorsFailureClass, latency: std::time::Duration, _span: &tracing::Span| {
                    warn!("✗ {} ({:?})", error, latency);
                }),
        )
}

/// WebSocket 서버 초기화 및 시작
pub async fn start_server(state_buffer: StateBuffer, input_buffer: InputBuffer<TouchRaycastInput>) -> Result<()> {
    let server_state = ServerState {
        state_buffer,
        input_buffer,
    };

    let app = build_router(server_state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 3000));
    info!("Server listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>()).await?;

    Ok(())
}
