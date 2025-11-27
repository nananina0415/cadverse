# 본 개발에서는 외부에서 불러사용하는 sim_interface or sim_public 과 캡슐화된내부구현 sim_logic or sim_private or sim_impl 을 분리

import math as m
import os
from pathlib import Path
from typing import List, Callable, Optional, Any, Dict
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


class Simulator:
    """
    시뮬레이션 실행 엔진
    - Simulation 객체를 소유하고 매 스텝마다 업데이트
    - step() 호출 시 자동으로 simulation.modelState에 결과 커밋
    """

    def __init__(self, simulation: Simulation, getUserInput: 'Callable[[], List]'):
        """
        Args:
            simulation: Simulation 객체 (상태 컨테이너)
            getUserInput: 사용자 입력을 읽는 함수 (getReadAccess()의 반환값)
        """
        self.simulation = simulation
        self.getUserInput = getUserInput
        self.step_count = 0
        # AR 드래그 상태
        self.interaction_state = AssemblyInteractionState()

    def step(self):
        """
        시뮬레이션 한 스텝 실행
        1. 사용자 입력 읽기 (향후 구현)
        2. Chrono 시뮬레이션 스텝 실행
        3. 결과를 simulation.modelState에 커밋
        """
        # Chrono 시뮬레이션 한 스텝 실행
        self.simulation.simHandle.sys.DoStepDynamics(self.simulation.dt)

        # 결과를 읽어서 modelState에 커밋
        bodies = self.simulation.simHandle.bodies
        new_states = [PartState.fromBody(b) for b in bodies]
        self.simulation.modelState.commit(new_states)

        # 1000 스텝마다 로그 출력 (버퍼 커밋 상태 포함)
        self.step_count += 1
        if self.step_count % 1000 == 0:
            sim_time = self.simulation.simHandle.sys.GetChTime()
            # 첫 번째 바디의 위치 확인
            if new_states:
                pos = new_states[0].pos
                print(f"[sim] Step {self.step_count}, Time: {sim_time:.3f}s, 버퍼 커밋: {len(new_states)} parts, pos=({pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f})", flush=True)

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


def _create_shaft_with_base(sys, shaft_meta, base_meta, motor_speed, bodies, joints, motors):
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
    motor = _make_rotation_motor(sys, shaft, base, shaft_center_world, shaft_axis, motor_speed)
    if hasattr(motor, "SetName"):
        motor.SetName(shaft_meta.get("motor_name", "shaft_motor"))
    motors.append(motor)

    print(f"[sim] 샤프트-베이스 조립 완료 (speed = {motor_speed} rad/s)")



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

    # 2) assemblies 기반 조립
    model_meta = sim_description.model_meta
    assemblies = model_meta.get("assemblies", [])
    print(f"[sim] assemblies 개수 = {len(assemblies)}")

    for asm in assemblies:
        asm_type = asm.get("type")
        print(f"[sim] assembly 처리: type = {asm_type}")

        if asm_type == "shaft_base":
            shaft_meta = asm["shaft"]
            base_meta = asm["base"]
            motor_speed = asm.get("motor_speed", 5.0)

            _create_shaft_with_base(
                sys=sys,
                shaft_meta=shaft_meta,
                base_meta=base_meta,
                motor_speed=motor_speed,
                bodies=bodies,
                joints=joints,
                motors=motors,
            )
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

    # 4) 초기 상태 생성
    init_states = [PartState.fromBody(b) for b in bodies]
    model_state_buffer = ReadWriteBuffer[PartState](init_states)

    # 5) Simulation 객체 생성
    simulation = Simulation(
        modelState=model_state_buffer,
        simHandle=sim_handle,
        dt=sim_description.dt
    )

    print(f"[sim] buildSimulation() 완료 → bodies={len(bodies)}, joints={len(joints)}, motors={len(motors)}")

    return simulation

# 유저입력을 다루는부분
# AI가 생성한걸 확인없이 가져온거라 참고용으로만 봐주세요.
import pychrono as chrono
import math

