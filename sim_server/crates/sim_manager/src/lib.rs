mod input_buffer;

use std::sync::Arc;
pub use input_buffer::InputBuffer;

// StateBuffer 타입 (루트 크레이트에서 전달받음)
pub type StateBuffer = Arc<dyn std::any::Any + Send + Sync>;

/// 시뮬레이션 시작
///
/// ## 인자
/// - `_buffer`: 프레임 버퍼 (Arc<SimStateBuffer>)
/// - `_input_buffer`: 입력 버퍼 (InputBuffer<T>)
///
/// ## TODO
/// - 별도 스레드에서 시뮬레이션 루프 실행
/// - PyChrono 초기화
/// - 매 프레임마다:
///   - input_buffer.flip_read()로 입력 읽기
///   - input_buffer.read_all()로 입력 가져오기
///   - 시뮬레이션에 입력 전달
///   - buffer.publish()로 상태 업데이트
pub fn start<T>(_buffer: StateBuffer, _input_buffer: InputBuffer<T>) {
    println!("Sim Manager - start() called");
    // TODO: 실제 시뮬레이션 로직 구현
    // - tokio::task::spawn_blocking 또는 std::thread::spawn
    // - PyChrono 초기화
    // - 시뮬레이션 루프
}
