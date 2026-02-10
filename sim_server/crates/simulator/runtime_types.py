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
#   - 런타임 출력(rot): {w,x,y,z}  (docs/07 기준)
#
# 호환성(레거시) 지원:
# - 과거 프로토타입에서 rot를 e0/e1/e2/e3로 주고받던 흔적이 있어,
#   from_dict에서는 e0/e1/e2/e3도 fallback으로 받아준다.
# - 입력 스키마도 actionPoint/fingerPoint/z_direction 같은 레거시 키를 fallback으로 받아준다.

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
        if not isinstance(d, dict):
            raise ValueError(f"Vec3 must be object, got: {type(d)}")
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
    def from_wxyz_dict(d: Dict[str, Any]) -> "QuatWXYZ":
        # docs/07: {"w":..,"x":..,"y":..,"z":..}
        return QuatWXYZ(float(d["w"]), float(d["x"]), float(d["y"]), float(d["z"]))

    @staticmethod
    def from_e0e1e2e3_dict(d: Dict[str, Any]) -> "QuatWXYZ":
        # legacy: {"e0":w,"e1":x,"e2":y,"e3":z}
        return QuatWXYZ(float(d["e0"]), float(d["e1"]), float(d["e2"]), float(d["e3"]))

    @staticmethod
    def from_any_dict(d: Dict[str, Any]) -> "QuatWXYZ":
        if not isinstance(d, dict):
            raise ValueError(f"Quaternion must be object, got: {type(d)}")

        # 우선 docs/07 (wxyz), 그 다음 legacy (e0..e3)
        if all(k in d for k in ("w", "x", "y", "z")):
            return QuatWXYZ.from_wxyz_dict(d)
        if all(k in d for k in ("e0", "e1", "e2", "e3")):
            return QuatWXYZ.from_e0e1e2e3_dict(d)
        raise ValueError(f"Quaternion must be wxyz or e0e1e2e3 dict, got keys={list(d.keys())}")

    def to_wxyz_dict(self) -> Dict[str, float]:
        # docs/07: {"w","x","y","z"}
        return {"w": float(self.w), "x": float(self.x), "y": float(self.y), "z": float(self.z)}

    def to_e0e1e2e3_dict(self) -> Dict[str, float]:
        # legacy export (필요 시)
        return {"e0": float(self.w), "e1": float(self.x), "e2": float(self.y), "e3": float(self.z)}


# ============================================================
# Runtime Output (Server -> Client)
# ============================================================

