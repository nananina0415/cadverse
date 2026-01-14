# docs/06_ar_interaction_schema.md

AR Interaction Schema (Runtime Input Protocol)
==============================================

본 문서는 AR/클라이언트가 서버(시뮬레이션)로 전송하는
상호작용 입력 이벤트의 JSON 스키마를 정의한다.

본 스키마는 "CAD → JSON 메타데이터"와 별개로,
런타임에서 발생하는 사용자 상호작용(터치/드래그)을
시뮬레이션 엔진이 해석 가능한 형태로 전달하기 위해 존재한다.

시뮬레이션 엔진은 본 문서의 입력만을 사용하여
토크/속도/제어 명령을 생성하거나 적용할 수 있다.

--------------------------------------------------
Global Notes
--------------------------------------------------

- Units
  - 모든 위치/길이: meter (m)
  - 모든 각도: radian (rad)
- Rotation Quaternion Ordering (Chrono)
  - e0 = w, e1 = x, e2 = y, e3 = z
- Encoding
  - UTF-8 JSON
- Update Frequency (recommended)
  - Server → Client ModelState: 10 Hz (100 ms)
  - Client → Server Interaction: 이벤트 기반 + 필요 시 30~60 Hz 권장

--------------------------------------------------
Core Types
--------------------------------------------------

Vector3

{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

Orientation (Quaternion)

{
  "e0": 1.0,
  "e1": 0.0,
  "e2": 0.0,
  "e3": 0.0
}

PartIndex

- parts 배열의 인덱스 (0-based)
- ModelStateMessage.parts[i] 와 동일한 순서라고 가정한다.

--------------------------------------------------
Server → Client
--------------------------------------------------

ModelStateMessage

서버가 클라이언트로 주기적으로 전송하는
"현재 시뮬레이션 상태" 메시지.

{
  "sim_time": 0.0,
  "parts": [
    {
      "pos": { "x": 0.0, "y": 0.0, "z": 0.0 },
      "rot": { "e0": 1.0, "e1": 0.0, "e2": 0.0, "e3": 0.0 }
    }
  ]
}

Notes
-----

- parts 배열의 순서는 "PartIndex"의 기준이 된다.
- rot는 쿼터니언이며 정규화(normalized)되어 있어야 한다.

--------------------------------------------------
Client → Server
--------------------------------------------------

InteractByScreen

터치 기반 상호작용의 이벤트 스트림.
클라이언트는 TouchStart → Touching(0..N회) → TouchEnd 순으로 전송한다.

### 1) TouchStart

{
  "type": "TouchStart",
  "payload": {
    "targetPartIndex": 0,
    "actionPoint": { "x": 0.0, "y": 0.0, "z": 0.0 },
    "fingerPoint": { "x": 0.12, "y": 0.05, "z": 0.30 },
    "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
  }
}

Field Meaning
-------------

- targetPartIndex
  - 사용자가 선택한(터치한) 파트의 인덱스

- actionPoint (LocalPosition)
  - 선택된 파트의 로컬 좌표계에서의 작용점(접촉점)
  - 즉, body-local position
  - 서버는 이 점을 통해 "어느 지점을 잡고 조작하는지"를 알 수 있다.

- fingerPoint (GlobalPosition)
  - 터치/포인터의 월드 좌표 위치
  - 이후 Touching 이벤트에서 업데이트됨

- z_direction (GlobalDirection)
  - 카메라의 전방 방향 또는 화면 법선에 대응되는 월드 방향 벡터
  - 일반적으로 "카메라 forward" (정규화 권장)

### 2) Touching

TouchStart 이후 드래그 중일 때 반복 전송되는 이벤트.

{
  "type": "Touching",
  "payload": {
    "fingerPoint": { "x": 0.10, "y": 0.05, "z": 0.29 },
    "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
  }
}

Notes
-----

- TouchStart에서 지정된 targetPartIndex, actionPoint는 유지된다고 가정한다.
- fingerPoint는 사용자의 드래그에 따라 지속적으로 갱신된다.

### 3) TouchEnd

터치가 종료되었음을 알리는 이벤트.

{
  "type": "TouchEnd",
  "payload": {}
}

--------------------------------------------------
Behavior Rules (Recommended Interpretation)
--------------------------------------------------

본 스키마는 "입력 데이터 형식"만 정의하며,
이를 "물리 구동(토크/속도)"으로 변환하는 방식은
시뮬레이션 엔진의 컨트롤러(Interaction Controller)가 담당한다.

기본 권장 해석은 아래와 같다.

- TouchStart
  - 조작 타겟(part) 선택 및 기준 벡터 설정
  - 필요 시 파트의 현재 pose/축 정보를 캐싱

- Touching
  - fingerPoint의 변화량과 z_direction을 이용해
    드래그 방향/회전 방향을 계산
  - 결과를 토크/속도 명령으로 변환하여 적용
    - torque actuator 사용 또는 body torque 적용

- TouchEnd
  - 입력 종료
  - 감쇠(damping)만 남기거나 제어 해제

--------------------------------------------------
Design Rules
--------------------------------------------------

- 상호작용 이벤트는 "의도(intent)"를 전달한다.
  (직접 force/torque를 보내는 것을 기본으로 하지 않는다)

- 좌표계는 WORLD/LOCAL이 혼동되지 않도록 명확히 구분한다.
  - fingerPoint, z_direction : WORLD
  - actionPoint             : BODY-LOCAL

- PartIndex 기반 프로토콜을 유지할 경우,
  서버와 클라이언트는 "parts 배열의 순서"를 항상 합의해야 한다.
  (안정성을 위해 향후 name 기반 ID로 확장 가능)

--------------------------------------------------
Future Extensions (Optional)
--------------------------------------------------

- targetPartName / stableId 지원
  - 인덱스 기반의 취약성을 줄이기 위해 name 기반 target 지정 가능

- gesture type 확장
  - Pinch(거리), Twist(회전), Two-finger translation 등

- constraint hint 전달
  - "이 파트는 x축 회전만 가능" 같은 affordance 정보
  - (이는 메타데이터 또는 별도 UX schema로 분리 권장)
