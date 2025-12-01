import math as m
import time
from typing import Optional, Dict, Any
import threading

import pychrono as chrono
import pychrono.irrlicht as chronoirr

# ============================================================
# 0. 헬퍼 함수들
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
    - 가장 긴 축(회전축)을 자동 검출한다
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
# 1. 어셈블리 등속/등각속도 컨트롤러 (base만 직접 제어)
# ============================================================

class AssemblyControllerVel:
    """
    base + shaft 어셈블리 중에서
    - base의 전역 속도 v, 각속도 ω를 들고 있다가
    - 매 step dt마다
        base_pos += v * dt
        base_rot = q(ω*dt) * base_rot
      을 적용한다.
    shaft는 조인트 + 모터가 알아서 따라오므로 직접 건드리지 않는다.
    """

    def __init__(self, base: chrono.ChBody, shaft: chrono.ChBody):
        self.base_pos = base.GetPos()
        self.base_rot = base.GetRot()

        self.lin_vel = chrono.ChVector3d(0, 0, 0)   # m/s
        self.ang_vel = chrono.ChVector3d(0, 0, 0)   # rad/s

    def set_velocity_from_command(self,
                                  cmd_id: Optional[int],
                                  lin_speed: float,
                                  ang_speed_rad: float):
        """
        1~12번 명령에 따라 lin_vel / ang_vel 설정
        cmd_id가 None이면 둘 다 0 (즉시 정지)
        """
        if cmd_id is None:
            self.lin_vel = chrono.ChVector3d(0, 0, 0)
            self.ang_vel = chrono.ChVector3d(0, 0, 0)
            return

        v = lin_speed
        w = ang_speed_rad

        lv = chrono.ChVector3d(0, 0, 0)
        wv = chrono.ChVector3d(0, 0, 0)

        # 병진 명령
        if cmd_id == 1:      # +X
            lv = chrono.ChVector3d(+v, 0, 0)
        elif cmd_id == 2:    # -X
            lv = chrono.ChVector3d(-v, 0, 0)
        elif cmd_id == 3:    # +Y
            lv = chrono.ChVector3d(0, +v, 0)
        elif cmd_id == 4:    # -Y
            lv = chrono.ChVector3d(0, -v, 0)
        elif cmd_id == 5:    # +Z
            lv = chrono.ChVector3d(0, 0, +v)
        elif cmd_id == 6:    # -Z
            lv = chrono.ChVector3d(0, 0, -v)

        # 회전 명령
        elif cmd_id == 7:    # +X 회전
            wv = chrono.ChVector3d(+w, 0, 0)
        elif cmd_id == 8:    # -X 회전
            wv = chrono.ChVector3d(-w, 0, 0)
        elif cmd_id == 9:    # +Y 회전
            wv = chrono.ChVector3d(0, +w, 0)
        elif cmd_id == 10:   # -Y 회전
            wv = chrono.ChVector3d(0, -w, 0)
        elif cmd_id == 11:   # +Z 회전
            wv = chrono.ChVector3d(0, 0, +w)
        elif cmd_id == 12:   # -Z 회전
            wv = chrono.ChVector3d(0, 0, -w)

        self.lin_vel = lv
        self.ang_vel = wv

    def integrate(self, dt: float):
        """
        v, ω를 가지고 base_pos/base_rot를 dt만큼 진화시킴.
        (shaft는 joint+motor가 따라붙음)
        """
        # 1) 병진
        dx = self.lin_vel.x * dt
        dy = self.lin_vel.y * dt
        dz = self.lin_vel.z * dt
        delta_t = chrono.ChVector3d(dx, dy, dz)

        def add_vec(a: chrono.ChVector3d, b: chrono.ChVector3d):
            return chrono.ChVector3d(a.x + b.x, a.y + b.y, a.z + b.z)

        self.base_pos = add_vec(self.base_pos, delta_t)

        # 2) 회전
        wx, wy, wz = self.ang_vel.x, self.ang_vel.y, self.ang_vel.z
        w_mag = m.sqrt(wx*wx + wy*wy + wz*wz)
        if w_mag > 1e-12:
            axis = chrono.ChVector3d(wx / w_mag, wy / w_mag, wz / w_mag)
            angle = w_mag * dt  # rad
            q_delta = quat_from_axis_angle(axis, angle)
            self.base_rot = q_delta * self.base_rot

    def apply(self, base: chrono.ChBody, shaft: chrono.ChBody):
        """현재 저장된 base_pos/base_rot를 실제 base 바디에 적용"""
        base.SetPos(self.base_pos)
        base.SetRot(self.base_rot)
        safe_zero_dynamics(base)
        # shaft는 joint+motor가 관리하므로 건드리지 않음

# ============================================================
# 2. Command 버퍼 (터미널 입력용)
# ============================================================

class DiscreteCommandBuffer:
    def __init__(self):
        self._latest_cmd: Optional[int] = None
        self._lock = threading.Lock()

    def set_command(self, cmd_id: Optional[int]):
        with self._lock:
            self._latest_cmd = cmd_id

    def read_inputs(self) -> Dict[str, Any]:
        with self._lock:
            cmd = self._latest_cmd
        return {"command_id": cmd}

# ============================================================
# 3. SimHandle + base/shaft + joint + motor
# ============================================================

