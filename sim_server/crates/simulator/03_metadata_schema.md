Simulation Metadata Schema
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
      "restitution": 0.05
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

Notes
-----

- geometry.visual
  - 시각화 전용
  - 물리 계산에 사용되지 않는다
  - offset은 BODY 기준 시각 메쉬 배치용 로컬 오프셋

- geometry.collision
  - 물리 계산용 단순 형상
  - 초기 구현에서는 box / cylinder / sphere 권장
  - (UPDATED) 단일/복합/자동근사 3가지 표현을 지원한다 (아래 참고)

- mechanical.inertia
  - mode = "explicit" : 메타에서 관성 직접 지정
  - mode = "auto_from_collision" : 충돌 형상 기준 자동 계산

- gearProps
  - category가 "gear"인 body에서만 사용
  - module 단위는 meter (예: 2 mm → 0.002)
  - 기어비 계산 및 gearPair 생성에 사용

--------------------------------------------------
Collision (UPDATED)
--------------------------------------------------

geometry.collision 은 아래 3가지 형태 중 하나를 허용한다.

(1) Single collision primitive (기존 방식)
------------------------------------------

- box

{
  "kind": "box",
  "hx": 0.10,
  "hy": 0.02,
  "hz": 0.10,

  "offset": {
    "pos": [0.0, 0.0, 0.0],
    "rot": [1.0, 0.0, 0.0, 0.0]
  }
}

- cylinder

{
  "kind": "cylinder",
  "radius": 0.02,
  "length": 0.10,

  "offset": {
    "pos": [0.0, 0.0, 0.0],
    "rot": [1.0, 0.0, 0.0, 0.0]
  }
}

- sphere

{
  "kind": "sphere",
  "radius": 0.02,

  "offset": {
    "pos": [0.0, 0.0, 0.0],
    "rot": [1.0, 0.0, 0.0, 0.0]
  }
}

Notes
- offset은 선택 사항이며 생략 시 아래 기본값을 사용한다.
  - pos = [0.0, 0.0, 0.0]
  - rot = [1.0, 0.0, 0.0, 0.0]

(2) Multiple collision primitives (복합 충돌 형상)
-------------------------------------------------

한 바디에 여러 개의 충돌 primitive를 정의할 수 있다.
샤프트 + 허브(기어) 같이 “축 원통 + 중앙 굵은 원통” 같은 형태에 권장한다.

{
  "name": "shaft",
  "category": "shaft",
  "geometry": {
    "visual": {
      "kind": "mesh",
      "file": "shaft_scaled.obj",
      "scale": [1.0, 1.0, 1.0],
      "offset": {
        "pos": [0.0, 0.0, 0.0],
        "rot": [1.0, 0.0, 0.0, 0.0]
      }
    },

    "collision": [
      {
        "kind": "cylinder",
        "radius": 0.01,
        "length": 0.12,
        "offset": {
          "pos": [0.0, 0.0, 0.0],
          "rot": [1.0, 0.0, 0.0, 0.0]
        }
      },
      {
        "kind": "cylinder",
        "radius": 0.02,
        "length": 0.02,
        "offset": {
          "pos": [0.0, 0.0, 0.01],
          "rot": [1.0, 0.0, 0.0, 0.0]
        }
      }
    ]
  },
  "mechanical": {
    "mass": 10.0,
    "fixed": false,
    "contact": { "friction": 0.4, "restitution": 0.05 }
  },
  "pose": { "pos": [0.0, 0.0, 0.03], "rot": [1.0, 0.0, 0.0, 0.0] }
}

(3) Collision auto-approximation (예외 규칙, Opt-in)
----------------------------------------------------

충돌 형상이 명시되지 않은 경우, 기본 동작은 에러(Fail)이다.
(추정 금지 원칙)

단, 아래처럼 명시적으로 허용한 경우에만 OBJ 기반 자동 근사를 사용할 수 있다.

방법 A) 간단 표기

"collision": "auto"

방법 B) 확장 표기

"collision": {
  "kind": "auto",
  "strategy": "default"
}

Notes
- auto-approximation은 collision에 한해서만 예외적으로 허용한다.
- 다음 정보는 절대 자동 추정하지 않는다:
  - 조인트 축, 기어비, gear mesh frame, explicit inertia
