# simulator/runtime_types.py
# Runtime I/O protocol types (docs/06_runtime_input_schema.md, 07_runtime_output_schema.md)
#
# 목적
# - 서버/AR 팀과 합의한 "런타임 입력(UserInput)" / "런타임 출력(SimState)" 스키마를
#   Python에서 타입으로 고정해두는 파일.
# - 메타데이터(SceneMeta 등)와 성격이 다르므로 metadata_types.py와 분리.
#
# 핵심 원칙
# - 좌표계: Right-handed
# - 단위: meter, radian
# - 입력/출력은 JSON 직렬화 가능해야 함
# - 회전(Quaternion) 표기:
#   - 내부 표준: w,x,y,z
#   - 런타임 출력(rot): e0=w, e1=x, e2=y, e3=z  (Chrono 문서/프로토타입 컨벤션)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Union


# ============================================================
# Core runtime value objects
# ============================================================

@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Vec3":
        return Vec3(float(d["x"]), float(d["y"]), float(d["z"]))

    def to_dict(self) -> Dict[str, float]:
        return {"x": float(self.x), "y": float(self.y), "z": float(self.z)}


@dataclass(frozen=True)
class QuatWXYZ:
    """내부 표준 쿼터니언: (w,x,y,z)"""
    w: float
    x: float
    y: float
    z: float

    @staticmethod
    def from_wxyz_list(v: List[float]) -> "QuatWXYZ":
        if not (isinstance(v, list) and len(v) == 4):
            raise ValueError(f"QuatWXYZ must be [w,x,y,z], got: {v}")
        return QuatWXYZ(float(v[0]), float(v[1]), float(v[2]), float(v[3]))

    @staticmethod
    def from_e0e1e2e3_dict(d: Dict[str, Any]) -> "QuatWXYZ":
        # runtime output convention: e0=w, e1=x, e2=y, e3=z
        return QuatWXYZ(float(d["e0"]), float(d["e1"]), float(d["e2"]), float(d["e3"]))

    def to_e0e1e2e3_dict(self) -> Dict[str, float]:
        return {"e0": float(self.w), "e1": float(self.x), "e2": float(self.y), "e3": float(self.z)}


# ============================================================
# Runtime Output (Server -> Client)
# ============================================================

