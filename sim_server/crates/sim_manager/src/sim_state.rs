// src/sim_state.rs
//
// Rust side simulation state definitions.
//
// 역할:
// - Python(PyChrono) 쪽 SimState / PartState를
//   Rust에서 안전하게 다루기 위한 "미러 구조체"
// - sim_manager 내부 (thread, buffer, network)에서 사용
//
// 설계 원칙:
// - Python runtime_types.SimState와 구조를 최대한 맞춘다
// - 불필요한 물리 계산 로직은 절대 넣지 않는다
// - Serialize 가능 (네트워크/로그/디버깅 용이)
// - Clone 가능 (StateBuffer publish 패턴에 유리)

use serde::Serialize;

/// 시뮬레이션 전체 상태
///
/// Python 쪽 runtime_types.SimState에 대응
#[derive(Debug, Clone, Serialize)]
pub struct SimState {
    /// 시뮬레이션 시간 (seconds)
    pub sim_time: f64,

    /// 모든 파트 상태
    pub parts: Vec<PartState>,
}

impl SimState {
    /// 빈 상태 생성 (초기화 / 에러 fallback 용)
    pub fn empty() -> Self {
        Self {
            sim_time: 0.0,
            parts: Vec::new(),
        }
    }
}

/// 개별 파트 상태
///
/// Python 쪽 runtime_types.PartState에 대응
#[derive(Debug, Clone, Serialize)]
pub struct PartState {
    /// 파트 이름 (metadata body name)
    pub name: String,

    /// 위치 (world, meters)
    pub pos: [f64; 3],

    /// 회전 (world quaternion: w, x, y, z)
    pub rot: [f64; 4],
}

impl PartState {
    /// 생성 헬퍼 (명시적 초기화용)
    pub fn new(
        name: impl Into<String>,
        pos: [f64; 3],
        rot: [f64; 4],
    ) -> Self {
        Self {
            name: name.into(),
            pos,
            rot,
        }
    }
}
