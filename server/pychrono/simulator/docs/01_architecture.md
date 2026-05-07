# docs/01_architecture.md

# System Architecture

## Overall Pipeline

CAD Model
  ↓
CAD-derived Metadata (JSON)
  ↓
Server / Runtime Interface
  ↓
Simulation Engine (PyChrono)
  ↓
Simulation State (Pose, Telemetry, Diagnostics)
  ↓
Server / AR Synchronization
  ↓
AR / Visualization Client

---

## Key Design Principles

- Metadata-driven Simulation
  모든 시뮬레이션 객체(바디/조인트/기어/구동/조립 가이드)는 JSON 메타데이터로 정의되며,
  시뮬레이션 엔진은 메타데이터를 해석하여 PyChrono 시스템을 구성한다.

- Physics-first, Visualization-separated
  물리 계산은 primitive / compound / auto / none 충돌 정책을 기반으로 수행하고,
  시각적 표현은 고해상도 mesh와 분리하여 관리한다.

- Runtime Intent-based Interaction
  AR 입력은 직접적인 force/torque 값이 아니라 TouchStart / Touching / TouchEnd 형태의 사용자 의도(intent)로 전달된다.
  시뮬레이션 엔진은 이를 내부 interaction controller에서 rotate 또는 spring mode로 해석한다.

- Engine Decoupling
  CAD / 서버 / AR / 시뮬레이션 엔진은 JSON 스키마 계약을 기준으로 분리된다.
  Rust 서버는 PyChrono 내부 구현을 알 필요 없이 Simulator 외부 인터페이스만 사용한다.

- Extensible Realism
  관성, 충돌, 마찰, 감쇠, 기어 효율/백래시, 조인트 리미트, telemetry 등을 단계적으로 확장할 수 있도록 설계한다.

---

## Modules and Boundaries

본 프로젝트는 아래 4개 영역으로 분리된다.

1) CAD / Metadata Generation
2) Server / Runtime Interface
3) Simulation Engine (PyChrono)
4) AR / Visualization Client

각 모듈은 서로의 내부 구현을 모르더라도,
정해진 데이터 계약(JSON 입력 / SimState 출력)을 기준으로 연동 가능해야 한다.

---

## Responsibility Split

### CAD / Metadata Team

- CAD 모델링 및 파트 분류
  - gear / shaft / base / link / generic
- 시뮬레이션에 필요한 속성 추출 및 정규화
  - pose
  - mass
  - inertia
  - collision geometry
  - joint type / axis / frame
  - gear parameters
  - actuator parameters
  - optional assembly guide
- OBJ mesh는 시각화용으로 제공
- 물리 계산에 필요한 정보는 metadata에 명시
- 단위 규칙 유지
  - Length: meter
  - Mass: kg
  - Time: s
  - Angle: rad
  - Quaternion: (w, x, y, z)

---

### Server / Runtime Interface

- Scene metadata JSON을 시뮬레이션 엔진에 전달
- SimOptions 설정
  - dt
  - physics preset
  - contact telemetry 여부
  - partNames 출력 여부
- Runtime input 전달
  - TouchStart
  - Touching
  - TouchEnd
- Python Simulation Engine 호출
  - Simulator.create(info)
  - Simulator.step(userInput)
  - Simulator.close()
- SimState를 받아 AR / client가 사용할 transform 형태로 변환

---

### Simulation Team

- SceneMeta를 PyChrono 시스템으로 변환
  - Bodies 생성
  - Joints 생성
  - GearPairs 생성
  - Actuators 생성
  - Collision filter 적용
  - Assembly guide 정보 구성
- 시뮬레이션 실행
  - force / torque accumulator clear
  - AR interaction control 적용
  - gear efficiency / backlash 보정
  - DoStepDynamics(dt)
- 상태 출력
  - PartState(pos/rot)
  - partNames
  - contact telemetry
  - interaction telemetry
  - gear / assembly / joint / actuator telemetry
  - diagnostics / warnings
- 안정성 관리
  - timestep
  - solver preset
  - damping
  - torque clamp
  - joint limit best-effort handling

---

### AR / Visualization Client

- 사용자 입력 이벤트 생성
  - target part 선택
  - touch start / drag / end
  - fingerPointWorld
  - cameraForwardWorld
  - actionPointLocal
- 서버로 runtime input 전달
- SimState의 PartState를 기반으로 모델 pose 동기화
- 필요 시 telemetry / diagnostics를 교육용 UI로 표시
  - 조인트 상태
  - 구동 상태
  - 접촉 상태
  - AR interaction 해석 결과

---

## Realistic Interaction and Dynamics Extensions

현재 엔진은 다음 확장 요소를 포함하거나 고려한다.

- Inertia
  - explicit inertia
  - collision 기반 auto inertia 옵션

- Collision
  - primitive collision
  - compound collision
  - auto collision
  - none collision
  - collisionFilter(ignoreJoints / ignoreGearPairs / ignorePairs / onlyPairs)

- Contact Material
  - friction
  - restitution
  - rolling / spinning friction
  - compliance / damping
  - stick-slip 완화 옵션

- Damping / Stabilization
  - body damping
  - AR rotate damping
  - torque clamp
  - no-flip guard

- Gear Runtime Correction
  - ideal gear constraint
  - efficiency
  - backlash
  - loss torque approximation

- Joint Limits
  - lower / upper limit
  - hard stop option
  - soft spring-damper option
  - binding compatibility 기반 best-effort 적용

- Assembly Guide
  - moving body와 target body의 local pose 기반 정렬 보조
  - assist / snap mode 확장 가능

---

## Data Contracts

### Input to Simulation Engine

1. Scene Metadata JSON
   - bodies
   - joints
   - gearPairs
   - actuators
   - collisionFilter
   - assemblyGuides

2. Runtime UserInput
   - TouchStart
   - Touching
   - TouchEnd

3. SimOptions
   - dt
   - physics_preset
   - allow_obj_auto_approx
   - emit_part_names
   - enable_contact_telemetry

### Output from Simulation Engine

1. SimState
   - sim_time
   - parts

2. Optional outputs
   - partNames
   - telemetry
   - interactionTelemetry
   - gearTelemetry
   - assemblyTelemetry
   - jointTelemetry
   - actuatorTelemetry
   - diagnostics
   - warnings

이 데이터 계약을 기반으로 CAD, 서버, AR, 시뮬레이션 엔진이 독립적으로 개발 및 연동될 수 있다.