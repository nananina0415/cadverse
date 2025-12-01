import math as m
import time
from typing import Optional, Dict, Any

import pychrono as chrono
import pychrono.irrlicht as chronoirr

# ============================================================
# 0. 공통 헬퍼
# ============================================================

def quat_from_axis_angle(axis: chrono.ChVector3d, angle: float) -> chrono.ChQuaterniond:
    """축(axis) + 각(angle, rad) → 단위 쿼터니언 (e0=w, e1=x, e2=y, e3=z)"""
    ax, ay, az = axis.x, axis.y, axis.z
    n2 = ax * ax + ay * ay + az * az
    if n2 < 1e-16:
        return chrono.QUNIT

    inv_n = 1.0 / m.sqrt(n2)
    ax *= inv_n
    ay *= inv_n
    az *= inv_n

    half = 0.5 * angle
    s = m.sin(half)
    c = m.cos(half)
    return chrono.ChQuaterniond(c, ax * s, ay * s, az * s)


def read_obj_bounds(path: str):
    """OBJ 파일의 bounding box 읽기"""
    xs, ys, zs = [], [], []
    with open(path, "r") as f:
        for line in f:
            if line.startswith("v "):
                _, x, y, z = line.split()
                xs.append(float(x))
                ys.append(float(y))
                zs.append(float(z))
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def detect_axis_and_center(path: str):
    """
    OBJ 파일의 bounding box로부터:
    - 중심점(center)
    - 가장 긴 축(회전축)을 자동 검출
    (1,0,0) / (0,1,0) / (0,0,1) 중 하나만 반환
    """
    xmin, xmax, ymin, ymax, zmin, zmax = read_obj_bounds(path)

    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2
    cz = (zmin + zmax) / 2
    center = chrono.ChVector3d(cx, cy, cz)

    dx = xmax - xmin
    dy = ymax - ymin
    dz = zmax - zmin

    if dx >= dy and dx >= dz:
        axis = chrono.ChVector3d(1, 0, 0)
    elif dy >= dx and dy >= dz:
        axis = chrono.ChVector3d(0, 1, 0)
    else:
        axis = chrono.ChVector3d(0, 0, 1)

    return center, axis


def quat_from_axis_for_joint(axis: chrono.ChVector3d) -> chrono.ChQuaterniond:
    """
    joint/motor의 로컬 z축을 원하는 world 축(axis) 방향으로 돌려주는 쿼터니언.
    (예전 simulate.py 로직 단순화)
    """
    # Z축 그대로
    if axis.x == 0 and axis.y == 0 and axis.z == 1:
        return chrono.QUNIT
    # z -> x
    if axis.x == 1 and axis.y == 0 and axis.z == 0:
        return chrono.QuatFromAngleY(-m.pi / 2)
    # z -> y
    if axis.x == 0 and axis.y == 1 and axis.z == 0:
        return chrono.QuatFromAngleX(+m.pi / 2)
    return chrono.QUNIT


def safe_zero_dynamics(body: chrono.ChBody):
    """가능한 범위에서 속도/가속도/힘 누적을 0으로 만들어 줌 (가속 느낌 방지)"""
    zero = chrono.ChVector3d(0, 0, 0)
    for name in ["SetPos_dt", "SetPos_dtdt", "SetWvel_loc", "SetWacc_loc"]:
        if hasattr(body, name):
            getattr(body, name)(zero)
    if hasattr(body, "Empty_forces_accumulators"):
        body.Empty_forces_accumulators()

# ============================================================
# 1. AR 버퍼 + Arcball 상태
# ============================================================

class ARBuffer:
    """
    - set_interact_event(msg): AR/네트워크에서 들어온 InteractByScreen JSON을 넣음
    - read_inputs(): step_sim 쪽에서 최신 입력을 읽어감
    """

    def __init__(self):
        self._latest_interact: Optional[Dict[str, Any]] = None

    def set_interact_event(self, msg: Optional[Dict[str, Any]]):
        self._latest_interact = msg

    def read_inputs(self) -> Dict[str, Any]:
        return {"interact": self._latest_interact}


class ArcballState:
    """
    트랙볼(arcball) 회전을 위한 상태:
    - active: 현재 드래그 중인지
    - start_finger: TouchStart 때 손가락 위치
    - center: 회전 중심 (여기서는 base 중심 근처)
    """

    def __init__(self):
        self.active: bool = False
        self.start_finger: Optional[chrono.ChVector3d] = None
        self.center: Optional[chrono.ChVector3d] = None

