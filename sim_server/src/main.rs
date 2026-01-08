use anyhow::Result;
use tracing::info;
use tracing_subscriber;

fn main() -> Result<()> {
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

    // 시뮬레이션 매니저 초기화
    info!("Initializing simulator...");
    sim_manager::init_simulator();

    // 서버 시작
    info!("Starting WebSocket server...");
    server::start_server();

    Ok(())
}
