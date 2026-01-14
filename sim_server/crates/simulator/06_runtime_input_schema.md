# docs/06_runtime_input_schema.md

Runtime Input Schema (Client → Server)
=====================================

본 문서는 AR/클라이언트가 서버(시뮬레이션)로 전송하는
런타임 상호작용 입력(UserInput) 이벤트의 JSON 스키마를 정의한다.

본 스키마는 CAD → JSON 메타데이터(03_metadata_schema.md)와 별개이며,
"사용자 입력(의도)"를 시뮬레이션 엔진이 해석 가능한 형태로 전달하기 위해 존재한다.

시뮬레이션 엔진은 본 입력을 사용하여
토크/속도/제어 명령을 생성하거나 적용할 수 있다.

--------------------------------------------------
Global Notes
--------------------------------------------------

- Units
  - 위치/길이: meter (m)
  - 각도: radian (rad)

- Coordinate system
  - Right-handed

- Quaternion ordering (프로젝트 표준, Chrono 매핑)
  - (w, x, y, z)
  - 문서/메타데이터/런타임 모두 동일하게 유지한다.

- Encoding
  - UTF-8 JSON

- Update Frequency (권장)
  - Client → Server Interaction: 이벤트 기반 + 필요 시 30~60 Hz 권장

--------------------------------------------------
Core Types (02_core_types.md와 동일)
--------------------------------------------------

Vector3 (WORLD)

{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

Quaternion (WORLD rotation)

{
  "w": 1.0,
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

PartIndex

- parts 배열의 인덱스 (0-based)
- Server → Client Output의 parts[i] 와 동일한 순서라고 가정한다.
- (안정성을 위해) name 기반 식별자도 함께 지원할 수 있다.

--------------------------------------------------
UserInput Envelope
--------------------------------------------------

클라이언트 → 서버 메시지는 아래 공통 구조를 가진다.

{
  "type": "<EventType>",
  "payload": { ... }
}

EventType은 아래 중 하나이다.
- "TouchStart"
- "Touching"
- "TouchEnd"

--------------------------------------------------
InteractByScreen (Touch / Drag)
--------------------------------------------------

터치 기반 상호작용 이벤트 스트림.
클라이언트는 TouchStart → Touching(0..N회) → TouchEnd 순으로 전송한다.

좌표계 규칙:
- fingerPoint, z_direction: WORLD
- actionPoint: BODY-LOCAL (타겟 파트의 로컬 좌표)

### 1) TouchStart

{
  "type": "TouchStart",
  "payload": {
    "target": {
      "partIndex": 0,
      "partName": "gear_A"
    },
    "actionPointLocal": { "x": 0.0, "y": 0.0, "z": 0.0 },
    "fingerPointWorld": { "x": 0.12, "y": 0.05, "z": 0.30 },
    "cameraForwardWorld": { "x": 0.0, "y": 0.0, "z": 1.0 }
  }
}

Field Meaning
-------------

- target.partIndex (optional)
  - 사용자가 선택한(터치한) 파트의 인덱스
  - 인덱스 기반 프로토콜을 유지할 때 사용

- target.partName (optional)
  - 사용자가 선택한 파트의 name
  - parts 배열 순서가 바뀌어도 안전하게 식별 가능
  - 서버/엔진은 가능하면 name을 우선 사용하고, 없으면 index로 fallback 권장

- actionPointLocal
  - 타겟 파트의 로컬 좌표계에서의 작용점(접촉점)
  - "어느 지점을 잡고 조작하는지"를 표현한다.

- fingerPointWorld
  - 터치/포인터의 월드 좌표 위치
  - 이후 Touching 이벤트에서 업데이트됨

- cameraForwardWorld
  - 카메라 전방 방향(또는 화면 법선) 월드 방향 벡터
  - 정규화(normalized) 권장
  - 기존 프로토타입의 z_direction과 동일 의미

### 2) Touching

TouchStart 이후 드래그 중일 때 반복 전송되는 이벤트.

{
  "type": "Touching",
  "payload": {
    "fingerPointWorld": { "x": 0.10, "y": 0.05, "z": 0.29 },
    "cameraForwardWorld": { "x": 0.0, "y": 0.0, "z": 1.0 }
  }
}

Notes
-----

- TouchStart에서 지정된 target(파트 선택)과 actionPointLocal은 유지된다고 가정한다.
- fingerPointWorld는 사용자의 드래그에 따라 지속적으로 갱신된다.

### 3) TouchEnd

터치 종료 이벤트.

{
  "type": "TouchEnd",
  "payload": {}
}

--------------------------------------------------
Behavior Rules (Recommended Interpretation)
--------------------------------------------------

본 스키마는 입력 데이터 형식만 정의한다.
입력을 물리 구동(토크/속도)으로 변환하는 방식은
시뮬레이션 엔진의 Interaction Controller가 담당한다.

권장 해석:

- TouchStart
  - 타겟(part) 선택 및 기준 벡터 설정
  - 필요 시 파트의 현재 pose/축 정보 캐싱

- Touching
  - fingerPointWorld 변화량 + cameraForwardWorld를 이용해
    드래그 방향/회전 방향 계산
  - 결과를 토크/속도 명령으로 변환하여 적용
    - torque actuator 사용 또는 body torque 적용

- TouchEnd
  - 입력 종료
  - 감쇠(damping)만 남기거나 제어 해제

--------------------------------------------------
Design Rules
--------------------------------------------------

- 입력 이벤트는 "의도(intent)"를 전달한다.
  (직접 force/torque 값을 보내는 것을 기본으로 하지 않는다)

- 좌표계 WORLD/LOCAL은 혼동되지 않도록 명확히 분리한다.
  - fingerPointWorld, cameraForwardWorld : WORLD
  - actionPointLocal                      : BODY-LOCAL

- target 식별자는 partName 지원을 권장한다.
  - 인덱스 기반만 사용할 경우, 서버/클라가 parts 순서를 항상 합의해야 한다.

--------------------------------------------------
Future Extensions (Optional)
--------------------------------------------------

- gesture 확장
  - Pinch(거리), Twist(회전), Two-finger translation 등

- constraint hint 전달
  - "이 파트는 x축 회전만 가능" 같은 affordance 정보
  - (메타데이터 또는 별도 UX schema로 분리 권장)
