# docs/02_core_types.md

Core Data Types

본 문서는 AR 기반 기계설계 시뮬레이터 프로젝트 전반에서
사용되는 핵심 데이터 타입과 그 표현 규칙을 정의한다.
모든 CAD → JSON → Simulation → AR 파이프라인은
본 타입 규칙을 전제로 구현된다.

--------------------------------------------------

Vector3

3차원 벡터 타입.
위치, 방향, 회전축, 힘, 속도, 가속도, 토크 등을 표현하는 데 사용된다.

JSON Representation

{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

Chrono Mapping

chrono.ChVector3d(x, y, z)

--------------------------------------------------

Quaternion

회전을 표현하는 쿼터니언 타입.
짐벌락 방지를 위해 모든 회전은 쿼터니언으로 표현한다.

Quaternion Ordering

(w, x, y, z)

JSON Representation

{
  "w": 1.0,
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

Chrono Mapping

chrono.ChQuaterniond(w, x, y, z)

--------------------------------------------------

Pose

공간 상의 위치와 회전을 함께 표현하는 타입.
모든 바디의 초기 상태 및 상태 출력에 사용된다.

JSON Representation

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

Chrono Mapping

Position  → chrono.ChVector3d
Rotation  → chrono.ChQuaterniond

--------------------------------------------------

Frame

조인트, 모터, 기구학적 기준점을 정의하기 위한 좌표계 타입.
위치와 회전을 동시에 포함한다.

Frame의 로컬 Z축은
조인트의 자유도 방향 또는 회전축으로 사용된다.

JSON Representation

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

Chrono Mapping

chrono.ChFramed(position, rotation)

--------------------------------------------------

Inertia (Rotational Inertia)

바디의 회전 관성을 정의하는 타입.
현실적인 가속/감속 거동을 구현하기 위해 필요하다.

최소 표현은 주관성분(Ixx, Iyy, Izz)만 사용한다.

JSON Representation (Minimal)

{
  "Ixx": 0.002,
  "Iyy": 0.002,
  "Izz": 0.0005
}

Chrono Mapping

chrono.ChBody.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))

--------------------------------------------------

ContactMaterial

접촉 시 마찰과 탄성을 정의하는 타입.
현실적인 감속, 미끄러짐, 에너지 손실을 표현한다.

JSON Representation

{
  "friction": 0.4,
  "restitution": 0.05
}

Chrono Mapping

chrono.ChContactMaterialNSC
- SetFriction(friction)
- SetRestitution(restitution)

--------------------------------------------------

ActuatorCommand

외부 입력(AR/서버)에서 시뮬레이션으로 전달되는
구동 명령 타입.

속도 기반 구동과 토크 기반 구동을 모두 포괄한다.

Logical Structure

{
  "target": "actuator_name",
  "type": "speed | torque",
  "value": 2.5
}

Usage

- speed: rad/s (회전 속도 명령)
- torque: N·m (회전 토크 명령)

--------------------------------------------------

PartState

시뮬레이션 결과로 출력되는 단일 바디의 상태 표현 타입.
AR 렌더링 및 서버 전송에 사용된다.

Logical Structure

{
  "name": "part_name",
  "position": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "rotation": {
    "w": 1.0,
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  }
}

Chrono Source

ChBody.GetPos()
ChBody.GetRot()

--------------------------------------------------

ModelState

씬 전체의 상태를 나타내는 컨테이너 타입.
여러 개의 PartState를 묶어 관리한다.

Logical Structure

[
  PartState,
  PartState,
  ...
]

Usage

- 시뮬레이션 한 스텝 결과 저장
- AR 클라이언트 전송
- 서버 상태 동기화

--------------------------------------------------

UserInput (Interaction Data)

외부 입력(AR, 서버 등)에서 시뮬레이션으로 전달되는 입력 타입.
직접적인 물리 파라미터가 아닌
의도(방향, 위치, 제스처 등)를 표현한다.

Logical Structure

{
  "point": {
    "x": 0.0,
    "y": 0.0,
    "z": 0.0
  },
  "direction": {
    "x": 0.0,
    "y": 0.0,
    "z": 1.0
  }
}

--------------------------------------------------

Conventions

- 좌표계: Right-handed
- 길이 단위: meter
- 질량 단위: kilogram
- 시간 단위: second
- 각도 단위: radian
- 회전 표현: Quaternion (w, x, y, z)

--------------------------------------------------

Design Rule

모든 타입은 다음 조건을 만족해야 한다.

- 엔진 내부 구현과 분리되어 정의될 것
- JSON 직렬화/역직렬화가 가능할 것
- PyChrono 타입으로 명확히 매핑 가능할 것
- 교육용 시각화 및 서버 통신에 적합할 것
