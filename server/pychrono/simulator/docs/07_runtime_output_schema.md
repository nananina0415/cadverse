# docs/07_runtime_output_schema.md

Runtime Output Schema (Server → Client)
======================================

본 문서는 서버(시뮬레이션)가 클라이언트(AR / Renderer / UI)로 전송하는
런타임 출력(SimState) 메시지의 JSON 스키마를 정의한다.

출력 메시지는 물리 시뮬레이션의 현재 상태를 전달하기 위한 것이며,
CAD / Metadata / Scene 정의와는 목적이 다르다.

- 입력 스키마: 06_runtime_input_schema.md
- 메타데이터 스키마: 03_metadata_schema.md


--------------------------------------------------
Global Rules
--------------------------------------------------

Units
-----

| Quantity | Unit |
|----------|------|
| Length | meter (m) |
| Angle | radian (rad) |
| Time | second (s) |
| Velocity | m/s |
| Angular velocity | rad/s |
| Force | N |
| Torque | N·m |
| Power | W |

Coordinate System
-----------------

- Right-handed
- WORLD 기준 좌표 사용

Quaternion Ordering
-------------------

프로젝트 표준:

(w, x, y, z)

Chrono mapping:

e0 = w
e1 = x
e2 = y
e3 = z

Encoding
--------

- UTF-8 JSON

Simulation Authority
--------------------

- 물리 상태의 단일 진실원(Source of Truth)은 서버 시뮬레이션이다.
- 클라이언트는 상태를 보간(interpolation)하여 렌더링한다.


--------------------------------------------------
Core Types
--------------------------------------------------

Vector3 (WORLD)

{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}


Quaternion (WORLD)

{
  "w": 1.0,
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}


--------------------------------------------------
PartState
--------------------------------------------------

단일 강체의 상태.

{
  "name": "gear_A",
  "pos": { "x": 0.0, "y": 0.03, "z": 0.03 },
  "rot": { "w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0 }
}

Field

| field | type | unit | optional | description |
|--------|------|-------|----------|-------------|
| name | string | - | no | metadata bodies[*].name |
| pos | Vector3 | m | no | WORLD position |
| rot | Quaternion | - | no | WORLD rotation |

Notes

- rot는 항상 normalized quaternion
- name은 metadata와 반드시 동일해야 한다


--------------------------------------------------
SimState
--------------------------------------------------

서버가 클라이언트로 전송하는 런타임 상태 메시지.

기본 구조

{
  "sim_time": 0.0,
  "parts": [ PartState ]
}

Field

| field | type | unit | optional | description |
|--------|------|-------|----------|-------------|
| sim_time | number | s | no | simulation time |
| parts | array | - | no | PartState list |


--------------------------------------------------
Message Metadata (Optional)
--------------------------------------------------

{
  "sim_time": 0.0,
  "seq": 120,
  "server_time_sec": 1730000000.0,
  "parts": [ ... ]
}

| field | type | optional | description |
|--------|--------|----------|------------|
| seq | int | yes | message sequence |
| server_time_sec | number | yes | server timestamp |
| partNames | string[] | yes | index mapping |


--------------------------------------------------
Contact Telemetry (Optional)
--------------------------------------------------

{
  "telemetry": {
    "contact_count": 4,
    "max_contact_force": 120.0,
    "max_pair": {
      "bodyA": "gear_A",
      "bodyB": "gear_B"
    }
  }
}

| field | type | unit | description |
|--------|------|------|-------------|
| contact_count | int | - | number of contacts |
| max_contact_force | number | N | max force |
| max_pair | object | - | body pair |


--------------------------------------------------
Gear Telemetry (Optional)
--------------------------------------------------

{
  "gearTelemetry": {
    "gp1": {
      "applied_efficiency": 0.8,
      "loss_torque": 0.01,
      "backlash_deadband": 0.02
    }
  }
}

| field | type | unit | description |
|--------|------|------|-------------|
| applied_efficiency | number | - | 0~1 |
| loss_torque | number | N·m | loss |
| backlash_deadband | number | rad | deadband |


--------------------------------------------------
Assembly Telemetry (Optional)
--------------------------------------------------

{
  "assemblyTelemetry": {
    "guide1": {
      "activeSnap": true,
      "snapCandidate": "target",
      "snapErrorPos": 0.02,
      "snapErrorAngle": 0.1,
      "snapMode": "assist"
    }
  }
}

| field | unit | description |
|--------|------|-------------|
| activeSnap | - | active |
| snapCandidate | - | name |
| snapErrorPos | m | position error |
| snapErrorAngle | rad | angle error |
| snapMode | - | assist / snap |


--------------------------------------------------
Joint Telemetry (Optional)
--------------------------------------------------

{
  "jointTelemetry": {
    "rev0": {
      "jointType": "revolute",
      "angle": 0.5,
      "angularVelocity": 2.0,
      "reactionForce": {...},
      "reactionTorque": {...},
      "estimatedPower": 1.2
    }
  }
}

| field | unit | description |
|--------|------|-------------|
| angle | rad | revolute |
| position | m | prismatic |
| angularVelocity | rad/s | |
| linearVelocity | m/s | |
| reactionForce | N | |
| reactionTorque | N·m | |
| estimatedPower | W | approx |


--------------------------------------------------
Actuator Telemetry (Optional)
--------------------------------------------------

{
  "actuatorTelemetry": {
    "motor0": {
      "actuatorType": "rotation_speed",
      "targetJoint": "rev0",
      "commandedSpeed": 5.0,
      "appliedTorque": 1.2,
      "estimatedPower": 2.3
    }
  }
}

| field | unit |
|--------|------|
| commandedSpeed | rad/s |
| commandedTorque | N·m |
| appliedTorque | N·m |
| estimatedPower | W |


--------------------------------------------------
Diagnostics (Optional)
--------------------------------------------------

{
  "diagnostics": [
    {
      "code": "AT_JOINT_LIMIT",
      "severity": "warn",
      "message": "joint limit reached",
      "target": "rev0"
    }
  ]
}

| field | description |
|--------|-------------|
| code | diagnostic id |
| severity | info / warn / error |
| message | text |
| target | object name |


Example codes

- AT_JOINT_LIMIT
- RESTING_CONTACT
- LIKELY_BLOCKED_BY_CONSTRAINT
- TARGET_FIXED


--------------------------------------------------
Design Rules
--------------------------------------------------

- 출력은 pose 전달이 기본 목적
- telemetry는 optional
- 서버 상태가 authoritative
- optional field는 생략 가능


--------------------------------------------------
Future Extensions
--------------------------------------------------

- power graphs
- constraint visualization
- slip detection
- energy telemetry
- education overlay
