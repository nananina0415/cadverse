# simulate.py  (시뮬레이터 엔진)

import pychrono as chrono
import pychrono.irrlicht as chronoirr

import os
import json
import re
import time
import math as m

#===================================================================================================
# 1. SimHandle 구조 정의

class SimHandle:
    def __init__(self, sys, bodies, joints, motors, buffer):
        self.sys = sys            # PyChrono 시스템
        self.bodies = bodies      # 생성된 모든 바디
        self.joints = joints      # 생성된 모든 조인트
        self.motors = motors      # 생성된 모든 모터
        self.buffer = buffer      # input/output buffer 핸들
        self.last_dump_time = 0   # (AR JSON용) 마지막 프레임 저장 시각

# Class SimHandle(시뮬레이션의 두뇌역할)
# 여러 값들을 하나로 묶어서 관리
# __int__(생성자):SimHandle이라는 상자를 새로 만들 때무슨 데이터를 이 상자에 넣어서 들고 다닐 것인지 선언하는 함수
# self.sys =sys
# 밖에서 만든 sys =chrono.ChsystemNSC()를 SimHadle 안에 self.sys 라는 이름으로 저장.
# handle.sys.DoStepDynamics(dt)처럼 handle을 통해 시스템에 접근할 수 있음.
# self.bodies = bodies
# 모든 바디를 리스트도 저장: 이 리스트는 Step_Sim에서 사용
# self.joints = joints
# 모든 조인트를 저장
# self.buffer
# 입력/츨략 버퍼

#===================================================================================================
# 2. make_sim() : 시뮬레이션 한 세트 초기화
# Pychrono 시스템을 만들고 필요한 바디/조인트/모터를 준비해서 SimHandle이라는 리모컨 객체로 묶어 반환하는 함수

def make_sim(model_meta, buffer_handle):
    # model_meta : json 형태의 메타 정보
    # buffer_handle : input/output 버퍼
    """
    model_meta 예시 구조 (조립 헬퍼 기반):

    {
    "assemblies": [
        {
        "type": "shaft_base",
        "shaft": {
            "name": "shaft",
            "mesh": "shaft_scaled.obj",
            "mass": 500,
            "fixed": False,
            "motor_name": "shaft_motor"
        },
        "base": {
            "name": "base",
            "mesh": "base_scaled.obj",
            "mass": 1000,
            "fixed": True
        },
        "motor_speed": 5.0
        },
        {
        "type": "gear_pair",
        "gearA": {
            "name": "gear_A",
            "mesh": "cad_models/gear_A_m2_z20_scaled.obj",
            "mass": 1000,
            "fixed": False,
            "motor_name": "gearA_motor"
        },
        "gearB": {
            "name": "gear_B",
            "mesh": "cad_models/gear_B_m2_z40_scaled.obj",
            "mass": 1000,
            "fixed": False
        },
        "motor_speed": 2.0
        }
    ]
    }

    buffer_handle : main.py에서 넘겨주는 input/output 버퍼 객체
    반환 : SimHandle(sys, bodies, joints, motors, buffer)
    """

    print("[sim] make_sim() 호출됨")

    # 1) PyChrono 시스템 생성
    sys = chrono.ChSystemNSC()
    sys.SetGravitationalAcceleration(chrono.ChVector3d(0, -9.81, 0))

    bodies = []
    joints = []
    motors = []
    # 바디 만들면 bodies에 append
    # 조인트 만들면 joints에 append
    # 모터 만들면 motors에 append
    # 결국 이 셋은 나중에 SimHandle에 들어가고 step_sim에서 계속 접근

    # 2) assemblies 기반 조립
    assemblies = model_meta.get("assemblies", [])
    print(f"[sim] assemblies 개수 = {len(assemblies)}")

    for asm in assemblies:
        asm_type = asm.get("type")
        print(f"[sim] assembly 처리: type = {asm_type}")

        if asm_type == "shaft_base":
            shaft_meta = asm["shaft"]
            base_meta  = asm["base"]
            motor_speed = asm.get("motor_speed", 5.0)

            create_shaft_with_base(
                sys=sys,
                shaft_meta=shaft_meta,
                base_meta=base_meta,
                motor_speed=motor_speed,
                bodies=bodies,
                joints=joints,
                motors=motors,
            )

        elif asm_type == "gear_pair":
            gearA_meta = asm["gearA"]
            gearB_meta = asm["gearB"]
            motor_speed = asm.get("motor_speed", 2.0)

            create_gear_pair(
                sys=sys,
                gearA_meta=gearA_meta,
                gearB_meta=gearB_meta,
                motor_speed=motor_speed,
                bodies=bodies,
                joints=joints,
                motors=motors,
            )

        else:
            print("[sim] 알 수 없는 assembly type:", asm_type)

    # 3) 모델 메타 기반 바디/조인트/모터 생성 (나중을 위한 부분)
    for b in model_meta.get("bodies", []):
        print("[sim] (flat) bodies 항목 발견 — 현재는 사용 안 함:", b)
        # 나중에 create_body(b) 함수 넣을 자리

    for j in model_meta.get("joints", []):
        print("[sim] (flat) joints 항목 발견 — 현재는 사용 안 함:", j)
        # 나중에 create_joint(j) 함수 넣을 자리

    for m in model_meta.get("motors", []):
        print("[sim] (flat) motors 항목 발견 — 현재는 사용 안 함:", m)
        # 나중에 create_motor(m) 함수 넣을 자리

    # 4) SimHandle 만들어서 반환
    handle = SimHandle(
        sys=sys,
        bodies=bodies,
        joints=joints,
        motors=motors,
        buffer=buffer_handle,
    )

    print(f"[sim] make_sim() 완료 → bodies={len(bodies)}, joints={len(joints)}, motors={len(motors)}")
    return handle
    # 이 handle을 main.py에 받아서 Step_sim(handle,dt), Kill_sim(handle)과 같이 사용