# ============================================================
# 2. 등각속도 회전 컨트롤러 (base만 직접 제어)
# ============================================================

class AssemblyControllerVel:
    """
    base의 전역 회전만 "각속도 벡터"로 관리하는 컨트롤러.
    - ang_vel: world 기준 각속도 벡터 (rad/s)
    - integrate(dt): ang_vel 고정 → 등각속도로 회전
    """

    def __init__(self, base: chrono.ChBody):
        self.base = base
        self.base_pos = base.GetPos()
        self.base_rot = base.GetRot()
        self.ang_vel = chrono.ChVector3d(0, 0, 0)

    def set_ang_vel(self, axis: chrono.ChVector3d, ang_speed_rad: float):
        """축 방향 + 크기(각속도)로 ang_vel 세팅"""
        ax, ay, az = axis.x, axis.y, axis.z
        n2 = ax*ax + ay*ay + az*az
        if n2 < 1e-16 or ang_speed_rad == 0.0:
            self.ang_vel = chrono.ChVector3d(0, 0, 0)
            return
        inv_n = 1.0 / m.sqrt(n2)
        ax *= inv_n
        ay *= inv_n
        az *= inv_n
        self.ang_vel = chrono.ChVector3d(ax*ang_speed_rad,
                                         ay*ang_speed_rad,
                                         az*ang_speed_rad)

    def stop_rotation(self):
        self.ang_vel = chrono.ChVector3d(0, 0, 0)

    def integrate(self, dt: float):
        """
        ang_vel을 가지고 base_rot를 dt만큼 진화시킴.
        (base_pos는 여기선 안 건드림 = 병진 없음)
        """
        wx, wy, wz = self.ang_vel.x, self.ang_vel.y, self.ang_vel.z
        w_mag = m.sqrt(wx*wx + wy*wy + wz*wz)
        if w_mag > 1e-12:
            axis = chrono.ChVector3d(wx / w_mag, wy / w_mag, wz / w_mag)
            angle = w_mag * dt  # rad
            q_delta = quat_from_axis_angle(axis, angle)
            self.base_rot = q_delta * self.base_rot

    def apply(self):
        self.base.SetPos(self.base_pos)
        self.base.SetRot(self.base_rot)
        safe_zero_dynamics(self.base)

# ============================================================
# 3. SimHandle + base/shaft + joint + motor
# ============================================================

class SimHandle:
    def __init__(self, sys, base, shaft, joint, motor, buffer: ARBuffer):
        self.sys = sys
        self.base = base
        self.shaft = shaft
        self.joint = joint
        self.motor = motor
        self.buffer = buffer

        self.arcball = ArcballState()
        self.controller = AssemblyControllerVel(base)


def create_base_shaft_with_motor(sys):
    """
    - base_scaled.obj, shaft_scaled.obj 로부터 base/shaft 생성
    - shaft_offset 만큼 샤프트를 올려서 조립
    - shaft OBJ에서 중심/축 자동 검출
    - 그 축을 따라 revolute + motor 생성
    """

    # 1) 베이스 생성
    base = chrono.ChBodyEasyMesh("base_scaled.obj", 1000, True, True)
    base.SetName("base")
    base.SetFixed(True)
    sys.Add(base)

    # 2) 샤프트 생성
    shaft = chrono.ChBodyEasyMesh("shaft_scaled.obj", 500, True, True)
    shaft.SetName("shaft")
    shaft.SetFixed(False)

    shaft_offset = chrono.ChVector3d(0.0, 0.0, 0.03)  # 필요시 튜닝
    shaft.SetPos(shaft_offset)
    sys.Add(shaft)

    # 3) 샤프트 OBJ에서 중심/축 자동 검출
    shaft_center_local, shaft_axis = detect_axis_and_center("shaft_scaled.obj")
    shaft_center_world = shaft_center_local + shaft_offset

    print("[asm] shaft center (local) =", shaft_center_local)
    print("[asm] shaft offset        =", shaft_offset)
    print("[asm] shaft center (world)=", shaft_center_world)
    print("[asm] shaft axis          =", shaft_axis)

    # 4) revolute 조인트 + 회전 모터
    q_joint = quat_from_axis_for_joint(shaft_axis)
    frame = chrono.ChFramed(shaft_center_world, q_joint)

    joint = chrono.ChLinkLockRevolute()
    joint.Initialize(shaft, base, frame)
    sys.AddLink(joint)

    motor = chrono.ChLinkMotorRotationSpeed()
    motor.Initialize(shaft, base, frame)

    # 👉 샤프트 자전 속도 (교육용이라 천천히)
    motor_speed = 2.0  # rad/s
    func = chrono.ChFunctionConst(motor_speed)
    motor.SetSpeedFunction(func)
    motor.SetName("shaft_motor")
    sys.AddLink(motor)

    print(f"[asm] shaft-base + motor 조립 완료 (motor_speed={motor_speed} rad/s)")
    return base, shaft, joint, motor


