use serde::{Deserialize, Serialize};

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

/// 클라이언트 → 서버: 유저 입력
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserInput {
    pub input_type: String,  // "click", "drag", "key" 등
    pub data: serde_json::Value,
}

/// 오브젝트 리스트 응답
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObjectList {
    pub objects: Vec<String>,
}
