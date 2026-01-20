# AR 터치 입력 시스템 분석 및 구현 계획

## 📋 프로토타입 분석 결과

### 1. 클라이언트 측 동작 방식 (Unity)

#### 1.1 ARInteractionController.cs - 터치 처리 로직

**터치 이벤트 3단계:**

1. **TouchStart** (터치 시작)
   - 스크린 좌표 → Ray 생성
   - Physics.Raycast로 3D 오브젝트 hit 검출
   - Hit된 오브젝트에서:
     - `worldHitPoint`: 월드 공간 좌표 (글로벌 좌표)
     - `localHitPoint`: 로컬 공간 좌표 (부품 기준 좌표)
     - `partIndex`: CompositeModel에서의 부품 인덱스
   - 서버로 전송할 데이터:
     ```json
     {
       "type": "TouchStart",
       "payload": {
         "targetPartIndex": <int>,           // 터치한 부품의 인덱스
         "actionPoint": {x, y, z},           // 로컬 좌표 (부품 기준)
         "fingerPoint": {x, y, z},           // 카메라(폰) 위치
         "z_direction": {x, y, z}            // 카메라 forward 방향
       }
     }
     ```

2. **Touching** (터치 이동 중)
   - 부품을 터치 중일 때만 (`_isTouching == true`)
   - 카메라 위치와 방향만 업데이트하여 전송
   - `actionPoint`는 고정 (처음 터치한 지점 유지)
   - 서버로 전송할 데이터:
     ```json
     {
       "type": "Touching",
       "payload": {
         "fingerPoint": {x, y, z},           // 변경된 카메라 위치
         "z_direction": {x, y, z}            // 변경된 카메라 방향
       }
     }
     ```

3. **TouchEnd** (터치 종료)
   - 터치 해제 시 전송
   - 빈 payload
   - 서버로 전송할 데이터:
     ```json
     {
       "type": "TouchEnd",
       "payload": {}
     }
     ```

#### 1.2 좌표 계산 방법

```csharp
// 1. 스크린 → 월드 레이캐스트
Ray ray = Camera.main.ScreenPointToRay(screenPos);

// 2. 물리 충돌 검사
if (Physics.Raycast(ray, out hit, Mathf.Infinity))
{
    Vector3 worldHitPoint = hit.point;                                  // 글로벌 좌표
    Vector3 localHitPoint = hitObject.transform.InverseTransformPoint(worldHitPoint);  // 로컬 좌표

    // 3. 카메라 정보
    Vector3 fingerPoint = Camera.main.transform.position;    // 폰의 위치
    Vector3 zDirection = Camera.main.transform.forward;      // 카메라가 보는 방향
}
```

#### 1.3 부품 인덱스 찾기

```csharp
private int GetPartIndex(GameObject partObject)
{
    // 1. 실제 메쉬 → 부모 wrapper 찾기
    Transform wrapper = partObject.transform.parent;

    // 2. CompositeModel 찾기
    CompositeModel model = wrapper.GetComponentInParent<CompositeModel>();

    // 3. CompositeModel의 파트 리스트에서 인덱스 찾기
    for (int i = 0; i < model.GetPartCount(); i++)
    {
        if (model.GetPart(i) == wrapper.gameObject)
            return i;
    }
    return -1;
}
```

---

### 2. 서버 측 처리 방식 (Python/Rust)

#### 2.1 메시지 수신 (server_logic.py)

```python
# WebSocket에서 수신한 메시지
msg = json.loads(data)
msg_type = msg.get("type")  # "TouchStart", "Touching", "TouchEnd"

# TouchStart 처리
if msg_type == "TouchStart":
    payload = msg.get("payload", {})
    part_idx = payload.get("targetPartIndex", -1)
    action_pt = payload.get("actionPoint", {})  # {x, y, z}
    finger_pt = payload.get("fingerPoint", {})  # {x, y, z}
    z_dir = payload.get("z_direction", {})      # {x, y, z}

    # 터치 상태 저장
    self.touch_state = {
        "active": True,
        "part_index": part_idx,
        "action_point_local": ChVector3d(action_pt.x, action_pt.y, action_pt.z)
    }
```

