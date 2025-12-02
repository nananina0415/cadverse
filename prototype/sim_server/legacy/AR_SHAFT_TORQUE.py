##AR_SHAFT_TORQUE.py
##샤프트 드래그-> 토크 적용 with 임시 테스트 코드 풀 버젼(참고용)
import math as m
import time
from typing import Optional, Dict, Any

import pychrono as chrono
import pychrono.irrlicht as chronoirr

# ============================================================
# 0. 벡터/쿼터니언/OBJ 헬퍼
# ============================================================

def vec_add(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(a.x + b.x, a.y + b.y, a.z + b.z)


def vec_sub(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(a.x - b.x, a.y - b.y, a.z - b.z)


def vec_scale(v: chrono.ChVector3d, s: float) -> chrono.ChVector3d:
    return chrono.ChVector3d(v.x * s, v.y * s, v.z * s)


def vec_length(v: chrono.ChVector3d) -> float:
    return m.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)


def vec_normalize(v: chrono.ChVector3d) -> chrono.ChVector3d:
    L = vec_length(v)
    if L < 1e-12:
        return chrono.ChVector3d(0, 0, 0)
    return chrono.ChVector3d(v.x / L, v.y / L, v.z / L)


def vec_cross(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    )


def vec_dot(a: chrono.ChVector3d, b: chrono.ChVector3d) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def quat_from_axis_angle(axis: chrono.ChVector3d, angle: float) -> chrono.ChQuaterniond:
    axis_n = vec_normalize(axis)
    if vec_length(axis_n) < 1e-12 or abs(angle) < 1e-12:
        return chrono.QUNIT

    half = 0.5 * angle
    s = m.sin(half)
    c = m.cos(half)
    return chrono.ChQuaterniond(c, axis_n.x * s, axis_n.y * s, axis_n.z * s)


def read_obj_bounds(path: str):
    xs, ys, zs = [], [], []
    with open(path, "r") as f:
        for line in f:
            if line.startswith("v "):
                _, x, y, z = line.split()
                xs.append(float(x)); ys.append(float(y)); zs.append(float(z))
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def detect_axis_and_center(path: str):
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
    # 로컬 z축을 world axis 방향으로 맞추는 단순 매핑
    if axis.x == 0 and axis.y == 0 and axis.z == 1:
        return chrono.QUNIT
    if axis.x == 1 and axis.y == 0 and axis.z == 0:
        return chrono.QuatFromAngleY(-m.pi / 2)
    if axis.x == 0 and axis.y == 1 and axis.z == 0:
        return chrono.QuatFromAngleX(+m.pi / 2)
    return chrono.QUNIT


def safe_zero_dynamics(body: chrono.ChBody):
    """속도/가속도 초기화 + 외력 누적 초기화(있는 경우)"""
    zero = chrono.ChVector3d(0, 0, 0)

    # 선속도 / 각속도 / 선가속도 / 각가속도 0으로
    if hasattr(body, "SetLinVel"):
        body.SetLinVel(zero)
    if hasattr(body, "SetAngVelParent"):
        body.SetAngVelParent(zero)
    elif hasattr(body, "SetAngVelLocal"):
        body.SetAngVelLocal(zero)

    if hasattr(body, "SetLinAcc"):
        body.SetLinAcc(zero)
    if hasattr(body, "SetAngAccParent"):
        body.SetAngAccParent(zero)
    elif hasattr(body, "SetAngAccLocal"):
        body.SetAngAccLocal(zero)

    # 누적 힘/토크 비우기
    if hasattr(body, "EmptyAccumulators"):
        body.EmptyAccumulators()


def clear_external_forces(body: chrono.ChBody):
    """이 바디에 누적된 외력/토크만 비움"""
    if hasattr(body, "EmptyAccumulators"):
        body.EmptyAccumulators()


def apply_torque(body: chrono.ChBody, torque: chrono.ChVector3d):
    """버전에 따라 AccumulateTorque / AddTorque 중 되는 걸 사용"""
    if hasattr(body, "AccumulateTorque"):
        try:
            body.AccumulateTorque(torque, False)
        except TypeError:
            body.AccumulateTorque(torque)
    elif hasattr(body, "AddTorque"):
        body.AddTorque(torque)
    else:
        # 최악의 경우: 토크 적용 API가 없으면 그냥 무시
        pass


def get_angvel_parent(body: chrono.ChBody) -> chrono.ChVector3d:
    """버전에 따라 각속도 읽기"""
    if hasattr(body, "GetAngVelParent"):
        return body.GetAngVelParent()
    elif hasattr(body, "GetAngVelLocal"):
        return body.GetAngVelLocal()
    else:
        return chrono.ChVector3d(0, 0, 0)


def set_angvel_parent(body: chrono.ChBody, w: chrono.ChVector3d):
    """버전에 따라 각속도 쓰기 """
    if hasattr(body, "SetAngVelParent"):
        body.SetAngVelParent(w)
    elif hasattr(body, "SetAngVelLocal"):
        body.SetAngVelLocal(w)


def vec_from_dict(d: Optional[Dict[str, float]]) -> chrono.ChVector3d:
    if not d:
        return chrono.ChVector3d(0, 0, 0)
    return chrono.ChVector3d(
        float(d.get("x", 0.0)),
        float(d.get("y", 0.0)),
        float(d.get("z", 0.0)),
    )

# ============================================================
# 1. AR 입력 버퍼
# ============================================================

class ARBuffer:
    def __init__(self):
        self._latest_interact: Optional[Dict[str, Any]] = None

    def set_interact_event(self, msg: Optional[Dict[str, Any]]):
        self._latest_interact = msg

    def read_inputs(self) -> Dict[str, Any]:
        return {"interact": self._latest_interact}

# ============================================================
# 2. 어셈블리 + 드래그 상태
# ============================================================

class DragState:
    def __init__(self):
        self.active: bool = False
        self.start_finger: Optional[chrono.ChVector3d] = None
        self.center: Optional[chrono.ChVector3d] = None


class SimHandle:
    def __init__(
        self,
        sys: chrono.ChSystemNSC,
        base: chrono.ChBody,
        shaft: chrono.ChBody,
        joint: chrono.ChLinkLockRevolute,
        buffer: ARBuffer,
        shaft_center_world: chrono.ChVector3d,
        shaft_axis_world: chrono.ChVector3d,
    ):
        self.sys = sys
        self.base = base
        self.shaft = shaft
        self.joint = joint
        self.buffer = buffer

        self.shaft_center_world = shaft_center_world
        self.shaft_axis_world = vec_normalize(shaft_axis_world)

        self.drag = DragState()


def create_assembly_with_joint(sys: chrono.ChSystemNSC, buffer: ARBuffer) -> SimHandle:
    # 1) base (고정)
    base = chrono.ChBodyEasyMesh("base_scaled.obj", 1000, True, True)
    base.SetName("base")
    base.SetFixed(True)
    sys.Add(base)

    # 2) shaft (회전하는 부품)
    shaft = chrono.ChBodyEasyMesh("shaft_scaled.obj", 500, True, True)
    shaft.SetName("shaft")
    shaft.SetFixed(False)

    shaft_offset = chrono.ChVector3d(0.0, 0.0, 0.03)
    shaft.SetPos(shaft_offset)
    sys.Add(shaft)

    # 3) 중심/축 검출
    shaft_center_local, shaft_axis = detect_axis_and_center("shaft_scaled.obj")
    shaft_center_world = vec_add(shaft_center_local, shaft_offset)

    print("[asm] shaft center (local) =", shaft_center_local)
    print("[asm] shaft offset        =", shaft_offset)
    print("[asm] shaft center (world)=", shaft_center_world)
    print("[asm] shaft axis          =", shaft_axis)

    # 4) revolute joint (축 고정)
    q_joint = quat_from_axis_for_joint(shaft_axis)
    frame = chrono.ChFramed(shaft_center_world, q_joint)

    joint = chrono.ChLinkLockRevolute()
    joint.Initialize(shaft, base, frame)
    sys.AddLink(joint)

    return SimHandle(sys, base, shaft, joint, buffer,
                     shaft_center_world, shaft_axis)

# ============================================================
# 3. 드래그 → 토크 변환
# ============================================================

DRAG_TORQUE = 0.005   # 드래그 시 주는 토크 크기
DAMP_FREE   = 8     # 손 뗀 후 감쇠 강도 (값 키우면 더 빨리 멈춤)
DAMP_DRAG   = 1.5     # 드래그 중 감쇠 강도 (너무 크면 잘 안 도는 느낌)
VEL_EPS     = 5e-3    # 이 이하 각속도면 그냥 0으로 스냅 (떨림 제거용)


def handle_drag_torque(handle: SimHandle, event: Optional[Dict[str, Any]]):
    shaft = handle.shaft
    drag = handle.drag
    center = handle.shaft_center_world
    axis = handle.shaft_axis_world

    if not event:
        drag.active = False
        return

    ev_type = event.get("type")
    payload = event.get("payload") or {}
    finger = vec_from_dict(payload.get("fingerPoint"))

    # TouchStart -----------------------------------------
    if ev_type == "TouchStart":
        drag.active = True
        drag.start_finger = finger
        drag.center = center
        # safe_zero_dynamics(shaft)  # 필요하면 활성화
        return

    # TouchEnd -------------------------------------------
    if ev_type == "TouchEnd":
        drag.active = False
        # 여기서는 바로 안 멈추고 감쇠에 맡김
        return

    # Touching -------------------------------------------
    if ev_type == "Touching" and drag.active and drag.center is not None and drag.start_finger is not None:
        c = drag.center
        start = drag.start_finger

        v0 = vec_sub(start, c)
        v1 = vec_sub(finger, c)

        len0 = vec_length(v0)
        len1 = vec_length(v1)
        if len0 < 1e-6 or len1 < 1e-6:
            return

        v0n = vec_normalize(v0)
        v1n = vec_normalize(v1)

        # 손가락 드래그가 만들어내는 회전축
        arc_axis = vec_cross(v0n, v1n)
        arc_axis_n = vec_normalize(arc_axis)
        if vec_length(arc_axis_n) < 1e-6:
            return

        # 드래그 축이 실제 샤프트 축과 같은 방향이면 +, 반대면 -
        sign = 1.0
        if vec_dot(arc_axis_n, axis) < 0.0:
            sign = -1.0

        torque_world = vec_scale(axis, sign * DRAG_TORQUE)
        apply_torque(shaft, torque_world)
        return

# ============================================================
# 4. step_sim_torque : AR 입력 반영 + 동역학 스텝 (+ 속도감쇠)
# ============================================================

def step_sim_torque(handle: SimHandle, dt: float):
    shaft = handle.shaft
    axis = handle.shaft_axis_world

    # 1) 입력 읽기
    inputs = handle.buffer.read_inputs()
    event = inputs.get("interact")

    # 매 스텝마다 외력/토크는 비우고(중복 누적 방지) → 이번 프레임 것만 적용
    clear_external_forces(shaft)

    # 2) 드래그에 따른 토크 적용
    handle_drag_torque(handle, event)

    # 3) 각속도 기반 감쇠 (축 방향 성분만 줄이기)
    w = get_angvel_parent(shaft)        # 현재 각속도
    w_along = vec_dot(w, axis)          # 축 방향 성분

    # 드래그 중인지 여부
    dragging = (
        event is not None
        and event.get("type") == "Touching"
        and handle.drag.active
    )
    lam = DAMP_DRAG if dragging else DAMP_FREE

    if abs(w_along) < VEL_EPS:
        w_along_new = 0.0
    else:
        # exp 감쇠: 더 안정적이고 덜 튐
        factor = m.exp(-lam * dt)
        w_along_new = w_along * factor

    # 축 방향 성분만 반영한 새로운 각속도 (1자유도만 유지)
    w_new = vec_scale(axis, w_along_new)
    set_angvel_parent(shaft, w_new)

    # 4) 동역학 스텝
    handle.sys.DoStepDynamics(dt)

# ============================================================
# 5. 테스트용 가짜 InteractByScreen 타임라인 (짧은 드래그)
# ============================================================

def fake_drag_timeline(t: float, dt: float) -> Optional[Dict[str, Any]]:
    """
    - 1.0초 : 2시 방향에서 TouchStart
    - 1.0 ~ 2.0초 : 2시 → 8시 반원 드래그 (약 1초 드래그)
    - 2.0초 : TouchEnd
    """
    # TouchStart
    if abs(t - 1.0) < dt * 0.5:
        R = 0.03
        angle = m.radians(30.0)  # 2시 방향
        fx = R * m.cos(angle)
        fy = R * m.sin(angle)
        return {
            "type": "TouchStart",
            "payload": {
                "targetPartIndex": 0,
                "actionPoint": {"x": 0.0, "y": 0.0, "z": 0.0},
                "fingerPoint": {"x": fx, "y": fy, "z": 0.0},
            },
        }

    # Touching : 2시→8시 (1초 동안 반원)
    if 1.0 < t < 2.0:
        R = 0.03
        tau = (t - 1.0) / 1.0     # 0 ~ 1
        angle = m.radians(30.0 + 180.0 * tau)  # 30° → 210°
        fx = R * m.cos(angle)
        fy = R * m.sin(angle)
        return {
            "type": "Touching",
            "payload": {
                "fingerPoint": {"x": fx, "y": fy, "z": 0.0},
            },
        }

    # TouchEnd
    if abs(t - 2.0) < dt * 0.5:
        return {"type": "TouchEnd", "payload": {}}

    return None

# ============================================================
# 6. 데모 실행
# ============================================================

def run_torque_drag_demo():
    print("[demo] Torque-drag shaft rotation demo 시작 ")

    sys = chrono.ChSystemNSC()
    sys.SetGravitationalAcceleration(chrono.ChVector3d(0, 0, 0))

    buffer = ARBuffer()
    handle = create_assembly_with_joint(sys, buffer)

    vis = chronoirr.ChVisualSystemIrrlicht()
    vis.AttachSystem(sys)
    vis.SetWindowSize(1280, 720)
    vis.SetWindowTitle("Torque drag → shaft rotation demo ")
    vis.Initialize()

    vis.AddSkyBox()
    vis.AddTypicalLights()
    vis.AddCamera(
        chrono.ChVector3d(0.15, 0.15, 0.25),
        chrono.ChVector3d(0.0, 0.0, 0.0),
    )

    dt = 0.01
    t = 0.0

    while vis.Run():
        event = fake_drag_timeline(t, dt)
        buffer.set_interact_event(event)

        step_sim_torque(handle, dt)
        t += dt

        vis.BeginScene()
        vis.Render()
        vis.EndScene()

        time.sleep(0.003)

    print("[demo] 종료")


if __name__ == "__main__":
    run_torque_drag_demo()
