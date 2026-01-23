use serde::{Deserialize, Serialize};

// TypeScript 인터페이스에서 자동 생성된 입력 메시지 구조체
use interface_codegen_macro::generate_from_typescript;
generate_from_typescript!("touch_raycast_input.ts");

/// 모든 터치 레이캐스트 입력을 포함하는 열거형
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum TouchRaycastInput {
    TouchStart(TouchStartPayload),
    Touching(TouchingPayload),
    TouchEnd(TouchEndPayload),
}

// 서버 → 클라이언트 메시지

/// 오브젝트의 위치와 회전 정보
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObjectTransform {
    pub name: String,
    pub position: [f32; 3],  // [x, y, z]
    pub rotation: [f32; 4],  // [x, y, z, w] (quaternion)
}

/// 서버 → 클라이언트: 오브젝트 상태 업데이트
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SimulationState {
    pub timestamp: f64,
    pub objects: Vec<ObjectTransform>,
}

/// 오브젝트 리스트 응답
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObjectList {
    pub objects: Vec<String>,
}
