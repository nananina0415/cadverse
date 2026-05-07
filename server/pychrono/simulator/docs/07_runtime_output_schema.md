# docs/07_runtime_output_schema.md

# Runtime Output Schema (Server → Client)

본 문서는 시뮬레이션 엔진이 서버를 통해
클라이언트(AR / Renderer / UI)로 전달하는
런타임 출력(SimState)의 JSON 구조를 정의한다.

출력 메시지는 시뮬레이션의 현재 물리 상태를 전달하며,
클라이언트는 이를 기반으로 렌더링 및 UI 표시를 수행한다.

---

## Global Rules

- Encoding: UTF-8 JSON
- Coordinate system: Right-handed (WORLD 기준)
- Rotation: Quaternion (w, x, y, z)

### Units

| Quantity | Unit |
|----------|------|
| Length | meter (m) |
| Time | second (s) |
| Angle | radian (rad) |
| Velocity | m/s |
| Angular velocity | rad/s |
| Force | N |
| Torque | N·m |
| Power | W |

---

## Core Types

### Vector3

{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

---

### Quaternion

{
  "w": 1.0,
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

---

## PartState

단일 rigid body의 상태

{
  "name": "shaft",
  "pos": { "x": 0.0, "y": 0.0, "z": 0.0 },
  "rot": { "w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0 }
}

Rules:

- name은 metadata와 동일해야 한다
- pos는 WORLD 좌표
- rot은 normalized quaternion

---

## SimState

시뮬레이션 한 step의 전체 상태

{
  "sim_time": 0.0,
  "parts": [ PartState ]
}

---

## Optional Fields

다음 필드는 상황에 따라 포함될 수 있다.

### Message Metadata

{
  "seq": 120,
  "server_time_sec": 1730000000.0,
  "partNames": ["base", "shaft"]
}

---

### Contact Telemetry

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

---

### Interaction Telemetry

{
  "interactionTelemetry": {
    "mode": "rotate",
    "active": true,
    "target": "shaft"
  }
}

---

### Gear Telemetry

{
  "gearTelemetry": {
    "gp1": {
      "applied_efficiency": 0.85,
      "loss_torque": 0.02,
      "backlash_deadband": 0.01
    }
  }
}

---

### Assembly Telemetry

{
  "assemblyTelemetry": {
    "guide1": {
      "activeSnap": true,
      "snapErrorPos": 0.01,
      "snapErrorAngle": 0.05
    }
  }
}

---

### Joint Telemetry

{
  "jointTelemetry": {
    "rev0": {
      "jointType": "revolute",
      "angle": 0.5,
      "angularVelocity": 2.0,
      "reactionForce": { "x": 0, "y": 0, "z": 0 },
      "reactionTorque": { "x": 0, "y": 0, "z": 0 }
    }
  }
}

---

### Actuator Telemetry

{
  "actuatorTelemetry": {
    "motor0": {
      "actuatorType": "rotation_speed",
      "targetJoint": "rev0",
      "commandedSpeed": 5.0,
      "appliedTorque": 1.2
    }
  }
}

---

### Diagnostics

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

---

### Warnings

{
  "warnings": [
    "constraint instability detected"
  ]
}

---

## Design Rules

- SimState는 서버가 authoritative (단일 진실원)
- 클라이언트는 이를 기반으로 렌더링한다
- telemetry 필드는 optional
- 필드가 없으면 해당 기능은 비활성 상태로 간주

---

## Summary

SimState는 다음 목적을 가진다:

- AR 렌더링을 위한 pose 전달
- 물리 상태 모니터링
- 디버깅 및 교육용 데이터 제공