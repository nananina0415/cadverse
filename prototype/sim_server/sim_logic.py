# 본 개발에서는 외부에서 불러사용하는 sim_interface or sim_public 과 캡슐화된내부구현 sim_logic or sim_private or sim_impl 을 분리

import math as m
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pychrono as chrono
from sim_data_models import PartState, SimDescription, Simulation
from utils.read_write_buffer import ReadWriteBuffer

# 리소스 디렉토리 경로
RESOURCES_DIR = Path(__file__).parent / "resources"


class SimHandle:
    """PyChrono 시뮬레이션의 핸들 (시스템, 바디, 조인트, 모터 등)"""

    def __init__(self, sys, bodies, joints, motors, buffer):
        self.sys = sys
        self.bodies = bodies
        self.joints = joints
        self.motors = motors
        self.buffer = buffer

        # --- AR 드래그용 추가 필드들 ---
        self.shaft_body: Optional[chrono.ChBody] = None
        self.shaft_center_world: Optional[chrono.ChVector3d] = None
        self.shaft_axis_world: Optional[chrono.ChVector3d] = None
        self.drag_controller: Optional["ShaftDragController"] = None



class Simulator:
    """
    시뮬레이션 실행 엔진
    - Simulation 객체를 소유하고 매 스텝마다 업데이트
    - step() 호출 시 자동으로 simulation.modelState에 결과 커밋
    """

    def __init__(self, simulation: Simulation, getUserInput: "Callable[[], List]"):
        """
        Args:
            simulation: Simulation 객체 (상태 컨테이너)
            getUserInput: 사용자 입력을 읽는 함수 (getReadAccess()의 반환값)
        """
        self.simulation = simulation
        self.getUserInput = getUserInput
        self.step_count = 0

    def step(self):
        """
        시뮬레이션 한 스텝 실행
        1. userInput 버퍼에서 최신 AR 이벤트를 읽어옴
        2. (선택) AR 드래그 컨트롤러에 이벤트 전달 → 토크/각속도 갱신
        3. Chrono 시뮬레이션 스텝 실행
        4. 결과를 simulation.modelState에 커밋
        """
        handle = self.simulation.simHandle
        dt = self.simulation.dt

        # 1) userInput 버퍼에서 최신 AR 이벤트 읽기
        event = None
        try:
            if self.getUserInput is not None:
                inputs = self.getUserInput()  # ReadWriteBuffer.getReadAccess() 결과
            else:
                inputs = []
        except Exception as e:
            print(f"[sim] getUserInput() 호출 중 에러: {e}")
            inputs = []

        if inputs:
            # userInput 버퍼에는 "최근 이벤트 1개"만 넣는다고 가정하고 마지막 것 사용
            event = inputs[-1]

        # 2) AR 드래그 컨트롤러가 있으면 이벤트를 전달하고 한 스텝 실행
        drag = getattr(handle, "drag_controller", None)
        if drag is not None:
            drag.set_event(event)
            drag.step(dt)

        # 3) Chrono 시뮬레이션 한 스텝 실행
        handle.sys.DoStepDynamics(dt)

        # 4) 결과를 읽어서 modelState에 커밋
        bodies = handle.bodies
        new_states = [PartState.fromBody(b) for b in bodies]
        self.simulation.modelState.commit(new_states)

        self.step_count += 1


    def clear(self):
        """시뮬레이터 정리 (Chrono 리소스 해제)"""
        # kill_sim() 내용을 직접 하드코딩
        handle = self.simulation.simHandle
        handle.sys.Clear()
        handle.bodies.clear()
        handle.joints.clear()
        handle.motors.clear()
        print("[sim] 시뮬레이터 리소스 정리 완료")


# 헬퍼 함수들