class RailInteractionManager:
    def __init__(self, system):
        self.system = system

        # 구성 요소들
        self.ray_body = None      # 카메라 따라다니는 바디 (Gun)
        self.bead = None          # 레일 위 구슬 (Bullet)
        self.rail_joint = None    # 레일 구속 (Prismatic)
        self.depth_spring = None  # 깊이 유지 스프링 (거리 고정용)
        self.drag_link = None     # 모델 당기는 링크

    def start_interaction(self, target_id, action_local_pos, cam_pos, cam_dir, init_distance):
        # 1. Ray Body 생성 (카메라 위치/각도 동기화용)
        self.ray_body = chrono.ChBody()
        self.ray_body.SetFixed(False) # 움직여야 하므로 Fixed False
        self.ray_body.SetBodyFixed(True) # 대신 물리엔진이 못 건드리고 우리가 강제 이동(Kinematic)
        self.system.Add(self.ray_body)

        # Ray Body 위치/자세 초기화 (Z축이 카메라 정면이 되도록)
        # Chrono의 기본 Z축을 cam_dir로 맞추는 회전 행렬 계산 필요 (여기서는 간단히 pos만 세팅한다고 가정)
        self.update_ray_body_transform(cam_pos, cam_dir)

        # 2. Bead (구슬) 생성
        self.bead = chrono.ChBody()
        self.bead.SetMass(0.01) # 가볍게
        self.bead.SetPos(cam_pos + cam_dir * init_distance) # 초기 위치는 거리 d 만큼 앞
        self.system.Add(self.bead)

        # 3. Rail Joint (Prismatic) 생성: RayBody <-> Bead
        # Z축(진행방향)으로만 움직이게 구속
        self.rail_joint = chrono.ChLinkLockPrismatic()
        self.rail_joint.Initialize(self.ray_body, self.bead, chrono.ChCoordsysd(cam_pos, self.ray_body.GetRot()))
        self.system.Add(self.rail_joint)

        # 4. [나중을 위한 포석] Depth Spring (거리 유지용)
        # 지금은 거리를 고정하지만, 나중엔 이 스프링에 힘을 가해 깊이를 조절함
        self.depth_spring = chrono.ChLinkTSDA()
        self.depth_spring.Initialize(self.ray_body, self.bead, False, chrono.ChVector3d(0,0,0), chrono.ChVector3d(0,0,0))
        self.depth_spring.SetSpringCoefficient(10000) # 거리 유지 (짱짱하게)
        self.depth_spring.SetDampingCoefficient(100)
        self.depth_spring.SetRestLength(init_distance) # 초기 거리 유지
        self.system.Add(self.depth_spring)

        # 5. Drag Link (실제 모델 연결)
        target_body = self.system.SearchBody(target_id)
        self.drag_link = chrono.ChLinkTSDA()
        self.drag_link.Initialize(target_body, self.bead, True, action_local_pos, chrono.ChVector3d(0,0,0)) # Bead 중심에 연결
        self.drag_link.SetSpringCoefficient(50000) # 모델을 강하게 당김
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
        x_axis = chrono.ChVector3d(1,0,0) # 임시
        if abs(z_axis.x) > 0.9: x_axis = chrono.ChVector3d(0,1,0)
        y_axis = (z_axis % x_axis).GetNormalized()
        x_axis = (y_axis % z_axis).GetNormalized()

        rot_matrix = chrono.ChMatrix33d(x_axis, y_axis, z_axis)
        self.ray_body.SetPos(pos)
        self.ray_body.SetRot(rot_matrix.Get_A_quaternion())

#    - AR 인터랙션: 각 모델을 한 덩어리로 드래그/회전
#    - getUserInput() 이 반환하는 이벤트 리스트를 받아서
#    - 각 바디에 rigid transform을 적용하는 헬퍼

class AssemblyInteractionState:
    """
    베이스+샤프트 한 세트를 드래그할 때 사용할 내부 상태.
    - active: 현재 드래그 중인지
    - start_finger: 드래그 시작 시 손가락 위치 (world)
    - base_pos0 / shaft_pos0: 드래그 시작 시점의 위치
    - base_rot0 / shaft_rot0: 드래그 시작 시점의 회전
    - center0: assembly 중심 (간단히 base, shaft 위치 평균으로 사용)
    """

    def __init__(self):
        self.active: bool = False
        self.start_finger: Optional[chrono.ChVector3d] = None

        self.base_pos0: Optional[chrono.ChVector3d] = None
        self.base_rot0: Optional[chrono.ChQuaterniond] = None

        self.shaft_pos0: Optional[chrono.ChVector3d] = None
        self.shaft_rot0: Optional[chrono.ChQuaterniond] = None

        self.center0: Optional[chrono.ChVector3d] = None


def _to_vec3(d: Optional[Dict[str, Any]]) -> chrono.ChVector3d:
    """{"x":..., "y":..., "z":...} 딕셔너리를 ChVector3d로 변환"""
    if not d:
        return chrono.ChVector3d(0, 0, 0)
    return chrono.ChVector3d(
        float(d.get("x", 0.0)),
        float(d.get("y", 0.0)),
        float(d.get("z", 0.0)),
    )


def _find_body_by_name(handle: SimHandle, name: str):
    """SimHandle.bodies에서 이름으로 ChBody 검색"""
    for b in handle.bodies:
        if hasattr(b, "GetName") and b.GetName() == name:
            return b
    return None


