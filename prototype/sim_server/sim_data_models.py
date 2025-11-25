# sim_data_models.py
# 시뮬레이션 관련 데이터 모델 및 타입 정의

import json
import struct
from dataclasses import dataclass
from typing import Any, Dict, TypeAlias
from pychrono import ChVector3d, ChQuaterniond
from utils.read_write_buffer import ReadWriteBuffer


@dataclass
class SimDescription:
    """외부에서 넘겨줄 시뮬레이션 설명 정보"""
    model_meta: Dict[str, Any]  # 그대로 dict로 들고 있게 유지
    dt: float = 1e-3  # 한 스텝 시간 간격

    @classmethod
    def fromJsonString(cls, json_str: str, dt: float = 1e-3) -> "SimDescription":
        """JSON 문자열에서 만드는 헬퍼"""
        meta = json.loads(json_str)
        return cls(model_meta=meta, dt=dt)

    @classmethod
    def fromJsonFile(cls, path: str, dt: float = 1e-3) -> "SimDescription":
        """JSON 파일 경로에서 만드는 헬퍼"""
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return cls(model_meta=meta, dt=dt)


@dataclass
class PartState:
    """개별 파트의 위치와 회전 상태"""
    # partId: int -> 버퍼의 인덱스로 사용
    pos: ChVector3d  # [x, y, z]
    rot: ChQuaterniond  # [e0, e1, e2, e3]

    @classmethod
    def fromBody(cls, body) -> "PartState":
        """simulate.py의 ChBody에서 위치와 회전을 읽어 PartState로 변환"""
        return cls(
            pos=body.GetPos(),
            rot=body.GetRot()
        )

    @classmethod
    def fromFrameDict(cls, d: Dict[str, Any]) -> "PartState":
        """dump_frame()에서 만든 dict -> PartState"""
        return cls(
            pos=d.get("pos", [0.0, 0.0, 0.0]),
            rot=d.get("rot", [1.0, 0.0, 0.0, 0.0]),
        )


ModelState: TypeAlias = ReadWriteBuffer[PartState]


@dataclass
class Simulation:
    """
    시뮬레이션 상태 컨테이너
    - modelState: 모든 파트의 상태를 담는 버퍼
    - simHandle: Chrono 시뮬레이션 핸들
    - dt: 시뮬레이션 타임스텝
    """
    modelState: ModelState
    simHandle: Any  # simulate.SimHandle
    dt: float