def _load_body_from_obj(meta):
    """OBJ 파일에서 ChBody 생성"""
    path = meta["mesh"]
    mass = meta.get("mass", 1000)
    fixed = meta.get("fixed", False)

    # 상대 경로를 resources 기준으로 변환
    # PyChrono는 한글 경로를 처리하지 못하므로 상대 경로만 사용
    if not os.path.isabs(path):
        rel_path = f"resources/{path}"
    else:
        rel_path = path

    # 경로 존재 확인 (절대 경로로 검증)
    check_path = str(RESOURCES_DIR / path) if not os.path.isabs(path) else path
    if not os.path.exists(check_path):
        raise FileNotFoundError(f"OBJ 파일을 찾을 수 없습니다: {check_path}")

    print(f"[sim] OBJ 파일 로드 중: {rel_path}")

    # PyChrono에는 상대 경로 전달 (한글 경로 이슈 회피)
    body = chrono.ChBodyEasyMesh(rel_path, mass, False, True)
    body.SetName(meta.get("name", "unnamed"))
    body.SetFixed(fixed)

    return body


def _read_obj_bounds(path):
    """OBJ 파일의 bounding box 읽기"""
    # 상대 경로를 절대 경로로 변환
    if not os.path.isabs(path):
        path = str(RESOURCES_DIR / path)

    xs, ys, zs = [], [], []
    with open(path, "r") as f:
        for line in f:
            if line.startswith("v "):
                _, x, y, z = line.split()
                xs.append(float(x))
                ys.append(float(y))
                zs.append(float(z))
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _detect_axis_and_center(path):
    """OBJ 파일에서 중심과 회전축 자동 검출"""
    xmin, xmax, ymin, ymax, zmin, zmax = _read_obj_bounds(path)

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


def _quat_from_axis(axis: chrono.ChVector3d):
    """축 방향을 쿼터니언으로 변환"""
    if axis.x == 0 and axis.y == 0 and axis.z == 1:
        return chrono.QUNIT
    if axis.x == 1 and axis.y == 0 and axis.z == 0:
        return chrono.QuatFromAngleY(-m.pi / 2)
    if axis.x == 0 and axis.y == 1 and axis.z == 0:
        return chrono.QuatFromAngleX(+m.pi / 2)
    return chrono.QUNIT


def _make_revolute(sys, body, base, center, axis):
    """회전 조인트 생성"""
    q = _quat_from_axis(axis)
    frame = chrono.ChFramed(center, q)

    joint = chrono.ChLinkLockRevolute()
    joint.Initialize(body, base, frame)
    sys.AddLink(joint)

    return joint


def _make_rotation_motor(sys, body, base, center, axis, speed):
    """회전 모터 생성"""
    q = _quat_from_axis(axis)
    frame = chrono.ChFramed(center, q)

    motor = chrono.ChLinkMotorRotationSpeed()
    motor.Initialize(body, base, frame)

    func = chrono.ChFunctionConst(speed)
    motor.SetSpeedFunction(func)

    sys.AddLink(motor)
    return motor


def _create_shaft_with_base(
    sys, shaft_meta, base_meta, motor_speed, bodies, joints, motors
):
    """샤프트-베이스 조립"""
    # 베이스 생성
    base = _load_body_from_obj(base_meta)
    base.SetFixed(True)
    sys.Add(base)
    bodies.append(base)

    # 샤프트 생성
    shaft = _load_body_from_obj(shaft_meta)
    shaft.SetFixed(False)
    offset_list = shaft_meta.get("offset", [0.0, 0.0, 0.0])
    shaft_offset = chrono.ChVector3d(offset_list[0], offset_list[1], offset_list[2])
    shaft.SetPos(shaft_offset)
    sys.Add(shaft)
    bodies.append(shaft)

    # 중심/축 검출
    shaft_mesh_path = shaft_meta["mesh"]
    shaft_center_local, shaft_axis = _detect_axis_and_center(shaft_mesh_path)
    shaft_center_world = shaft_center_local + shaft_offset

    # 조인트 생성
    rev = _make_revolute(sys, shaft, base, shaft_center_world, shaft_axis)
    joints.append(rev)

    # 모터 생성
    motor = _make_rotation_motor(
        sys, shaft, base, shaft_center_world, shaft_axis, motor_speed
    )
    if hasattr(motor, "SetName"):
        motor.SetName(shaft_meta.get("motor_name", "shaft_motor"))
    motors.append(motor)

    print(f"[sim] 샤프트-베이스 조립 완료 (speed = {motor_speed} rad/s)")
    # AR 드래그 컨트롤러에서 쓸 샤프트 정보 리턴
    return {
        "base": base,
        "shaft": shaft,
        "shaft_center_world": shaft_center_world,
        "shaft_axis_world": shaft_axis,
    }


