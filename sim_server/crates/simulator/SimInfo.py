# SimInfo.py
# -----------------------------------------------------------------------------
# Simulation Metadata -> Typed (dataclass) representation
# Target: Project Chrono / PyChrono 8.0.0
#
# - 엔진(Chrono) 객체를 만들지는 않는다. (builder가 담당)
# - "메타데이터에 없는 정보를 엔진이 추론하지 않는다" 원칙을 따른다.
# - 다만, builder에서 debug 옵션으로 auto-approx(OBJ 추정) 등을 켤 수 있게,
#   SimInfo에는 그 "정책 옵션"만 담는다.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple
from simulator.metadata_types import SceneMeta, BodyDef, JointDef, GearPairDef, ActuatorDef

# =============================================================================
# 0) Core JSON math types
# =============================================================================

Vec3 = Tuple[float, float, float]          # (x, y, z)  [meter]
Quat = Tuple[float, float, float, float]   # (w, x, y, z)

DEFAULT_GRAVITY: Vec3 = (0.0, -9.81, 0.0)
QUNIT: Quat = (1.0, 0.0, 0.0, 0.0)


def _as_vec3(v: Any, *, name: str) -> Vec3:
    if isinstance(v, (list, tuple)) and len(v) == 3:
        return (float(v[0]), float(v[1]), float(v[2]))
    raise ValueError(f"{name} must be a length-3 array like [x,y,z]. got={v!r}")


def _as_quat(v: Any, *, name: str) -> Quat:
    if isinstance(v, (list, tuple)) and len(v) == 4:
        return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
    raise ValueError(f"{name} must be a length-4 array like [w,x,y,z]. got={v!r}")


@dataclass(frozen=True)
class Pose:
    """World pose. Units: meter / quaternion(w,x,y,z)."""
    pos: Vec3 = (0.0, 0.0, 0.0)
    rot: Quat = QUNIT

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> "Pose":
        if not d:
            return Pose()
        return Pose(
            pos=_as_vec3(d.get("pos", (0.0, 0.0, 0.0)), name="pose.pos"),
            rot=_as_quat(d.get("rot", QUNIT), name="pose.rot"),
        )


# =============================================================================
# 1) Geometry (visual / collision)
# =============================================================================

VisualKind = Literal["mesh"]
CollisionKind = Literal["box", "cylinder", "sphere"]


@dataclass(frozen=True)
class VisualOffset:
    """
    Visual-only offset in BODY-LOCAL coordinates.
    (OBJ 원점/축 보정용)
    """
    pos: Vec3 = (0.0, 0.0, 0.0)
    rot: Quat = QUNIT

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> "VisualOffset":
        if not d:
            return VisualOffset()
        return VisualOffset(
            pos=_as_vec3(d.get("pos", (0.0, 0.0, 0.0)), name="visual.offset.pos"),
            rot=_as_quat(d.get("rot", QUNIT), name="visual.offset.rot"),
        )


@dataclass(frozen=True)
class VisualGeometry:
    kind: VisualKind = "mesh"
    file: str = ""  # e.g. "gear_A_scaled.obj"
    scale: Vec3 = (1.0, 1.0, 1.0)
    offset: VisualOffset = field(default_factory=VisualOffset)

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["VisualGeometry"]:
        if not d:
            return None
        kind = d.get("kind", "mesh")
        if kind != "mesh":
            raise ValueError(f"visual.kind must be 'mesh'. got={kind!r}")
        return VisualGeometry(
            kind="mesh",
            file=str(d.get("file", "")),
            scale=_as_vec3(d.get("scale", (1.0, 1.0, 1.0)), name="visual.scale"),
            offset=VisualOffset.from_dict(d.get("offset")),
        )


