pub mod sim_state_buffer;

use anyhow::Result;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber;
use sim_state_buffer::SimStateBuffer;

#[tokio::main]
async fn main() -> Result<()> {
    // 로깅 초기화
    tracing_subscriber::fmt()
        .with_target(false)
        .with_thread_ids(true)
        .init();

    info!("Starting CADverse Simulation Server");

    // CAD 데이터 로드
    info!("Loading CAD data...");
    cad_data_loader::load_cad_data("resources/base.obj");
    cad_data_loader::parse_obj_file("resources/shaft.obj")?;

    // 프레임 버퍼 생성
    info!("Creating frame buffer...");
    let buffer = Arc::new(SimStateBuffer::new());
    let buffer_for_sim = buffer.clone();
    let buffer_for_server = buffer.clone();

    // 시뮬레이션 매니저 초기화
    info!("Initializing simulator...");
    sim_manager::start(buffer_for_sim);

    // 서버 시작
    info!("Starting WebSocket server...");
    server::start_server(buffer_for_server).await?;

    Ok(())
}
