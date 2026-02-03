# docs/07_runtime_output_schema.md

Runtime Output Schema (Server → Client)
======================================

본 문서는 서버(시뮬레이션)가 클라이언트(AR/렌더러)로 전송하는
런타임 출력(SimState) 메시지의 JSON 스키마를 정의한다.

출력은 "물리 시뮬레이션 결과(강체 포즈)"를 전달하기 위한 것으로,
CAD/메타데이터(03_metadata_schema.md)와는 목적이 다르다.

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

- Encoding
  - UTF-8 JSON

- Update Frequency (권장)
  - Server → Client ModelState: 10 Hz (100 ms)
  - (필요 시) 더 높은 주파수는 네트워크/성능을 보고 조정

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

--------------------------------------------------
PartState
--------------------------------------------------

단일 바디(파트)의 상태.
AR 렌더링 및 클라이언트 동기화에 사용한다.

{
  "name": "gear_A",
  "pos": { "x": 0.0, "y": 0.03, "z": 0.03 },
  "rot": { "w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0 }
}

Notes
-----

- pos/rot는 WORLD 기준이다.
- rot는 정규화(normalized)되어 있어야 한다.
- name은 03_metadata_schema.md의 bodies[*].name 과 동일해야 한다.

--------------------------------------------------
SimState / ModelStateMessage
--------------------------------------------------

서버가 클라이언트로 주기적으로 전송하는
"현재 시뮬레이션 상태" 메시지.

기본 형태:

{
  "sim_time": 0.0,
  "parts": [
    {
      "name": "base",
      "pos": { "x": 0.0, "y": 0.0, "z": 0.0 },
      "rot": { "w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0 }
    },
    {
      "name": "shaft",
      "pos": { "x": 0.0, "y": 0.0, "z": 0.03 },
      "rot": { "w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0 }
    }
  ]
}

Field Meaning
-------------

- sim_time
  - 시뮬레이션 시간 (seconds)
  - 엔진 내부 dt 누적값

- parts
  - PartState 배열
  - 이 배열의 순서는 "PartIndex 기반 입력"의 기준이 될 수 있다.

--------------------------------------------------
Message Metadata (Recommended, Optional)
--------------------------------------------------

네트워크 동기/디버깅/정렬 안정성을 위해,
출력 메시지에 아래 필드를 선택적으로 포함하는 것을 권장한다.

{
  "sim_time": 0.0,
  "seq": 120,
  "server_time_sec": 1730000000.123,
  "parts": [ ... ]
}

- seq (integer, optional)
  - 서버가 전송하는 상태 메시지 시퀀스 번호(증가)
  - 클라이언트에서 드롭/역순 수신 감지에 사용

- server_time_sec (number, optional)
  - 서버 기준 wall-clock timestamp(초)
  - 클라이언트에서 지연 측정/보간에 활용 가능

--------------------------------------------------
Part Index Agreement (Optional)
--------------------------------------------------

입력 프로토콜(06_runtime_input_schema.md)에서
target.partIndex를 사용할 경우, 서버/클라이언트는
parts 배열의 순서를 항상 합의해야 한다.

권장 방식 1) parts를 "고정 순서"로 유지
- 서버는 항상 같은 순서로 parts를 출력한다.
- 예: metadata bodies의 순서, 또는 name 정렬 순서

권장 방식 2) partNames 테이블을 함께 제공 (더 안전)
- parts는 여전히 배열이지만, index→name 매핑을 명시한다.

{
  "sim_time": 0.0,
  "partNames": ["base", "shaft", "gear_A", "gear_B"],
  "parts": [
    { "pos": {...}, "rot": {...} },
    { "pos": {...}, "rot": {...} },
    { "pos": {...}, "rot": {...} },
    { "pos": {...}, "rot": {...} }
  ]
}

Notes
-----

- 위 방식은 네트워크 비용을 줄이면서도 index 안정성을 확보한다.
- 이 프로젝트는 name 기반 입력을 우선으로 두되,
  index 기반도 병행 지원하는 것을 권장한다.

권장 규칙(중요):
- 서버는 가능하면 partNames를 "초기 1회" 또는 "변경 시"에만 보내고,
  평상시에는 parts만 보내는 방식도 가능하다.
  (네트워크 절감 + 안정성 확보)

--------------------------------------------------
Design Rules
--------------------------------------------------

- 출력은 "렌더링 가능한 포즈"를 제공하는 것이 목적이다.
  (충돌/접촉/힘/토크 등 상세 물리량은 기본 스키마에서 제외)

- name은 메타데이터(bodies[*].name)와 1:1 매핑되어야 한다.

- Quaternion ordering은 반드시 (w,x,y,z)로 고정한다.
  (Rust/Unity 등에서 (x,y,z,w) 관습이 있으므로 특히 주의)

- 입력(target)과의 합의
  - 클라이언트 입력은 partName 우선(권장), partIndex는 보조(fallback)로 사용한다.
  - partIndex를 쓸 경우, Output의 parts 순서 또는 partNames 합의가 반드시 필요하다.

--------------------------------------------------
Future Extensions (Optional)
--------------------------------------------------

- velocities
  - 선속도/각속도 포함
  - 예: lin_vel_world, ang_vel_world

- forces
  - 접촉력, 모터 토크 등 디버깅용 물리량 포함

- contacts
  - 충돌 접촉점 정보 (디버그/시각화 목적)

- selection/interaction debug (선택)
  - 서버가 현재 어떤 part를 조작 중인지 표시하는 디버그 필드
  - 예: activeInteraction { interactionId, partName }