#==================================================================================================
# 상태/버퍼/json 관련 헬퍼

## 바디 상태를 dict로 변환
def body_to_state_dict(body):
    """
    PyChrono 바디 하나를
    { "name": str, "pos": [x,y,z], "rot": [e0,e1,e2,e3] }
    형태의 dict로 변환해주는 헬퍼.
    AR/버퍼/JSON으로 넘기기 좋은 형태.
    """

    pos = body.GetPos()   # ChVector3d
    rot = body.GetRot()   # ChQuaterniond (e0, e1, e2, e3)

    state = {
        "name": body.GetName(),
        "pos": [pos.x, pos.y, pos.z],
        "rot": [rot.e0, rot.e1, rot.e2, rot.e3],
    }
    return state

## 한 프레임 전체 덤프 구조 만들기
def dump_frame(t, bodies):
    """
    시간 t에서 여러 바디 상태를 모아서
    하나의 "프레임" JSON 구조로 만드는 헬퍼.

    반환 예시:
    {
    "time": 0.05,
    "bodies": [
        { "name": "shaft", "pos": [...], "rot": [...] },
        { "name": "gear_A", "pos": [...], "rot": [...] },
        ...
    ]
    }
    """
    frame = {
        "time": float(t),
        "bodies": [body_to_state_dict(b) for b in bodies]
    }
    return frame

#==================================================================================================
# 3. step_sim() : 시뮬레이션 한 스텝 진행

