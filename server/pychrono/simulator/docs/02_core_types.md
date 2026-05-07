# docs/02_core_types.md

# Core Data Types

본 문서는 AR 기반 기구학 교육용 시뮬레이터에서
사용되는 핵심 데이터 타입과 표현 규칙을 정의한다.

모든 CAD → JSON → Simulation → Server → AR 파이프라인은
본 타입 규칙을 기반으로 동작한다.

---

## Vector3

3차원 벡터 타입.

위치, 방향, 회전축, 속도, 힘, 토크 등 다양한 물리량 표현에 사용된다.

### JSON Representation

{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

### Chrono Mapping

chrono.ChVector3d(x, y, z)

---

## Quaternion

회전을 표현하는 타입.

짐벌락(gimbal lock)을 방지하기 위해 모든 회전은 쿼터니언으로 표현한다.

### Ordering

(w, x, y, z)

### JSON Representation

{
  "w": 1.0,
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

### Chrono Mapping

chrono.ChQuaterniond(w, x, y, z)

---

## Pose

공간 상의 위치와 회전을 함께 표현하는 타입.

모든 바디의 초기 상태 및 시뮬레이션 결과에 사용된다.

### JSON Representation

{
  "pos": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "rot": {
    "w": 1.0,
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  }
}

### Chrono Mapping

- Position → chrono.ChVector3d
- Rotation → chrono.ChQuaterniond

---

## Frame

조인트, 액추에이터, 기준 좌표계를 정의하기 위한 타입.

Frame의 로컬 Z축은 회전축 또는 자유도 방향으로 사용된다.

### JSON Representation

{
  "pos": { ... },
  "rot": { ... }
}

### Chrono Mapping

chrono.ChFramed(position, rotation)

---

## Inertia (Rotational Inertia)

바디의 회전 관성을 정의하는 타입.

현실적인 동역학 거동을 위해 필수 요소이다.

### JSON Representation (Minimal)

{
  "Ixx": 0.01,
  "Iyy": 0.01,
  "Izz": 0.01
}

### Chrono Mapping

chrono.ChBody.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))

---

## ContactMaterial

접촉 시 마찰 및 탄성 특성을 정의하는 타입.

### JSON Representation

{
  "friction": 0.4,
  "restitution": 0.05
}

### Chrono Mapping

chrono.ChContactMaterialNSC

---

## PartState

시뮬레이션 결과로 출력되는 단일 바디의 상태.

### JSON Structure

{
  "name": "part_name",
  "pos": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "rot": {
    "w": 1.0,
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  }
}

### Source

- ChBody.GetPos()
- ChBody.GetRot()

---

## SimState

시뮬레이션 한 스텝의 전체 상태.

### JSON Structure

{
  "sim_time": 0.0,
  "parts": [
    PartState,
    ...
  ]
}

### Optional Fields

- partNames
- telemetry
- interactionTelemetry
- gearTelemetry
- assemblyTelemetry
- jointTelemetry
- actuatorTelemetry
- diagnostics
- warnings

---

## UserInput (Interaction Events)

외부 입력(AR / 서버)에서 전달되는 사용자 상호작용 이벤트.

직접적인 물리값이 아닌 “의도(intent)” 기반 입력으로 정의된다.

### Structure

{
  "type": "TouchStart | Touching | TouchEnd",
  "payload": { ... }
}

---

### TouchStart

{
  "type": "TouchStart",
  "payload": {
    "targetPartIndex": 0,
    "actionPoint": { "x": 0, "y": 0, "z": 0 },
    "fingerPoint": { "x": 0, "y": 0, "z": 0 },
    "z_direction": { "x": 0, "y": 0, "z": 1 }
  }
}

---

### Touching

{
  "type": "Touching",
  "payload": {
    "fingerPoint": { "x": 0, "y": 0, "z": 0 },
    "z_direction": { "x": 0, "y": 0, "z": 1 }
  }
}

---

### TouchEnd

{
  "type": "TouchEnd",
  "payload": {}
}

---

## Diagnostics (Optional)

시뮬레이션 상태 및 디버깅 정보를 포함하는 구조.

예:

- contact 상태
- reaction force
- AR interaction 상태
- constraint 안정성

---

## Conventions

- 좌표계: Right-handed
- 길이 단위: meter
- 질량 단위: kilogram
- 시간 단위: second
- 각도 단위: radian
- 회전 표현: Quaternion (w, x, y, z)

---

## Design Rules

모든 타입은 다음 조건을 만족해야 한다.

- 엔진 내부 구현과 독립적으로 정의될 것
- JSON 직렬화/역직렬화 가능할 것
- PyChrono 타입으로 명확히 매핑 가능할 것
- 서버 및 AR 통신에 적합할 것
- 실시간 상호작용을 고려한 구조일 것