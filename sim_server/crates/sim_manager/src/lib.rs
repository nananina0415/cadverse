use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime};

use crate::simulator::Simulator;

pub type StateBuffer = Arc<dyn std::any::Any + Send + Sync>;

/// 시뮬레이션 매니저 스레드를 시작합니다.
///
/// 주어진 폴더(`folder_path`) 내의 `metadata.json` 변경을 감지하여
/// 시뮬레이터를 자동으로 재로딩(Hot-Reload)하고, 매 프레임 `step`을 실행합니다.
pub fn start(folder_path: String, _buffer: StateBuffer) -> JoinHandle<()> {
    thread::spawn(move || {
        let root_path = PathBuf::from(folder_path);
        let target_file = root_path.join("metadata.json");

        let mut current_sim: Option<Simulator> = None;
        let mut last_modified: Option<SystemTime> = None;

        println!("[SimManager] Watcher thread started at: {:?}", root_path);

        loop {
            // ----------------------------------------------------------------
            // 1. File Watcher & Hot Reload Logic
            // ----------------------------------------------------------------
            if let Ok(metadata) = fs::metadata(&target_file) {
                if let Ok(modified_time) = metadata.modified() {
                    // 파일 수정 시간이 변경되었을 경우 리로드 수행
                    if last_modified != Some(modified_time) {
                        println!("[SimManager] Detected file change. Reloading...");

                        // Python 바인딩이 참조할 환경변수 업데이트
                        std::env::set_var("SIM_SCENE_JSON", target_file.to_str().unwrap_or(""));

                        match Simulator::new() {
                            Ok(sim) => {
                                println!("[SimManager] Simulator loaded successfully.");
                                current_sim = Some(sim);
                                last_modified = Some(modified_time);
                            }
                            Err(e) => {
                                eprintln!("[SimManager] Failed to reload simulator: {:?}", e);
                            }
                        }
                    }
                }
            }

            // ----------------------------------------------------------------
            // 2. Simulation Loop
            // ----------------------------------------------------------------
            if let Some(sim) = &current_sim {
                // 시뮬레이션 1 Step 실행
                if let Err(e) = sim.step() {
                    eprintln!("[SimManager] Step execution failed: {:?}", e);
                }

                // Physics Update Rate 조절 (약 1000Hz)
                thread::sleep(Duration::from_millis(1));
            } else {
                // 시뮬레이터가 로드되지 않은 상태 (파일 대기 중)
                // CPU 점유율 방지를 위해 Long Sleep (2Hz)
                thread::sleep(Duration::from_millis(500));
            }
        }
    })
}