def step_sim(handle, dt):
    """
    한 프레임(dt 초)만큼 시뮬레이션을 진행하는 함수.

    1) 입력 버퍼 읽기 (있으면)
    2) 입력을 모터/바디에 반영
    3) PyChrono 시스템 한 스텝 진행
    4) 현재 상태를 출력 버퍼에 기록
    """

    sys = handle.sys
    buffer = handle.buffer

    # 1) 입력 읽기 (버퍼가 있고 read_inputs가 있으면 호출)
    inputs = None  #입력 없음 상태로 시작
    if buffer is not None and hasattr(buffer, "read_inputs"):
        try:
            inputs = buffer.read_inputs()
            # 외부에서 들어온 조작값을 읽어옴
        except Exception as e:
            print("[sim] read_inputs() 호출 중 에러:", e)

    # 2) 입력 -> 모터에 반영
    #    inputs 예시:
    #    {
    #      "motors": [
    #      {"name": "shaft_motor", "speed": 3.0},
    #      {"name": "gearA_motor", "speed": 1.5}
    #      ]
    #    }
    #    - 아직 입력이 없으면 그냥 모터는 make_sim에서 설정한 기본 속도로 돈다
    if inputs is not None:
        # 예시 형식: inputs = {"motors": [{"name": "shaft_motor", "speed": 3.0}, ...]}
        # 입력이 있을 대만 모터 제어 실행
        motor_cmds = inputs.get("motors", [])
        for cmd in motor_cmds:
            target_name = cmd.get("name")
            target_speed = cmd.get("speed")

            if target_name is None or target_speed is None:
                continue

            for m in handle.motors:
                # 모터에 이름이 붙어 있다고 가정 (m.SetName(...)을 make_sim에서 해두면 좋음)
                m_name = ""
                if hasattr(m, "GetName"):
                    m_name = m.GetName()

                if m_name == target_name:
                    # 간단하게: 새로운 Const 함수로 속도 갱신
                    func = chrono.ChFunctionConst(target_speed)
                    m.SetSpeedFunction(func)
                    # print("[sim] 모터 속도 갱신:", m_name, "=", target_speed)

    # 3) PyChrono 시스템 한 스텝 진행
    sys.DoStepDynamics(dt)
    # ㄴ 현재 힘/토크/조인터 조건/모터 조건 등을 바탕으로 dt초 동안의 운동을 계산
    #   각 바디의 위치/속도/회전 상태 업데이트

    # 4) 현재 상태를 프레임(JSON용 dict)으로 만들기
    t = sys.GetChTime()  # 현재 시뮬레이션 시간
    frame = dump_frame(t, handle.bodies)
    # frame 예시:
    # {
    #   "time": 0.05,
    #   "bodies": [
    #       {"name": "shaft", "pos":[...], "rot":[...]},
    #       {"name": "gear_A", ...},
    #       ...
    #   ]
    # }

    # 출력 버퍼가 있고 write_outputs가 구현되어 있다면 호출
    if buffer is not None and hasattr(buffer, "write_outputs"):
        try:
            buffer.write_outputs(frame)
        except Exception as e:
            print("[sim] write_outputs() 호출 중 에러:", e)

#==================================================================================================

# 4. kill_sim() : 시뮬레이션 종료/정리
#  ㄴ AR JSON 프레임 기록이 있으면 저장
#  ㄴ 파이크로노 시스템 내부 리소스 해제
#  ㄴ 바디/조인트/모터 리스트 비워주기
#  ㄴ 종료 로그 출력

def kill_sim(handle):
    """
    시뮬레이션 종료 처리:
    - JSON 덤프(필요할 경우)
    - 리소스 정리
    - 로그 출력
    """

    print("[sim] kill_sim() 호출됨 — 시뮬레이션 종료 처리 시작")

    # 1) AR/JSON 프레임 덤프 저장 (옵션)
    #    만약 handle.buffer가 JSON 기록을 가지고 있다면 저장
    if handle.buffer is not None:
        if hasattr(handle.buffer, "save_json"):
            try:
                handle.buffer.save_json()
                print("[sim] AR 프레임 JSON 저장 완료")
            except Exception as e:
                print("[sim] JSON 저장 중 오류:", e)

    # 2) PyChrono 시스템 자체는 C++ 기반이라,
    #    Python 쪽에서는 크게 정리할 게 없음.
    #    필요한 경우 여기서 custom cleanup 가능.
    handle.sys.Clear()   # 안전하게 모든 Chrono 객체 제거

    # 3) 내부 참조 제거
    #   ㄴSimHandle 내부 목록 삭제
    handle.bodies.clear()
    handle.joints.clear()
    handle.motors.clear()

    print("[sim] 시뮬레이터 리소스 정리 완료 — kill_sim() 종료")