def buildSimulation(sim_description: SimDescription) -> Simulation:
    """
    SimDescription으로부터 Simulation 객체 생성
    make_sim() 내용을 직접 하드코딩
    """
    print("[sim] buildSimulation() 호출됨")

    # 1) PyChrono 시스템 생성
    sys = chrono.ChSystemNSC()
    sys.SetGravitationalAcceleration(chrono.ChVector3d(0, -9.81, 0))

    bodies = []
    joints = []
    motors = []

    # AR 드래그용으로 대표 샤프트 한 개만 추적
    primary_shaft_info = None

    # 2) assemblies 기반 조립
    model_meta = sim_description.model_meta
    assemblies = model_meta.get("assemblies", [])
    print(f"[sim] assemblies 개수 = {len(assemblies)}")

    for asm in assemblies:
        asm_type = asm.get("type")
        print(f"[sim] assembly 처리: type = {asm_type}")

        if asm_type == "shaft_base":
            # parts 배열에서 shaft와 base 찾기
            parts = asm.get("parts", [])
            shaft_meta = next((p for p in parts if p.get("name") == "shaft"), None)
            base_meta = next((p for p in parts if p.get("name") == "base"), None)
            motor_speed = asm.get("motor_speed", 5.0)

            if shaft_meta is None or base_meta is None:
                print(f"[sim] 경고: shaft 또는 base를 찾을 수 없음")
                continue

            info = _create_shaft_with_base(
                sys=sys,
                shaft_meta=shaft_meta,
                base_meta=base_meta,
                motor_speed=motor_speed,
                bodies=bodies,
                joints=joints,
                motors=motors,
            )

            # 첫 번째 shaft_base 세트를 AR 드래그 타겟으로 사용
            if primary_shaft_info is None:
                primary_shaft_info = info

        else:
            print(f"[sim] 알 수 없는 assembly type: {asm_type}")

    # 3) SimHandle 생성
    sim_handle = SimHandle(
        sys=sys,
        bodies=bodies,
        joints=joints,
        motors=motors,
        buffer=None,
    )

    # 3-1) 샤프트 정보 / 드래그 컨트롤러 세팅
    if primary_shaft_info is not None:
        sim_handle.shaft_body = primary_shaft_info["shaft"]
        sim_handle.shaft_center_world = primary_shaft_info["shaft_center_world"]
        sim_handle.shaft_axis_world = primary_shaft_info["shaft_axis_world"]

        # AR 드래그 컨트롤러 인스턴스 생성
        sim_handle.drag_controller = ShaftDragController(sim_handle)
        print("[sim] ShaftDragController 초기화 완료")
    else:
        print("[sim] 경고: shaft_base 어셈블리를 찾지 못해 드래그 컨트롤러를 설정하지 못했습니다.")


    # 4) 초기 상태 생성
    init_states = [PartState.fromBody(b) for b in bodies]
    model_state_buffer = ReadWriteBuffer[PartState](init_states)

    # 5) Simulation 객체 생성
    simulation = Simulation(
        modelState=model_state_buffer, simHandle=sim_handle, dt=sim_description.dt
    )

    print(
        f"[sim] buildSimulation() 완료 → bodies={len(bodies)}, joints={len(joints)}, motors={len(motors)}"
    )

    return simulation



# 유저입력을 다루는부분
# AI가 생성한걸 확인없이 가져온거라 참고용으로만 봐주세요.


