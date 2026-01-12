# docs/03_metadata_schema.md

Simulation Metadata Schema

본 문서는 AR 기반 기계설계 시뮬레이터에서 사용하는
시뮬레이션 메타데이터(JSON)의 구조를 정의한다.
시뮬레이션 엔진은 본 문서의 규칙을 전제로 구현된다.

--------------------------------------------------

Top-level Structure

{
  "sceneName": "example_scene",
  "gravity": [0.0, -9.81, 0.0],

  "bodies": [],
  "joints": [],
  "gearPairs": [],
  "actuators": []
}

--------------------------------------------------

Bodies

Bodies 항목은 시뮬레이션에 포함되는 모든 강체를 정의한다.
각 Body는 시각적 표현, 충돌 형상, 기계적 특성을 분리하여 기술한다.

{
  "name": "gear_A",
  "category": "gear",

  "geometry": {
    "visual": {
      "kind": "mesh",
      "file": "gear_A_scaled.obj"
    },
    "collision": {
      "kind": "cylinder",
      "radius": 0.02,
      "length": 0.02
    }
  },

  "mechanical": {
    "mass": 5.0,
    "fixed": false,

    "inertia": {
      "Ixx": 0.002,
      "Iyy": 0.002,
      "Izz": 0.0005
    },

    "contact": {
      "friction": 0.4,
      "restitution": 0.05
    },

    "damping": {
      "rotational": 0.02
    },

    "gearProps": {
      "module": 0.002,
      "teeth": 20,
      "face_width": 0.02
    }
  },

  "pose": {
    "pos": [0.0, 0.03, 0.03],
    "rot": [1.0, 0.0, 0.0, 0.0]
  }
}

Notes

- geometry.visual 은 시각화 전용이며 물리 계산에는 사용되지 않는다.
- geometry.collision 은 물리 계산용 단순 형상을 정의한다.
- inertia, contact, damping 항목은
  현실적인 가속/감속 및 에너지 손실을 표현하기 위해 사용된다.
- gearProps 는 기어 전용 바디에서만 사용된다.

--------------------------------------------------

Joints

Joints 항목은 두 Body 사이의 기구학적 구속을 정의한다.

{
  "name": "rev_gearA_base",
  "type": "revolute",

  "body1": "gear_A",
  "body2": "base",

  "frame": {
    "pos": [0.0, 0.03, 0.03],
    "rot": [1.0, 0.0, 0.0, 0.0]
  }
}

Supported Joint Types

- revolute   : 회전 1자유도
- prismatic  : 병진 1자유도
- fixed      : 완전 고정

Notes

- frame의 로컬 Z축은 조인트의 자유도 방향을 의미한다.
- frame은 월드 좌표계 기준으로 정의된다.

--------------------------------------------------

GearPairs

GearPairs 항목은 두 기어 바디 사이의 이상적 기어 구속을 정의한다.

{
  "name": "gear_pair_1",
  "gearA": "gear_A",
  "gearB": "gear_B",

  "gearProps": {
    "efficiency": 0.95,
    "backlash": 0.0
  }
}

Notes

- gearA, gearB는 Bodies에서 category가 "gear"인 항목을 참조해야 한다.
- efficiency, backlash 항목은
  현실적인 손실 모델을 적용할 때 사용된다 (선택 사항).

--------------------------------------------------

Actuators

Actuators 항목은 조인트 또는 바디에 작용하는 구동기를 정의한다.

{
  "name": "gearA_motor",
  "type": "rotation_speed",
  "targetJoint": "rev_gearA_base",

  "speed": 5.0
}

Torque-based Actuator Example

{
  "name": "gearA_motor",
  "type": "rotation_torque",
  "targetJoint": "rev_gearA_base",

  "torque": 2.5
}

Supported Actuator Types

- rotation_speed  : 회전 속도 강제 (이상적 구동)
- rotation_torque : 회전 토크 적용 (현실적 구동)

Notes

- speed 단위: rad/s
- torque 단위: N·m
- torque 기반 액추에이터는
  하중에 따라 속도가 변하는 현실적인 거동을 표현한다.

--------------------------------------------------

Conventions

- Coordinate system: Right-handed
- Length unit: meter
- Mass unit: kilogram
- Time unit: second
- Angle unit: radian
- Rotation representation: Quaternion (w, x, y, z)

--------------------------------------------------

Design Rules

- 모든 수치는 SI 단위를 사용한다.
- 모든 참조(name)는 유일해야 한다.
- 시뮬레이션 엔진은
  메타데이터에 명시된 정보만을 사용하여 시스템을 구성한다.
- 현실적인 구동 요소(inertia, contact, damping, torque actuator)는
  단계적으로 활성화 가능해야 한다.