def make_sim(buffer: ARBuffer) -> SimHandle:
    sys = chrono.ChSystemNSC()
    sys.SetGravitationalAcceleration(chrono.ChVector3d(0, 0, 0))
    base, shaft, joint, motor = create_base_shaft_with_motor(sys)
    return SimHandle(sys, base, shaft, joint, motor, buffer)

# ============================================================
# 4. Arcball 이벤트 처리 (등각속도 버전)
# ============================================================

# 손가락으로 방향만 정해주고, 실제 각속도 크기는 항상 이 값으로 고정
ARCBALL_SPEED_DEG = 60.0           # 초당 20도
ARCBALL_SPEED_RAD = m.radians(ARCBALL_SPEED_DEG)


def handle_arcball_event(handle: SimHandle, event: Optional[Dict[str, Any]]):
    """
    트랙볼(arcball) 스타일:
    - TouchStart: 시작 손가락 위치 / 회전 중심 스냅샷
    - Touching: v0, v1로 회전축(axis)만 계산 → 고정된 각속도로 회전하도록 컨트롤러에 전달
    - TouchEnd: 각속도 0 → 즉시 스탑
    """
    if not event:
        return

    itype = event.get("type")
    payload = event.get("payload") or {}
    arc = handle.arcball
    base = handle.base
    ctrl = handle.controller

    def vec3(d: Optional[Dict[str, Any]]):
        if not d:
            return chrono.ChVector3d(0, 0, 0)
        return chrono.ChVector3d(
            float(d.get("x", 0.0)),
            float(d.get("y", 0.0)),
            float(d.get("z", 0.0)),
        )

    # --------------------------------------
    # TouchStart
    # --------------------------------------
    if itype == "TouchStart":
        finger = vec3(payload.get("fingerPoint"))

        arc.active = True
        arc.start_finger = finger
        arc.center = base.GetPos()  # 대충 base 중심을 회전 중심으로 사용

        ctrl.stop_rotation()
        safe_zero_dynamics(base)

        print("[arcball] TouchStart:", finger)
        return

    # --------------------------------------
    # Touching
    # --------------------------------------
    if itype == "Touching":
        if not arc.active:
            return

        finger = vec3(payload.get("fingerPoint"))
        start_finger = arc.start_finger
        center = arc.center

        if start_finger is None or center is None:
            ctrl.stop_rotation()
            return

        # v0 = 시작 손가락 벡터 (center 기준)
        v0 = chrono.ChVector3d(
            start_finger.x - center.x,
            start_finger.y - center.y,
            start_finger.z - center.z,
        )
        # v1 = 현재 손가락 벡터 (center 기준)
        v1 = chrono.ChVector3d(
            finger.x - center.x,
            finger.y - center.y,
            finger.z - center.z,
        )

        # 길이 체크
        len0_sq = v0.x*v0.x + v0.y*v0.y + v0.z*v0.z
        len1_sq = v1.x*v1.x + v1.y*v1.y + v1.z*v1.z
        if len0_sq < 1e-12 or len1_sq < 1e-12:
            ctrl.stop_rotation()
            return

        inv0 = 1.0 / m.sqrt(len0_sq)
        inv1 = 1.0 / m.sqrt(len1_sq)
        v0n = chrono.ChVector3d(v0.x*inv0, v0.y*inv0, v0.z*inv0)
        v1n = chrono.ChVector3d(v1.x*inv1, v1.y*inv1, v1.z*inv1)

        # 회전축 = v0 × v1  (방향만 사용)
        axis = chrono.ChVector3d(
            v0n.y * v1n.z - v0n.z * v1n.y,
            v0n.z * v1n.x - v0n.x * v1n.z,
            v0n.x * v1n.y - v0n.y * v1n.x,
        )
        axis_len_sq = axis.x*axis.x + axis.y*axis.y + axis.z*axis.z
        if axis_len_sq < 1e-12:
            ctrl.stop_rotation()
            return

        # ✅ 각속도 크기는 ARCBALL_SPEED_RAD 로 "고정"
        ctrl.set_ang_vel(axis, ARCBALL_SPEED_RAD)
        return

    # --------------------------------------
    # TouchEnd
    # --------------------------------------
    if itype == "TouchEnd":
        if arc.active:
            print("[arcball] TouchEnd: stop rotation")
            ctrl.stop_rotation()
            safe_zero_dynamics(base)

        arc.active = False
        arc.start_finger = None
        arc.center = None
        return