class RailInteractionManager:
    def __init__(self, system):
        self.system = system

        # 구성 요소들
        self.ray_body = None  # 카메라 따라다니는 바디 (Gun)
        self.bead = None  # 레일 위 구슬 (Bullet)
        self.rail_joint = None  # 레일 구속 (Prismatic)
        self.depth_spring = None  # 깊이 유지 스프링 (거리 고정용)
        self.drag_link = None  # 모델 당기는 링크

    def start_interaction(
        self, target_id, action_local_pos, cam_pos, cam_dir, init_distance
    ):
        # 1. Ray Body 생성 (카메라 위치/각도 동기화용)
        self.ray_body = chrono.ChBody()
        self.ray_body.SetFixed(False)  # 움직여야 하므로 Fixed False
        self.ray_body.SetBodyFixed(
            True
        )  # 대신 물리엔진이 못 건드리고 우리가 강제 이동(Kinematic)
        self.system.Add(self.ray_body)

        # Ray Body 위치/자세 초기화 (Z축이 카메라 정면이 되도록)
        # Chrono의 기본 Z축을 cam_dir로 맞추는 회전 행렬 계산 필요 (여기서는 간단히 pos만 세팅한다고 가정)
        self.update_ray_body_transform(cam_pos, cam_dir)

        # 2. Bead (구슬) 생성
        self.bead = chrono.ChBody()
        self.bead.SetMass(0.01)  # 가볍게
        self.bead.SetPos(
            cam_pos + cam_dir * init_distance
        )  # 초기 위치는 거리 d 만큼 앞
        self.system.Add(self.bead)

        # 3. Rail Joint (Prismatic) 생성: RayBody <-> Bead
        # Z축(진행방향)으로만 움직이게 구속
        self.rail_joint = chrono.ChLinkLockPrismatic()
        self.rail_joint.Initialize(
            self.ray_body,
            self.bead,
            chrono.ChCoordsysd(cam_pos, self.ray_body.GetRot()),
        )
        self.system.Add(self.rail_joint)

        # 4. [나중을 위한 포석] Depth Spring (거리 유지용)
        # 지금은 거리를 고정하지만, 나중엔 이 스프링에 힘을 가해 깊이를 조절함
        self.depth_spring = chrono.ChLinkTSDA()
        self.depth_spring.Initialize(
            self.ray_body,
            self.bead,
            False,
            chrono.ChVector3d(0, 0, 0),
            chrono.ChVector3d(0, 0, 0),
        )
        self.depth_spring.SetSpringCoefficient(10000)  # 거리 유지 (짱짱하게)
        self.depth_spring.SetDampingCoefficient(100)
        self.depth_spring.SetRestLength(init_distance)  # 초기 거리 유지
        self.system.Add(self.depth_spring)

        # 5. Drag Link (실제 모델 연결)
        target_body = self.system.SearchBody(target_id)
        self.drag_link = chrono.ChLinkTSDA()
        self.drag_link.Initialize(
            target_body, self.bead, True, action_local_pos, chrono.ChVector3d(0, 0, 0)
        )  # Bead 중심에 연결
        self.drag_link.SetSpringCoefficient(50000)  # 모델을 강하게 당김
        self.drag_link.SetDampingCoefficient(500)
        self.drag_link.SetRestLength(0)
        self.system.Add(self.drag_link)

    def update_interaction(self, cam_pos, cam_dir):
        # 매 프레임: 카메라(RayBody)만 옮기면 레일, 구슬, 링크가 싹 다 따라옴
        self.update_ray_body_transform(cam_pos, cam_dir)

        # (나중에 깊이 보정 로직이 들어갈 자리)
        # depth_input = get_user_depth_input()
        # self.depth_spring.SetRestLength(self.initial_dist + depth_input * scale)

    def end_interaction(self):
        # 정리
        self.system.Remove(self.drag_link)
        self.system.Remove(self.depth_spring)
        self.system.Remove(self.rail_joint)
        self.system.Remove(self.bead)
        self.system.Remove(self.ray_body)

    def update_ray_body_transform(self, pos, dir):
        # 카메라 좌표계로 RayBody 강제 이동
        # Dir 벡터를 Rotation Quaternion으로 변환하는 로직 포함
        z_axis = dir.GetNormalized()
        x_axis = chrono.ChVector3d(1, 0, 0)  # 임시
        if abs(z_axis.x) > 0.9:
            x_axis = chrono.ChVector3d(0, 1, 0)
        y_axis = (z_axis % x_axis).GetNormalized()
        x_axis = (y_axis % z_axis).GetNormalized()

        rot_matrix = chrono.ChMatrix33d(x_axis, y_axis, z_axis)
        self.ray_body.SetPos(pos)
        self.ray_body.SetRot(rot_matrix.Get_A_quaternion())


