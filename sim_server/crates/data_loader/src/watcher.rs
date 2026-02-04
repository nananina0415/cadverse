use std::path::Path;
use std::time::Duration;
use crossbeam_channel::Sender;
use notify::RecursiveMode;
use notify_debouncer_mini::new_debouncer;
use tracing::{info, error};

use crate::types::LoaderMessage;
use crate::loader;

/// 폴더 감시를 시작한다.
///
/// .obj 또는 .json 파일 변경이 감지되면 씬을 다시 로드하여 채널로 전송한다.
/// 500ms 디바운스 적용 (CAD 내보내기가 여러 파일을 연속 기록할 수 있으므로).
///
/// 별도 OS 스레드에서 실행되며, JoinHandle을 반환한다.
pub fn start_watcher(
    folder: &Path,
    tx: Sender<LoaderMessage>,
) -> anyhow::Result<std::thread::JoinHandle<()>> {
    let folder = folder.to_path_buf();

    let handle = std::thread::spawn(move || {
        // notify 이벤트를 받을 내부 채널
        let (notify_tx, notify_rx) = crossbeam_channel::unbounded();

        let mut debouncer = match new_debouncer(
            Duration::from_millis(500),
            move |events: Result<Vec<notify_debouncer_mini::DebouncedEvent>, notify::Error>| {
                if let Ok(events) = events {
                    let _ = notify_tx.send(events);
                }
            },
        ) {
            Ok(d) => d,
            Err(e) => {
                error!("파일 감시자 생성 실패: {}", e);
                let _ = tx.send(LoaderMessage::Error(format!(
                    "파일 감시자 생성 실패: {}",
                    e
                )));
                return;
            }
        };

        if let Err(e) = debouncer
            .watcher()
            .watch(&folder, RecursiveMode::Recursive)
        {
            error!("폴더 감시 시작 실패: {}", e);
            let _ = tx.send(LoaderMessage::Error(format!(
                "폴더 감시 시작 실패: {}",
                e
            )));
            return;
        }

        info!("파일 감시 시작: {:?}", folder);

        // 이벤트 루프
        loop {
            match notify_rx.recv() {
                Ok(events) => {
                    // metadata.json 변경인지 확인
                    let relevant = events.iter().any(|e| {
                        e.path.file_name().and_then(|n| n.to_str()) == Some("metadata.json")
                    });

                    if relevant {
                        info!("관련 파일 변경 감지, 씬 리로드 중...");
                        match loader::load_scene(&folder) {
                            Ok(data) => {
                                let _ = tx.send(LoaderMessage::SceneLoaded(data));
                            }
                            Err(e) => {
                                error!("씬 리로드 실패: {}", e);
                                let _ = tx.send(LoaderMessage::Error(e.to_string()));
                            }
                        }
                    }
                }
                Err(_) => {
                    info!("감시 채널 종료");
                    break;
                }
            }
        }
    });

    Ok(handle)
}
