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
    PartState,
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
        if getattr(info, "body_order", None):
            self._body_order = list(info.body_order)  # type: ignore[attr-defined]
        else:
            # ✅ SceneMeta.bodies 순서를 PartIndex 기준으로 사용(스키마/06-07과 정합)
            try:
                self._body_order = [b.name for b in info.scene.bodies]
            except Exception:
                # 최후 fallback (그래도 고정 순서가 필요)
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
        dt = float(self.info.options.dt)

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
            # runtime_types.PartState.from_chrono_body는 name을 받더라도 무시하도록 구현되어 있음
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

        ✅ 현재 프로젝트 스키마(06)는 TouchStart/Touching/TouchEnd 이벤트 기반이다.
        즉, 이 함수는 "이벤트(의도)"를 받아서
        이후 Interaction Controller 계층에서 speed/torque 명령으로 변환하는 방향이 맞다.

        다만, 지금까지의 테스트 코드/프로토타입에서는 아래 형태의 "직접 명령"도 썼기 때문에,
        호환을 위해 아래 2가지 입력을 모두 안전하게 받는다:

        1) (legacy) userInput.motor_speeds / userInput.torque_cmds 형태
        2) (schema-06) TouchStart/Touching/TouchEnd 이벤트 Union
        """

        # ------------------------------------------------------------
        # (A) legacy path: motor_speeds / torque_cmds 가 있는 경우만 처리
        # ------------------------------------------------------------
        motor_speeds = getattr(userInput, "motor_speeds", None)
        torque_cmds = getattr(userInput, "torque_cmds", None)

        if isinstance(motor_speeds, dict) or isinstance(torque_cmds, dict):
            # 1) rotation_speed actuator 업데이트
            if isinstance(motor_speeds, dict) and motor_speeds:
                for act_name, speed in motor_speeds.items():
                    built_act = self.actuators.get(act_name)
                    if built_act is None:
                        continue
                    if built_act.meta.type != "rotation_speed":
                        continue

                    motor = built_act.link  # chrono.ChLinkMotorRotationSpeed
                    try:
                        motor.SetSpeedFunction(chrono.ChFunctionConst(float(speed)))
                    except Exception:
                        pass

            # 2) rotation_torque actuator 업데이트(가능한 경우)
            if isinstance(torque_cmds, dict) and torque_cmds:
                for act_name, torque in torque_cmds.items():
                    built_act = self.actuators.get(act_name)
                    if built_act is None:
                        continue
                    if built_act.meta.type != "rotation_torque":
                        continue

                    motor = built_act.link  # chrono.ChLinkMotorRotationTorque (존재할 때만)
                    try:
                        motor.SetTorqueFunction(chrono.ChFunctionConst(float(torque)))
                    except Exception:
                        pass

            return

        # ------------------------------------------------------------
        # (B) schema-06 path: TouchStart/Touching/TouchEnd 이벤트
        # ------------------------------------------------------------
        # 현재 단계에서는 "입력 이벤트 → 물리 명령 변환" 로직(Interaction Controller)이
        # 아직 main.py에 들어오지 않았으므로,
        # 여기서는 이벤트를 받아도 절대 크래시 나지 않게만 유지한다.
        #
        # TODO(다음 단계):
        # - TouchStart에서 target/actionPointLocal 저장
        # - Touching에서 fingerPointWorld 변화량 + cameraForwardWorld로 회전 의도 계산
        # - 계산된 의도를 actuator speed/torque로 변환해서 위 legacy path처럼 적용
        _ = userInput  # placeholder (no-op)


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