- visual.kind="mesh" 와 visual.file 이 존재해야 한다.
- 엔진 런타임 옵션(예: allow_obj_auto_approx=true)에서 추가로 허용해야 한다.

권장 기본 전략 예시(엔진 구현 기준)
- category="base"  : OBJ AABB 기반 box 1개
- category="shaft" : PCA 축 기반 long cylinder 1개
                    + hub 검출 시 short cylinder 1개 추가
- 기타             : AABB box fallback

--------------------------------------------------
Joints
--------------------------------------------------

Joints 항목은 두 Body 사이의 기구학적 구속을 정의한다.

Example:

{
  "name": "rev_gearA_base",
  "type": "revolute",

  "body1": "gear_A",
  "body2": "base",

  "frame": {
    "pos": [0.0, 0.03, 0.03],
    "rot": [1.0, 0.0, 0.0, 0.0]
  },

  "limits": {
    "lower": -3.14,
    "upper":  3.14
  }
}

Supported Joint Types
---------------------

- revolute   : 회전 1 자유도
- prismatic  : 병진 1 자유도
- fixed      : 완전 고정

Notes
-----

- frame의 로컬 Z축이 조인트의 자유도 방향이다
- frame은 WORLD 좌표계 기준
- limits는 선택 사항 (초기 구현에서는 무시 가능)

--------------------------------------------------
GearPairs
--------------------------------------------------

GearPairs 항목은 두 기어 바디 사이의 이상적 기어 구속을 정의한다.

Example:

{
  "name": "gear_pair_1",

  "gearA": "gear_A",
  "gearB": "gear_B",

  "ratio_sign": -1,

  "enforcePhase": false,

  "meshFrame": {
    "pos": [0.03, 0.03, 0.03],
    "rot": [1.0, 0.0, 0.0, 0.0]
  },

  "gearProps": {
    "efficiency": 0.95,
    "backlash": 0.0
  }
}

Notes
-----

- gearA, gearB는 Bodies에서 category="gear" 여야 한다
- ratio = (gearA.pitch_radius / gearB.pitch_radius) * ratio_sign
- ratio_sign:
  - 외접 기어: -1
  - 내접 기어: +1
- meshFrame은 선택 사항이며,
  미지정 시 엔진은 조인트 프레임 또는 gearA 포즈를 기준으로 한다
- 향후 헬리컬 기어/백래시 모델에 사용 가능

--------------------------------------------------
Actuators
--------------------------------------------------

Actuators 항목은 조인트 또는 바디에 작용하는 구동기를 정의한다.

Rotation Speed Actuator (Ideal)
-------------------------------

{
  "name": "gearA_motor",
  "type": "rotation_speed",
  "targetJoint": "rev_gearA_base",

  "speed": 5.0
}

Rotation Torque Actuator (Realistic)
------------------------------------

{
  "name": "gearA_motor",
  "type": "rotation_torque",
  "targetJoint": "rev_gearA_base",

  "torqueModel": {
    "type": "const",
    "value": 2.5
  }
}

Supported Actuator Types
------------------------

- rotation_speed  : 속도 강제 (이상적 구동)
- rotation_torque : 토크 적용 (현실적 구동)

Notes
-----

- speed 단위  : rad/s
- torque 단위 : N·m
- torque actuator는 하중에 따라 속도가 변한다
- targetJoint의 frame Z축을 회전축으로 사용한다

--------------------------------------------------
Design Rules (UPDATED)
--------------------------------------------------

- 모든 name은 유일해야 한다
- 모든 축, 프레임, 관성, 기어비는 메타데이터에 명시되어야 한다
- 시뮬레이션 엔진은 메타데이터에 없는 정보를 추론하지 않는다

- 단, 충돌 형상(collision)에 한해서만
  아래 조건을 모두 만족하면 OBJ 기반 자동 근사를 예외적으로 허용할 수 있다.
  - geometry.collision 이 "auto" 또는 { "kind": "auto" } 로 명시됨
  - 엔진 옵션에서 allow_obj_auto_approx=true 로 허용됨
  - geometry.visual.kind="mesh" 및 file이 존재함

- 현실성 요소(contact, damping, torque actuator)는
  단계적으로 활성화 가능해야 한다
