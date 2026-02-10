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

- Simulation Authority
  - 물리 상태의 단일 진실원(Source of Truth)은 서버 시뮬레이션이다.
  - 클라이언트는 상태를 보간(interpolation)하여 렌더링한다.

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
  - 상태 메시지 시퀀스 번호
  - 드롭/역순 수신 감지

- server_time_sec (number, optional)
  - 서버 wall-clock timestamp

--------------------------------------------------
Part Index Agreement (Optional)
--------------------------------------------------

입력 프로토콜(06_runtime_input_schema.md)에서
target.partIndex를 사용할 경우, 서버/클라이언트는
parts 배열의 순서를 항상 합의해야 한다.

권장 방식 1) 고정 순서 유지

- metadata bodies 순서 기반
- 또는 name 정렬

권장 방식 2) partNames 매핑 제공

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

--------------------------------------------------
Extended Telemetry (UPDATED, Optional)
--------------------------------------------------

교육용 시뮬레이터 및 디버깅 목적에서,
다음 물리량을 선택적으로 출력할 수 있다.

### Velocities

{
  "name": "shaft",
  "pos": {...},
  "rot": {...},

  "lin_vel_world": { "x": 0.0, "y": 0.0, "z": 0.0 },
  "ang_vel_world": { "x": 0.0, "y": 5.0, "z": 0.0 }
}

- PyChrono
  - GetPos_dt()
  - GetAngVelParent() or converted world angvel

### Reaction Forces (Joint)

{
  "jointName": "rev_shaft_base",
  "reaction_force_world": {...},
  "reaction_torque_world": {...}
}

- ChLink.GetReactionForce()
- ChLink.GetReactionTorque()

### Motor Telemetry

{
  "actuatorName": "shaft_motor",
  "applied_torque": 2.5,
  "angular_speed": 4.8
}

교육 시각화 / 그래프 / UI 피드백용

--------------------------------------------------
Contact / Collision Debug (UPDATED, Optional)
--------------------------------------------------

충돌 구현 이후 디버그/교육 목적 출력 확장 가능.

예:

{
  "contacts": [
    {
      "bodyA": "gear_A",
      "bodyB": "gear_B",
      "point_world": { "x": 0.01, "y": 0.03, "z": 0.02 },
      "normal_world": { "x": 1.0, "y": 0.0, "z": 0.0 },
      "normal_force": 12.5
    }
  ]
}

용도:

- 접촉 시각화
- 기어 맞물림 교육
- 충돌 디버깅

--------------------------------------------------
Interaction Debug (Optional)
--------------------------------------------------

AR 상호작용 디버그용 출력 확장.

{
  "activeInteraction": {
    "interactionId": "uuid",
    "partName": "shaft",
    "mode": "rotate"
  }
}

- 현재 조작 대상 표시
- rotate / spring 모드 시각화 가능

--------------------------------------------------
Design Rules
--------------------------------------------------

- 출력은 렌더링 가능한 포즈 제공이 1차 목적
- 물리 상세값은 optional telemetry로 확장
- name은 metadata와 1:1 매핑
- quaternion ordering은 (w,x,y,z) 고정
- 서버 상태가 authoritative

--------------------------------------------------
Future Extensions
--------------------------------------------------

- constraint forces visualization
- energy / power telemetry
- gear mesh slip detection
- collision heatmap
- educational overlay data
