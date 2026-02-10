# Simulator Documentation

이 디렉토리는 AR 기반 기계설계 시뮬레이터의
시뮬레이션 엔진 계층과 그 계약(스키마)을 정의한다.

본 시뮬레이터는 CAD에서 추출된 메타데이터(JSON)를 입력으로 받아
PyChrono(Project Chrono 8.0)를 이용해 실제 물리 거동을 계산하고,
그 결과를 서버 및 AR 클라이언트로 전달하는 것을 목표로 한다.

---

## Design Principles

- Metadata-driven
  시뮬레이션 엔진은 CAD/OBJ로부터 정보를 추론하지 않는다.
  모든 기구/물리 정보는 메타데이터(JSON)에 명시된다.

- Physics-first & Visualization-separated
  시각화(OBJ/mesh)와 물리 계산(충돌 형상)은 분리된다.

- Engine decoupling
  CAD / Server / AR / Simulation Engine은 스키마 계약을 기준으로 독립 개발된다.

- Progressive realism expansion
  초기에는 안정적인 상호작용/감쇠를 확보하고, 이후 충돌·마찰·접촉 등 현실성을 단계적으로 확장한다.

- Unit conventions
  m, kg, s, rad, quaternion(w,x,y,z)

---

## Overall Pipeline

CAD Model
→ CAD-derived Metadata (JSON)
→ Simulation Engine (PyChrono)
→ Simulation State
→ Server / AR Client

---

## Runtime Contract

### Input
- Scene Metadata JSON
- Runtime Commands / AR Interaction Events

### Output
- Part pose / rotation
- Optional telemetry (velocity, torque, reaction force, contact 등 확장 가능)

---

## Collision Model Policy

시각화 mesh와 물리 충돌 형상은 분리한다.

충돌 형상 정의는 다음 4가지 정책을 지원한다:

1. Explicit Primitive
   - Box / Cylinder / Sphere 등 기본 도형 명시

2. Compound
   - 여러 primitive를 결합한 충돌 형상

3. Auto (추정)
   - 명시되지 않은 경우, 시뮬레이터가 합리적인 단순 형상을 자동 생성

4. None
   - 충돌 비활성화 (contact 제외)

OBJ(mesh)는 시각화 전용이며,
충돌 계산에는 직접 사용하지 않는다.

---

## Python Code Structure

### metadata_types.py

시뮬레이션 메타데이터(JSON)의 정적 스키마 정의.

- CAD → JSON → Python 객체 변환
- 시뮬레이션 구조 정의

주요 타입:
- SceneMeta
- BodyDef
- JointDef
- GearPairDef
- ActuatorDef

이 파일은 시뮬레이션을 **어떻게 구성할 것인가**를 정의한다.

---

### SimInfo.py

시뮬레이션 실행 정보 컨테이너.

- SceneMeta 포함
- dt (time step)
- body_order / PartIndex 정의

이 파일은 시뮬레이션을 **어떤 정책으로 실행할 것인가**를 정의한다.

---

### sim_builder.py

메타데이터를 PyChrono 시스템으로 변환하는 빌더.

- SceneMeta → Chrono System
- Body / Joint / GearPair / Actuator 생성
- 충돌 형상은 primitive / compound / auto 정책 기반
- OBJ는 시각화 전용

주요 엔트리:

build_system_from_scene(meta: SceneMeta)

현실적 거동 확장의 핵심 구현 지점이다.

---

### runtime_types.py

서버 / AR 통신용 런타임 타입 정의.

#### Output
- PartState
- SimState

#### Input
- UserInput
- TouchStart
- Touching
- TouchEnd

docs/06, docs/07 스키마와 대응된다.

---

### main.py

시뮬레이션 엔진 외부 인터페이스.

서버는 Simulator 클래스만 사용한다.

- Simulator.create(info)
- Simulator.step(userInput) → SimState

내부 Chrono 구성은 sim_builder.py에 위임된다.

---

## Interaction Controller (main.py 내부)

### Rotate Mode

조건:
- revolute joint 1개
- other joint 0개

동작:
- 드래그 증분 기반 토크 적용
- TouchEnd 이후 축방향 감쇠
- chatter 방지 snap
- 1-step 부호 반전 방지 clamp

---

### Spring Mode

조건:
- 그 외 모든 경우

동작:
- 가상 스프링-댐퍼 힘 적용

---

## PyChrono Binding Compatibility

바인딩 차이를 흡수하기 위한 보강 로직 포함:

- world / local angvel 자동 판별 및 변환
- force / torque accumulator step마다 clear
- TouchStart 중 actuator drive neutralize

---

## Documentation Files (docs/)

00_overview.md
프로젝트 목표와 철학

01_architecture.md
CAD → Metadata → Simulation → AR 구조

02_core_types.md
Vector / Quaternion / Pose 정의

03_metadata_schema.md
메타데이터(JSON) 구조

04_pychrono_api_mapping.md
Chrono API 매핑 규칙

05_simulation_flow.md
시뮬레이션 실행 흐름

06_runtime_input_schema.md
AR → Server 입력 스키마

07_runtime_output_schema.md
Server → Client 출력 스키마

---

## Notes

- 필수 필드만 만족하면 시뮬레이션은 동작 가능해야 한다.
- 메타데이터는 점진적으로 확장 가능해야 한다.
- 서버와 시뮬레이터는 스키마 계약 기준으로 독립 개발된다.
- 충돌/접촉 확장은 안정적 인터랙션 이후 단계적으로 진행한다.