@dataclass(frozen=True)
class PartState:
    """
    07_runtime_output_schema.md에서 정의할 "parts" 원자 단위.
    - name/pos/rot 는 WORLD 기준
    - rot는 {w,x,y,z}로 직렬화 (docs/07)
    """
    name: str
    pos: Vec3
    rot: QuatWXYZ

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PartState":
        # docs/07: {"name":..., "pos":{x,y,z}, "rot":{w,x,y,z}}
        if not isinstance(d, dict):
            raise ValueError(f"PartState must be object, got: {type(d)}")
        return PartState(
            name=str(d.get("name", "")),
            pos=Vec3.from_dict(d["pos"]),
            rot=QuatWXYZ.from_any_dict(d["rot"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        # docs/07 준수
        return {
            "name": str(self.name),
            "pos": self.pos.to_dict(),
            "rot": self.rot.to_wxyz_dict(),
        }

    @staticmethod
    def from_chrono_body(body: Any, *, name: str) -> "PartState":
        """
        Chrono body -> PartState 변환 헬퍼.
        - name: docs/07에서 요구하는 bodies[*].name 과 동일한 문자열
        - pos: WORLD (x,y,z)
        - rot: WORLD quaternion (w,x,y,z) == Chrono (e0,e1,e2,e3)
        """
        p = body.GetPos()
        q = body.GetRot()  # Chrono: e0=w, e1=x, e2=y, e3=z
        return PartState(
            name=str(name),
            pos=Vec3(float(p.x), float(p.y), float(p.z)),
            rot=QuatWXYZ(float(q.e0), float(q.e1), float(q.e2), float(q.e3)),
        )


@dataclass(frozen=True)
class SimState:
    """
    서버가 클라이언트로 내보내는 상태 메시지.

    docs/07 기본:
    - sim_time: float
    - parts: List[PartState]

    docs/07 Optional:
    - partNames: List[str]  (index 안정성)
    - seq: int              (증가하는 시퀀스)
    - server_time_sec: float (서버 wall-clock timestamp, seconds)
    """
    sim_time: float
    parts: List[PartState]

    # (Optional) index 안정성 / 디버깅용
    partNames: Optional[List[str]] = None
    seq: Optional[int] = None
    server_time_sec: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SimState":
        if not isinstance(d, dict):
            raise ValueError(f"SimState must be object, got: {type(d)}")

        sim_time = float(d["sim_time"])
        seq = int(d["seq"]) if "seq" in d and d["seq"] is not None else None
        server_time_sec = float(d["server_time_sec"]) if "server_time_sec" in d and d["server_time_sec"] is not None else None

        partNames = [str(x) for x in d.get("partNames", [])] if "partNames" in d else None
        raw_parts = d.get("parts", [])

        # ---- Parse parts in two possible modes ----
        # Mode A) parts = [{name,pos,rot}, ...]
        # Mode B) partNames = [...], parts = [{pos,rot}, ...] (name omitted, index implied)
        parts: List[PartState] = []

        if isinstance(raw_parts, list) and raw_parts:
            # If first element has "name", assume Mode A.
            if isinstance(raw_parts[0], dict) and "name" in raw_parts[0]:
                parts = [PartState.from_dict(p) for p in raw_parts]
            else:
                # Mode B (name omitted) - requires partNames
                if partNames is None:
                    raise ValueError("SimState.parts has no 'name' field; requires 'partNames' to map indices.")
                if len(raw_parts) != len(partNames):
                    raise ValueError(
                        f"SimState.parts length ({len(raw_parts)}) must match partNames length ({len(partNames)}) in index-mapped mode."
                    )
                for nm, p in zip(partNames, raw_parts):
                    if not isinstance(p, dict):
                        raise ValueError(f"SimState.parts item must be object, got: {type(p)}")
                    # p expected: {"pos":..., "rot":...}
                    parts.append(
                        PartState(
                            name=str(nm),
                            pos=Vec3.from_dict(p["pos"]),
                            rot=QuatWXYZ.from_any_dict(p["rot"]),
                        )
                    )
        else:
            parts = []

        return SimState(
            sim_time=sim_time,
            parts=parts,
            partNames=partNames,
            seq=seq,
            server_time_sec=server_time_sec,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "sim_time": float(self.sim_time),
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.partNames is not None:
            out["partNames"] = [str(x) for x in self.partNames]
        if self.seq is not None:
            out["seq"] = int(self.seq)
        if self.server_time_sec is not None:
            out["server_time_sec"] = float(self.server_time_sec)
        return out


# ============================================================
# Runtime Input (Client -> Server)
# ============================================================

PartIndex = int


@dataclass(frozen=True)
class PartRef:
    """
    타겟 파트 지정.
    - docs/06: payload.target.partIndex / payload.target.partName (둘 다 optional)
    - 레거시: targetPartIndex / targetPartName 같은 키가 payload 최상단에 있던 버전도 fallback 지원
    """
    partIndex: Optional[PartIndex] = None
    partName: Optional[str] = None

    @staticmethod
    def from_any(d: Dict[str, Any]) -> "PartRef":
        if not isinstance(d, dict):
            raise ValueError(f"PartRef payload must be object, got: {type(d)}")

        # 1) docs/06: {"target": {"partIndex":..,"partName":..}}
        if "target" in d and isinstance(d["target"], dict):
            t = d["target"]
            return PartRef(
                partIndex=int(t["partIndex"]) if "partIndex" in t and t["partIndex"] is not None else None,
                partName=str(t["partName"]) if "partName" in t and t["partName"] is not None else None,
            )

        # 2) 레거시 형태: {"targetPartIndex": 3} / {"targetPartName": "gear_A"}
        if "targetPartIndex" in d or "targetPartName" in d:
            return PartRef(
                partIndex=int(d["targetPartIndex"]) if "targetPartIndex" in d and d["targetPartIndex"] is not None else None,
                partName=str(d["targetPartName"]) if "targetPartName" in d and d["targetPartName"] is not None else None,
            )

        # 3) 확장 형태(예전 코드): {"partIndex": 3} / {"partName": "gear_A"}
        return PartRef(
            partIndex=int(d["partIndex"]) if "partIndex" in d and d["partIndex"] is not None else None,
            partName=str(d["partName"]) if "partName" in d and d["partName"] is not None else None,
        )

    def to_target_dict(self) -> Dict[str, Any]:
        # docs/06 준수: payload.target = {partIndex?, partName?}
        t: Dict[str, Any] = {}
        if self.partIndex is not None:
            t["partIndex"] = int(self.partIndex)
        if self.partName is not None:
            t["partName"] = str(self.partName)
        return {"target": t}


# ---- Common optional meta fields (docs/06 Recommended) ----

@dataclass(frozen=True)
class InputMeta:
    interactionId: Optional[str] = None
    timestampSec: Optional[float] = None
    seq: Optional[int] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "InputMeta":
        if not isinstance(d, dict):
            raise ValueError(f"InputMeta must be object, got: {type(d)}")
        interactionId = str(d["interactionId"]) if "interactionId" in d and d["interactionId"] is not None else None
        timestampSec = float(d["timestampSec"]) if "timestampSec" in d and d["timestampSec"] is not None else None
        seq = int(d["seq"]) if "seq" in d and d["seq"] is not None else None
        return InputMeta(interactionId=interactionId, timestampSec=timestampSec, seq=seq)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.interactionId is not None:
            out["interactionId"] = str(self.interactionId)
        if self.timestampSec is not None:
            out["timestampSec"] = float(self.timestampSec)
        if self.seq is not None:
            out["seq"] = int(self.seq)
        return out


@dataclass(frozen=True)
class TouchStartPayload:
    # docs/06
    target: PartRef
    actionPointLocal: Vec3        # BODY-LOCAL
    fingerPointWorld: Vec3        # WORLD
    cameraForwardWorld: Vec3      # WORLD (camera forward)

    # docs/06 recommended optional fields
    meta: InputMeta = InputMeta()

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchStartPayload":
        if not isinstance(d, dict):
            raise ValueError(f"TouchStartPayload must be object, got: {type(d)}")

        target = PartRef.from_any(d)

        # docs/06 keys (preferred)
        if "actionPointLocal" in d:
            ap = Vec3.from_dict(d["actionPointLocal"])
        else:
            # legacy fallback
            ap = Vec3.from_dict(d.get("actionPoint", {"x": 0, "y": 0, "z": 0}))

        if "fingerPointWorld" in d:
            fp = Vec3.from_dict(d["fingerPointWorld"])
        else:
            fp = Vec3.from_dict(d.get("fingerPoint", {"x": 0, "y": 0, "z": 0}))

        if "cameraForwardWorld" in d:
            cf = Vec3.from_dict(d["cameraForwardWorld"])
        else:
            cf = Vec3.from_dict(d.get("z_direction", {"x": 0, "y": 0, "z": 1}))

        meta = InputMeta.from_dict(d)

        return TouchStartPayload(
            target=target,
            actionPointLocal=ap,
            fingerPointWorld=fp,
            cameraForwardWorld=cf,
            meta=meta,
        )

    def to_dict(self) -> Dict[str, Any]:
        # docs/06 준수
        out: Dict[str, Any] = {
            **self.target.to_target_dict(),
            "actionPointLocal": self.actionPointLocal.to_dict(),
            "fingerPointWorld": self.fingerPointWorld.to_dict(),
            "cameraForwardWorld": self.cameraForwardWorld.to_dict(),
            **self.meta.to_dict(),
        }
        return out

    # 레거시 코드 호환용 프로퍼티
    @property
    def interactionId(self) -> Optional[str]:
        return self.meta.interactionId

    @property
    def timestampSec(self) -> Optional[float]:
        return self.meta.timestampSec

    @property
    def seq(self) -> Optional[int]:
        return self.meta.seq

    @property
    def actionPoint(self) -> Vec3:
        return self.actionPointLocal

    @property
    def fingerPoint(self) -> Vec3:
        return self.fingerPointWorld

    @property
    def z_direction(self) -> Vec3:
        return self.cameraForwardWorld


@dataclass(frozen=True)
class TouchingPayload:
    # docs/06
    fingerPointWorld: Vec3      # WORLD
    cameraForwardWorld: Vec3    # WORLD

    # docs/06 recommended: target or interactionId
    target: Optional[PartRef] = None
    meta: InputMeta = InputMeta()

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchingPayload":
        if not isinstance(d, dict):
            raise ValueError(f"TouchingPayload must be object, got: {type(d)}")

        if "fingerPointWorld" in d:
            fp = Vec3.from_dict(d["fingerPointWorld"])
        else:
            fp = Vec3.from_dict(d.get("fingerPoint", {"x": 0, "y": 0, "z": 0}))

        if "cameraForwardWorld" in d:
            cf = Vec3.from_dict(d["cameraForwardWorld"])
        else:
            cf = Vec3.from_dict(d.get("z_direction", {"x": 0, "y": 0, "z": 1}))

        # target is optional (recommended in docs/06)
        target = PartRef.from_any(d) if ("target" in d or "targetPartIndex" in d or "targetPartName" in d or "partIndex" in d or "partName" in d) else None
        meta = InputMeta.from_dict(d)

        return TouchingPayload(
            fingerPointWorld=fp,
            cameraForwardWorld=cf,
            target=target,
            meta=meta,
        )

    def to_dict(self) -> Dict[str, Any]:
        # docs/06 준수
        out: Dict[str, Any] = {
            "fingerPointWorld": self.fingerPointWorld.to_dict(),
            "cameraForwardWorld": self.cameraForwardWorld.to_dict(),
            **self.meta.to_dict(),
        }
        if self.target is not None:
            out.update(self.target.to_target_dict())
        return out

    # 레거시 코드 호환용 프로퍼티
    @property
    def interactionId(self) -> Optional[str]:
        return self.meta.interactionId

    @property
    def timestampSec(self) -> Optional[float]:
        return self.meta.timestampSec

    @property
    def seq(self) -> Optional[int]:
        return self.meta.seq

    @property
    def fingerPoint(self) -> Vec3:
        return self.fingerPointWorld

    @property
    def z_direction(self) -> Vec3:
        return self.cameraForwardWorld


@dataclass(frozen=True)
class TouchEndPayload:
    # docs/06 recommended: target or interactionId
    target: Optional[PartRef] = None
    meta: InputMeta = InputMeta()

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchEndPayload":
        if not isinstance(d, dict):
            # TouchEnd는 payload {}가 일반적이지만, None이면 {}로 취급
            d = {}

        target = PartRef.from_any(d) if ("target" in d or "targetPartIndex" in d or "targetPartName" in d or "partIndex" in d or "partName" in d) else None
        meta = InputMeta.from_dict(d)

        return TouchEndPayload(target=target, meta=meta)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            **self.meta.to_dict(),
        }
        if self.target is not None:
            out.update(self.target.to_target_dict())
        return out

    @property
    def interactionId(self) -> Optional[str]:
        return self.meta.interactionId

    @property
    def timestampSec(self) -> Optional[float]:
        return self.meta.timestampSec

    @property
    def seq(self) -> Optional[int]:
        return self.meta.seq


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
    if not isinstance(d, dict):
        raise ValueError(f"UserInput must be object, got: {type(d)}")

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
    # TouchStart: payload.target
    if isinstance(event, TouchStartEvent):
        if event.payload.target.partName:
            return event.payload.target.partName

        idx = event.payload.target.partIndex
        if idx is None:
            return None
        if 0 <= idx < len(part_names):
            return part_names[idx]
        return None

    # Touching: optional payload.target
    if isinstance(event, TouchingEvent):
        if event.payload.target is None:
            return None
        if event.payload.target.partName:
            return event.payload.target.partName
        idx = event.payload.target.partIndex
        if idx is None:
            return None
        if 0 <= idx < len(part_names):
            return part_names[idx]
        return None

    # TouchEnd: optional payload.target
    if isinstance(event, TouchEndEvent):
        if event.payload.target is None:
            return None
        if event.payload.target.partName:
            return event.payload.target.partName
        idx = event.payload.target.partIndex
        if idx is None:
            return None
        if 0 <= idx < len(part_names):
            return part_names[idx]
        return None

    return None
