# simulator/metadata_types.py
# Simulation Metadata Schema (docs/03_metadata_schema.md) -> Python dataclasses
#
# - JSON(dict) 을 "타입이 있는 객체"로 변환
# - 필드 누락/형식 오류를 가능한 빨리 검출
#
# [UPDATED]
# - geometry.collision:
#     (1) 단일 primitive dict
#     (2) 복합 primitive list[dict]
#     (3) auto-approx opt-in: "auto" 또는 {"kind":"auto", "strategy":"default"}
# - collision primitive는 BODY-LOCAL offset(Pose)을 선택적으로 가질 수 있음
#   (미지정 시 identity)

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Union


# =========================
# Core value objects
# =========================

@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    @staticmethod
    def from_list(v: List[float]) -> "Vec3":
        if not (isinstance(v, list) and len(v) == 3):
            raise ValueError(f"Vec3 must be [x,y,z], got: {v}")
        return Vec3(float(v[0]), float(v[1]), float(v[2]))

    @staticmethod
    def from_any(v: Any) -> "Vec3":
        # 허용: [x,y,z] 또는 {"x":..,"y":..,"z":..}
        if isinstance(v, list):
            return Vec3.from_list(v)
        if isinstance(v, dict):
            return Vec3(float(v["x"]), float(v["y"]), float(v["z"]))
        raise ValueError(f"Vec3 must be list or dict, got: {type(v)}")

    def to_list(self) -> List[float]:
        return [float(self.x), float(self.y), float(self.z)]

    def to_dict(self) -> Dict[str, float]:
        return {"x": float(self.x), "y": float(self.y), "z": float(self.z)}


@dataclass(frozen=True)
class Quat:
    # Quaternion ordering: [w,x,y,z]  (docs 기준)
    w: float
    x: float
    y: float
    z: float

    @staticmethod
    def from_list(q: List[float]) -> "Quat":
        if not (isinstance(q, list) and len(q) == 4):
            raise ValueError(f"Quat must be [w,x,y,z], got: {q}")
        return Quat(float(q[0]), float(q[1]), float(q[2]), float(q[3]))

    @staticmethod
    def from_any(q: Any) -> "Quat":
        # 허용: [w,x,y,z] 또는 {"w":..,"x":..,"y":..,"z":..}
        if isinstance(q, list):
            return Quat.from_list(q)
        if isinstance(q, dict):
            return Quat(float(q["w"]), float(q["x"]), float(q["y"]), float(q["z"]))
        raise ValueError(f"Quat must be list or dict, got: {type(q)}")

    def to_list(self) -> List[float]:
        return [float(self.w), float(self.x), float(self.y), float(self.z)]

    def to_dict(self) -> Dict[str, float]:
        return {"w": float(self.w), "x": float(self.x), "y": float(self.y), "z": float(self.z)}


@dataclass(frozen=True)
class Pose:
    # NOTE:
    # - Body pose 뿐 아니라 Joint frame / Gear mesh frame 등 "WORLD frame"도
    #   동일한 JSON 구조를 사용하므로 Pose 타입을 재사용한다.
    # - collision.offset, visual.offset 은 BODY-LOCAL frame 의미로 사용 가능
    pos: Vec3
    rot: Quat

    @staticmethod
    def identity() -> "Pose":
        return Pose(pos=Vec3(0.0, 0.0, 0.0), rot=Quat(1.0, 0.0, 0.0, 0.0))

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Pose":
        if not isinstance(d, dict):
            raise ValueError(f"Pose must be object, got: {d}")
        if "pos" not in d or "rot" not in d:
            raise ValueError(f"Pose must have 'pos' and 'rot', got keys={list(d.keys())}")
        return Pose(
            pos=Vec3.from_any(d["pos"]),
            rot=Quat.from_any(d["rot"]),
        )

    @staticmethod
    def from_optional_dict(d: Optional[Dict[str, Any]]) -> "Pose":
        if d is None:
            return Pose.identity()
        if not isinstance(d, dict):
            raise ValueError(f"Pose must be object, got: {d}")
        pos = d.get("pos", [0.0, 0.0, 0.0])
        rot = d.get("rot", [1.0, 0.0, 0.0, 0.0])
        return Pose(pos=Vec3.from_any(pos), rot=Quat.from_any(rot))

    def to_dict(self) -> Dict[str, Any]:
        return {"pos": self.pos.to_list(), "rot": self.rot.to_list()}


