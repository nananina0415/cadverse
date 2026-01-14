# simulator/main.py
#
# "시뮬레이션 엔진의 외부 인터페이스" 역할
# - 서버/AR 쪽에서 Simulator를 가져다 쓰는 진입점
# - 내부 Chrono 구성은 sim_builder.py로 위임
#
# 요구 형태(의도):
#   class Simulator:
#       def __new__(info: SimInfo):
#       def step(userInput: UserInput) -> SimState
#
# Python에서는 보통 __init__를 쓰지만,
# 팀원 요청을 만족시키기 위해 create(info) + step()를 제공.

from __future__ import annotations

from typing import Dict, List, Optional

import pychrono as chrono

from .SimInfo import SimInfo
from .runtime_types import (
    UserInput,
    SimState,
    PartState
)

from .sim_builder import build_system_from_scene


class Simulator:
    """
    Simulator = 메타데이터 기반 PyChrono 시뮬 엔진 래퍼

    - create(info)로 생성
    - step(userInput) -> SimState 로 한 tick 진행
    - close()로 리소스 정리
    """

    # -----------------------------
    # Construction
    # -----------------------------
    def __init__(self, info: SimInfo):
        self.info: SimInfo = info

        # ✅ sim_builder.py는 SceneMeta를 받는 build_system_from_scene(meta)만 제공
        built = build_system_from_scene(info.scene)

        self.sys: chrono.ChSystemNSC = built.sys
        self.bodies = built.bodies        # Dict[str, BuiltBody]
        self.joints = built.joints        # Dict[str, BuiltJoint]
        self.actuators = built.actuators  # Dict[str, BuiltActuator]

        self.sim_time: float = 0.0

        # 출력 순서 고정 (PartIndex 기반 통신을 위함)
        if info.body_order:
            self._body_order = list(info.body_order)
        else:
            self._body_order = sorted(self.bodies.keys())

        self.part_index: Dict[str, int] = {n: i for i, n in enumerate(self._body_order)}

    @classmethod
    def create(cls, info: SimInfo) -> "Simulator":
        return cls(info)

    # -----------------------------
    # Public API
    # -----------------------------
    def step(self, userInput: Optional[UserInput] = None) -> SimState:
        """
        한 스텝 진행:
        1) userInput(AR/서버 이벤트)을 actuator 명령 등으로 변환
        2) DoStepDynamics(dt)
        3) 현재 바디 포즈를 SimState로 반환
        """
        dt = float(self.info.dt)

        # 1) 입력 반영
        if userInput is not None:
            self._apply_user_input(userInput)

        # 2) 물리 스텝
        self.sys.DoStepDynamics(dt)
        self.sim_time += dt

        # 3) 상태 스냅샷
        parts: List[PartState] = []
        for name in self._body_order:
            b = self.bodies[name].body
            parts.append(PartState.from_chrono_body(b, name=name))

        return SimState(sim_time=self.sim_time, parts=parts)

    def close(self) -> None:
        """Chrono 리소스 정리"""
        try:
            self.sys.Clear()
        except Exception:
            pass

    # -----------------------------
    # Input handling (extensible)
    # -----------------------------
    def _apply_user_input(self, userInput: UserInput) -> None:
        """
        입력을 엔진에 반영하는 내부 함수.

        현재 최소 규칙:
        - userInput.motor_speeds: {"actuatorName": rad/s}
          -> rotation_speed actuator의 speed를 갱신

        - userInput.torque_cmds: {"actuatorName": torque_Nm}
          -> rotation_torque actuator인 경우:
             - Chrono에 ChLinkMotorRotationTorque가 있으면 토크 함수 갱신
             - 없으면(빌더가 NotImplemented를 띄우는 환경) 이 경로는 무시(확장 필요)
        """

        # 1) rotation_speed actuator 업데이트
        if userInput.motor_speeds:
            for act_name, speed in userInput.motor_speeds.items():
                built_act = self.actuators.get(act_name)
                if built_act is None:
                    continue

                # sim_builder의 BuiltActuator.meta.type 이 "rotation_speed" / "rotation_torque"
                if built_act.meta.type != "rotation_speed":
                    continue

                motor = built_act.link  # chrono.ChLinkMotorRotationSpeed
                try:
                    motor.SetSpeedFunction(chrono.ChFunctionConst(float(speed)))
                except Exception:
                    # 바인딩/버전 차이 방어
                    pass

        # 2) rotation_torque actuator 업데이트(가능한 경우)
        if userInput.torque_cmds:
            for act_name, torque in userInput.torque_cmds.items():
                built_act = self.actuators.get(act_name)
                if built_act is None:
                    continue
                if built_act.meta.type != "rotation_torque":
                    continue

                motor = built_act.link  # chrono.ChLinkMotorRotationTorque (존재할 때만)
                # Torque motor인 경우 SetTorqueFunction이 있을 수 있음
                try:
                    motor.SetTorqueFunction(chrono.ChFunctionConst(float(torque)))
                except Exception:
                    # 이 환경에서는 torque motor가 없거나, sim_builder에서 per-step 토크 방식으로 확장해야 함
                    pass


# -----------------------------
# (선택) 간단한 수동 테스트용 런너
# -----------------------------
if __name__ == "__main__":
    info = SimInfo.from_json_file("resources/test_scene.json", dt=1e-3)  # 예시
    sim = Simulator.create(info)

    for _ in range(1000):
        state = sim.step(None)

    print("[sim] done. sim_time =", state.sim_time)
    sim.close()