@dataclass(frozen=True)
class PartState:
    """
    07_runtime_output_schema.md에서 정의할 "parts" 원자 단위.
    - pos/rot 는 WORLD 기준
    - rot는 e0/e1/e2/e3로 직렬화
    """
    pos: Vec3
    rot: QuatWXYZ

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PartState":
        return PartState(
            pos=Vec3.from_dict(d["pos"]),
            rot=QuatWXYZ.from_e0e1e2e3_dict(d["rot"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pos": self.pos.to_dict(),
            "rot": self.rot.to_e0e1e2e3_dict(),
        }

    # (선택) pychrono에서 바로 만들고 싶을 때를 위한 헬퍼 자리:
    # @staticmethod
    # def from_chrono_body(body: "chrono.ChBody") -> "PartState":
    #     ...


@dataclass(frozen=True)
class SimState:
    """
    서버가 클라이언트로 내보내는 상태 메시지.
    - sim_time: 시뮬레이션 시간(초)
    - parts: PartState 배열 (PartIndex는 이 배열 index로 정의)
    """
    sim_time: float
    parts: List[PartState]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SimState":
        return SimState(
            sim_time=float(d["sim_time"]),
            parts=[PartState.from_dict(p) for p in d.get("parts", [])],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sim_time": float(self.sim_time),
            "parts": [p.to_dict() for p in self.parts],
        }


# ============================================================
# Runtime Input (Client -> Server)
# ============================================================

PartIndex = int

@dataclass(frozen=True)
class PartRef:
    """
    타겟 파트 지정.
    - 현재 프로토콜은 PartIndex 기반이지만,
      안정성을 위해 name 기반도 옵션으로 열어둠(06 확장안).
    """
    partIndex: Optional[PartIndex] = None
    partName: Optional[str] = None

    @staticmethod
    def from_any(d: Dict[str, Any]) -> "PartRef":
        # 허용 형태:
        # 1) {"targetPartIndex": 3}  (기존 프로토타입 형태)
        # 2) {"partIndex": 3} / {"partName": "gear_A"} (확장 형태)
        if "targetPartIndex" in d:
            return PartRef(partIndex=int(d["targetPartIndex"]))
        return PartRef(
            partIndex=int(d["partIndex"]) if "partIndex" in d else None,
            partName=str(d["partName"]) if "partName" in d else None,
        )

    def to_target_dict(self) -> Dict[str, Any]:
        # 기본은 인덱스를 쓰되, 없으면 name 사용
        if self.partIndex is not None:
            return {"targetPartIndex": int(self.partIndex)}
        if self.partName is not None:
            return {"targetPartName": str(self.partName)}
        return {}


@dataclass(frozen=True)
class TouchStartPayload:
    target: PartRef
    actionPoint: Vec3      # BODY-LOCAL
    fingerPoint: Vec3      # WORLD
    z_direction: Vec3      # WORLD (camera forward)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchStartPayload":
        # d에는 targetPartIndex가 payload 내부에 존재하는 기존형을 우선 지원
        target = PartRef.from_any(d)
        return TouchStartPayload(
            target=target,
            actionPoint=Vec3.from_dict(d["actionPoint"]),
            fingerPoint=Vec3.from_dict(d["fingerPoint"]),
            z_direction=Vec3.from_dict(d["z_direction"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        out = {
            **self.target.to_target_dict(),
            "actionPoint": self.actionPoint.to_dict(),
            "fingerPoint": self.fingerPoint.to_dict(),
            "z_direction": self.z_direction.to_dict(),
        }
        return out


@dataclass(frozen=True)
class TouchingPayload:
    fingerPoint: Vec3      # WORLD
    z_direction: Vec3      # WORLD

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchingPayload":
        return TouchingPayload(
            fingerPoint=Vec3.from_dict(d["fingerPoint"]),
            z_direction=Vec3.from_dict(d["z_direction"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerPoint": self.fingerPoint.to_dict(),
            "z_direction": self.z_direction.to_dict(),
        }


@dataclass(frozen=True)
class TouchEndPayload:
    @staticmethod
    def from_dict(_: Dict[str, Any]) -> "TouchEndPayload":
        return TouchEndPayload()

    def to_dict(self) -> Dict[str, Any]:
        return {}


# ---- Event wrappers (discriminated union) ----

TouchEventType = Literal["TouchStart", "Touching", "TouchEnd"]

@dataclass(frozen=True)
class TouchStartEvent:
    type: Literal["TouchStart"]
    payload: TouchStartPayload

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchStartEvent":
        return TouchStartEvent(type="TouchStart", payload=TouchStartPayload.from_dict(d.get("payload", {})))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "TouchStart", "payload": self.payload.to_dict()}


@dataclass(frozen=True)
class TouchingEvent:
    type: Literal["Touching"]
    payload: TouchingPayload

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchingEvent":
        return TouchingEvent(type="Touching", payload=TouchingPayload.from_dict(d.get("payload", {})))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "Touching", "payload": self.payload.to_dict()}


@dataclass(frozen=True)
class TouchEndEvent:
    type: Literal["TouchEnd"]
    payload: TouchEndPayload

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchEndEvent":
        return TouchEndEvent(type="TouchEnd", payload=TouchEndPayload.from_dict(d.get("payload", {})))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "TouchEnd", "payload": self.payload.to_dict()}


UserInput = Union[TouchStartEvent, TouchingEvent, TouchEndEvent]


def user_input_from_dict(d: Dict[str, Any]) -> UserInput:
    """
    런타임 입력 dict(JSON)을 UserInput 타입으로 파싱하는 단일 엔트리.
    서버/엔진 코드에서는 이 함수만 호출하면 됨.
    """
    t = d.get("type")
    if t == "TouchStart":
        return TouchStartEvent.from_dict(d)
    if t == "Touching":
        return TouchingEvent.from_dict(d)
    if t == "TouchEnd":
        return TouchEndEvent.from_dict(d)
    raise ValueError(f"Unknown UserInput.type: {t}")


def user_input_to_dict(ev: UserInput) -> Dict[str, Any]:
    """UserInput -> JSON dict"""
    return ev.to_dict()


# ============================================================
# (Optional) helper for index-based protocols
# ============================================================

def resolve_target_part_name(
    event: UserInput,
    part_names: List[str],
) -> Optional[str]:
    """
    PartIndex 기반 입력을 name으로 해석하고 싶을 때 사용.
    - part_names는 SimState.parts와 동일한 순서의 이름 배열(엔진이 제공/합의)
    """
    if isinstance(event, TouchStartEvent):
        idx = event.payload.target.partIndex
        if idx is None:
            return event.payload.target.partName
        if 0 <= idx < len(part_names):
            return part_names[idx]
        return None
    # Touching/TouchEnd는 target을 포함하지 않는 설계이므로 None
    return None