# ============================================================
#  AR Touch → Torque 기반 1-DOF Shaft Rotation Controller
#  (AR 드래그를 토크로 변환하여 축 방향 회전 구현)
#
#  사용 흐름:
#   1. buildSimulation 후:
#        sim.simHandle.drag_controller = ShaftDragController(sim.simHandle)
#
#   2. 서버 WebSocket 이벤트 수신 시:
#        drag_controller.set_event(ws_event_dict)
#
#   3. 시뮬 step() 내부에서 매 tick 호출:
#        drag_controller.step(dt)
# ============================================================


def _vec_from_dict(d: Optional[Dict[str, float]]) -> chrono.ChVector3d:
    if not d:
        return chrono.ChVector3d(0, 0, 0)
    return chrono.ChVector3d(
        float(d.get("x", 0.0)),
        float(d.get("y", 0.0)),
        float(d.get("z", 0.0)),
    )


def _vec_length(v: chrono.ChVector3d) -> float:
    return (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5


def _vec_normalize(v: chrono.ChVector3d) -> chrono.ChVector3d:
    L = _vec_length(v)
    if L < 1e-12:
        return chrono.ChVector3d(0, 0, 0)
    return chrono.ChVector3d(v.x / L, v.y / L, v.z / L)


def _vec_add(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(a.x + b.x, a.y + b.y, a.z + b.z)


def _vec_sub(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(a.x - b.x, a.y - b.y, a.z - b.z)


def _vec_scale(v: chrono.ChVector3d, s: float) -> chrono.ChVector3d:
    return chrono.ChVector3d(v.x * s, v.y * s, v.z * s)


def _vec_cross(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    )


def _vec_dot(a: chrono.ChVector3d, b: chrono.ChVector3d) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def _get_angvel(body: chrono.ChBody) -> chrono.ChVector3d:
    """가능하면 parent 기준 각속도를 읽는다."""
    if hasattr(body, "GetAngVelParent"):
        return body.GetAngVelParent()
    elif hasattr(body, "GetAngVelLocal"):
        return body.GetAngVelLocal()
    return chrono.ChVector3d(0, 0, 0)


def _set_angvel(body: chrono.ChBody, w: chrono.ChVector3d):
    """가능하면 parent 기준 각속도를 쓴다."""
    if hasattr(body, "SetAngVelParent"):
        body.SetAngVelParent(w)
    elif hasattr(body, "SetAngVelLocal"):
        body.SetAngVelLocal(w)


def _clear_forces(body: chrono.ChBody):
    """이 바디에 누적된 외력/토크만 비움"""
    if hasattr(body, "EmptyAccumulators"):
        body.EmptyAccumulators()


def _apply_torque(body: chrono.ChBody, t: chrono.ChVector3d):
    """버전에 따라 AccumulateTorque / AddTorque 중 되는 걸 사용"""
    if hasattr(body, "AccumulateTorque"):
        try:
            body.AccumulateTorque(t, False)
        except TypeError:
            body.AccumulateTorque(t)
    elif hasattr(body, "AddTorque"):
        body.AddTorque(t)


# ============================================================
#  Shaft Drag Controller Class
# ============================================================
# ㄴ현재 단순한 1-DOF용 로직, 이 부분을 교체하여 다양한 자유도 컨트롤러 구현 가능
class ShaftDragController:
    """
    하나의 회전 샤프트에 대해
    - TouchStart / Touching / TouchEnd 이벤트를 받아
    - 토크 적용 + 축 방향 각속도 감쇠를 수행하는 컨트롤러.

    전제:
      - sim_handle 안에 다음 정보가 존재한다고 가정한다.
        * sim_handle.sys              : ChSystemNSC
        * sim_handle.bodies[1]        : shaft 바디 (또는 별도 참조를 쓰도록 수정 가능)
        * sim_handle.shaft_center_world : 샤프트 중심 (ChVector3d)
        * sim_handle.shaft_axis_world   : 샤프트 축 (ChVector3d)
      - 아직 실제 코드에서는 이 필드를 추가/연결하지 않았으므로
        이 컨트롤러를 사용하기 전 그 부분을 먼저 세팅해야 한다.
    """

    DRAG_TORQUE = 0.005   # 드래그 시 주는 토크 크기
    DAMP_FREE = 8.0       # 손 뗀 후 감쇠 강도 (값 키우면 더 빨리 멈춤)
    DAMP_DRAG = 1.5       # 드래그 중 감쇠 강도 (너무 크면 잘 안 도는 느낌)
    VEL_EPS = 5e-3        # 이 이하 각속도면 그냥 0으로 스냅 (떨림 제거용)

    def __init__(self, sim_handle: Any):
        self.handle = sim_handle
        self.active: bool = False
        self.start_finger: Optional[chrono.ChVector3d] = None
        self.event: Optional[Dict[str, Any]] = None

    def set_event(self, event: Optional[Dict[str, Any]]):
        """
        서버(WebSocket)에서 받은 InteractByScreen 이벤트를 그대로 넘겨주면 됨.
        event 예:
          {
            "type": "TouchStart" | "Touching" | "TouchEnd",
            "payload": { ... }
          }
        """
        self.event = event

    def step(self, dt: float):
        """
        매 시뮬레이션 스텝마다 호출:
        - 마지막으로 set_event()로 등록된 이벤트를 해석해서
          토크를 적용하고 축 방향 각속도에 감쇠를 걸어준다.
        - 샤프트 하나만 1자유도 회전하는 것을 상정.
        """
        ev = self.event

        # shaft 바디 찾기:
        #  - 가능하면 sim_handle.shaft_body 사용
        #  - 없으면 bodies[1] (기존 가정)로 fallback
        if getattr(self.handle, "shaft_body", None) is not None:
            shaft = self.handle.shaft_body
        else:
            # bodies가 2개 이상이라는 기존 가정 유지
            shaft = self.handle.bodies[1]

        # 축/중심도 sim_handle에 세팅된 값을 사용 (없으면 기본값)
        axis_vec = self.handle.shaft_axis_world or chrono.ChVector3d(0, 0, 1)
        center = self.handle.shaft_center_world or chrono.ChVector3d(0, 0, 0)
        axis = _vec_normalize(axis_vec)


        # 1) 이번 프레임 시작 시 외력/토크 비우기 (중복 누적 방지)
        _clear_forces(shaft)

        # 2) 터치 이벤트 → 토크 생성
        if not ev:
            self.active = False
        else:
            et = ev.get("type")
            payload = ev.get("payload", {})

            if et == "TouchStart":
                self.active = True
                self.start_finger = _vec_from_dict(payload.get("fingerPoint"))
                # 필요하면 여기서 속도 초기화 가능
                # _set_angvel(shaft, chrono.ChVector3d(0, 0, 0))

            elif et == "TouchEnd":
                self.active = False

            elif et == "Touching" and self.active and self.start_finger is not None:
                finger = _vec_from_dict(payload.get("fingerPoint"))
                v0 = _vec_sub(self.start_finger, center)
                v1 = _vec_sub(finger, center)

                if _vec_length(v0) >= 1e-6 and _vec_length(v1) >= 1e-6:
                    v0n = _vec_normalize(v0)
                    v1n = _vec_normalize(v1)

                    arc_axis = _vec_cross(v0n, v1n)
                    arc_axis_n = _vec_normalize(arc_axis)

                    if _vec_length(arc_axis_n) >= 1e-6:
                        # 드래그 축과 샤프트 축의 방향성 비교 → 부호 결정
                        sign = 1.0 if _vec_dot(arc_axis_n, axis) >= 0.0 else -1.0
                        torque_world = _vec_scale(axis, sign * self.DRAG_TORQUE)
                        _apply_torque(shaft, torque_world)

        # 3) 축 방향 각속도 감쇠
        w = _get_angvel(shaft)
        w_along = _vec_dot(w, axis)

        dragging_now = (
            ev is not None
            and ev.get("type") == "Touching"
            and self.active
        )
        lam = self.DAMP_DRAG if dragging_now else self.DAMP_FREE

        if abs(w_along) < self.VEL_EPS:
            w_along_new = 0.0
        else:
            # exp 감쇠: 더 안정적이고 덜 튐
            w_along_new = w_along * m.exp(-lam * dt)

        w_new = _vec_scale(axis, w_along_new)
        _set_angvel(shaft, w_new)
