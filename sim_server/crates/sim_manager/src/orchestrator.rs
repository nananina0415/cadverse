use std::sync::Arc;
use std::thread::JoinHandle;

use anyhow::Result;
use tracing::{info, error, warn};

use crate::sim_loop_thread::{run_sim_loop, InputSource, StateSink, SimLoopControl};
use crate::simulator_binding::Simulator;

/// 시뮬레이션 생명주기를 관리하는 오케스트레이터.
///
/// 핵심 설계:
/// - input/sink 버퍼는 서버 스레드와 공유된 Arc 참조
/// - 시뮬레이션 교환 시 같은 버퍼를 재사용하므로 서버는 끊김 없음
///
/// 교환 순서 (다운타임 최소화):
/// 1. 새 Simulator 생성 (Python 초기화 - 느릴 수 있음)
/// 2. 기존 sim loop 스레드 정지
/// 3. 같은 버퍼로 새 sim loop 시작
/// 4. 기존 Simulator 자동 drop
pub struct SimOrchestrator<I, S>
where
    I: InputSource,
    S: StateSink,
{
    input: Arc<I>,
    sink: Arc<S>,

    // 현재 실행 중인 시뮬레이션
    current_handle: Option<JoinHandle<Result<()>>>,
    current_control: Option<SimLoopControl>,
}

impl<I, S> SimOrchestrator<I, S>
where
    I: InputSource,
    S: StateSink,
{
    pub fn new(input: Arc<I>, sink: Arc<S>) -> Self {
        Self {
            input,
            sink,
            current_handle: None,
            current_control: None,
        }
    }

    /// 시뮬레이션을 교환한다.
    ///
    /// 1. 새 Simulator Python 객체 생성 (느릴 수 있음)
    /// 2. 기존 시뮬레이션 스레드 정지
    /// 3. 같은 버퍼로 새 루프 시작
    pub fn swap_simulation(&mut self, scene_path: &str) {
        info!("새 시뮬레이션 생성 중: {}", scene_path);

        // 1. 새 Simulator 먼저 생성 (기존은 아직 돌고 있음)
        let new_sim = match Simulator::new(scene_path) {
            Ok(sim) => {
                info!("새 Simulator 생성 완료");
                sim
            }
            Err(e) => {
                error!("Simulator 생성 실패: {:#}", e);
                // 에러 체인 전체 출력
                for cause in e.chain().skip(1) {
                    error!("  caused by: {}", cause);
                }
                return;
            }
        };

        // 2. 기존 시뮬레이션 정지
        self.stop_current();

        // 3. 같은 버퍼로 새 루프 시작
        self.start_with(new_sim);
    }

    /// 기존 시뮬레이션 스레드를 정지하고 join한다.
    fn stop_current(&mut self) {
        if let Some(control) = self.current_control.take() {
            info!("기존 시뮬레이션 정지 중...");
            control.stop();
        }
        if let Some(handle) = self.current_handle.take() {
            match handle.join() {
                Ok(Ok(())) => info!("시뮬레이션 스레드 정상 종료"),
                Ok(Err(e)) => warn!("시뮬레이션 스레드 에러 종료: {}", e),
                Err(_) => error!("시뮬레이션 스레드 패닉"),
            }
        }
    }

    /// 이미 생성된 Simulator로 루프를 시작한다.
    fn start_with(&mut self, simulator: Simulator) {
        info!("시뮬레이션 루프 시작");

        let (handle, control) = run_sim_loop(
            simulator,
            self.input.clone(),
            self.sink.clone(),
            None, // target_dt: 기본 1ms sleep
        );

        self.current_handle = Some(handle);
        self.current_control = Some(control);
    }

    /// 채널에서 LoaderMessage를 수신하며 핫스왑을 수행하는 메인 루프.
    /// 별도 스레드에서 실행된다.
    pub fn run(mut self, rx: crossbeam_channel::Receiver<cad_data_loader::LoaderMessage>) {
        std::thread::spawn(move || {
            info!("SimOrchestrator 리로드 대기 루프 시작");
            loop {
                match rx.recv() {
                    Ok(cad_data_loader::LoaderMessage::SceneLoaded(data)) => {
                        info!("새 씬 데이터 수신, 핫스왑 수행...");
                        let scene_path = data
                            .scene_json_path
                            .to_string_lossy()
                            .to_string();
                        self.swap_simulation(&scene_path);
                    }
                    Ok(cad_data_loader::LoaderMessage::Error(e)) => {
                        error!("로더 에러: {}. 기존 시뮬레이션 유지.", e);
                    }
                    Err(_) => {
                        info!("로더 채널 종료, 오케스트레이터 정지");
                        self.stop_current();
                        break;
                    }
                }
            }
        });
    }
}
