pub mod sim_state_buffer;
pub mod qr_display;

use anyhow::Result;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber;
use sim_state_buffer::SimStateBuffer;

#[tokio::main]
async fn main() -> Result<()> {
    // 로깅 초기화
    #[cfg(debug_assertions)]
    {
        // Debug 빌드: 상세 로그
        tracing_subscriber::fmt()
            .with_target(false)
            .with_thread_ids(true)
            .init();
        info!("Starting CADverse Simulation Server (Debug)");
    }

    #[cfg(not(debug_assertions))]
    {
        // Release 빌드: 에러만 출력
        tracing_subscriber::fmt()
            .with_target(false)
            .with_max_level(tracing::Level::ERROR)
            .init();
    }

    // CAD 데이터 로드
    #[cfg(debug_assertions)]
    info!("Loading CAD data...");

    cad_data_loader::load_cad_data("resources/base.obj");
    cad_data_loader::parse_obj_file("resources/shaft.obj")?;

    // 프레임 버퍼 생성
    #[cfg(debug_assertions)]
    info!("Creating frame buffer...");

    let buffer = Arc::new(SimStateBuffer::new());
    let buffer_for_sim = buffer.clone();
    let buffer_for_server = buffer.clone();

    // 입력 버퍼 생성
    #[cfg(debug_assertions)]
    info!("Creating input buffer...");

    let input_buffer = sim_manager::InputBuffer::new();
    let input_buffer_for_sim = input_buffer.clone();
    let input_buffer_for_server = input_buffer.clone();

    // 시뮬레이션 매니저 초기화
    #[cfg(debug_assertions)]
    info!("Initializing simulator...");

    sim_manager::start(buffer_for_sim, input_buffer_for_sim);

    // QR 코드 출력
    if let Err(e) = qr_display::display_qr_code(3000) {
        eprintln!("Failed to display QR code: {}", e);
    }

    // 서버 시작
    #[cfg(debug_assertions)]
    info!("Starting WebSocket server...");

    server::start_server(buffer_for_server, input_buffer_for_server).await?;

    Ok(())
}