# =========================
# Geometry
# =========================

VisualKind = Literal["mesh"]

@dataclass(frozen=True)
class VisualMesh:
    kind: VisualKind
    file: str
    scale: Vec3
    # body-local offset
    offset: Pose

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "VisualMesh":
        if not isinstance(d, dict):
            raise ValueError(f"geometry.visual must be object, got: {type(d)}")
        if d.get("kind") != "mesh":
            raise ValueError(f"visual.kind must be 'mesh', got: {d.get('kind')}")
        if "file" not in d:
            raise ValueError("visual.file is required")
        scale = d.get("scale", [1, 1, 1])

        # [FIX] offset은 pos/rot 부분 생략이 가능해야 함 -> from_optional_dict 사용
        offset = d.get("offset", None)

        return VisualMesh(
            kind="mesh",
            file=str(d["file"]),
            scale=Vec3.from_any(scale),
            offset=Pose.from_optional_dict(offset),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "mesh",
            "file": str(self.file),
            "scale": self.scale.to_list(),
            "offset": self.offset.to_dict(),
        }


# ---- Collision (UPDATED) ----
CollisionPrimitiveKind = Literal["box", "cylinder", "sphere"]

@dataclass(frozen=True)
class CollisionPrimitive:
    """
    단일 collision primitive.

    - kind: box|cylinder|sphere
    - offset: BODY-LOCAL Pose (선택, 기본 identity)
    """
    kind: CollisionPrimitiveKind
    offset: Pose = field(default_factory=Pose.identity)

    # box
    hx: Optional[float] = None
    hy: Optional[float] = None
    hz: Optional[float] = None

    # cylinder or sphere
    radius: Optional[float] = None

    # cylinder
    length: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CollisionPrimitive":
        if not isinstance(d, dict):
            raise ValueError(f"collision primitive must be object, got: {type(d)}")

        kind = d.get("kind")
        if kind not in ("box", "cylinder", "sphere"):
            raise ValueError(f"collision.kind must be box|cylinder|sphere, got: {kind}")

        offset = Pose.from_optional_dict(d.get("offset"))

        if kind == "box":
            if "hx" not in d or "hy" not in d or "hz" not in d:
                raise ValueError("collision.box requires hx, hy, hz")
            return CollisionPrimitive(
                kind="box",
                offset=offset,
                hx=float(d["hx"]),
                hy=float(d["hy"]),
                hz=float(d["hz"]),
            )

        if kind == "cylinder":
            if "radius" not in d or "length" not in d:
                raise ValueError("collision.cylinder requires radius, length")
            return CollisionPrimitive(
                kind="cylinder",
                offset=offset,
                radius=float(d["radius"]),
                length=float(d["length"]),
            )

        # sphere
        if "radius" not in d:
            raise ValueError("collision.sphere requires radius")
        return CollisionPrimitive(
            kind="sphere",
            offset=offset,
            radius=float(d["radius"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"kind": self.kind}
        if self.offset != Pose.identity():
            out["offset"] = self.offset.to_dict()

        # [FIX] None을 0.0으로 "채우지" 않고, 유효성 보장(깨진 충돌 형상 방지)
        if self.kind == "box":
            if self.hx is None or self.hy is None or self.hz is None:
                raise ValueError("CollisionPrimitive(box) missing hx/hy/hz")
            out.update({"hx": float(self.hx), "hy": float(self.hy), "hz": float(self.hz)})

        elif self.kind == "cylinder":
            if self.radius is None or self.length is None:
                raise ValueError("CollisionPrimitive(cylinder) missing radius/length")
            out.update({"radius": float(self.radius), "length": float(self.length)})

        elif self.kind == "sphere":
            if self.radius is None:
                raise ValueError("CollisionPrimitive(sphere) missing radius")
            out.update({"radius": float(self.radius)})

        return out


CollisionStrategy = Literal["default", "base_aabb", "shaft_pca_hub2cyl", "aabb_box"]
_ALLOWED_COLLISION_STRATEGIES = {"default", "base_aabb", "shaft_pca_hub2cyl", "aabb_box"}

@dataclass(frozen=True)
class CollisionAuto:
    """
    collision auto-approx (OPT-IN).

    허용 입력 형태:
    - "auto"
    - {"kind":"auto", "strategy":"default"}
    """
    kind: Literal["auto"] = "auto"
    strategy: CollisionStrategy = "default"

    @staticmethod
    def from_any(v: Any) -> "CollisionAuto":
        if v == "auto":
            return CollisionAuto()

        if isinstance(v, dict):
            if v.get("kind") != "auto":
                raise ValueError(f"collision.kind must be 'auto' for auto object, got: {v.get('kind')}")
            strategy = v.get("strategy", "default")
            if strategy is None:
                strategy = "default"
            strategy = str(strategy)

            if strategy not in _ALLOWED_COLLISION_STRATEGIES:
                raise ValueError(
                    f"collision.auto.strategy must be one of {sorted(_ALLOWED_COLLISION_STRATEGIES)}, got: {strategy}"
                )
            # [FIX] type: ignore 제거 (검증 후 문자열이므로 OK)
            return CollisionAuto(strategy=strategy)

        raise ValueError(f"collision auto must be 'auto' or object, got: {type(v)}")

    def to_dict(self) -> Dict[str, Any]:
        # 항상 object로 내보내고 싶으면 이걸 쓰면 됨
        return {"kind": "auto", "strategy": str(self.strategy)}


# collision can be:
# - single primitive object
# - list of primitive objects
# - auto directive
CollisionSpec = Union[CollisionPrimitive, List[CollisionPrimitive], CollisionAuto]


@dataclass(frozen=True)
class Geometry:
    visual: VisualMesh
    collision: CollisionSpec

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Geometry":
        if not isinstance(d, dict):
            raise ValueError(f"geometry must be object, got: {type(d)}")

        if "visual" not in d:
            raise ValueError("geometry.visual is required")
        if "collision" not in d:
            raise ValueError(
                "geometry.collision is required. "
                "Use an explicit primitive, a list of primitives, or opt-in auto as "
                "collision:'auto' / {kind:'auto'}."
            )

        visual = VisualMesh.from_dict(d["visual"])
        col_raw = d["collision"]

        # (3) auto
        if col_raw == "auto" or (isinstance(col_raw, dict) and col_raw.get("kind") == "auto"):
            collision: CollisionSpec = CollisionAuto.from_any(col_raw)
            return Geometry(visual=visual, collision=collision)

        # (2) multiple
        if isinstance(col_raw, list):
            if len(col_raw) == 0:
                raise ValueError("geometry.collision list must not be empty")
            prims = [CollisionPrimitive.from_dict(x) for x in col_raw]
            return Geometry(visual=visual, collision=prims)

        # (1) single primitive
        if isinstance(col_raw, dict):
            prim = CollisionPrimitive.from_dict(col_raw)
            return Geometry(visual=visual, collision=prim)

        raise ValueError(f"geometry.collision must be object | list | 'auto', got: {type(col_raw)}")

    def to_dict(self) -> Dict[str, Any]:
        if isinstance(self.collision, list):
            col = [p.to_dict() for p in self.collision]
        elif isinstance(self.collision, CollisionAuto):
            col = self.collision.to_dict()
        else:
            col = self.collision.to_dict()

        return {"visual": self.visual.to_dict(), "collision": col}


# =========================
# Mechanical
# =========================

InertiaMode = Literal["explicit", "auto_from_collision"]

@dataclass(frozen=True)
class Inertia:
    mode: InertiaMode
    Ixx: Optional[float] = None
    Iyy: Optional[float] = None
    Izz: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Inertia":
        if not isinstance(d, dict):
            raise ValueError(f"inertia must be object, got: {type(d)}")

        mode = d.get("mode", "explicit")
        if mode not in ("explicit", "auto_from_collision"):
            raise ValueError(f"inertia.mode must be explicit|auto_from_collision, got: {mode}")

        if mode == "explicit":
            if "Ixx" not in d or "Iyy" not in d or "Izz" not in d:
                raise ValueError("inertia(mode=explicit) requires Ixx, Iyy, Izz")
            return Inertia(
                mode="explicit",
                Ixx=float(d["Ixx"]),
                Iyy=float(d["Iyy"]),
                Izz=float(d["Izz"]),
            )
        return Inertia(mode="auto_from_collision")

    def to_dict(self) -> Dict[str, Any]:
        if self.mode == "explicit":
            return {
                "mode": "explicit",
                "Ixx": float(self.Ixx or 0.0),
                "Iyy": float(self.Iyy or 0.0),
                "Izz": float(self.Izz or 0.0),
            }
        return {"mode": "auto_from_collision"}


@dataclass(frozen=True)
class Contact:
    friction: float
    restitution: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Contact":
        if not isinstance(d, dict):
            raise ValueError(f"contact must be object, got: {type(d)}")
        return Contact(
            friction=float(d.get("friction", 0.4)),
            restitution=float(d.get("restitution", 0.05)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"friction": float(self.friction), "restitution": float(self.restitution)}


DampingType = Literal["viscous_torque"]

@dataclass(frozen=True)
class Damping:
    type: DampingType
    coef: float
    # viscous_torque: tau = -coef * omega (coef unit: N·m·s/rad)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Damping":
        if not isinstance(d, dict):
            raise ValueError(f"damping must be object, got: {type(d)}")
        dtype = d.get("type", "viscous_torque")
        if dtype != "viscous_torque":
            raise ValueError(f"damping.type currently supports only viscous_torque, got: {dtype}")
        return Damping(type="viscous_torque", coef=float(d.get("coef", 0.0)))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "viscous_torque", "coef": float(self.coef)}


@dataclass(frozen=True)
class GearProps:
    # module in meter (e.g., 2 mm -> 0.002)
    module: float
    teeth: int
    face_width: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearProps":
        if not isinstance(d, dict):
            raise ValueError(f"gearProps must be object, got: {type(d)}")
        if "module" not in d or "teeth" not in d:
            raise ValueError("gearProps requires module and teeth")
        return GearProps(
            module=float(d["module"]),
            teeth=int(d["teeth"]),
            face_width=float(d.get("face_width", 0.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"module": float(self.module), "teeth": int(self.teeth), "face_width": float(self.face_width)}


@dataclass(frozen=True)
class Mechanical:
    mass: float
    fixed: bool
    inertia: Inertia
    contact: Contact
    damping: Optional[Damping] = None
    gearProps: Optional[GearProps] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Mechanical":
        if not isinstance(d, dict):
            raise ValueError(f"mechanical must be object, got: {type(d)}")
        return Mechanical(
            mass=float(d.get("mass", 1.0)),
            fixed=bool(d.get("fixed", False)),
            inertia=Inertia.from_dict(d.get("inertia", {"mode": "explicit", "Ixx": 0, "Iyy": 0, "Izz": 0})),
            contact=Contact.from_dict(d.get("contact", {})),
            damping=Damping.from_dict(d["damping"]) if "damping" in d else None,
            gearProps=GearProps.from_dict(d["gearProps"]) if "gearProps" in d else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "mass": float(self.mass),
            "fixed": bool(self.fixed),
            "inertia": self.inertia.to_dict(),
            "contact": self.contact.to_dict(),
        }
        if self.damping is not None:
            out["damping"] = self.damping.to_dict()
        if self.gearProps is not None:
            out["gearProps"] = self.gearProps.to_dict()
        return out


BodyCategory = Literal["gear", "shaft", "base", "link", "generic"]
_ALLOWED_BODY_CATEGORIES = {"gear", "shaft", "base", "link", "generic"}

@dataclass(frozen=True)
class BodyDef:
    name: str
    category: BodyCategory
    geometry: Geometry
    mechanical: Mechanical
    pose: Pose

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "BodyDef":
        if not isinstance(d, dict):
            raise ValueError(f"body must be object, got: {type(d)}")

        if "name" not in d:
            raise ValueError("body.name is required")
        if "geometry" not in d:
            raise ValueError(f"Body '{d.get('name','?')}': geometry is required")
        if "mechanical" not in d:
            raise ValueError(f"Body '{d.get('name','?')}': mechanical is required")
        if "pose" not in d:
            raise ValueError(f"Body '{d.get('name','?')}': pose is required")

        cat = d.get("category", "generic")
        if cat is None:
            cat = "generic"
        cat = str(cat)
        if cat not in _ALLOWED_BODY_CATEGORIES:
            raise ValueError(f"body.category must be one of {sorted(_ALLOWED_BODY_CATEGORIES)}, got: {cat}")

        return BodyDef(
            name=str(d["name"]),
            category=cat,  # type: ignore
            geometry=Geometry.from_dict(d["geometry"]),
            mechanical=Mechanical.from_dict(d["mechanical"]),
            pose=Pose.from_dict(d["pose"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": str(self.name),
            "category": str(self.category),
            "geometry": self.geometry.to_dict(),
            "mechanical": self.mechanical.to_dict(),
            "pose": self.pose.to_dict(),
        }


# =========================
# Joints
# =========================

JointType = Literal["revolute", "prismatic", "fixed"]

@dataclass(frozen=True)
class JointLimits:
    lower: float
    upper: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JointLimits":
        if not isinstance(d, dict):
            raise ValueError(f"limits must be object, got: {type(d)}")
        return JointLimits(lower=float(d["lower"]), upper=float(d["upper"]))

    def to_dict(self) -> Dict[str, Any]:
        return {"lower": float(self.lower), "upper": float(self.upper)}


@dataclass(frozen=True)
class JointDef:
    name: str
    type: JointType
    body1: str
    body2: str
    frame: Pose   # NOTE: 의미는 "WORLD frame"
    limits: Optional[JointLimits] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JointDef":
        if not isinstance(d, dict):
            raise ValueError(f"joint must be object, got: {type(d)}")

        if "name" not in d or "type" not in d:
            raise ValueError("joint requires name and type")
        jtype = d.get("type")
        if jtype not in ("revolute", "prismatic", "fixed"):
            raise ValueError(f"joint.type must be revolute|prismatic|fixed, got: {jtype}")
        if "body1" not in d or "body2" not in d:
            raise ValueError(f"Joint '{d.get('name','?')}': body1/body2 required")

        return JointDef(
            name=str(d["name"]),
            type=jtype,  # type: ignore
            body1=str(d["body1"]),
            body2=str(d["body2"]),
            frame=Pose.from_dict(d["frame"]),
            limits=JointLimits.from_dict(d["limits"]) if "limits" in d else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": str(self.name),
            "type": str(self.type),
            "body1": str(self.body1),
            "body2": str(self.body2),
            "frame": self.frame.to_dict(),
        }
        if self.limits is not None:
            out["limits"] = self.limits.to_dict()
        return out


# =========================
# GearPairs
# =========================

@dataclass(frozen=True)
class GearPairProps:
    efficiency: float = 1.0
    backlash: float = 0.0

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearPairProps":
        if not isinstance(d, dict):
            raise ValueError(f"gearProps must be object, got: {type(d)}")
        return GearPairProps(
            efficiency=float(d.get("efficiency", 1.0)),
            backlash=float(d.get("backlash", 0.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"efficiency": float(self.efficiency), "backlash": float(self.backlash)}


@dataclass(frozen=True)
class GearPairDef:
    name: str
    gearA: str
    gearB: str
    ratio_sign: int = -1
    enforcePhase: bool = False
    meshFrame: Optional[Pose] = None   # NOTE: 의미는 "WORLD frame"
    gearProps: Optional[GearPairProps] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearPairDef":
        if not isinstance(d, dict):
            raise ValueError(f"gearPair must be object, got: {type(d)}")
        if "name" not in d or "gearA" not in d or "gearB" not in d:
            raise ValueError("gearPair requires name, gearA, gearB")

        return GearPairDef(
            name=str(d["name"]),
            gearA=str(d["gearA"]),
            gearB=str(d["gearB"]),
            ratio_sign=int(d.get("ratio_sign", -1)),
            enforcePhase=bool(d.get("enforcePhase", False)),
            meshFrame=Pose.from_dict(d["meshFrame"]) if "meshFrame" in d else None,
            gearProps=GearPairProps.from_dict(d["gearProps"]) if "gearProps" in d else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": str(self.name),
            "gearA": str(self.gearA),
            "gearB": str(self.gearB),
            "ratio_sign": int(self.ratio_sign),
            "enforcePhase": bool(self.enforcePhase),
        }
        if self.meshFrame is not None:
            out["meshFrame"] = self.meshFrame.to_dict()
        if self.gearProps is not None:
            out["gearProps"] = self.gearProps.to_dict()
        return out


# =========================
# Actuators
# =========================

ActuatorType = Literal["rotation_speed", "rotation_torque"]

@dataclass(frozen=True)
class TorqueModelConst:
    type: Literal["const"]
    value: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TorqueModelConst":
        if not isinstance(d, dict):
            raise ValueError(f"torqueModel must be object, got: {type(d)}")
        if d.get("type") != "const":
            raise ValueError(f"torqueModel.type currently supports only 'const', got: {d.get('type')}")
        return TorqueModelConst(type="const", value=float(d["value"]))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "const", "value": float(self.value)}


TorqueModel = Union[TorqueModelConst]


@dataclass(frozen=True)
class ActuatorDef:
    name: str
    type: ActuatorType
    targetJoint: str
    speed: Optional[float] = None
    torqueModel: Optional[TorqueModel] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ActuatorDef":
        if not isinstance(d, dict):
            raise ValueError(f"actuator must be object, got: {type(d)}")

        atype = d.get("type")
        if atype not in ("rotation_speed", "rotation_torque"):
            raise ValueError(f"actuator.type must be rotation_speed|rotation_torque, got: {atype}")

        if atype == "rotation_speed":
            if "speed" not in d:
                raise ValueError("rotation_speed actuator requires 'speed'")
            return ActuatorDef(
                name=str(d["name"]),
                type="rotation_speed",
                targetJoint=str(d["targetJoint"]),
                speed=float(d["speed"]),
            )

        # rotation_torque
        if "torqueModel" not in d:
            raise ValueError("rotation_torque actuator requires 'torqueModel'")
        return ActuatorDef(
            name=str(d["name"]),
            type="rotation_torque",
            targetJoint=str(d["targetJoint"]),
            torqueModel=TorqueModelConst.from_dict(d["torqueModel"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": str(self.name), "type": str(self.type), "targetJoint": str(self.targetJoint)}
        if self.type == "rotation_speed":
            out["speed"] = float(self.speed or 0.0)
        else:
            out["torqueModel"] = (
                self.torqueModel.to_dict() if self.torqueModel is not None else {"type": "const", "value": 0.0}
            )
        return out


# =========================
# Scene Meta (top-level)
# =========================

@dataclass(frozen=True)
class SceneMeta:
    sceneName: str
    gravity: Vec3
    bodies: List[BodyDef]
    joints: List[JointDef]
    gearPairs: List[GearPairDef]
    actuators: List[ActuatorDef]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SceneMeta":
        if not isinstance(d, dict):
            raise ValueError(f"SceneMeta must be object, got: {type(d)}")

        bodies = [BodyDef.from_dict(x) for x in d.get("bodies", [])]
        joints = [JointDef.from_dict(x) for x in d.get("joints", [])]
        gearPairs = [GearPairDef.from_dict(x) for x in d.get("gearPairs", [])]
        actuators = [ActuatorDef.from_dict(x) for x in d.get("actuators", [])]

        # 여기서도 최소한의 sanity check는 해두면 디버깅이 빨라짐
        if len(bodies) == 0:
            raise ValueError("SceneMeta.bodies must not be empty")

        return SceneMeta(
            sceneName=str(d.get("sceneName", "unnamed_scene")),
            gravity=Vec3.from_any(d.get("gravity", [0.0, -9.81, 0.0])),
            bodies=bodies,
            joints=joints,
            gearPairs=gearPairs,
            actuators=actuators,
        )

    @staticmethod
    def from_json_str(json_str: str) -> "SceneMeta":
        return SceneMeta.from_dict(json.loads(json_str))

    @staticmethod
    def from_json_file(path: str, encoding: str = "utf-8") -> "SceneMeta":
        with open(path, "r", encoding=encoding) as f:
            return SceneMeta.from_dict(json.load(f))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sceneName": str(self.sceneName),
            "gravity": self.gravity.to_list(),
            "bodies": [b.to_dict() for b in self.bodies],
            "joints": [j.to_dict() for j in self.joints],
            "gearPairs": [g.to_dict() for g in self.gearPairs],
            "actuators": [a.to_dict() for a in self.actuators],
        }


# =========================
# Minimal validation helpers (optional)
# =========================

def validate_scene(meta: SceneMeta) -> None:
    """기본적인 참조 무결성 검증. (필요 시 확장)"""

    body_names_list = [b.name for b in meta.bodies]
    joint_names_list = [j.name for j in meta.joints]
    gearpair_names_list = [g.name for g in meta.gearPairs]
    actuator_names_list = [a.name for a in meta.actuators]

    def _assert_unique(names: List[str], what: str) -> None:
        s = set()
        dup = set()
        for n in names:
            if n in s:
                dup.add(n)
            s.add(n)
        if dup:
            raise ValueError(f"Duplicate {what} name(s): {sorted(dup)}")

    _assert_unique(body_names_list, "body")
    _assert_unique(joint_names_list, "joint")
    _assert_unique(gearpair_names_list, "gearPair")
    _assert_unique(actuator_names_list, "actuator")

    body_names = set(body_names_list)
    joint_names = set(joint_names_list)

    # joints refer to bodies
    for j in meta.joints:
        if j.body1 not in body_names:
            raise ValueError(f"Joint {j.name} refers missing body1: {j.body1}")
        if j.body2 not in body_names:
            raise ValueError(f"Joint {j.name} refers missing body2: {j.body2}")

    # gearPairs refer to gear bodies + gearProps existence
    for gp in meta.gearPairs:
        if gp.gearA not in body_names or gp.gearB not in body_names:
            raise ValueError(f"GearPair {gp.name} refers missing gear body: {gp.gearA}, {gp.gearB}")

        gearA_def = next((b for b in meta.bodies if b.name == gp.gearA), None)
        gearB_def = next((b for b in meta.bodies if b.name == gp.gearB), None)
        if gearA_def is None or gearB_def is None:
            continue

        # [ADD] docs 규칙: gearPair가 참조하는 바디는 category="gear" 여야 함
        if gearA_def.category != "gear" or gearB_def.category != "gear":
            raise ValueError(f"GearPair {gp.name}: gearA/gearB must have category='gear'")

        if gearA_def.mechanical.gearProps is None or gearB_def.mechanical.gearProps is None:
            raise ValueError(f"GearPair {gp.name}: gear bodies must have mechanical.gearProps")

    # actuators refer to joints
    for a in meta.actuators:
        if a.targetJoint not in joint_names:
            raise ValueError(f"Actuator {a.name} refers missing joint: {a.targetJoint}")
