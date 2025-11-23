import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simulate


# 상태 표현용 클래스
@dataclass
class ModelState:
    name: str
    pos: List[float]  # [x, y, z]
    rot: List[float]  # [e0, e1, e2, e3]

    @classmethod
    def from_body(cls, body) -> "ModelState":
        """simulate.py의 ChBody를 ModelState로 변환"""
        pos = body.GetPos()
        rot = body.GetRot()
        return cls(
            name=body.GetName(),
            pos=[pos.x, pos.y, pos.z],
            rot=[rot.e0, rot.e1, rot.e2, rot.e3],
        )


@dataclass
class SimState:
    modelStates: List[ModelState]


@dataclass
class SimDescription:
    """외부에서 넘겨줄 시뮬레이션 설명 정보"""

    simMetaJson: str  # JSON 문자열로 된 model_meta
    dt: float = 1e-3  # 한 스텝 시간 간격(기본 0.001초)

    def to_model_meta(self) -> Dict[str, Any]:
        return json.loads(self.simMetaJson)


# 2. Simulator 래퍼 클래스
class Simulator:
    """
    내부적으로는 simulate.make_sim / step_sim / kill_sim을 사용하고,
    외부에서는 Simulator.step(prevState, userInput) 형태로 쓰게 해주는 래퍼.
    """

    def __init__(self, handle: simulate.SimHandle, dt: float = 1e-3):
        self.handle = handle  # simulate.py에서 만든 SimHandle
        self.dt = dt

    def step(
        self,
        prev_state: Optional[SimState] = None,
        user_input: Optional[Dict[str, Any]] = None,
    ) -> SimState:
        """
        한 스텝 진행 후 새로운 SimState 반환.
        """

        # TODO: user_input을 simulate.step_sim에 반영하고 싶다면
        #       handle.buffer 등에 써준 뒤 step_sim 호출하는 식으로 확장 가능
        simulate.step_sim(self.handle, self.dt)

        # 스텝 이후의 현재 상태를 읽어서 SimState로 변환
        bodies = self.handle.bodies
        model_states = [ModelState.from_body(b) for b in bodies]
        return SimState(modelStates=model_states)

    def clear(self):
        """시뮬레이터 정리(리소스 해제)"""
        simulate.kill_sim(self.handle)


# make_sim
def make_sim(sim_description: SimDescription) -> Tuple[Simulator, SimState]:
    """
    simulate.make_sim()을 호출해 파이크로노 시스템을 초기화하고,
    Simulator 객체로 감싸서 반환
    """

    # 1) SimDescription 안의 JSON → model_meta dict로 변환
    model_meta = sim_description.to_model_meta()

    # 2) simulate.py의 make_sim 호출 (버퍼는 일단 None으로)
    handle = simulate.make_sim(model_meta, buffer_handle=None)

    # 3) 초기 상태 구성
    init_model_states = [ModelState.from_body(b) for b in handle.bodies]
    init_state = SimState(modelStates=init_model_states)

    # 4) Simulator 래퍼 생성
    simulator = Simulator(handle=handle, dt=sim_description.dt)

    return simulator, init_state