#### 2.2 물리 시뮬레이션 적용

- `actionPoint` (로컬 좌표): 힘이 가해지는 지점
- `fingerPoint` (월드 좌표): 카메라 위치 = 사용자 손가락 위치
- `z_direction`: 카메라 방향 = 힘의 방향

시뮬레이션에서:
1. `actionPoint`를 월드 좌표로 변환
2. `fingerPoint`와 `actionPoint` 사이의 벡터로 힘의 크기/방향 계산
3. 부품에 힘 적용

---

## 🎯 새 프로젝트 구현 계획

### Phase 1: 클라이언트 측 (Unity C#)

#### 1.1 TouchRaycastInput.cs 작성
**위치:** `ar_client/Assets/Scripts/Input/TouchRaycastInput.cs`

**역할:**
- 터치/마우스 입력 감지
- 레이캐스트로 오브젝트 hit 검출
- 좌표 계산 (글로벌 → 로컬 변환)
- 부품 인덱스 찾기
- 서버로 메시지 전송

**주요 메서드:**
```csharp
public class TouchRaycastInput : MonoBehaviour
{
    private ServerProxy _server;
    private bool _isTouching = false;
    private Vector3 _touchStartWorldPoint;
    private int _selectedPartIndex = -1;

    void Update()
    {
        HandleTouchInput();
    }

    private void HandleTouchStart(Vector2 screenPos)
    {
        // Ray 생성 및 레이캐스트
        // 좌표 계산 (월드, 로컬)
        // 부품 인덱스 찾기
        // TouchStart 메시지 전송
    }

    private void HandleTouchMove(Vector2 screenPos)
    {
        // Touching 메시지 전송 (fingerPoint, z_direction만)
    }

    private void HandleTouchEnd()
    {
        // TouchEnd 메시지 전송
        // 상태 초기화
    }

    private int GetPartIndex(GameObject hitObject)
    {
        // CompositeModel에서 인덱스 찾기
    }
}
```

#### 1.2 TouchRaycastMessage.cs 작성
**위치:** `ar_client/Assets/Scripts/Input/TouchRaycastMessage.cs`

**역할:**
- 터치 레이캐스트 입력 메시지 데이터 구조 정의
- JSON 직렬화

```csharp
namespace CADverse.Input
{
    [Serializable]
    public class TouchStartMessage
    {
        public string type = "TouchStart";
        public TouchStartPayload payload;
    }

    [Serializable]
    public class TouchStartPayload
    {
        public int targetPartIndex;
        public Vector3Data actionPoint;     // 로컬 좌표
        public Vector3Data fingerPoint;     // 카메라 위치
        public Vector3Data z_direction;     // 카메라 방향
    }

    [Serializable]
    public class TouchingMessage
    {
        public string type = "Touching";
        public TouchingPayload payload;
    }

    [Serializable]
    public class TouchingPayload
    {
        public Vector3Data fingerPoint;     // 카메라 위치
        public Vector3Data z_direction;     // 카메라 방향
    }

    [Serializable]
    public class TouchEndMessage
    {
        public string type = "TouchEnd";
        public object payload = new object();  // 빈 객체
    }

    [Serializable]
    public class Vector3Data
    {
        public float x, y, z;

        public Vector3Data(Vector3 v)
        {
            x = v.x; y = v.y; z = v.z;
        }
    }
}
```

#### 1.3 ServerProxy 수정
**위치:** `ar_client/Assets/Scripts/Server/ServerProxy.cs`

**추가 메서드:**
```csharp
/// <summary>
/// 터치 레이캐스트 입력 전송
/// </summary>
public async Task SendTouchRaycastInput(string json)
{
    if (!IsConnected) return;

    await _wsClient.SendTextAsync(json);
}
```

---

### Phase 2: 서버 측 (Rust)

#### 2.1 DataModel 확장
**위치:** `sim_server/crates/server/src/models.rs`

