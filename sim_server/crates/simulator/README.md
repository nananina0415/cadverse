# Simulator Documentation

이 디렉토리는 AR 기반 기계설계 시뮬레이터의
시뮬레이션 엔진 계층과 그 계약(스키마)을 정의한다.

본 시뮬레이터는 CAD에서 추출된 메타데이터(JSON)를 입력으로 받아
PyChrono(Project Chrono 8.0)를 이용해 실제 물리 거동을 계산하고,
그 결과를 서버 및 AR 클라이언트로 전달하는 것을 목표로 한다.

---

## Design Principles

- 시뮬레이션 엔진은 CAD/OBJ로부터 정보를 추론하지 않는다
- 모든 기구/물리 정보는 메타데이터(JSON)에 명시된다
- 시각화(OBJ)와 물리 계산(충돌 형상)은 분리된다
- 서버/AR과의 통신은 명시적인 런타임 스키마를 따른다

---

## Overall Pipeline

CAD Model
→ CAD-derived Metadata (JSON)
→ Simulation Engine (PyChrono)
→ Simulation State
→ Server / AR Client

---

## Python Code Structure

### metadata_types.py

시뮬레이션 메타데이터(JSON)의 정적 스키마를 정의한다.

- CAD → JSON → Python 객체 변환
- 시뮬레이션 “구조” 정의
- 주요 타입:
  - SceneMeta
  - BodyDef
  - JointDef
  - GearPairDef
  - ActuatorDef

이 파일은 시뮬레이션을 **어떻게 구성할 것인가**를 정의한다.

---

### SimInfo.py

시뮬레이션 실행 정보를 담는 상위 컨테이너.

- SceneMeta 포함
- 시간 간격(dt)
- PartIndex 기준 body_order 정의

이 파일은 시뮬레이션을 **어떤 정책으로 실행할 것인가**를 정의한다.

---

### sim_builder.py

메타데이터를 PyChrono 시스템으로 변환하는 빌더.

- SceneMeta → Chrono System
- Body / Joint / GearPair / Actuator 생성
- 충돌 형상은 primitive 기반
- OBJ는 시각화 전용

주요 엔트리 함수:

build_system_from_scene(meta: SceneMeta)

시뮬레이션 기능 확장의 대부분은 이 파일에서 이루어진다.

---

### runtime_types.py

서버 / AR과 통신하기 위한 런타임 타입 정의.

- Runtime Output (Server → Client)
  - PartState
  - SimState

- Runtime Input (Client → Server)
  - UserInput
  - TouchStart / Touching / TouchEnd

docs/06, docs/07 스키마와 1:1 대응된다.

---

### main.py

시뮬레이션 엔진의 외부 인터페이스.

서버는 이 파일의 Simulator 클래스만 사용한다.

- Simulator.create(info)
- Simulator.step(userInput) → SimState

내부 PyChrono 구성은 sim_builder.py에 위임된다.

---

## Documentation Files (docs/)

00_overview.md
프로젝트 목표와 기본 철학

01_architecture.md
전체 시스템 구조 (CAD → Metadata → Simulation → AR)

02_core_types.md
Vector, Quaternion, Pose 등 핵심 수학 타입 정의

03_metadata_schema.md
시뮬레이션 메타데이터(JSON) 구조 규칙

04_pychrono_api_mapping.md
메타데이터와 PyChrono API 매핑 규칙

05_simulation_flow.md
시뮬레이션 초기화 및 실행 흐름

06_runtime_input_schema.md
AR / Client → Server 런타임 입력 스키마

07_runtime_output_schema.md
Server → Client 런타임 출력 스키마

---

## Notes

- CAD에서 모든 정보를 제공하지 않아도,
  필수 필드만 만족하면 시뮬레이션은 동작 가능하다
- 점진적으로 메타데이터를 확장하는 구조를 목표로 한다
- 서버와 시뮬레이터는 스키마 계약을 기준으로 독립 개발된다
