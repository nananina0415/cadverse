# simulate.py  (시뮬레이터 엔진)

import pychrono as chrono
import time


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
# 입력/출력 버퍼

# 2. make_sim() : 시뮬레이션 한 세트 초기화
# Pychrono 시스템을 만들고 필요한 바디/조인트/모터를 준비해서 SimHandle이라는 리모컨 객체로 묶어 반환하는 함수

def make_sim(model_meta, buffer_handle):
    # model_meta: json 형태의 메타 정보
    # buffer_handle: input/output 버퍼
    """
    model_meta : { "bodies": [...], "joints": [...], "motors": [...] }
    buffer_handle : input/output buffer 객체 (main.py에서 넘겨줌)

    반환 : SimHandle(sys, bodies, joints, motors, buffer)
    """

    print("[sim] make_sim() 호출됨")

    # 1) PyChrono 시스템 생성
    sys = chrono.ChSystemNSC()
    sys.SetGravitationalAcceleration(chrono.ChVector3d(0,-9.81,0))  # 중력 (필요하면 수정 가능)

    bodies = []
    joints = []
    motors = []
    # 바디 만들면 bodies에 append
    # 조인트 만들면 joints에 append
    # 모터 만들면 motors에 append
    # 결국 이 셋은 나중에 SimHandle에 들어가고 step_sim에서 계속 접근

    # 2) 모델 메타 기반으로 바디 생성
    for b in model_meta.get("bodies", []):
        print(f"[sim] 바디 생성 준비: {b}")
        # 나중에 create_body(b) 함수 넣을 자리

    # 3) 모델 메타 기반으로 조인트 생성
    for j in model_meta.get("joints", []):
        print(f"[sim] 조인트 생성 준비: {j}")
        # 나중에 create_joint(j) 함수 넣을 자리

    # 4) 모터 생성
    for m in model_meta.get("motors", []):
        print(f"[sim] 모터 생성 준비: {m}")
        # 나중에 create_motor(m) 함수 넣을 자리

    # 5) SimHandle 만들어서 반환
    handle = SimHandle(
        sys=sys,
        bodies=bodies,
        joints=joints,
        motors=motors,
        buffer=buffer_handle
    )

    print("[sim] make_sim() 완료 → SimHandle 반환")
    return handle

    # 이 handle을 main.py에 받아서 Step_sim(handle,dt), Kill_sim(handle)과 같이 사용


# 헬퍼: 바디 상태를 dict로 변환

def body_to_state_dict(body):
    """PyChrono 바디 → JSON/버퍼로 넘기기 좋은 dict 형태로 변환"""
    pos = body.GetPos()   # ChVector3d
    rot = body.GetRot()   # ChQuaterniond (e0, e1, e2, e3)

    state = {
        "name": body.GetName(),
        "pos": [pos.x, pos.y, pos.z],
        "rot": [rot.e0, rot.e1, rot.e2, rot.e3],
    }
    return state


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
    inputs = None
    if buffer is not None and hasattr(buffer, "read_inputs"):
        try:
            inputs = buffer.read_inputs()
            # 외부에서 들어온 조작값을 읽어옴
        except Exception as e:
            print("[sim] read_inputs() 호출 중 에러:", e)

    # 2) 입력 → 모터에 반영
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

    # 4) 현재 상태를 출력 버퍼에 기록
    states = []
    for body in handle.bodies:
        states.append(body_to_state_dict(body))

    # 출력 버퍼가 있고 write_outputs가 구현되어 있다면 호출
    if buffer is not None and hasattr(buffer, "write_outputs"):
        try:
            buffer.write_outputs(states)
        except Exception as e:
            print("[sim] write_outputs() 호출 중 에러:", e)


# 4. kill_sim() : 시뮬레이션 종료/정리


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
    handle.sys.Clear()   # 안전하게 모든 Chrono 객체 제거 (선택)

    # 3) 내부 참조 제거
    handle.bodies.clear()
    handle.joints.clear()
    handle.motors.clear()

    print("[sim] 시뮬레이터 리소스 정리 완료 — kill_sim() 종료")