**추가 구조체:**
```rust
#[derive(Debug, Deserialize, Serialize)]
pub struct TouchStartMessage {
    pub r#type: String,  // "TouchStart"
    pub payload: TouchStartPayload,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct TouchStartPayload {
    #[serde(rename = "targetPartIndex")]
    pub target_part_index: i32,
    #[serde(rename = "actionPoint")]
    pub action_point: Vector3,
    #[serde(rename = "fingerPoint")]
    pub finger_point: Vector3,
    pub z_direction: Vector3,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct TouchingMessage {
    pub r#type: String,  // "Touching"
    pub payload: TouchingPayload,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct TouchingPayload {
    #[serde(rename = "fingerPoint")]
    pub finger_point: Vector3,
    pub z_direction: Vector3,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct TouchEndMessage {
    pub r#type: String,  // "TouchEnd"
    pub payload: serde_json::Value,  // empty object
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Vector3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}
```

#### 2.2 WebSocket 핸들러 수정
**위치:** `sim_server/crates/server/src/websocket.rs`

**메시지 파싱 및 처리:**
```rust
async fn handle_websocket_message(
    msg: String,
    sim_input: Arc<ArcSwap<Option<SimulationInput>>>,
) -> Result<(), Error> {
    // JSON 파싱
    let value: serde_json::Value = serde_json::from_str(&msg)?;
    let msg_type = value["type"].as_str().unwrap_or("");

    match msg_type {
        "TouchStart" => {
            let touch_msg: TouchStartMessage = serde_json::from_value(value)?;
            // SimulationInput 업데이트
            let input = SimulationInput::TouchStart {
                part_index: touch_msg.payload.target_part_index,
                action_point: touch_msg.payload.action_point,
                finger_point: touch_msg.payload.finger_point,
                z_direction: touch_msg.payload.z_direction,
            };
            sim_input.store(Arc::new(Some(input)));
            info!("TouchStart received: part={}", touch_msg.payload.target_part_index);
        }
        "Touching" => {
            let touch_msg: TouchingMessage = serde_json::from_value(value)?;
            // fingerPoint와 z_direction 업데이트
            let input = SimulationInput::Touching {
                finger_point: touch_msg.payload.finger_point,
                z_direction: touch_msg.payload.z_direction,
            };
            sim_input.store(Arc::new(Some(input)));
            info!("Touching received");
        }
        "TouchEnd" => {
            // 입력 클리어
            sim_input.store(Arc::new(None));
            info!("TouchEnd received");
        }
        _ => {
            warn!("Unknown message type: {}", msg_type);
        }
    }

    Ok(())
}
```

#### 2.3 SimulationInput enum 정의
**위치:** `sim_server/crates/simulation/src/types.rs`

```rust
#[derive(Debug, Clone)]
pub enum SimulationInput {
    TouchStart {
        part_index: i32,
        action_point: Vector3,   // 로컬 좌표
        finger_point: Vector3,   // 월드 좌표
        z_direction: Vector3,
    },
    Touching {
        finger_point: Vector3,
        z_direction: Vector3,
    },
}
```

---

## 📝 구현 체크리스트

### Client (Unity)
- [ ] `TouchRaycastInput.cs` 생성
  - [ ] 터치/마우스 입력 감지
  - [ ] 레이캐스트 구현
  - [ ] 글로벌 → 로컬 좌표 변환
  - [ ] 부품 인덱스 찾기
  - [ ] TouchStart 메시지 전송
  - [ ] Touching 메시지 전송
  - [ ] TouchEnd 메시지 전송
- [ ] `TouchRaycastMessage.cs` 생성
  - [ ] TouchStartMessage 구조체
  - [ ] TouchingMessage 구조체
  - [ ] TouchEndMessage 구조체
  - [ ] Vector3Data 구조체
  - [ ] JSON 직렬화
- [ ] `ServerProxy.cs` 수정
  - [ ] SendTouchRaycastInput 메서드 추가
- [ ] MainManager 연결
  - [ ] TouchRaycastInput 컴포넌트 추가
  - [ ] ServerProxy 참조 전달