@dataclass(frozen=True)
class CollisionGeometry:
    """
    Collision geometry is for physics; recommended primitives for performance.
    - box: provide (sx,sy,sz) full-size OR (hx,hy,hz) half-size
    - cylinder: provide radius + length + axis (BODY-LOCAL)
    - sphere: provide radius
    """
    kind: CollisionKind

    # box
    sx: Optional[float] = None
    sy: Optional[float] = None
    sz: Optional[float] = None
    hx: Optional[float] = None
    hy: Optional[float] = None
    hz: Optional[float] = None

    # cylinder / sphere
    radius: Optional[float] = None
    length: Optional[float] = None
    axis: Optional[Vec3] = None  # BODY-LOCAL axis for cylinder (default z)

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["CollisionGeometry"]:
        if not d:
            return None
        kind = d.get("kind")
        if kind not in ("box", "cylinder", "sphere"):
            raise ValueError(f"collision.kind must be box/cylinder/sphere. got={kind!r}")

        if kind == "box":
            return CollisionGeometry(
                kind="box",
                sx=d.get("sx"),
                sy=d.get("sy"),
                sz=d.get("sz"),
                hx=d.get("hx"),
                hy=d.get("hy"),
                hz=d.get("hz"),
            )

        if kind == "sphere":
            return CollisionGeometry(kind="sphere", radius=float(d.get("radius", 0.01)))

        # cylinder
        axis = d.get("axis", (0.0, 0.0, 1.0))
        return CollisionGeometry(
            kind="cylinder",
            radius=float(d.get("radius", 0.01)),
            length=float(d.get("length", 0.1)),
            axis=_as_vec3(axis, name="collision.axis"),
        )


@dataclass(frozen=True)
class GeometrySpec:
    visual: Optional[VisualGeometry] = None
    collision: Optional[CollisionGeometry] = None

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> "GeometrySpec":
        if not d:
            return GeometrySpec()
        return GeometrySpec(
            visual=VisualGeometry.from_dict(d.get("visual")),
            collision=CollisionGeometry.from_dict(d.get("collision")),
        )


# =============================================================================
# 2) Mechanical properties
# =============================================================================

InertiaMode = Literal["explicit", "auto_from_collision"]
DampingType = Literal["viscous_torque"]
BodyCategory = Literal["base", "shaft", "gear", "unknown"]


@dataclass(frozen=True)
class InertiaSpec:
    mode: InertiaMode = "explicit"
    Ixx: float = 1e-3
    Iyy: float = 1e-3
    Izz: float = 1e-3

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["InertiaSpec"]:
        if d is None:
            return None
        mode = d.get("mode", "explicit")
        if mode not in ("explicit", "auto_from_collision"):
            raise ValueError(f"inertia.mode must be explicit/auto_from_collision. got={mode!r}")
        return InertiaSpec(
            mode=mode,
            Ixx=float(d.get("Ixx", 1e-3)),
            Iyy=float(d.get("Iyy", 1e-3)),
            Izz=float(d.get("Izz", 1e-3)),
        )


@dataclass(frozen=True)
class ContactSpec:
    friction: float = 0.4
    restitution: float = 0.05

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["ContactSpec"]:
        if d is None:
            return None
        return ContactSpec(
            friction=float(d.get("friction", 0.4)),
            restitution=float(d.get("restitution", 0.05)),
        )


@dataclass(frozen=True)
class DampingSpec:
    type: DampingType = "viscous_torque"
    coef: float = 0.0

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["DampingSpec"]:
        if d is None:
            return None
        dtype = d.get("type", "viscous_torque")
        if dtype != "viscous_torque":
            raise ValueError(f"damping.type currently supports only 'viscous_torque'. got={dtype!r}")
        return DampingSpec(type="viscous_torque", coef=float(d.get("coef", 0.0)))


@dataclass(frozen=True)
class GearProps:
    """
    module in meter. e.g. 2mm => 0.002
    pitch_radius = (module * teeth) / 2
    """
    module: float
    teeth: int
    face_width: float = 0.0

    @property
    def pitch_radius(self) -> float:
        return 0.5 * float(self.module) * int(self.teeth)

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["GearProps"]:
        if d is None:
            return None
        return GearProps(
            module=float(d.get("module", 0.0)),
            teeth=int(d.get("teeth", 0)),
            face_width=float(d.get("face_width", 0.0)),
        )


