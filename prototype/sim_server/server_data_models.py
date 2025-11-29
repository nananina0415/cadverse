# server_data_models.py
# 서버 관련 데이터 모델 및 타입 정의

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from sim_data_models import UserInput
from utils.read_write_buffer import ReadWriteBuffer


@dataclass
class ServerConfig:
    """서버 설정"""

    host: str = "0.0.0.0"
    port: int = 8000
    resources_dir: str = "./resources"

    @classmethod
    def fromJson(cls, jsonPath: str) -> "ServerConfig":
        """JSON 파일에서 설정 로드"""
        with open(jsonPath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def toDict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "host": self.host,
            "port": self.port,
            "resources_dir": self.resources_dir,
        }


@dataclass
class Server:
    """
    서버 상태 컨테이너
    - config: 서버 설정
    - userInput: 사용자 입력 버퍼
    - hasClientConnected: 클라이언트 연결 여부 (시뮬레이션 시작 트리거)
    """

    config: ServerConfig
    userInput: ReadWriteBuffer[UserInput]
    hasClientConnected: bool = False


# ===== WebSocket 메시지 DTO =====


@dataclass
class Position:
    """3D 위치"""

    x: float
    y: float
    z: float

    def toDict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class Rotation:
    """쿼터니언 회전"""

    e0: float
    e1: float
    e2: float
    e3: float

    def toDict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class PartStateDTO:
    """파트 상태 (클라이언트 전송용)"""

    pos: Position
    rot: Rotation

    def toDict(self) -> Dict[str, Any]:
        return {"pos": self.pos.toDict(), "rot": self.rot.toDict()}

    @classmethod
    def fromPartState(cls, part_state) -> "PartStateDTO":
        """PartState 객체로부터 DTO 생성"""
        return cls(
            pos=Position(x=part_state.pos.x, y=part_state.pos.y, z=part_state.pos.z),
            rot=Rotation(
                e0=part_state.rot.e0,
                e1=part_state.rot.e1,
                e2=part_state.rot.e2,
                e3=part_state.rot.e3,
            ),
        )


@dataclass
class ModelStateMessage:
    """서버 → 클라이언트: 모델 상태 메시지"""

    parts: List[PartStateDTO]

    def toJson(self) -> str:
        """JSON 문자열로 직렬화"""
        return json.dumps([p.toDict() for p in self.parts])

    @classmethod
    def fromPartStates(cls, part_states: List) -> "ModelStateMessage":
        """PartState 리스트로부터 메시지 생성"""
        return cls(parts=[PartStateDTO.fromPartState(ps) for ps in part_states])


@dataclass
class UserInputMessage:
    """
    클라이언트 → 서버: 사용자 입력 메시지 (파싱용)
    - point: 기준점 위치 {x, y, z}
    - direction: 방향 단위벡터 {x, y, z}
    """

    point: Dict[str, float]
    direction: Dict[str, float]

    def toDict(self) -> Dict[str, Any]:
        return {"point": self.point, "direction": self.direction}

    @classmethod
    def fromJson(cls, json_str: str) -> "UserInputMessage":
        """JSON 문자열로부터 메시지 파싱"""
        try:
            data = json.loads(json_str)
            return cls(
                point=data.get("point", {"x": 0.0, "y": 0.0, "z": 0.0}),
                direction=data.get("direction", {"x": 0.0, "y": 0.0, "z": 1.0}),
            )
        except json.JSONDecodeError:
            # JSON 파싱 실패 시 기본값 사용
            return cls(
                point={"x": 0.0, "y": 0.0, "z": 0.0},
                direction={"x": 0.0, "y": 0.0, "z": 1.0},
            )
