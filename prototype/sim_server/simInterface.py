# simInterface.py

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import json
import simulate  # simulate.py


# 1.상태 표현용 클래스

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

    @classmethod  #dump_frame()에서 만든 dict -> ModelState
    def from_frame_dict(cls, d: Dict[str, Any]) -> "ModelState":
        return cls(
            name=d.get("name", ""),
            pos=d.get("pos", [0.0, 0.0, 0.0]),
            rot=d.get("rot", [1.0, 0.0, 0.0, 0.0]),
        )


@dataclass
class SimState:
    modelStates: List[ModelState]


# 시뮬레이션 설명

@dataclass
class SimDescription:
    """외부에서 넘겨줄 시뮬레이션 설명 정보"""

    model_meta: Dict[str, Any]  # 그대로 dict로 들고 있게 유지
    dt: float = 1e-3            # 한 스텝 시간 간격

    # JSON 문자열에서 만드는 헬퍼
    @classmethod
    def from_json_str(cls, json_str: str, dt: float = 1e-3) -> "SimDescription":
        meta = json.loads(json_str)
        return cls(model_meta=meta, dt=dt)

    # JSON 파일 경로에서 만드는 헬퍼
    @classmethod
    def from_json_file(cls, path: str, dt: float = 1e-3) -> "SimDescription":
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return cls(model_meta=meta, dt=dt)


# 2.Simulator 래퍼 클래스

class Simulator:
    """
    내부적으로는 simulate.make_sim / step_sim / kill_sim을 사용하고,
    외부에서는 Simulator.step(prevState, userInput) 형태로 쓰는 래퍼.
    """

    def __init__(self, handle: simulate.SimHandle, dt: float = 1e-3):
        self.handle = handle # simulate.py에서 만든 SimHandle
        self.dt = dt

    def step(
        self,
        prev_state: Optional[SimState] = None,
        user_input: Optional[Dict[str, Any]] = None,
    ) -> SimState:
        # 1) simulate.py 쪽으로 한 스텝 요청
        simulate.step_sim(self.handle, self.dt)

        # 2) buffer가 있으면 frame(JSON)에서 읽어오기 시도
        buffer = getattr(self.handle, "buffer", None)
        if buffer is not None and hasattr(buffer, "read_outputs"):
            try:
                frame = buffer.read_outputs()
            except Exception as e:
                print("[simInterface] buffer.read_outputs() 에러:", e)
                frame = None

            if isinstance(frame, dict):
                body_dicts = frame.get("bodies", [])
                model_states = [
                    ModelState.from_frame_dict(d) for d in body_dicts
                ]
                return SimState(modelStates=model_states)

        # 3) 기본 동작: Chrono 바디에서 직접 읽기
        bodies = self.handle.bodies
        model_states = [ModelState.from_body(b) for b in bodies]
        return SimState(modelStates=model_states)

    def clear(self):
        """시뮬레이터 정리(리소스 해제)"""
        simulate.kill_sim(self.handle)


# make_sim

def make_sim(
    sim_description: SimDescription,
    buffer_handle: Any = None,        # 나중에 버퍼 객체를 넘겨줄 자리
) -> Tuple[Simulator, SimState]:
    """
    simulate.make_sim()을 그대로 호출해서 파이크로노 시스템 초기화 후 handle을 만들고,
    그걸 Simulator로 감싼 뒤 초기 상태까지 같이 반환
    """

    # 1) SimDescription 안의 model_meta 사용
    handle = simulate.make_sim(sim_description.model_meta,
                            buffer_handle=buffer_handle)

    # 2) 초기 상태: step 하기 전 위치/회전 읽기
    init_states = [ModelState.from_body(b) for b in handle.bodies]
    init_state = SimState(modelStates=init_states)

    # 3) Simulator 생성 (dt도 sim_description에서 가져오기)
    simulator = Simulator(handle=handle, dt=sim_description.dt)

    return simulator, init_state