@dataclass(frozen=True)
class MechanicalSpec:
    mass: float = 1.0
    fixed: bool = False
    inertia: Optional[InertiaSpec] = None
    contact: Optional[ContactSpec] = None
    damping: Optional[DampingSpec] = None
    gearProps: Optional[GearProps] = None

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> "MechanicalSpec":
        if not d:
            return MechanicalSpec()
        return MechanicalSpec(
            mass=float(d.get("mass", 1.0)),
            fixed=bool(d.get("fixed", False)),
            inertia=InertiaSpec.from_dict(d.get("inertia")),
            contact=ContactSpec.from_dict(d.get("contact")),
            damping=DampingSpec.from_dict(d.get("damping")),
            gearProps=GearProps.from_dict(d.get("gearProps")),
        )


# =============================================================================
# 3) Scene elements: bodies / joints / gearPairs / actuators
# =============================================================================

@dataclass(frozen=True)
class BodyDef:
    name: str
    category: BodyCategory = "unknown"
    geometry: GeometrySpec = field(default_factory=GeometrySpec)
    mechanical: MechanicalSpec = field(default_factory=MechanicalSpec)
    pose: Pose = field(default_factory=Pose)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "BodyDef":
        if "name" not in d:
            raise ValueError("body missing required field: name")
        category = d.get("category", "unknown")
        if category not in ("base", "shaft", "gear", "unknown"):
            category = "unknown"  # 느슨하게 허용(팀 확장 대비)
        return BodyDef(
            name=str(d["name"]),
            category=category,  # type: ignore
            geometry=GeometrySpec.from_dict(d.get("geometry")),
            mechanical=MechanicalSpec.from_dict(d.get("mechanical")),
            pose=Pose.from_dict(d.get("pose")),
        )


JointType = Literal["revolute", "prismatic", "fixed"]


@dataclass(frozen=True)
class JointLimits:
    lower: float
    upper: float

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["JointLimits"]:
        if d is None:
            return None
        return JointLimits(lower=float(d.get("lower", 0.0)), upper=float(d.get("upper", 0.0)))


@dataclass(frozen=True)
class JointDef:
    name: str
    type: JointType
    body1: str
    body2: str
    frame: Pose  # world frame; local Z axis is DOF axis
    limits: Optional[JointLimits] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JointDef":
        for k in ("name", "type", "body1", "body2"):
            if k not in d:
                raise ValueError(f"joint missing required field: {k}")

        jtype = d["type"]
        if jtype not in ("revolute", "prismatic", "fixed"):
            raise ValueError(f"joint.type must be revolute/prismatic/fixed. got={jtype!r}")

        return JointDef(
            name=str(d["name"]),
            type=jtype,  # type: ignore
            body1=str(d["body1"]),
            body2=str(d["body2"]),
            frame=Pose.from_dict(d.get("frame")),
            limits=JointLimits.from_dict(d.get("limits")),
        )


@dataclass(frozen=True)
class GearPairProps:
    efficiency: float = 1.0
    backlash: float = 0.0

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["GearPairProps"]:
        if d is None:
            return None
        return GearPairProps(
            efficiency=float(d.get("efficiency", 1.0)),
            backlash=float(d.get("backlash", 0.0)),
        )


@dataclass(frozen=True)
class GearPairDef:
    name: str
    gearA: str
    gearB: str
    ratio_sign: int = -1            # -1 external, +1 internal
    enforcePhase: bool = False
    meshFrame: Optional[Pose] = None
    gearProps: Optional[GearPairProps] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearPairDef":
        for k in ("name", "gearA", "gearB"):
            if k not in d:
                raise ValueError(f"gearPair missing required field: {k}")
        rs = int(d.get("ratio_sign", -1))
        if rs not in (-1, 1):
            raise ValueError("gearPair.ratio_sign must be -1 or +1")
        return GearPairDef(
            name=str(d["name"]),
            gearA=str(d["gearA"]),
            gearB=str(d["gearB"]),
            ratio_sign=rs,
            enforcePhase=bool(d.get("enforcePhase", False)),
            meshFrame=Pose.from_dict(d.get("meshFrame")) if d.get("meshFrame") else None,
            gearProps=GearPairProps.from_dict(d.get("gearProps")),
        )


