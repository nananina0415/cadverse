# docs/04_pychrono_api_mapping.md

PyChrono API Mapping

본 문서는 시뮬레이션 메타데이터(JSON)가
PyChrono (Project Chrono 8.0)의 API로
어떻게 변환되는지를 정의한다.

시뮬레이션 엔진 구현은
본 매핑 규칙을 기준으로 작성되어야 한다.

--------------------------------------------------

System

JSON.gravity
→ chrono.ChSystemNSC.SetGravitationalAcceleration(chrono.ChVector3d)

Simulation step
→ chrono.ChSystemNSC.DoStepDynamics(dt)

--------------------------------------------------

Core Math Types

Vector3
→ chrono.ChVector3d(x, y, z)

Quaternion (w, x, y, z)
→ chrono.ChQuaterniond(w, x, y, z)

Frame (pose + rotation)
→ chrono.ChFramed(position, rotation)

--------------------------------------------------

Bodies

JSON bodies[*]
→ chrono.ChBody

pose.pos
→ ChBody.SetPos(chrono.ChVector3d)

pose.rot
→ ChBody.SetRot(chrono.ChQuaterniond)

mechanical.fixed
→ ChBody.SetFixed(bool)

mechanical.mass
→ ChBody.SetMass(mass)

mechanical.inertia
→ ChBody.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))

--------------------------------------------------

Collision & Contact Material

geometry.collision
→ ChCollisionShape (Cylinder / Box / Sphere 등)

mechanical.contact
→ chrono.ChContactMaterialNSC

contact.friction
→ ChContactMaterialNSC.SetFriction(friction)

contact.restitution
→ ChContactMaterialNSC.SetRestitution(restitution)

Notes

- 충돌 형상은 계산 효율을 위해 단순 도형을 사용한다.
- 시각적 메쉬는 충돌 계산에 사용되지 않는다.

--------------------------------------------------

Joints

JSON joints[*]
→ chrono.ChLink

revolute
→ chrono.ChLinkLockRevolute

prismatic
→ chrono.ChLinkLockPrismatic

fixed
→ chrono.ChLinkLockLock

JSON.frame
→ chrono.ChFramed
(local Z-axis = joint DOF axis)

Initialization
→ joint.Initialize(body1, body2, frame)

--------------------------------------------------

GearPairs

JSON gearPairs[*]
→ chrono.ChLinkLockGear

Transmission ratio
→ rA / rB

Pitch radius
→ (module × teeth) / 2

Efficiency / Backlash (optional)
→ 사용자 정의 손실 모델 또는 토크 감쇠 로직

Notes

- 기어 치형 접촉은 직접 계산하지 않는다.
- 기어 전달은 이상적 기구학적 구속으로 모델링된다.

--------------------------------------------------

Actuators

rotation_speed
→ chrono.ChLinkMotorRotationSpeed

speed
→ chrono.ChFunctionConst(speed)

rotation_torque
→ chrono.ChLinkMotorRotationTorque

torque
→ chrono.ChFunctionConst(torque)

Initialization
→ motor.Initialize(body, base, frame)

--------------------------------------------------

Runtime Interaction (External Control)

External torque apply
→ ChBody.AccumulateTorque(torque)
또는
→ ChBody.AddTorque(torque)

Angular velocity read
→ ChBody.GetAngVelParent()
또는
→ ChBody.GetAngVelLocal()

Angular velocity write (control override)
→ ChBody.SetAngVelParent()

Force/Torque accumulator clear
→ ChBody.EmptyAccumulators()

--------------------------------------------------

State Output

Body position
→ ChBody.GetPos()

Body rotation
→ ChBody.GetRot()

(Optional) Reaction force / torque
→ ChLink.GetReactionForce()
→ ChLink.GetReactionTorque()

--------------------------------------------------

Design Rules

- Visual geometry와 collision geometry는 분리한다.
- 모든 물리 파라미터는 메타데이터에서만 정의된다.
- PyChrono API 호출은 메타데이터 필드를
  기계적으로 매핑하는 방식으로 구현한다.
- 기어 및 액추에이터는
  단계적으로 현실 모델을 확장할 수 있어야 한다.
- Target engine version: PyChrono 8.0
