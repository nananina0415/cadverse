pub mod sim_state_buffer;
pub mod qr_display;

use anyhow::Result;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber;

use sim_state_buffer::SimStateBuffer;
use sim_manager::{InputBuffer, InputSource, StateSink, SimState, SimOrchestrator};
use server::models::{SimulationState, ObjectTransform};
use server::TouchRaycastInput;

// ================================================================
// Trait 어댑터: sim_manager 트레이트 ↔ sim_server 타입
// ================================================================

/// SimStateBuffer를 StateSink로 연결 (SimState → SimulationState 변환 포함)
struct SimStateSink {
    buffer: Arc<SimStateBuffer>,
}

impl StateSink for SimStateSink {
    fn publish(&self, state: SimState) {
        let sim_state = SimulationState {
            timestamp: state.sim_time,
            objects: state
                .parts
                .iter()
                .map(|p| ObjectTransform {
                    name: p.name.clone(),
                    position: [p.pos[0] as f32, p.pos[1] as f32, p.pos[2] as f32],
                    rotation: [p.rot[0] as f32, p.rot[1] as f32, p.rot[2] as f32, p.rot[3] as f32],
                })
                .collect(),
        };
        self.buffer.publish(sim_state);
    }
}

/// InputBuffer<TouchRaycastInput>를 InputSource로 연결
struct TouchInputSource {
    buffer: InputBuffer<TouchRaycastInput>,
}

impl InputSource for TouchInputSource {
    type Input = Vec<TouchRaycastInput>;

    fn read(&self) -> Option<Self::Input> {
        self.buffer.flip_read();
        let inputs = self.buffer.read_all();
        if inputs.is_empty() {
            None
        } else {
            Some(inputs)
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    // 로깅 초기화
    #[cfg(debug_assertions)]
    {
        tracing_subscriber::fmt()
            .with_target(false)
            .with_thread_ids(true)
            .init();
        info!("Starting CADverse Simulation Server (Debug)");
    }

    #[cfg(not(debug_assertions))]
    {
        tracing_subscriber::fmt()
            .with_target(false)
            .with_max_level(tracing::Level::ERROR)
            .init();
    }

    // 프레임 버퍼 생성
    let buffer = Arc::new(SimStateBuffer::new());

    // 입력 버퍼 생성
    let input_buffer: InputBuffer<TouchRaycastInput> = InputBuffer::new();
    let input_buffer_for_server = input_buffer.clone();

    // 트레이트 어댑터 생성
    let sink = Arc::new(SimStateSink {
        buffer: buffer.clone(),
    });
    let input_source = Arc::new(TouchInputSource {
        buffer: input_buffer,
    });

    // data_loader: 폴더 선택 + notify 기반 파일 감시
    info!("CAD 폴더 선택 중...");
    let folder = cad_data_loader::pick_cad_folder()?;
    info!("CAD 폴더 선택됨: {:?}", folder);

    // 초기 씬 로드
    let scene = cad_data_loader::load_scene(&folder)?;
    info!("초기 씬 로드 완료: {:?}", scene.scene_json_path);

    // notify watcher 시작 (metadata.json 변경 감지 → 채널 전송)
    let (tx, rx) = crossbeam_channel::unbounded();
    let _watcher_handle = cad_data_loader::start_watcher(&folder, tx)?;
    info!("파일 감시 시작됨");

    // sim_manager: orchestrator 생성 및 초기 시뮬레이션 로드
    let mut orchestrator = SimOrchestrator::new(input_source, sink);

    let scene_path = scene.scene_json_path.to_string_lossy().to_string();
    orchestrator.swap_simulation(&scene_path);

    // orchestrator를 별도 스레드에서 실행 (LoaderMessage 수신 대기)
    orchestrator.run(rx);
    info!("시뮬레이션 오케스트레이터 시작됨");

    // QR 코드 GUI 창 출력 (5cm 크기, DPI 자동 감지)
    if let Err(e) = qr_display::display_qr_code(3000, Some(5.0)) {
        eprintln!("Failed to display QR code: {}", e);
    }

    // 서버 시작
    info!("WebSocket 서버 시작 중...");
    server::start_server(buffer, input_buffer_for_server).await?;

    Ok(())
}