ActuatorType = Literal["rotation_speed", "rotation_torque"]


@dataclass(frozen=True)
class TorqueModel:
    type: Literal["const"] = "const"
    value: float = 0.0  # N*m

    @staticmethod
    def from_dict(d: Optional[Dict[str, Any]]) -> Optional["TorqueModel"]:
        if d is None:
            return None
        t = d.get("type", "const")
        if t != "const":
            raise ValueError(f"torqueModel.type currently supports only 'const'. got={t!r}")
        return TorqueModel(type="const", value=float(d.get("value", 0.0)))


@dataclass(frozen=True)
class ActuatorDef:
    name: str
    type: ActuatorType
    targetJoint: str
    speed: Optional[float] = None          # rad/s (rotation_speed)
    torqueModel: Optional[TorqueModel] = None  # (rotation_torque)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ActuatorDef":
        for k in ("name", "type", "targetJoint"):
            if k not in d:
                raise ValueError(f"actuator missing required field: {k}")

        at = d["type"]
        if at not in ("rotation_speed", "rotation_torque"):
            raise ValueError(f"actuator.type must be rotation_speed/rotation_torque. got={at!r}")

        if at == "rotation_speed":
            if "speed" not in d:
                raise ValueError("rotation_speed actuator requires 'speed'")
            return ActuatorDef(
                name=str(d["name"]),
                type="rotation_speed",
                targetJoint=str(d["targetJoint"]),
                speed=float(d["speed"]),
            )

        # rotation_torque
        tm = TorqueModel.from_dict(d.get("torqueModel"))
        if tm is None:
            raise ValueError("rotation_torque actuator requires 'torqueModel'")
        return ActuatorDef(
            name=str(d["name"]),
            type="rotation_torque",
            targetJoint=str(d["targetJoint"]),
            torqueModel=tm,
        )


# =============================================================================
# 4) SimInfo (top-level)
# =============================================================================

@dataclass
class SimOptions:
    """
    엔진 빌드/런타임 정책. (메타데이터가 아닌 '운영 옵션')
    - allow_obj_auto_approx: collision이 비었을 때 OBJ로 근사 허용(디버그)
    - strict_no_inference: 메타에 없는 정보는 절대 추론하지 않음(프로덕션)
    """
    dt: float = 1e-3
    allow_obj_auto_approx: bool = False
    strict_no_inference: bool = True


