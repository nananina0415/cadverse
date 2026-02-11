# Project Overview

본 프로젝트는 단순한 시각적 애니메이션이 아닌,
실제 역학적 거동을 반영하는 기계설계 교육용 시뮬레이터를 목표로 한다.

## Key Principles

1. Metadata-driven Simulation
   - 모든 시뮬레이션 모델은 외부 메타데이터(JSON)에 의해 정의된다.

2. Physics-first, Visualization-separated
   - 물리 계산은 단순한 충돌 도형을 기반으로 수행
   - 시각적 표현은 고해상도 CAD/OBJ 메쉬를 사용

3. Engine Decoupling
   - CAD / 서버 / AR / 시뮬레이션 로직은 명확히 분리된다.

4. PyChrono 기반
   - Project Chrono 8.0의 물리 엔진을 Python(PyChrono)에서 사용한다.