# ============================================================
# 5. step_sim_arcball: AR 입력 반영 + dynamics 한 스텝
# ============================================================

def step_sim_arcball(handle: SimHandle, dt: float):
    """
    1) buffer.read_inputs() → InteractByScreen 이벤트
    2) handle_arcball_event → controller.ang_vel 세팅
    3) controller.integrate(dt) → base_rot 업데이트 (등각속도)
    4) controller.apply() → base에 적용
    5) sys.DoStepDynamics(dt) → joint + motor 포함 동역학 스텝
    """
    sys = handle.sys
    buffer = handle.buffer
    ctrl = handle.controller

    # 1) 입력 읽기 + arcball 처리
    inputs = buffer.read_inputs()
    interact_msg = inputs.get("interact")
    handle_arcball_event(handle, interact_msg)

    # 2) 등각속도 회전 적분
    ctrl.integrate(dt)
    ctrl.apply()

    # 3) 동역학 스텝
    sys.DoStepDynamics(dt)

# ============================================================
# 6. 테스트: 가짜 손가락 궤적으로 arcball 테스트
# ============================================================

def fake_arcball_event_timeline(t: float, dt: float) -> Optional[Dict[str, Any]]:
    """
    시간 t에 따라 가짜 InteractByScreen 이벤트 생성:
    - 1.0초: TouchStart (x축 오른쪽에서 시작)
    - 1.0~4.0초: 손가락이 90도 정도의 호를 그리면서 Touching
    - 4.0초: TouchEnd
    """
    # TouchStart
    if abs(t - 1.0) < dt * 0.5:
        R = 0.03  # 반지름 3cm
        return {
            "type": "TouchStart",
            "payload": {
                "targetPartIndex": 1,
                "fingerPoint": {"x": R, "y": 0.0, "z": 0.0},
            },
        }

    # Touching: 1.0~4.0초 동안 quarter circle (3시 → 12시 방향)
    if 1.0 < t < 4.0:
        T = 3.0
        tau = (t - 1.0) / T  # 0~1
        # 90도(π/2 rad) 정도만 돌도록
        angle = (m.pi/2.0) * tau
        R = 0.03
        fx = R * m.cos(angle)   # x
        fy = R * m.sin(angle)   # y
        fz = 0.0
        return {
            "type": "Touching",
            "payload": {
                "fingerPoint": {"x": fx, "y": fy, "z": fz},
            },
        }

    # TouchEnd
    if abs(t - 4.0) < dt * 0.5:
        return {
            "type": "TouchEnd",
            "payload": {},
        }

    return None


def run_arcball_constant_speed_demo():
    """
    - base_scaled.obj + shaft_scaled.obj + 자동 축검출 + 모터
    - arcball 입력은 등각속도로 base를 회전시키는 역할만 수행
    - 가짜 손가락 궤적(fake_arcball_event_timeline)으로 동작 확인
    """
    print("[test] run_arcball_constant_speed_demo() 시작")

    buffer = ARBuffer()
    handle = make_sim(buffer)
    sys = handle.sys

    # 시각화 세팅
    vis = chronoirr.ChVisualSystemIrrlicht()
    vis.AttachSystem(sys)
    vis.SetWindowSize(1024, 768)
    vis.SetWindowTitle("Arcball Constant Angular Speed Demo")
    vis.Initialize()

    vis.AddSkyBox()
    vis.AddTypicalLights()
    vis.AddCamera(chrono.ChVector3d(0.05, 0.05, 0.12))

    dt = 0.01
    sim_time = 0.0
    end_time = 80.0

    step_count = 0

    while vis.Run() and sim_time < end_time:
        # 1) 가짜 AR 이벤트 생성
        event = fake_arcball_event_timeline(sim_time, dt)
        buffer.set_interact_event(event)

        # 2) 시뮬 한 스텝
        step_sim_arcball(handle, dt)
        sim_time += dt
        step_count += 1

        # 3) 렌더링
        vis.BeginScene()
        vis.Render()
        vis.EndScene()

        time.sleep(0.005)

    print(f"[test] 종료: step_count={step_count}, sim_time={sim_time:.3f}")


if __name__ == "__main__":
    run_arcball_constant_speed_demo()
