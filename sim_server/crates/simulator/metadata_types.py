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
        # allow missing fields with defaults
        pos = d.get("pos", [0.0, 0.0, 0.0])
        rot = d.get("rot", [1.0, 0.0, 0.0, 0.0])
        return Pose(pos=Vec3.from_any(pos), rot=Quat.from_any(rot))


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
        scale = d.get("scale", [1, 1, 1])
        offset = d.get("offset", {"pos": [0, 0, 0], "rot": [1, 0, 0, 0]})
        return VisualMesh(
            kind="mesh",
            file=str(d["file"]),
            scale=Vec3.from_any(scale),
            offset=Pose.from_dict(offset),
        )


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
            return CollisionPrimitive(
                kind="box",
                offset=offset,
                hx=float(d["hx"]),
                hy=float(d["hy"]),
                hz=float(d["hz"]),
            )

        if kind == "cylinder":
            return CollisionPrimitive(
                kind="cylinder",
                offset=offset,
                radius=float(d["radius"]),
                length=float(d["length"]),
            )

        # sphere
        return CollisionPrimitive(
            kind="sphere",
            offset=offset,
            radius=float(d["radius"]),
        )


CollisionStrategy = Literal["default", "base_aabb", "shaft_pca_hub2cyl", "aabb_box"]
_ALLOWED_COLLISION_STRATEGIES = {"default", "base_aabb", "shaft_pca_hub2cyl", "aabb_box"}

