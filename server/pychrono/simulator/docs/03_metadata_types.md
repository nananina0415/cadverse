# docs/03_metadata_schema.md

# Metadata Schema

본 문서는 AR 기반 기구학 시뮬레이터의
시뮬레이션 메타데이터(JSON) 구조를 정의한다.

시뮬레이션 엔진은 metadata_types.py에서 정의된 구조를 기반으로
PyChrono 시스템을 구성하며,
모든 물리/기구학 정보는 메타데이터에 명시적으로 제공되어야 한다.

---

## Top-level Structure

{
  "sceneName": "example_scene",
  "gravity": [0.0, -9.81, 0.0],

  "bodies": [],
  "joints": [],

  "gearPairs": [],
  "actuators": []
}

---

## Design Principles

- Metadata-driven
  모든 시뮬레이션 요소는 JSON으로 정의된다.

- No implicit inference
  엔진은 조인트, 축, 관성 등을 자동 추론하지 않는다.

- Physics-first
  모든 상호작용은 물리 기반으로 처리된다.

---

## Bodies

각 Body는 시각, 충돌, 물리 속성을 포함한다.

### Structure

{
  "name": "part_name",
  "category": "base | gear | shaft | link | generic",

  "pose": {
    "pos": [x, y, z],
    "rot": [w, x, y, z]
  },

  "geometry": {
    "visual": {
      "kind": "mesh",
      "file": "path/to/obj",
      "scale": [1,1,1],

      "offset": {
        "pos": [0,0,0],
        "rot": [1,0,0,0]
      }
    },

    "collision": "auto | none | primitive | compound"
  },

  "mechanical": {
    "mass": 1.0,
    "fixed": false,

    "inertia": {
      "mode": "explicit",
      "Ixx": 0.01,
      "Iyy": 0.01,
      "Izz": 0.01
    },

    "contact": {
      "friction": 0.4,
      "restitution": 0.05
    },

    "damping": {
      "type": "viscous_torque",
      "coef": 0.02
    }
  }
}

---

## Collision Model

### 1. Auto (기본)

"collision": "auto"

- OBJ 기반 단순 형상 생성
- 빠른 시뮬레이션 목적

---

### 2. Primitive

{
  "kind": "box | cylinder | sphere",
  ...
}

---

### 3. Compound

[
  { primitive },
  { primitive }
]

---

### 4. None

"collision": "none"

---

## Joints

### Structure

{
  "name": "joint_name",
  "type": "revolute | prismatic | fixed",

  "body1": "name",
  "body2": "name",

  "frame": {
    "pos": [x,y,z],
    "rot": [w,x,y,z]
  },

  "limits": {
    "lower": -1.57,
    "upper": 1.57
  }
}

---

## Joint Behavior

- frame.local Z축 = 자유도 방향
- limits는 optional
- best-effort constraint 적용

---

## GearPairs

### Structure

{
  "name": "gear_pair",
  "gearA": "gear_A",
  "gearB": "gear_B",

  "ratio_sign": -1,

  "meshFrame": {
    "pos": [x,y,z],
    "rot": [w,x,y,z]
  }
}

---

## Gear Runtime Behavior

엔진 내부에서 다음 요소를 고려한다:

- ideal constraint
- efficiency
- backlash
- loss torque approximation

---

## Actuators

### Rotation Speed

{
  "type": "rotation_speed",
  "targetJoint": "joint_name",
  "speed": 5.0
}

---

### Rotation Torque

{
  "type": "rotation_torque",
  "targetJoint": "joint_name",
  "torqueModel": {
    "type": "const",
    "value": 2.5
  }
}

---

## Interaction Integration (IMPORTANT)

메타데이터는 AR interaction과 직접 연결되지 않는다.

- AR 입력 → runtime_types.py → main.py
- main.py → interaction controller → 물리 입력 변환

---

## Runtime Physics Features (Implemented)

현재 엔진에는 다음 요소가 구현되어 있다:

### Inertia
- explicit inertia 사용
- fallback inertia 지원

### Contact
- friction
- restitution

### Damping
- viscous damping
- AR rotate damping

### Stabilization
- torque clamp
- no-flip guard
- settle logic

### Interaction Controller
- rotate mode
- spring mode

### Constraint Handling
- closed-loop 안정성 처리
- joint separation 방지

---

## Design Rules

- 모든 name은 unique
- 모든 물리 정보는 metadata에 명시
- 시각(mesh)와 물리(collision)는 분리
- simulation은 metadata만으로 구성 가능해야 함

---

## Summary

이 스키마는:

- CAD → Simulation 변환 기준
- 서버 / AR와의 데이터 계약 기준
- 물리 기반 상호작용 구현 기준

을 동시에 만족해야 한다.