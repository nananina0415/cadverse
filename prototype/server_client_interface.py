"""
서버-클라이언트 간 WebSocket 통신 인터페이스 정의
JSON 스키마 및 DTO (Data Transfer Object)
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import json


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
        return {
            "pos": self.pos.toDict(),
            "rot": self.rot.toDict()
        }

    @classmethod
    def fromPartState(cls, part_state) -> "PartStateDTO":
        """PartState 객체로부터 DTO 생성"""
        return cls(
            pos=Position(
                x=part_state.pos.x,
                y=part_state.pos.y,
                z=part_state.pos.z
            ),
            rot=Rotation(
                e0=part_state.rot.e0,
                e1=part_state.rot.e1,
                e2=part_state.rot.e2,
                e3=part_state.rot.e3
            )
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
    """클라이언트 → 서버: 사용자 입력 메시지"""
    data: Dict[str, Any]

    def toDict(self) -> Dict[str, Any]:
        return {"data": self.data}

    @classmethod
    def fromJson(cls, json_str: str) -> "UserInputMessage":
        """JSON 문자열로부터 메시지 파싱"""
        try:
            data = json.loads(json_str)
            return cls(data=data)
        except json.JSONDecodeError:
            # JSON 파싱 실패 시 raw 문자열을 메시지로 처리
            return cls(data={"message": json_str})
