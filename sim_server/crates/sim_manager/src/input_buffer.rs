use std::sync::Arc;
use parking_lot::RwLock;

/// 입력 메시지를 담는 트리플 버퍼
///
/// - Write 버퍼: WebSocket에서 새 입력 저장
/// - Read 버퍼: 시뮬레이션에서 읽음
/// - Swap 버퍼: Write와 Read 사이의 중간 버퍼
#[derive(Clone)]
pub struct InputBuffer<T> {
    buffers: Arc<RwLock<TripleBuffer<T>>>,
}

struct TripleBuffer<T> {
    /// 현재 쓰기 중인 버퍼
    write: Vec<T>,
    /// 시뮬레이션이 읽을 버퍼
    read: Vec<T>,
    /// 스왑용 중간 버퍼
    swap: Vec<T>,
}

impl<T> InputBuffer<T> {
    pub fn new() -> Self {
        Self {
            buffers: Arc::new(RwLock::new(TripleBuffer {
                write: Vec::new(),
                read: Vec::new(),
                swap: Vec::new(),
            })),
        }
    }

    /// 새 입력 메시지 추가 (WebSocket 핸들러에서 호출)
    pub fn push(&self, input: T) {
        let mut buffers = self.buffers.write();
        buffers.write.push(input);
    }

    /// Write 버퍼와 Swap 버퍼를 교환
    /// WebSocket 프레임 끝에서 호출
    pub fn flip_write(&self) {
        let mut buffers = self.buffers.write();
        let write_ptr = &mut buffers.write as *mut Vec<T>;
        let swap_ptr = &mut buffers.swap as *mut Vec<T>;
        unsafe {
            std::ptr::swap(write_ptr, swap_ptr);
        }
        buffers.write.clear();
    }

    /// Swap 버퍼와 Read 버퍼를 교환
    /// 시뮬레이션 프레임 시작 시 호출
    pub fn flip_read(&self) {
        let mut buffers = self.buffers.write();
        let swap_ptr = &mut buffers.swap as *mut Vec<T>;
        let read_ptr = &mut buffers.read as *mut Vec<T>;
        unsafe {
            std::ptr::swap(swap_ptr, read_ptr);
        }
        buffers.swap.clear();
    }

    /// 읽기 버퍼의 모든 입력 가져오기 (시뮬레이션에서 호출)
    pub fn read_all(&self) -> Vec<T>
    where
        T: Clone,
    {
        let buffers = self.buffers.read();
        buffers.read.clone()
    }

    /// 읽기 버퍼 클리어 (프레임 처리 후)
    pub fn clear_read(&self) {
        let mut buffers = self.buffers.write();
        buffers.read.clear();
    }
}

impl<T> Default for InputBuffer<T> {
    fn default() -> Self {
        Self::new()
    }
}
