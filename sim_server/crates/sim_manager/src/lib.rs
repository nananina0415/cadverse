use std::sync::Arc;

// StateBuffer 타입 (루트 크레이트에서 전달받음)
pub type StateBuffer = Arc<dyn std::any::Any + Send + Sync>;

/// 시뮬레이션 시작
///
/// ## 인자
/// - `_buffer`: 프레임 버퍼 (Arc<SimStateBuffer>)
///
/// ## TODO
/// - 별도 스레드에서 시뮬레이션 루프 실행
/// - PyChrono 초기화
/// - 매 프레임마다 buffer.publish() 호출
pub fn start(_buffer: StateBuffer) {
    println!("Sim Manager - start() called");
    // TODO: 실제 시뮬레이션 로직 구현
    // - tokio::task::spawn_blocking 또는 std::thread::spawn
    // - PyChrono 초기화
    // - 시뮬레이션 루프
}
