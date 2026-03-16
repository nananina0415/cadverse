안녕하세요, 구자웅입니다.

안녕하세요. 임영훈입니다.

안녕하세요, 김민준입니다.

# Simulation Engine – Supported Features (Kinematics-Based)

본 시뮬레이션 엔진은 PyChrono 기반의 교육용 기계 시스템 시뮬레이터로,
기구학(Kinematics)에서 다루는 조인트와 구조를 중심으로 설계되었다.

본 문서는 현재 엔진이 지원하는 조인트 종류, 기구 구조, 물리 기능, 텔레메트리 기능을 정리한 것이다.

이 엔진의 목표는 다음과 같다.

- 기구학 교육용 시뮬레이션
- AR 기반 인터랙션 실습
- 조립 시뮬레이션
- 기어 / 링크 / 슬라이더 / 축 구조 동작 확인
- 물리 상태 및 반력 시각화

본 엔진은 일반적인 범용 물리엔진이 아니라
> 기구학 수준의 시뮬레이션을 위한 교육용 물리 엔진
을 목표로 한다.
---

## 1. Rigid Body Simulation

지원 기능

- 강체 생성
- 질량 설정
- fixed body 지원
- explicit inertia 지원
- 자동 inertia 계산 (best-effort)
- 중력 적용

지원 항목

- mass
- fixed
- inertia
- gravity

---

## 2. Collision / Contact

지원 기능

- primitive collision shape
- compound collision
- contact material 설정

지원 material 옵션

- friction
- restitution
- rolling friction (best-effort)
- spinning friction (best-effort)

지원 기능

- collision filter
- ignore pair
- gear pair collision ignore
- joint 연결 body self-collision off

Contact telemetry 지원

- contact_count
- max_contact_force
- max_pair

---

## 3. Supported Joints (Kinematics-Based)

기구학에서 사용하는 조인트 기준으로 지원 여부를 정리한다.

| Joint type    | 지원 | 방식 |
|---------------|-----|------|
| Revolute      | ✅ | 직접 지원 |
| Prismatic     | ✅ | 직접 지원 |
| Fixed         | ✅ | 직접 지원 |
| Gear pair     | ✅ | 직접 지원 |
| Rack & pinion | ✅ | gear + prismatic |
| 4-bar linkage | ✅ | revolute 조합 |
| Slider-crank  | ✅ | revolute + prismatic |
| Double crank  | ✅ | revolute 조합 |
| Rocker        | ✅ | revolute 조합 |
| Universal     | ⚠ | revolute + revolute |
| Spherical     | ⚠ | revolute 3개 조합 |
| Cylindrical   | ⚠ | revolute + prismatic |
| Screw         | ⚠ | gear / ratio 근사 |
| Planar        | ⚠ | prismatic + revolute |
| Cam / follower| ⚠ | contact 기반 |
| Generic 6DOF  | ❌ | 직접 지원 없음 |

설명

- 직접 지원: 엔진에 joint 타입 존재
- 조합: 여러 joint로 구현 가능
- 근사: 완전하지 않지만 동작 가능
- 미지원: 구조적으로 없음

---

## 4. Joint Limits / Stops

지원 기능

- angle limit
- position limit
- soft stop (best-effort)
- spring / damper (best-effort)

지원 대상

- revolute
- prismatic

---

## 5. Actuator Support

지원 actuator

| Actuator       | 지원 |
|----------------|-----|
| rotation speed  | ✅ |
| rotation torque | ✅ |
| prismatic speed | ⚠ |
| prismatic force | ⚠ |

출력 telemetry

- commandedSpeed
- commandedTorque
- appliedTorque
- estimatedPower

---

## 6. Gear Support

지원 기능

- gear ratio
- phase sync
- efficiency 근사
- backlash 근사
- loss torque 계산

telemetry

- applied_efficiency
- loss_torque
- backlash_deadband

---

## 7. Assembly Assist (교육용 조립 보조)

지원 기능

- snap candidate 탐색
- 위치 오차 계산
- 각도 오차 계산
- tolerance 기반 assist
- snap force 적용
- alignment assist
- active snap telemetry

telemetry

- activeSnap
- snapCandidate
- snapErrorPos
- snapErrorAngle
- snapMode

---

## 8. AR / Touch Interaction

지원 이벤트

- TouchStart
- Touching
- TouchEnd

지원 동작

### Rotate mode

- revolute 축 기반 회전
- drag torque
- damping
- anti-flip clamp

### Spring mode

- virtual spring
- damper
- free body 이동

---

## 9. Runtime Telemetry

출력 가능 항목

### Parts

- position
- rotation
- velocity
- angular velocity

### Contact

- contact_count
- max_contact_force

### Gear

- efficiency
- loss torque
- backlash

### Assembly

- activeSnap
- snapCandidate
- snapErrorPos
- snapErrorAngle

### Joint telemetry

- angle
- position
- angularVelocity
- linearVelocity
- reactionForce
- reactionTorque
- estimatedPower

### Actuator telemetry

- commandedSpeed
- commandedTorque
- appliedTorque
- estimatedPower

### Diagnostics

- actuator stalled
- joint limit
- blocked
- high loss
- alignment in progress

---

## 10. Scope of the Engine

이 엔진은 다음 범위를 목표로 한다.

- 기구학 교육
- 기계요소 교육
- AR 기반 인터랙션
- 조립 시뮬레이션
- 기어 / 링크 / 슬라이더 동작
- 물리 상태 시각화

범용 물리엔진 수준의 기능은 목표가 아니다.

제한 사항

- 일부 joint는 조합으로 구현
- 일부 동작은 근사 모델
- 고급 CAE 해석은 지원하지 않음

---

## 11. Summary

현재 엔진이 지원하는 핵심 기능

- rigid body dynamics
- revolute / prismatic joint
- gear approximation
- linkage structures
- actuator control
- collision / contact
- assembly assist
- AR interaction
- telemetry / diagnostics

이 엔진은

> 교육용 기구학 시뮬레이션을 위한 인터랙티브 물리 엔진

을 목표로 한다.
