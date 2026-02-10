# docs/04_pychrono_api_mapping.md (Project Chrono / PyChrono 8.x)

본 문서는 시뮬레이션 메타데이터(JSON)가 PyChrono(Project Chrono 8.x)의
어떤 API 호출로 변환되는지(=매핑 규칙)를 정의한다.

목표:
- 메타데이터 필드를 **기계적으로** Chrono 객체/함수로 매핑한다.
- 시각화(OBJ mesh)와 물리(충돌 형상)는 분리한다.
- 바인딩/버전 차이(특히 angvel getter/setter, force/torque 적용 API 차이)를 흡수하는
  **fallback 규칙**을 문서화한다.

---

## 0) System / Simulation Loop

### Contact method 선택
- 기본: `chrono.ChSystemNSC`
  - Non-smooth contact (complementarity 기반) 접촉
  - 강체/마찰 접촉에서 비교적 견고하게 쓰기 쉬움

(옵션) Smooth contact:
- `chrono.ChSystemSMC`
  - penalty 기반(침투 허용) 접촉
  - 탄성/감쇠 모델링에 유리하지만 파라미터/시간스텝에 민감할 수 있음

### Gravity
- JSON: `scene.gravity = [gx, gy, gz]`
- Chrono:
  - 우선 시도: `sys.SetGravitationalAcceleration(chrono.ChVector3d(gx, gy, gz))`
  - (구버전/바인딩) 다른 setter가 있으면 해당 함수 사용

### Step
- 매 스텝:
  - (옵션/바인딩 이슈 대응) 바디 force/torque accumulator clear
  - 사용자 입력/AR interaction forces/torques apply
  - `sys.DoStepDynamics(dt)`

---

## 1) Core Math Types

### Vector3
- JSON: `[x, y, z]`
- Chrono: `chrono.ChVector3d(x, y, z)`

### Quaternion (w, x, y, z)
- JSON: `[w, x, y, z]`
- Chrono: `chrono.ChQuaterniond(w, x, y, z)`

### Frame
- JSON:
  - `pos: [x, y, z]`
  - `rot: [w, x, y, z]`
- Chrono:
  - `chrono.ChFramed(chrono.ChVector3d, chrono.ChQuaterniond)` 또는
  - 링크 Initialize에서 frame으로 전달되는 타입(바인딩 제공 타입)에 맞춤

규칙:
- joint frame의 local Z축이 DOF 축(회전/병진 방향)

---

## 2) Bodies

### Body 생성
- JSON: `bodies[*]`
- Chrono:
  - 보통 `chrono.ChBody` 또는 helper(`ChBodyEasyBox` 등)로 생성 후 시스템에 추가
  - `sys.Add(body)`

### Pose
- JSON: `pose.pos`, `pose.rot`
- Chrono:
  - `body.SetPos(ChVector3d)`
  - `body.SetRot(ChQuaterniond)`

### Fixed
- JSON: `mechanical.fixed`
- Chrono:
  - `body.SetFixed(True/False)`

### Mass
- JSON: `mechanical.mass`
- Chrono:
  - `body.SetMass(mass)`

### Inertia (explicit)
- JSON: `mechanical.inertia.mode == "explicit"`
  - `Ixx, Iyy, Izz`
- Chrono:
  - `body.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))`
- 추가(엔진 내부 캐시 권장):
  - 바인딩에서 inertia getter가 없을 수 있으므로,
    엔진에서 body에 `_inertia_diag_local = ChVector3d(Ixx,Iyy,Izz)` 같은 형태로 캐시 가능

### Inertia (auto_from_collision) [선택]
- JSON: `mechanical.inertia.mode == "auto_from_collision"`
- Chrono:
  - 충돌 primitive로부터 근사 관성 계산(엔진 구현)
  - 결과를 `SetInertiaXX`로 설정

---

## 3) Visual Geometry (렌더/AR 전용)

- JSON: `geometry.visual`
  - `kind="mesh"`, `file="*.obj"`, `scale`, `offset`
- Chrono:
  - 시뮬 엔진 레벨에서는 **물리 계산에 사용하지 않음**
  - (옵션) Chrono visualization asset로 붙일 수 있으나,
    기본 엔진은 "pose/state만 출력"하므로 시각화는 외부에서 처리 가능

---

## 4) Collision Geometry & Contact Material

### 4.1 Contact Material
- JSON: `mechanical.contact`
  - `friction`, `restitution` 등
- Chrono (NSC):
  - `mat = chrono.ChContactMaterialNSC()`
  - `mat.SetFriction(mu)`
  - `mat.SetRestitution(e)`
  - (옵션) rolling/spinning friction 등 추가 파라미터가 있으면 대응

(참고) SMC일 때는 `chrono.ChContactMaterialSMC()` 계열 사용.

### 4.2 Collision model enable
- Chrono:
  - `body.EnableCollision(True/False)`
  - collision shape를 collision model에 add 후 build

### 4.3 Collision 정의 3종 매핑 (UPDATED)

#### (1) Single primitive
- JSON: `geometry.collision = { kind: "box"/"cylinder"/"sphere", ... , offset? }`
- Chrono:
  - collision model에 해당 shape 1개 add
  - offset(pos/rot)이 있으면 local transform으로 적용

#### (2) Multiple primitives (복합)
- JSON: `geometry.collision = [ {primitive1}, {primitive2}, ... ]`
- Chrono:
  - collision model에 shape를 **여러 개 add**
  - 각 primitive의 offset을 개별 적용

#### (3) Auto approximation (opt-in)
- JSON:
  - `"collision": "auto"` 또는 `{ "kind": "auto", "strategy": "default" }`