#===============================================================================================
# 헬퍼 함수


# 1. 바디 관련 함수들

## 1) OBJ bounding box → 중심/회전축 자동 검출

def read_obj_bounds(path):
    xs, ys, zs = [], [], []
    with open(path, "r") as f:
        for line in f:
            if line.startswith("v "):
                _, x, y, z = line.split()
                xs.append(float(x))
                ys.append(float(y))
                zs.append(float(z))
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

def detect_axis_and_center(path):
    """
    OBJ 파일의 bounding box로부터:
    - 중심점(center)
    - 가장 긴 축(회전축)을 자동 검출한다
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



## 2) 기어 파일명에서 module(m)/teeth(z) 파싱 + 피치반지름 계산

import re

def parse_module_teeth_from_name(fn):
    """
    파일명에서 m(모듈, mm)과 z(치수)를 파싱한다.
    예: gear_A_m2_z20.obj
    """
    name = fn.lower()
    m_m = re.search(r"m(\d+(\.\d+)?)", name)
    m_z = re.search(r"z(\d+)", name)

    if not (m_m and m_z):
        return None, None

    return float(m_m.group(1)), int(m_z.group(1))

def pitch_radius_from_name(fn, fallback=None):
    """
    피치반지름 r[m] = (module[m] * z) / 2
    파일명에서 정보가 없으면 fallback 사용
    """
    module_mm, z = parse_module_teeth_from_name(fn)
    if module_mm and z:
        module_m = module_mm / 1000.0
        return 0.5 * module_m * z
    return fallback

## 3) OBJ 로드하여 ChBodyEasyMesh 생성
def load_body_from_obj(meta):
    """
    meta = {
        "name": "shaft",
        "mesh": "shaft_scaled.obj",
        "type": "shaft",  # or "gear" or "base"
        "mass": 1000,
        "fixed": False
    }
    """

    path = meta["mesh"]
    mass = meta.get("mass", 1000)
    fixed = meta.get("fixed", False)

    body = chrono.ChBodyEasyMesh(path, mass, False, True)
    body.SetName(meta.get("name", "unnamed"))
    body.SetFixed(fixed)

    return body

#==================================================================================================
# 2. 조인트/모터 관련 함수

## 1) 축을 쿼터니언으로 바꿔주는 헬퍼

def quat_from_axis(axis: chrono.ChVector3d):
    """
    joint/motor의 로컬 z축을
    원하는 world 축(axis) 방향으로 돌려주는 쿼터니언을 만든다.

    detect_axis_and_center()에서 axis는 딱 세 가지 중 하나:
    (1,0,0), (0,1,0), (0,0,1)
    라고 가정.
    """

    # Z축 그대로 쓰는 경우 (기본)
    if axis.x == 0 and axis.y == 0 and axis.z == 1:
        return chrono.QUNIT

    # X축으로 돌리고 싶은 경우: z -> x
    # 대략 y축을 -90도 회전시키면 z가 x로 감
    if axis.x == 1 and axis.y == 0 and axis.z == 0:
        return chrono.QuatFromAngleY(-m.pi / 2)

    # Y축으로 돌리고 싶은 경우: z -> y
    # 대략 x축을 +90도 회전시키면 z가 y로 감
    if axis.x == 0 and axis.y == 1 and axis.z == 0:
        return chrono.QuatFromAngleX(+m.pi / 2)

    # 혹시 모르는 이상한 경우에는 그냥 QUNIT
    return chrono.QUNIT


## 2) make_revolute : 회전 조인트 생성 헬퍼
def make_revolute(sys, body, base, center, axis):
    """
    sys    : ChSystemNSC
    body   : 회전할 바디
    base   : 기준 바디(대부분 ground 또는 base)
    center : 회전중심 (ChVector3d)
    axis   : 회전축 (ChVector3d, (1,0,0)/(0,1,0)/(0,0,1) 중 하나)
    """

    q = quat_from_axis(axis)
    frame = chrono.ChFramed(center, q)

    joint = chrono.ChLinkLockRevolute()
    joint.Initialize(body, base, frame)
    sys.AddLink(joint)

    return joint


## 3) make_rotation_motor: 회전 모터 생성 헬퍼
def make_rotation_motor(sys, body, base, center, axis, speed):
    """
    speed : rad/s (기본 회전속도)
    """

    q = quat_from_axis(axis)
    frame = chrono.ChFramed(center, q)

    motor = chrono.ChLinkMotorRotationSpeed()
    motor.Initialize(body, base, frame)

    func = chrono.ChFunctionConst(speed)
    motor.SetSpeedFunction(func)

    sys.AddLink(motor)
    return motor


## 4) make_gear_link : 기어 링크 생성 헬퍼
def make_gear_link(sys, gearA, gearB, rA, rB):
    """
    gearA, gearB : ChBody
    rA, rB       : pitch radius (meter)
    """

    ratio = (rA / rB) if rB != 0 else 1.0

    link = chrono.ChLinkLockGear()
    link.Initialize(gearA, gearB, chrono.ChFramed())
    link.SetTransmissionRatio(ratio)
    link.SetEnforcePhase(False)  # 위상 강제 X (프리한 회전)

    sys.AddLink(link)
    return link

#================================================================================================
# 3.조립헬퍼
## 1) 샤프트 + 베이스 + 회전조인트 + 모터

def create_shaft_with_base(sys, shaft_meta, base_meta, motor_speed, bodies, joints, motors):
    """
    샤프트-베이스 한 세트를 조립하는 헬퍼.

    파라미터 예시:
    shaft_meta = {
        "name": "shaft",
        "mesh": "shaft_scaled.obj",
        "mass": 500,
        "fixed": False   # 어차피 샤프트는 여기서 강제로 False로 둠
    }

    base_meta = {
        "name": "base",
        "mesh": "base_scaled.obj",
        "mass": 1000,
        "fixed": True    # 여기서 강제로 True로 둠
    }

    motor_speed = 5.0  # rad/s

    bodies, joints, motors : SimHandle에 들어갈 리스트들 (참조로 전달)
    """

    # 베이스 바디 생성
    base = load_body_from_obj(base_meta)
    base.SetFixed(True)  # 베이스는 무조건 고정
    sys.Add(base)
    bodies.append(base)

    # 샤프트 바디 생성
    shaft = load_body_from_obj(shaft_meta)
    shaft.SetFixed(False)  # 샤프트는 회전할 수 있어야 함
    sys.Add(shaft)
    bodies.append(shaft)

    # 샤프트 OBJ에서 중심/회전축 자동 검출
    shaft_mesh_path = shaft_meta["mesh"]
    shaft_center, shaft_axis = detect_axis_and_center(shaft_mesh_path)

    print("[asm] shaft center =", shaft_center)
    print("[asm] shaft axis   =", shaft_axis)

    # 회전 조인트 생성 (샤프트 - 베이스)
    rev = make_revolute(
        sys=sys,
        body=shaft,
        base=base,
        center=shaft_center,
        axis=shaft_axis
    )
    joints.append(rev)

    # 회전 모터 생성 (샤프트 - 베이스)
    motor = make_rotation_motor(
        sys=sys,
        body=shaft,
        base=base,
        center=shaft_center,
        axis=shaft_axis,
        speed=motor_speed
    )
    # 모터 이름을 달아두면 step_sim에서 입력으로 제어 가능
    if hasattr(motor, "SetName"):
        motor.SetName(shaft_meta.get("motor_name", "shaft_motor"))

    motors.append(motor)

    print("[asm] 샤프트-베이스 조립 완료 (speed =", motor_speed, "rad/s)")
    return {
        "base": base,
        "shaft": shaft,
        "revolute": rev,
        "motor": motor,
    }

## 2) 기어 A/B + 조인트 + 모터 + 기어링크

def create_gear_pair(sys, gearA_meta, gearB_meta, motor_speed, bodies, joints, motors, ground=None):
    """
    기어 두 개(gearA, gearB)를 한 세트로 조립하는 헬퍼.

    gearA_meta / gearB_meta 예시:
    {
        "name": "gear_A",
        "mesh": "cad_models/gear_A_m2_z20_scaled.obj",
        "mass": 1000,
        "fixed": False   # 여기서는 회전 가능 바디로 사용
    }

    motor_speed : rad/s (기어 A에 거는 모터 기본 속도)

    bodies, joints, motors : SimHandle에 들어갈 리스트들 (참조로 전달)
    ground : 고정 기준 바디 (없으면 여기서 새로 생성)
    """

    # ground(고정 기준 바디) 준비
    if ground is None:
        ground = chrono.ChBody()
        ground.SetFixed(True)
        sys.Add(ground)
        bodies.append(ground)

    # 기어 바디 생성
    gearA = load_body_from_obj(gearA_meta)
    gearA.SetFixed(False)
    sys.Add(gearA)
    bodies.append(gearA)

    gearB = load_body_from_obj(gearB_meta)
    gearB.SetFixed(False)
    sys.Add(gearB)
    bodies.append(gearB)

    # 파일명에서 피치반지름 rA, rB 계산
    fnA = os.path.basename(gearA_meta["mesh"])
    fnB = os.path.basename(gearB_meta["mesh"])

    rA = pitch_radius_from_name(fnA, fallback=gearA_meta.get("pitch_radius", 0.02))
    rB = pitch_radius_from_name(fnB, fallback=gearB_meta.get("pitch_radius", 0.04))

    print(f"[gear] A pitch radius = {rA:.6f} m")
    print(f"[gear] B pitch radius = {rB:.6f} m")

    # 기어 중심 배치 (중심거리 = rA + rB)
    centerA = chrono.ChVector3d(0, 0, 0)
    centerB = chrono.ChVector3d(rA + rB, 0, 0)

    gearA.SetPos(centerA)
    gearB.SetPos(centerB)

    print("[gear] center distance =", rA + rB)

    # 기본 회전축: z축 (0,0,1)
    axis = chrono.ChVector3d(0, 0, 1)

    # 회전 조인트 (gearA - ground, gearB - ground)
    revA = make_revolute(
        sys=sys,
        body=gearA,
        base=ground,
        center=centerA,
        axis=axis,
    )
    revB = make_revolute(
        sys=sys,
        body=gearB,
        base=ground,
        center=centerB,
        axis=axis,
    )
    joints.extend([revA, revB])

    # 5) 모터 (gearA - ground)
    motor = make_rotation_motor(
        sys=sys,
        body=gearA,
        base=ground,
        center=centerA,
        axis=axis,
        speed=motor_speed,
    )
    if hasattr(motor, "SetName"):
        motor.SetName(gearA_meta.get("motor_name", "gearA_motor"))
    motors.append(motor)

    # 6) 기어링크 (gearA - gearB)
    gear_link = make_gear_link(sys, gearA, gearB, rA, rB)
    joints.append(gear_link)

    print(f"[gear] gear pair 조립 완료 (motor speed = {motor_speed} rad/s)")
    return {
        "ground": ground,
        "gearA": gearA,
        "gearB": gearB,
        "revA": revA,
        "revB": revB,
        "motor": motor,
        "gear_link": gear_link,
    }