@dataclass(frozen=True)
class CollisionAuto:
    """
    collision auto-approx (OPT-IN).

    허용 입력 형태:
    - "auto"
    - {"kind":"auto", "strategy":"default"}

    NOTE:
    - 실제 OBJ 추정은 builder/runtime 옵션에서 허용될 때만 수행 (스키마는 의도만 표현)
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

            return CollisionAuto(strategy=strategy)  # type: ignore[arg-type]

        raise ValueError(f"collision auto must be 'auto' or object, got: {type(v)}")


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
            # opt-in 원칙을 강제: omission은 허용하지 않음
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
        mode = d.get("mode", "explicit")
        if mode not in ("explicit", "auto_from_collision"):
            raise ValueError(f"inertia.mode must be explicit|auto_from_collision, got: {mode}")

        if mode == "explicit":
            return Inertia(
                mode="explicit",
                Ixx=float(d["Ixx"]),
                Iyy=float(d["Iyy"]),
                Izz=float(d["Izz"]),
            )
        return Inertia(mode="auto_from_collision")


@dataclass(frozen=True)
class Contact:
    friction: float
    restitution: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Contact":
        return Contact(
            friction=float(d.get("friction", 0.4)),
            restitution=float(d.get("restitution", 0.05)),
        )


DampingType = Literal["viscous_torque"]

@dataclass(frozen=True)
class Damping:
    type: DampingType
    coef: float
    # viscous_torque: tau = -coef * omega (coef unit: N·m·s/rad)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Damping":
        dtype = d.get("type", "viscous_torque")
        if dtype != "viscous_torque":
            raise ValueError(f"damping.type currently supports only viscous_torque, got: {dtype}")
        return Damping(type="viscous_torque", coef=float(d.get("coef", 0.0)))


@dataclass(frozen=True)
class GearProps:
    # module in meter (e.g., 2 mm -> 0.002)
    module: float
    teeth: int
    face_width: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearProps":
        return GearProps(
            module=float(d["module"]),
            teeth=int(d["teeth"]),
            face_width=float(d.get("face_width", 0.0)),
        )


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
        return Mechanical(
            mass=float(d.get("mass", 1.0)),
            fixed=bool(d.get("fixed", False)),
            inertia=Inertia.from_dict(d.get("inertia", {"mode": "explicit", "Ixx": 0, "Iyy": 0, "Izz": 0})),
            contact=Contact.from_dict(d.get("contact", {})),
            damping=Damping.from_dict(d["damping"]) if "damping" in d else None,
            gearProps=GearProps.from_dict(d["gearProps"]) if "gearProps" in d else None,
        )


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
        return JointLimits(lower=float(d["lower"]), upper=float(d["upper"]))


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
        jtype = d.get("type")
        if jtype not in ("revolute", "prismatic", "fixed"):
            raise ValueError(f"joint.type must be revolute|prismatic|fixed, got: {jtype}")

        return JointDef(
            name=str(d["name"]),
            type=jtype,  # type: ignore
            body1=str(d["body1"]),
            body2=str(d["body2"]),
            frame=Pose.from_dict(d["frame"]),
            limits=JointLimits.from_dict(d["limits"]) if "limits" in d else None,
        )


# =========================
# GearPairs
# =========================

@dataclass(frozen=True)
class GearPairProps:
    efficiency: float = 1.0
    backlash: float = 0.0

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearPairProps":
        return GearPairProps(
            efficiency=float(d.get("efficiency", 1.0)),
            backlash=float(d.get("backlash", 0.0)),
        )


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
        return GearPairDef(
            name=str(d["name"]),
            gearA=str(d["gearA"]),
            gearB=str(d["gearB"]),
            ratio_sign=int(d.get("ratio_sign", -1)),
            enforcePhase=bool(d.get("enforcePhase", False)),
            meshFrame=Pose.from_dict(d["meshFrame"]) if "meshFrame" in d else None,
            gearProps=GearPairProps.from_dict(d["gearProps"]) if "gearProps" in d else None,
        )


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
        if d.get("type") != "const":
            raise ValueError(f"torqueModel.type currently supports only 'const', got: {d.get('type')}")
        return TorqueModelConst(type="const", value=float(d["value"]))


TorqueModel = Union[TorqueModelConst]


@dataclass(frozen=True)
class ActuatorDef:
    name: str
    type: ActuatorType
    targetJoint: str
    # speed actuator
    speed: Optional[float] = None
    # torque actuator
    torqueModel: Optional[TorqueModel] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ActuatorDef":
        atype = d.get("type")
        if atype not in ("rotation_speed", "rotation_torque"):
            raise ValueError(f"actuator.type must be rotation_speed|rotation_torque, got: {atype}")

        if atype == "rotation_speed":
            return ActuatorDef(
                name=str(d["name"]),
                type="rotation_speed",
                targetJoint=str(d["targetJoint"]),
                speed=float(d["speed"]),
            )

        return ActuatorDef(
            name=str(d["name"]),
            type="rotation_torque",
            targetJoint=str(d["targetJoint"]),
            torqueModel=TorqueModelConst.from_dict(d["torqueModel"]),
        )


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
        return SceneMeta(
            sceneName=str(d.get("sceneName", "unnamed_scene")),
            gravity=Vec3.from_any(d.get("gravity", [0.0, -9.81, 0.0])),
            bodies=[BodyDef.from_dict(x) for x in d.get("bodies", [])],
            joints=[JointDef.from_dict(x) for x in d.get("joints", [])],
            gearPairs=[GearPairDef.from_dict(x) for x in d.get("gearPairs", [])],
            actuators=[ActuatorDef.from_dict(x) for x in d.get("actuators", [])],
        )

    @staticmethod
    def from_json_str(json_str: str) -> "SceneMeta":
        return SceneMeta.from_dict(json.loads(json_str))

    @staticmethod
    def from_json_file(path: str, encoding: str = "utf-8") -> "SceneMeta":
        with open(path, "r", encoding=encoding) as f:
            return SceneMeta.from_dict(json.load(f))


# =========================
# Minimal validation helpers (optional)
# =========================

def validate_scene(meta: SceneMeta) -> None:
    """기본적인 참조 무결성 검증. (필요 시 확장)"""

    # ---- uniqueness checks (schema design rule) ----
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
        if gearA_def.mechanical.gearProps is None or gearB_def.mechanical.gearProps is None:
            raise ValueError(f"GearPair {gp.name}: gear bodies must have mechanical.gearProps")

    # actuators refer to joints
    for a in meta.actuators:
        if a.targetJoint not in joint_names:
            raise ValueError(f"Actuator {a.name} refers missing joint: {a.targetJoint}")