- 규칙:
  - 기본 동작은 Fail(추정 금지), 오직 opt-in일 때만 허용
  - 시각 mesh(OBJ)의 정보를 이용해
    - base: AABB box 1개
    - shaft: long cylinder(+ optional hub cylinder)
    - 기타: AABB box fallback
- Chrono:
  - auto로 생성된 primitive들을 collision model에 add

> 주의: OBJ로부터 “조인트 축/기어비/관성(명시값)” 등은 절대 추정하지 않는다.
> auto는 collision shape에만 제한적으로 허용한다.

---

## 5) Joints (Constraints)

- JSON: `joints[*]`
- Chrono:
  - revolute  -> `chrono.ChLinkLockRevolute`
  - prismatic -> `chrono.ChLinkLockPrismatic`
  - fixed     -> `chrono.ChLinkLockLock` (또는 고정 링크 계열)
- Initialize:
  - `link.Initialize(body1, body2, frame_world)`
- frame:
  - local Z축이 joint axis (회전축/이동축)

(옵션) limits:
- Chrono limit API를 지원할 경우 매핑
- 초기 단계에서는 무시 가능

---

## 6) GearPairs (Ideal constraint)

- JSON: `gearPairs[*]`
- Chrono:
  - 대표: `chrono.ChLinkLockGear`
- Ratio:
  - pitch radius: `r = (module * teeth) / 2`
  - `ratio = (rA / rB) * ratio_sign`
- meshFrame:
  - 지정 시 해당 frame으로 Initialize
  - 미지정 시 엔진 규칙(예: joint frame / gearA pose)로 결정

주의:
- 기어 치형 접촉을 직접 계산하지 않고,
  이상적 구속(kinematic constraint)으로 모델링한다.

---

## 7) Actuators (Motors)

### rotation_speed (Ideal)
- Chrono:
  - `chrono.ChLinkMotorRotationSpeed`
  - `motor.SetSpeedFunction(chrono.ChFunctionConst(speed))`
  - `motor.Initialize(body, base, frame_world)`

### rotation_torque (Realistic)
- Chrono:
  - `chrono.ChLinkMotorRotationTorque`
  - `motor.SetTorqueFunction(chrono.ChFunctionConst(torque))`
  - `motor.Initialize(body, base, frame_world)`

주의:
- AR 인터랙션(TouchStart/Drag)이 들어오면,
  엔진은 해당 구동기를 중립화/비활성화할 수 있어야 한다
  (드라이브가 AR 제어와 싸우지 않게).

---

## 8) Runtime Interaction (External Control / AR)

### 8.1 Force/Torque apply (바인딩 호환 우선순위)

실측(테스트 결과 기반):
- 어떤 PyChrono 바인딩에서는 `AddForce(vec)`가 `ChForce` shared_ptr을 요구하는 등
  "벡터만 넣는 형태"가 동작하지 않을 수 있다.
- torque는 `AccumulateTorque(vec, local)`가 가장 안정적으로 존재하는 편이다.

권장 규칙:
- Torque:
  1) `body.AccumulateTorque(tau_world, local=False)` 시도
  2) 실패 시 `local=True`로 시도

- Force at point:
  1) `body.AccumulateForce(F_world, p_world, local=False)` 시도
  2) 실패 시 `local=True`
  3) (최후) `tau = (p_world - com) x F_world`로 torque로 환산해 적용

### 8.2 Accumulator clear
- 바인딩/설정에 따라 accumulator가 step마다 자동 리셋되지 않을 수 있어
  엔진에서 DoStepDynamics 전에 clear를 수행할 수 있다.
- 우선순위:
  - `body.EmptyAccumulators()`
  - (주의) `body.RemoveAllForces()`는 force object까지 제거할 수 있으므로 최후 수단

### 8.3 Angular velocity get/set (바인딩 차이 흡수)

실측(테스트 결과 기반):
- 어떤 바인딩은 `GetAngVel`/`SetAngVel`이 없고
  `GetAngVelLocal`/`SetAngVelLocal`만 제공한다.

권장 규칙(읽기):
1) `GetWvel_par` / `GetAngVelWorld` / `GetWvel` 등 world 계열 우선
2) 없으면 `GetAngVel()`를 시도하되,
   `GetAngVelLocal()`이 있다면 비교해서 local 여부를 판정하고 필요 시 q로 world 변환
3) 마지막으로 `GetAngVelLocal()`을 q로 회전해 world로 변환

쓰기(가능하면 지양):
- control override로 SetAngVelLocal 등이 필요할 수 있으나,
  기본 정책은 "물리 적분을 존중"하고 overwrite는 최소화한다.

---

## 9) State Output (Server / AR)

- Body pose:
  - `pos = body.GetPos()`
  - `rot = body.GetRot()`
- (옵션) velocities:
  - linvel: `GetPos_dt` / `GetVel` 등 바인딩별 후보 사용
  - angvel: 위의 angvel world 규칙 사용
- (옵션) constraint reaction:
  - `link.GetReactionForce()`
  - `link.GetReactionTorque()`
  (바인딩 지원 시)

---

## 10) Design Rules

- Visual mesh와 collision geometry는 분리한다.
- 메타데이터에 없는 정보는 추론하지 않는다.
  - 예외: collision이 명시적으로 "auto"로 opt-in된 경우에만
    OBJ 기반 collision approximation을 허용한다.
- 바인딩/버전 차이는 엔진 내부 helper로 흡수하고,
  문서(본 파일)에 fallback 규칙을 기록한다.

Target engine version:
- PyChrono / Project Chrono 8.x
- Default contact method: NSC (`ChSystemNSC`)
