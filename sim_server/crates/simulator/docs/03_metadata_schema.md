# docs/03_metadata_schema.md
==========================

본 문서는 AR 기반 기계설계 시뮬레이터에서 사용하는
시뮬레이션 메타데이터(JSON)의 구조를 정의한다.

시뮬레이션 엔진은 본 문서에 정의된 정보만을 사용하여
물리 시스템과 시각화를 구성한다.
(CAD/OBJ 파일로부터 축, 관성, 기어비 등을 추론하지 않는다.)

단, 충돌 형상(collision)에 한해 명시적으로 허용된 경우에만
OBJ 기반 자동 근사(auto-approximation)를 사용할 수 있다.

--------------------------------------------------
Top-level Structure
--------------------------------------------------

{
  "sceneName": "example_scene",
  "gravity": [0.0, -9.81, 0.0],

  "bodies": [],
  "joints": [],
  "gearPairs": [],
  "actuators": []
}

--------------------------------------------------
Global Conventions
--------------------------------------------------

- Coordinate system : Right-handed
- Length unit       : meter
- Mass unit         : kilogram
- Time unit         : second
- Angle unit        : radian
- Rotation          : Quaternion (w, x, y, z)

- All frames (pose, joint frame, gear mesh frame)
  are defined in WORLD coordinates.

- geometry.visual.offset is defined
  in BODY-LOCAL coordinates.

- geometry.collision[*].offset is defined
  in BODY-LOCAL coordinates.

- Cylinder primitive axis convention
  - Cylinder 기본 축은 BODY-LOCAL Z축이다.
  - 다른 축을 원하면 offset.rot로 회전시켜 표현한다.

--------------------------------------------------
Bodies
--------------------------------------------------

Bodies 항목은 시뮬레이션에 포함되는 모든 강체를 정의한다.
각 Body는 시각적 표현, 충돌 형상, 기계적 특성을 분리하여 기술한다.

Example:

{
  "name": "gear_A",
  "category": "gear",

  "geometry": {
    "visual": {
      "kind": "mesh",
      "file": "gear_A_scaled.obj",
      "scale": [1.0, 1.0, 1.0],

      "offset": {
        "pos": [0.0, 0.0, 0.0],
        "rot": [1.0, 0.0, 0.0, 0.0]
      }
    },

    "collision": {
      "enabled": true,
      "kind": "cylinder",
      "radius": 0.02,
      "length": 0.02
    }
  },

  "mechanical": {
    "mass": 5.0,
    "fixed": false,

    "inertia": {
      "mode": "explicit",
      "Ixx": 0.002,
      "Iyy": 0.002,
      "Izz": 0.0005
    },

    "contact": {
      "friction": 0.4,
      "restitution": 0.05,

      "rollingFriction": 0.001,
      "spinningFriction": 0.001,

      "contactStiffness": 1e6,
      "contactDamping": 1e3
    },

    "damping": {
      "type": "viscous_torque",
      "coef": 0.02
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

--------------------------------------------------
Collision (UPDATED)
--------------------------------------------------

geometry.collision 은 아래 3가지 형태 중 하나를 허용한다.

--------------------------------------------------
(1) Single collision primitive
--------------------------------------------------

Supported primitives:

- box
- cylinder
- sphere

Example:

{
  "enabled": true,
  "kind": "box",

  "hx": 0.10,
  "hy": 0.02,
  "hz": 0.10,

  "offset": {
    "pos": [0,0,0],
    "rot": [1,0,0,0]
  }
}

--------------------------------------------------
(2) Multiple collision primitives
--------------------------------------------------

복합 충돌 형상 정의 가능.

Example:

"collision": [
  {
    "kind": "cylinder",
    "radius": 0.01,
    "length": 0.12
  },
  {
    "kind": "cylinder",
    "radius": 0.02,
    "length": 0.02,
    "offset": {
      "pos": [0,0,0.01],
      "rot": [1,0,0,0]
    }
  }
]

--------------------------------------------------
(3) Auto approximation (Opt-in only)
--------------------------------------------------

기본 동작: collision 미정의 → FAIL

예외 허용:

"collision": "auto"

또는

"collision": {
  "kind": "auto",
  "strategy": "default",
  "resolutionHint": "low"
}

Auto strategy examples:

- base  → AABB box
- shaft → PCA cylinder
- gear  → disk approx

--------------------------------------------------
Collision Filtering (NEW)
--------------------------------------------------

선택적으로 충돌 그룹 정의 가능.

"collisionFilter": {
  "group": 1,
  "mask": [1,2]
}

용도:

- 특정 부품 간 충돌만 허용
- base 제외
- 교육용 간섭 제거 모드

--------------------------------------------------
Joints
--------------------------------------------------

Example:

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

Supported types:

- revolute
- prismatic
- fixed

Rule:

frame.local Z = DOF axis

--------------------------------------------------
GearPairs
--------------------------------------------------

Example:

{
  "name": "gear_pair_1",

  "gearA": "gear_A",
  "gearB": "gear_B",

  "ratio_sign": -1,

  "meshFrame": {
    "pos": [0.03,0.03,0.03],
    "rot": [1,0,0,0]
  }
}

--------------------------------------------------
Actuators
--------------------------------------------------

Rotation Speed:

{
  "type": "rotation_speed",
  "targetJoint": "rev_gearA_base",
  "speed": 5.0
}

Rotation Torque:

{
  "type": "rotation_torque",
  "targetJoint": "rev_gearA_base",
  "torqueModel": {
    "type": "const",
    "value": 2.5
  }
}

--------------------------------------------------
Design Rules (UPDATED)
--------------------------------------------------

- 모든 name은 유일
- 모든 축/프레임/관성은 메타에 명시
- 엔진은 메타 없는 정보 추론 금지

예외:

collision auto approximation만 허용

조건:

- collision = auto
- allow_obj_auto_approx = true
- visual.mesh 존재

--------------------------------------------------
Reality Extension Policy
--------------------------------------------------

현실성 요소는 단계적으로 활성화:

Level 0 — Primitive collision
Level 1 — Compound collision
Level 2 — Contact material
Level 3 — Friction/rolling/spinning
Level 4 — Gear contact realism
Level 5 — Advanced backlash/compliance
