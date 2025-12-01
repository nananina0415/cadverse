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
            # parts 배열에서 shaft와 base 찾기
            parts = asm.get("parts", [])
            shaft_meta = next((p for p in parts if p.get("name") == "shaft"), None)
            base_meta = next((p for p in parts if p.get("name") == "base"), None)
            motor_speed = asm.get("motor_speed", 5.0)

            if shaft_meta is None or base_meta is None:
                print(f"[sim] 경고: shaft 또는 base를 찾을 수 없음")
                continue

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
        modelState=model_state_buffer, simHandle=sim_handle, dt=sim_description.dt
    )

    print(
        f"[sim] buildSimulation() 완료 → bodies={len(bodies)}, joints={len(joints)}, motors={len(motors)}"
    )

    return simulation


import math

# 유저입력을 다루는부분
# AI가 생성한걸 확인없이 가져온거라 참고용으로만 봐주세요.
import pychrono as chrono


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
