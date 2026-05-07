# Project Overview

본 프로젝트는 AR의 실시간 상호작용 기술을 활용하여,
기구학 교육에서 사용자가 기계 구조의 움직임을 직관적으로 이해할 수 있도록 돕는
기구학 교육용 시뮬레이터 제작을 목표로 한다.

본 시뮬레이터는 단순한 시각적 애니메이션이 아니라,
사용자의 AR 입력을 실제 물리 기반 시뮬레이션으로 변환하고,
그 결과를 실시간 상태 정보로 출력하는 구조를 지향한다.

## Key Principles

1. Metadata-driven Simulation
   - 모든 시뮬레이션 모델은 외부 메타데이터(JSON)에 의해 정의된다.
   - 엔진은 CAD/OBJ 파일로부터 조인트, 축, 관성 등의 물리 정보를 임의로 추론하지 않는다.

2. Physics-first, Visualization-separated
   - 물리 계산은 단순화된 충돌 도형과 명시된 물리 속성을 기반으로 수행한다.
   - 시각적 표현은 고해상도 CAD/OBJ 메쉬를 사용하되, 물리 계산과 분리한다.

3. Real-time AR Interaction
   - 사용자의 AR 터치/드래그 입력을 런타임 이벤트로 받아 시뮬레이션에 반영한다.
   - 입력은 직접적인 힘/토크 값이 아니라 사용자 의도(intent)로 전달되며,
     시뮬레이션 엔진 내부에서 회전, 스프링-댐퍼, 감쇠 등의 물리 제어로 변환된다.

4. Engine Decoupling
   - CAD / 서버 / AR / 시뮬레이션 로직은 명확히 분리된다.
   - 각 모듈은 JSON 기반 스키마 계약을 통해 독립적으로 개발 및 연동된다.

5. PyChrono 기반
   - Project Chrono 8.0의 물리 엔진을 Python(PyChrono)에서 사용한다.
   - 시뮬레이션 엔진은 외부에서 `Simulator.create()`와 `Simulator.step()`을 통해 사용할 수 있도록 구성된다.

6. Extensible Runtime Output
   - 기본 출력은 각 파트의 위치와 회전 상태이다.
   - 필요에 따라 접촉 정보, 조인트 상태, 액추에이터 상태, AR interaction telemetry,
     diagnostics 등의 교육용/디버그용 정보를 확장 출력할 수 있다.