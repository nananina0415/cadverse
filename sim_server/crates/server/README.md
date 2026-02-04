# server

axum 기반 HTTP/WebSocket 서버. AR 클라이언트에 시뮬레이션 상태 전송 및 OBJ 파일 서빙.

## 모듈 구조

```
src/
├── lib.rs        # 서버 초기화 + ServerState 정의
├── models/
│   └── mod.rs    # 데이터 모델 (SimulationState, TouchRaycastInput 등)
├── routes.rs     # HTTP 엔드포인트 (오브젝트 리스트, OBJ 다운로드, QR)
└── websocket.rs  # WebSocket 핸들러 (상태 전송 + 입력 수신)
```

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/cadverse` | WebSocket 업그레이드 |
| GET | `/cadverse/object` | 오브젝트 이름 리스트 (JSON) |
| GET | `/cadverse/object/{name}` | OBJ 메쉬 파일 다운로드 |
| GET | `/cadverse/qr` | QR 코드 패턴 (0/1 텍스트) |

### GET /cadverse/object

선택된 CAD 폴더에서 `.obj` 파일 목록 반환.

```json
{ "objects": ["base", "shaft", "gear"] }
```

### GET /cadverse/object/{name}

OBJ 파일 내용 반환. Content-Type: `model/obj`

### WebSocket /cadverse

양방향 통신:
- 서버 → 클라이언트: `SimulationState` (오브젝트 위치/회전)
- 클라이언트 → 서버: `TouchRaycastInput` (터치 입력)

## ServerState

```rust
pub struct ServerState {
    pub state_buffer: Arc<dyn Any + Send + Sync>,           // SimStateBuffer
    pub input_buffer: InputBuffer<TouchRaycastInput>,        // 입력 버퍼
    pub model_folder: Arc<ArcSwap<PathBuf>>,                 // OBJ 서빙 폴더
}
```

- `state_buffer`: `Arc<SimStateBuffer>`를 `Any`로 타입 소거하여 전달
- `input_buffer`: 시뮬레이션 스레드와 공유되는 트리플 버퍼
- `model_folder`: `ArcSwap`으로 런타임에 폴더 경로 교체 가능

## 데이터 모델 (models/)

### 서버 → 클라이언트

```rust
pub struct SimulationState {
    pub timestamp: f64,
    pub objects: Vec<ObjectTransform>,
}

pub struct ObjectTransform {
    pub name: String,
    pub position: [f32; 3],     // [x, y, z]
    pub rotation: [f32; 4],     // [x, y, z, w] (Unity 쿼터니언 순서)
}
```

### 클라이언트 → 서버

```rust
pub enum TouchRaycastInput {
    TouchStart(TouchStartPayload),
    Touching(TouchingPayload),
    TouchEnd(TouchEndPayload),
}
```

`interface_codegen_macro`로 TypeScript 인터페이스에서 자동 생성됨.

## 동적 폴더 서빙

OBJ 파일 서빙 경로가 하드코딩이 아닌 `model_folder`에서 동적으로 결정됨:

```rust
// routes.rs
let model_dir = state.model_folder.load_full();  // ArcSwap에서 현재 경로 읽기
let file_path = model_dir.join(format!("{}.obj", name));
```

## 의존성

| 크레이트 | 용도 |
|----------|------|
| `axum` | HTTP/WebSocket 프레임워크 |
| `arc-swap` | model_folder 동적 교체 |
| `serde`/`serde_json` | JSON 직렬화 |
| `qrcode` | QR 패턴 생성 |
| `local-ip-address` | 서버 IP 감지 |