### Server (Rust)
- [ ] `models.rs` 확장
  - [ ] TouchStartMessage 구조체
  - [ ] TouchingMessage 구조체
  - [ ] TouchEndMessage 구조체
  - [ ] Vector3 구조체
- [ ] `websocket.rs` 수정
  - [ ] 메시지 타입별 파싱
  - [ ] TouchStart 처리
  - [ ] Touching 처리
  - [ ] TouchEnd 처리
  - [ ] SimulationInput 업데이트
- [ ] `simulation` 크레이트 수정
  - [ ] SimulationInput enum 정의
  - [ ] 입력 처리 로직 (물리 시뮬레이션)

---

## 🔑 핵심 포인트

### 1. 좌표 시스템
- **actionPoint**: 부품 로컬 좌표 (부품 기준)
- **fingerPoint**: 월드 좌표 (카메라 위치)
- **worldHitPoint**: 월드 좌표 (레이캐스트 hit 지점)
- Unity의 `InverseTransformPoint`로 월드 → 로컬 변환

### 2. 터치 상태 관리
- TouchStart에서 `_isTouching = true`, 부품 인덱스 저장
- Touching은 `_isTouching == true`일 때만 전송
- TouchEnd에서 상태 초기화

### 3. 레이캐스트 요구사항
- 부품에 MeshCollider 필수
- CompositeModel 구조 필요:
  ```
  CompositeModel
  ├─ Part0_wrapper (로컬 오프셋 적용)
  │  └─ Part0_mesh (실제 메쉬 + MeshCollider)
  ├─ Part1_wrapper
  │  └─ Part1_mesh
  ...
  ```

### 4. 메시지 형식
- JSON 문자열로 전송
- `type` 필드로 메시지 구분
- `payload`에 실제 데이터

---

## 📚 참고: 프로토타입 파일 구조

```
prototype/
├── ar_client/Assets/Scripts/
│   ├── AR_Interaction/
│   │   ├── ARInteractionController.cs    ✅ 터치 입력 처리
│   │   └── ForceArrowVisualizer.cs        (화살표 시각화)
│   ├── Communication/
│   │   ├── SimServer.cs                   ✅ 서버 통신 래퍼
│   │   └── SimServerDataModels.cs         ✅ 데이터 모델
│   └── AR_World/
│       ├── CompositeModel.cs              ✅ 부품 컨테이너
│       └── ModelStateSetter.cs            (상태 업데이트)
└── sim_server/
    ├── server_logic.py                    ✅ 서버 로직
    ├── server_data_models.py              ✅ 데이터 모델
    └── sim_logic.py                       (시뮬레이션 로직)
```

---

## 🚀 구현 순서

1. **Client 먼저 구현** (테스트 쉬움)
   - TouchRaycastInput 기본 구조
   - 레이캐스트 및 로그 출력
   - 메시지 생성 및 JSON 직렬화
   - ServerProxy로 전송

2. **Server 구현**
   - 메시지 수신 및 파싱
   - 로그로 확인
   - SimulationInput 업데이트

3. **통합 테스트**
   - Unity Editor에서 마우스 클릭
   - 서버 로그 확인
   - WebSocket 연결 확인

4. **물리 시뮬레이션 연결** (별도 작업)
   - SimulationInput을 받아서 힘 계산
   - 부품에 힘 적용

---

## 🔮 향후 확장 계획

현재 구현하는 **터치 레이캐스트 입력**은 손가락으로 화면을 터치하여 3D 오브젝트를 선택하는 방식입니다.

**향후 추가될 입력 방식:**
- **HandJointInput**: 손 관절 추적 기반 입력 (AR Foundation Hand Tracking)
- **GestureInput**: 제스처 기반 입력 (핀치, 스와이프 등)
- **VoiceInput**: 음성 명령 입력
- **ControllerInput**: AR 컨트롤러 입력

각 입력 방식은 독립적인 컴포넌트로 구현되며, 모두 ServerProxy를 통해 메시지를 전송합니다.

**명명 규칙:**
- `Touch` → 터치 기반
- `Raycast` → 레이캐스트 사용
- `HandJoint` → 손 관절 추적
- `Gesture` → 제스처 인식
- 등등...