def apply_ar_interaction(
    handle: SimHandle,
    interaction: AssemblyInteractionState,
    events: List[Dict[str, Any]],
):
    """
    AR 입력(InteractByScreen 스타일 이벤트들)을 받아
    base + shaft 두 바디를 함께 이동/회전시킨다.

    전제:
      - getUserInput() 이 반환하는 각 이벤트는 다음 형태라고 가정:
        {
          "type": "TouchStart" | "Touching" | "TouchEnd",
          "payload": {
              "targetPartName": "shaft" or "base" (선택, 없으면 기본 "shaft"),
              "fingerPoint": { "x":..., "y":..., "z":... },
              ...
          }
        }
      - 실제 JSON(TS 타입)은 sim_interface 층에서 이 포맷으로 변환 후 넘겨준다.
    """
    if not events:
        return

    # 일단 가장 마지막 이벤트만 반영 (한 스텝에 여러 개 들어와도 마지막 상태 기준으로)
    event = events[-1]
    etype = event.get("type")
    payload = event.get("payload") or {}

    # base / shaft 찾기 (이름은 meta에서 지정한 이름 사용)
    base = _find_body_by_name(handle, "base")
    shaft = _find_body_by_name(handle, "shaft")

    if base is None or shaft is None:
        # 아직 조립이 안 되어 있거나 이름이 다르면 아무것도 안 함
        return

    # ========= TouchStart =========
    if etype == "TouchStart":
        # (필요하면 targetPartName으로 어떤 assembly를 조작할지 나눌 수도 있음)
        finger = _to_vec3(payload.get("fingerPoint"))

        interaction.active = True
        interaction.start_finger = finger

        interaction.base_pos0 = base.GetPos()
        interaction.base_rot0 = base.GetRot()
        interaction.shaft_pos0 = shaft.GetPos()
        interaction.shaft_rot0 = shaft.GetRot()

        # assembly 중심 (base, shaft 위치 평균)
        bp = interaction.base_pos0
        sp = interaction.shaft_pos0
        cx = 0.5 * (bp.x + sp.x)
        cy = 0.5 * (bp.y + sp.y)
        cz = 0.5 * (bp.z + sp.z)
        interaction.center0 = chrono.ChVector3d(cx, cy, cz)

        # 드래그 시작 시 속도/각속도도 한번 0으로 초기화해두면 깔끔
        zero = chrono.ChVector3d(0, 0, 0)
        for body in (base, shaft):
            body.SetPos_dt(zero)
            body.SetPos_dtdt(zero)
            body.SetWvel_loc(zero)
            body.SetWacc_loc(zero)
            body.Empty_forces_accumulators()

        return

    # ========= Touching =========
    if etype == "Touching":
        if not interaction.active:
            return

        finger = _to_vec3(payload.get("fingerPoint"))
        start_finger = interaction.start_finger or chrono.ChVector3d(0, 0, 0)

        base_pos0 = interaction.base_pos0 or base.GetPos()
        shaft_pos0 = interaction.shaft_pos0 or shaft.GetPos()
        center0 = interaction.center0 or chrono.ChVector3d(0, 0, 0)

        # 1) 손가락 이동량 → translation
        delta = chrono.ChVector3d(
            finger.x - start_finger.x,
            finger.y - start_finger.y,
            finger.z - start_finger.z,
        )

        # 2) 손가락의 x 이동량을 assembly의 z축 회전으로 매핑 (간단한 프로토타입)
        dx = finger.x - start_finger.x
        scale = 5.0  # 1m → 약 5rad 회전 (튜닝 가능)
        angle = scale * dx

        c = m.cos(angle)
        s = m.sin(angle)

        def rigid_transform(pos0: chrono.ChVector3d) -> chrono.ChVector3d:
            # center0 기준 로컬 좌표
            rx = pos0.x - center0.x
            ry = pos0.y - center0.y
            rz = pos0.z - center0.z
            # z축 회전
            x1 = c * rx - s * ry
            y1 = s * rx + c * ry
            z1 = rz
            # 다시 center0로 되돌리고, translation(delta) 적용
            return chrono.ChVector3d(
                center0.x + x1 + delta.x,
                center0.y + y1 + delta.y,
                center0.z + z1 + delta.z,
            )

        # 위치
        new_base_pos = rigid_transform(base_pos0)
        new_shaft_pos = rigid_transform(shaft_pos0)
        base.SetPos(new_base_pos)
        shaft.SetPos(new_shaft_pos)

        # 회전 (여기서는 그냥 z축 회전 쿼터니언을 곱해주는 단순 버전)
        try:
            q_delta = chrono.QuatFromAngleZ(angle)
        except AttributeError:
            q_delta = chrono.QUNIT

        base.SetRot(q_delta * (interaction.base_rot0 or base.GetRot()))
        shaft.SetRot(q_delta * (interaction.shaft_rot0 or shaft.GetRot()))

        return

    # ========= TouchEnd =========
    if etype == "TouchEnd":
        if interaction.active:
            # 드래그 끝나는 순간, 그 포즈에서 "딱" 멈추도록 속도/각속도 0으로
            zero = chrono.ChVector3d(0, 0, 0)
            for body in (base, shaft):
                body.SetPos_dt(zero)
                body.SetPos_dtdt(zero)
                body.SetWvel_loc(zero)
                body.SetWacc_loc(zero)
                body.Empty_forces_accumulators()

        # 상태 초기화
        interaction.active = False
        interaction.start_finger = None
        interaction.base_pos0 = None
        interaction.base_rot0 = None
        interaction.shaft_pos0 = None
        interaction.shaft_rot0 = None
        interaction.center0 = None

        return
