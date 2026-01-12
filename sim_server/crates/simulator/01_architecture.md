# docs/01_architecture.md

# System Architecture

## Overall Pipeline

CAD Model
  ↓
CAD-derived Metadata (JSON)
  ↓
Simulation Engine (PyChrono)
  ↓
Simulation State (Pose, Rotation, optional: Vel/Force)
  ↓
Server / AR Synchronization
  ↓
AR / Visualization Client

---

## Key Design Principles

- Metadata-driven Simulation
  모든 시뮬레이션 객체(바디/조인트/기어/구동)는 JSON 메타데이터로 정의되며,
  시뮬레이션 엔진은 메타를 “해석하여” 시스템을 구성한다.

- Physics-first, Visualization-separated
  물리 계산은 단순 충돌 형상(primitive) 중심으로 수행하고,
  시각적 표현은 고해상도 메쉬(mesh)를 별도로 붙이는 방식으로 구성한다.

- Extensible Realism
  처음에는 “움직임이 되는 단계”로 시작하되,
  관성/마찰/감쇠/토크 기반 구동 등 현실 거동 요소를 단계적으로 추가할 수 있도록 설계한다.

---

## Modules and Boundaries

본 프로젝트는 아래 3개 영역이 명확히 분리되어야 한다.

1) CAD/Metadata Generation (External)
2) Simulation Engine (PyChrono)
3) Server/AR Client (Interaction + Visualization)

각 모듈은 서로의 내부 구현을 모르더라도,
정해진 데이터 계약(JSON 입력 / State 출력)만으로 연동 가능해야 한다.

---

## Responsibility Split

### CAD / Metadata Team

- CAD 모델링 및 파트 분류(gear/shaft/base 등)
- 시뮬레이션에 필요한 속성 추출 및 정규화
  - 질량(mass)
  - 관성(inertia) 또는 최소한의 관성 근사
  - 조인트 타입/축/프레임 정보
  - 기어 파라미터(module, teeth 등)
  - (현실 구동 단계) 접촉 재질(friction/restitution), 감쇠(damping), 효율/백래시 등
- JSON 메타데이터 생성 및 예제 제공
- 메타데이터의 단위 규칙 유지
  - Length: meter
  - Mass: kg
  - Time: s
  - Angle: rad
  - Quaternion: (w, x, y, z)

---

### Simulation Team

- JSON 메타데이터를 PyChrono 시스템으로 변환
  - Bodies 생성 (pose, mass, inertia, collision/visual)
  - Joints 생성 (revolute/prismatic/fixed + frame)
  - GearPairs 생성 (ideal gear constraint + transmission ratio)
  - Actuators 생성 (speed motor / torque motor)
- 시뮬레이션 실행 및 상태 출력
  - DoStepDynamics(dt)
  - Body pose 출력 (pos/rot)
  - (현실 구동 단계) 속도/가속도/반력/토크 등 선택 출력 지원
- 외부 입력을 물리적 구동으로 반영
  - 속도 명령 → speed motor 갱신
  - 토크 명령 → torque motor 또는 body torque 적용
  - (선택) 제어기(PID/필터/클램핑) 계층 구성
- 성능/안정성 관리
  - timestep 정책, solver 설정, collision 단순화

---

### Server / AR Team

- 사용자 입력 이벤트 수집 및 정규화
  - TouchStart / Touching / TouchEnd
  - 조작 대상(body/joint) 선택 결과
  - 드래그/회전/슬라이드 제스처 파라미터
- 입력 이벤트를 “시뮬레이션 명령” 형태로 변환
  - speed command: actuator speed 설정
  - torque command: actuator torque 또는 body torque 설정
  - (선택) 목표 각도/위치 기반 제어 명령
- 시뮬레이션 상태 수신 및 시각화 렌더링
  - PartState(포즈) 기반 모델 동기화
  - 네트워크 지연을 고려한 보간/예측(선택)
- 사용자에게 교육용 피드백 제공(선택)
  - 회전 속도, 전달비, 하중감, 토크/반력 정보 표시

---

## Realistic Actuation (Reality Stage) Additions

현실적인 구동을 위해 아래 요소들이 단계적으로 추가된다.

- Inertia (관성)
  - 질량만으로는 현실적인 회전 응답 구현이 어려움
  - 최소형 관성: [Ixx, Iyy, Izz] 또는 전체 텐서

- Contact Material (마찰/탄성)
  - friction/restitution을 통해 현실적인 감속/접촉 거동 구현

- Damping / Loss
  - 회전 감쇠(마찰/베어링 손실) 모델 추가
  - 기어 효율/손실 모델(선택)

- Torque-based Actuation
  - 속도 강제 방식은 하중 변화가 반영되지 않음
  - 토크 기반 구동은 하중에 따라 속도가 변하는 현실 거동 구현 가능

- Optional Force Feedback Outputs
  - 조인트 반력, 전달 토크, 동력(파워) 등 교육용 출력 확장 가능

---

## Data Contracts (Interface Summary)

- Input to Simulation Engine
  1) Scene Metadata JSON (bodies/joints/gears/actuators)
  2) Runtime Commands / Events (speed/torque/selection/gesture)

- Output from Simulation Engine
  1) Model State (per-body pose)
  2) Optional telemetry (vel, reaction force, torque, power)

이 데이터 계약을 기반으로 팀 간 병렬 개발이 가능해야 한다.