@dataclass
class SimInfo:
    """
    엔진 독립적인 '시뮬레이션 정의(계약)'.
    builder가 이 정보를 받아 Chrono 시스템을 구성한다.
    """
    sceneName: str = "unnamed_scene"
    gravity: Vec3 = DEFAULT_GRAVITY

    bodies: List[BodyDef] = field(default_factory=list)
    joints: List[JointDef] = field(default_factory=list)
    gearPairs: List[GearPairDef] = field(default_factory=list)
    actuators: List[ActuatorDef] = field(default_factory=list)

    options: SimOptions = field(default_factory=SimOptions)

    # --- Derived mappings (server/AR integration) ---
    part_name_to_index: Dict[str, int] = field(init=False, default_factory=dict)
    part_index_to_name: List[str] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._rebuild_part_index()

    # -------------------------
    # Constructors
    # -------------------------
    @staticmethod
    def from_dict(meta: Dict[str, Any], *, options: Optional[SimOptions] = None) -> "SimInfo":
        if not isinstance(meta, dict):
            raise ValueError("SimInfo.from_dict expects a dict")

        info = SimInfo(
            sceneName=str(meta.get("sceneName", "unnamed_scene")),
            gravity=_as_vec3(meta.get("gravity", DEFAULT_GRAVITY), name="gravity"),
            bodies=[BodyDef.from_dict(b) for b in meta.get("bodies", [])],
            joints=[JointDef.from_dict(j) for j in meta.get("joints", [])],
            gearPairs=[GearPairDef.from_dict(g) for g in meta.get("gearPairs", [])],
            actuators=[ActuatorDef.from_dict(a) for a in meta.get("actuators", [])],
            options=options or SimOptions(),
        )
        info.validate()  # early fail
        return info

    @staticmethod
    def from_json_string(s: str, *, options: Optional[SimOptions] = None) -> "SimInfo":
        meta = json.loads(s)
        return SimInfo.from_dict(meta, options=options)

    @staticmethod
    def from_json_file(path: str, *, options: Optional[SimOptions] = None) -> "SimInfo":
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return SimInfo.from_dict(meta, options=options)

    # -------------------------
    # Derived mappings
    # -------------------------
    def _rebuild_part_index(self) -> None:
        self.part_index_to_name = [b.name for b in self.bodies]
        self.part_name_to_index = {name: i for i, name in enumerate(self.part_index_to_name)}

    # -------------------------
    # Validation
    # -------------------------
    def validate(self) -> None:
        """
        - name uniqueness
        - reference integrity
        - minimal semantic checks (gear category, required props, etc.)
        """
        # body name unique
        bnames = [b.name for b in self.bodies]
        if len(set(bnames)) != len(bnames):
            dup = _find_dups(bnames)
            raise ValueError(f"Duplicate body names: {dup}")

        self._rebuild_part_index()

        body_set = set(bnames)

        # joints reference check
        jnames = [j.name for j in self.joints]
        if len(set(jnames)) != len(jnames):
            dup = _find_dups(jnames)
            raise ValueError(f"Duplicate joint names: {dup}")

        for j in self.joints:
            if j.body1 not in body_set:
                raise ValueError(f"Joint '{j.name}' references missing body1='{j.body1}'")
            if j.body2 not in body_set:
                raise ValueError(f"Joint '{j.name}' references missing body2='{j.body2}'")

        # actuators reference check
        anames = [a.name for a in self.actuators]
        if len(set(anames)) != len(anames):
            dup = _find_dups(anames)
            raise ValueError(f"Duplicate actuator names: {dup}")

        joint_set = set(jnames)
        for a in self.actuators:
            if a.targetJoint not in joint_set:
                raise ValueError(f"Actuator '{a.name}' references missing targetJoint='{a.targetJoint}'")

        # gearPairs reference check + gearProps check
        gnames = [g.name for g in self.gearPairs]
        if len(set(gnames)) != len(gnames):
            dup = _find_dups(gnames)
            raise ValueError(f"Duplicate gearPair names: {dup}")

        body_by_name = {b.name: b for b in self.bodies}
        for gp in self.gearPairs:
            if gp.gearA not in body_set or gp.gearB not in body_set:
                raise ValueError(f"GearPair '{gp.name}' references missing gear body")
            bA = body_by_name[gp.gearA]
            bB = body_by_name[gp.gearB]
            if bA.category != "gear" or bB.category != "gear":
                raise ValueError(
                    f"GearPair '{gp.name}' requires both bodies category='gear'. "
                    f"got A={bA.category}, B={bB.category}"
                )
            if bA.mechanical.gearProps is None or bB.mechanical.gearProps is None:
                raise ValueError(
                    f"GearPair '{gp.name}' requires gearProps on both gears "
                    f"(module/teeth). missing on A or B."
                )
            if bA.mechanical.gearProps.teeth <= 0 or bB.mechanical.gearProps.teeth <= 0:
                raise ValueError(f"GearPair '{gp.name}' gear teeth must be > 0")
            if bA.mechanical.gearProps.module <= 0 or bB.mechanical.gearProps.module <= 0:
                raise ValueError(f"GearPair '{gp.name}' gear module must be > 0 (meter)")

        # inertia explicit requires Ixx/Iyy/Izz positive-ish
        for b in self.bodies:
            ins = b.mechanical.inertia
            if ins and ins.mode == "explicit":
                if ins.Ixx <= 0 or ins.Iyy <= 0 or ins.Izz <= 0:
                    raise ValueError(f"Body '{b.name}' inertia must be positive for explicit mode")

        # dt sanity
        if self.options.dt <= 0:
            raise ValueError("options.dt must be > 0")


def _find_dups(items: List[str]) -> List[str]:
    seen = set()
    dups = set()
    for x in items:
        if x in seen:
            dups.add(x)
        seen.add(x)
    return sorted(list(dups))
