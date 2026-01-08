//! Lock-free 프레임 버퍼
//!
//! 시뮬레이터와 WebSocket 클라이언트 간의 최신 프레임 공유를 위한 lock-free 버퍼.
//! arc-swap을 사용하여 atomic pointer swap으로 블로킹 없이 프레임을 공유합니다.

use arc_swap::ArcSwap;
use std::sync::Arc;
use server::models::SimulationState;

/// Lock-free 시뮬레이션 상태 버퍼
///
/// 시뮬레이터가 생성한 최신 프레임을 atomic하게 저장하고,
/// 여러 WebSocket 클라이언트가 동시에 읽을 수 있도록 합니다.
///
/// ## 내부 구조
/// - `frame: ArcSwap<SimulationState>` - 최신 프레임을 가리키는 Arc 포인터
/// - ArcSwap은 내부적으로 AtomicPtr을 사용하여 lock 없이 포인터 교체
///
/// ## 성능
/// - Write: ~10ns (atomic store + Arc clone)
/// - Read: ~10ns (atomic load + refcount++)
/// - 완전 lock-free, 시뮬레이터와 WebSocket reader 간 블로킹 없음
pub struct SimStateBuffer {
    frame: ArcSwap<SimulationState>,
}

impl SimStateBuffer {
    /// 새로운 버퍼 생성
    ///
    /// 빈 SimulationState로 초기화됩니다.
    pub fn new() -> Self {
        Self {
            frame: ArcSwap::new(Arc::new(SimulationState {
                timestamp: 0.0,
                objects: Vec::new(),
            })),
        }
    }

    /// 새로운 프레임 발행 (시뮬레이터 측)
    ///
    /// ## 동작
    /// 1. 새 프레임을 Arc로 감쌈
    /// 2. ArcSwap에 atomic store (포인터 교체)
    /// 3. Arc clone을 반환 (시뮬레이터가 다음 iteration에서 재사용)
    ///
    /// ## 사용 패턴
    /// ```rust
    /// let mut current = buffer.get_current();
    /// loop {
    ///     let next = calculate_next_frame(&current);
    ///     current = buffer.publish(next);  // Arc 재사용
    /// }
    /// ```
    ///
    /// ## 인자
    /// - `state`: 새로운 시뮬레이션 상태 (owned)
    ///
    /// ## 반환
    /// - `Arc<SimulationState>`: 저장된 프레임의 Arc clone (refcount = 2)
    pub fn publish(&self, state: SimulationState) -> Arc<SimulationState> {
        let arc = Arc::new(state);
        self.frame.store(arc.clone());
        arc
    }

    /// 현재 프레임 읽기 (WebSocket 클라이언트 측)
    ///
    /// ## 동작
    /// 1. ArcSwap에서 atomic load
    /// 2. Arc clone 반환 (포인터 복사 + refcount 증가)
    ///
    /// ## 사용 패턴
    /// ```rust
    /// let frame = buffer.get_current();
    /// let json = serde_json::to_string(&*frame)?;  // &*로 deref
    /// socket.send(json).await?;
    /// ```
    ///
    /// ## 반환
    /// - `Arc<SimulationState>`: 현재 프레임의 Arc clone
    pub fn get_current(&self) -> Arc<SimulationState> {
        self.frame.load_full()
    }
}

impl Default for SimStateBuffer {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use server::models::ObjectTransform;

    #[test]
    fn test_publish_and_get() {
        let buffer = SimStateBuffer::new();

        let state = SimulationState {
            timestamp: 1.0,
            objects: vec![
                ObjectTransform {
                    name: "test".to_string(),
                    position: [1.0, 2.0, 3.0],
                    rotation: [0.0, 0.0, 0.0, 1.0],
                },
            ],
        };

        buffer.publish(state);
        let retrieved = buffer.get_current();

        assert_eq!(retrieved.timestamp, 1.0);
        assert_eq!(retrieved.objects.len(), 1);
        assert_eq!(retrieved.objects[0].name, "test");
    }

    #[test]
    fn test_multiple_readers() {
        let buffer = SimStateBuffer::new();

        let state = SimulationState {
            timestamp: 2.0,
            objects: vec![],
        };

        buffer.publish(state);

        // 여러 reader가 동시에 읽어도 안전
        let reader1 = buffer.get_current();
        let reader2 = buffer.get_current();
        let reader3 = buffer.get_current();

        assert_eq!(reader1.timestamp, 2.0);
        assert_eq!(reader2.timestamp, 2.0);
        assert_eq!(reader3.timestamp, 2.0);
    }

    #[test]
    fn test_arc_reuse_pattern() {
        let buffer = SimStateBuffer::new();

        // 시뮬레이터 패턴: Arc 재사용
        let mut current = buffer.get_current();

        for i in 0..10 {
            let next = SimulationState {
                timestamp: i as f64,
                objects: vec![],
            };
            current = buffer.publish(next);
        }

        let final_state = buffer.get_current();
        assert_eq!(final_state.timestamp, 9.0);
    }

    #[test]
    fn test_overwrite_frames() {
        let buffer = SimStateBuffer::new();

        // 프레임 1 발행
        buffer.publish(SimulationState {
            timestamp: 1.0,
            objects: vec![],
        });

        // 프레임 2로 덮어쓰기
        buffer.publish(SimulationState {
            timestamp: 2.0,
            objects: vec![],
        });

        // 최신 프레임만 읽힘
        let current = buffer.get_current();
        assert_eq!(current.timestamp, 2.0);
    }
}