class SimHandle:
    def __init__(self, sys, base, shaft, joint, motor, buffer: DiscreteCommandBuffer):
        self.sys = sys
        self.base = base
        self.shaft = shaft
        self.joint = joint
        self.motor = motor
        self.buffer = buffer
        self.controller = AssemblyControllerVel(base, shaft)


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

    # 샤프트 자전 속도 (여기에서 조절 가능)
    motor_speed = 2.0  # rad/s
    func = chrono.ChFunctionConst(motor_speed)
    motor.SetSpeedFunction(func)
    motor.SetName("shaft_motor")
    sys.AddLink(motor)

    print(f"[asm] shaft-base + motor 조립 완료 (motor_speed={motor_speed} rad/s)")
    return base, shaft, joint, motor


def make_sim(buffer: DiscreteCommandBuffer) -> SimHandle:
    sys = chrono.ChSystemNSC()
    sys.SetGravitationalAcceleration(chrono.ChVector3d(0, 0, 0))

    base, shaft, joint, motor = create_base_shaft_with_motor(sys)
    return SimHandle(sys, base, shaft, joint, motor, buffer)

# ============================================================
# 4. step_sim_discrete: 등속/등각속 제어 + 동역학 스텝
# ============================================================

def step_sim_discrete(handle: SimHandle,
                      dt: float,
                      lin_speed: float,
                      ang_speed_rad: float):
    sys = handle.sys
    buf = handle.buffer
    ctrl = handle.controller

    # 1) 입력 읽기
    cmd_id = None
    try:
        inputs = buf.read_inputs()
        cmd_id = inputs.get("command_id", None)
    except Exception as e:
        print("[sim] read_inputs 에러:", e)

    # 2) 속도 세팅
    ctrl.set_velocity_from_command(cmd_id, lin_speed, ang_speed_rad)

    # 3) 등속/등각속도 적분
    ctrl.integrate(dt)

    # 4) 실제 base 바디에 적용
    ctrl.apply(handle.base, handle.shaft)

    # 5) 동역학 스텝
    sys.DoStepDynamics(dt)

# ============================================================
# 5. 터미널 입력 쓰레드
# ============================================================

def command_input_loop(buffer: DiscreteCommandBuffer, stop_flag: threading.Event):
    """
    터미널에서 1~12 / 공백 / q 입력 받는 루프.
    - 1~12 : 해당 명령으로 등속/등각속도 시작
    - 공백(엔터만) : 즉시 정지
    - q : 종료 플래그 세팅
    """
    print("\n[input] 명령 입력 도움말")
    print("  1~6  : +X/-X, +Y/-Y, +Z/-Z 병진")
    print("  7~12 : +X/-X, +Y/-Y, +Z/-Z 회전")
    print("  빈 엔터 : 정지 (None)")
    print("  q     : 종료 요청\n")

    while not stop_flag.is_set():
        try:
            s = input("[input] command (1-12, empty=stop, q=quit): ").strip()
        except EOFError:
            break

        if s.lower() == "q":
            print("[input] 종료 요청 (q)")
            buffer.set_command(None)
            stop_flag.set()
            break

        if s == "":
            buffer.set_command(None)
            print("[input] → stop (command=None)")
            continue

        try:
            cmd = int(s)
            if 1 <= cmd <= 12:
                buffer.set_command(cmd)
                print(f"[input] → set command = {cmd}")
            else:
                print("[input] 1~12 사이의 숫자만 입력해주세요.")
        except ValueError:
            print("[input] 잘못된 입력입니다. (예: 1, 5, 11, 빈엔터, q)")

# ============================================================
# 6. 데모 실행
# ============================================================

def run_discrete_velocity_terminal_demo():
    """
    - Irrlicht 시각화 창이 열려 있는 동안
    - VSCode 터미널에서 1~12 / 빈 엔터 / q 를 계속 입력해서
      base+shaft 어셈블리를 등속/등각속도로 움직여보는 데모
    """
    print("[test] run_discrete_velocity_terminal_demo() 시작")

    buffer = DiscreteCommandBuffer()
    handle = make_sim(buffer)
    sys = handle.sys

    # 터미널 입력용 쓰레드 시작
    stop_flag = threading.Event()
    t_input = threading.Thread(
        target=command_input_loop,
        args=(buffer, stop_flag),
        daemon=True,
    )
    t_input.start()

    # 시각화 설정
    vis = chronoirr.ChVisualSystemIrrlicht()
    vis.AttachSystem(sys)
    vis.SetWindowSize(1024, 768)
    vis.SetWindowTitle("Discrete Velocity + Terminal Command Demo")
    vis.Initialize()

    vis.AddSkyBox()
    vis.AddTypicalLights()
    vis.AddCamera(chrono.ChVector3d(0.05, 0.05, 0.12))

    dt = 0.01
    sim_time = 0.0
    end_time = 9999.0  # 사실상 무한, q 누르거나 창 닫으면 끝

    # 속도 설정 (여기서 체감 속도 조절)
    LIN_SPEED = 0.2        # m/s
    ANG_SPEED_DEG = 30.0     # deg/s
    ANG_SPEED_RAD = m.radians(ANG_SPEED_DEG)

    step_count = 0

    while vis.Run() and sim_time < end_time and not stop_flag.is_set():
        step_sim_discrete(handle, dt, LIN_SPEED, ANG_SPEED_RAD)
        sim_time += dt
        step_count += 1

        vis.BeginScene()
        vis.Render()
        vis.EndScene()

        time.sleep(0.005)

    print(f"[test] 종료: step_count={step_count}, sim_time={sim_time:.3f}")
    stop_flag.set()


if __name__ == "__main__":
    run_discrete_velocity_terminal_demo()
