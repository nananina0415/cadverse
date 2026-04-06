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
#
# [UPDATED: 1-2 Collision Filtering]
# - SceneMeta에 collisionFilter(운영 정책) 추가
#   - ignoreJoints: joint로 직접 연결된 두 body 사이 collision disable (기본 True 권장)
#   - ignoreGearPairs: gearPair로 묶인 두 gear 사이 collision disable (기본 True 권장)
#   - ignorePairs: 명시적으로 충돌을 끌 pair 목록 (["a","b"] or {"a":"...","b":"..."} 형태 지원)
#   - (선택) onlyPairs: 허용할 pair만 지정 (이 모드가 있으면 나머지는 전부 ignore로 간주)
#
# [UPDATED: 2-1.1 Auto Inertia From Collision]
# - mechanical.inertia.mode = "auto_from_collision" 허용
# - (선택) inertia.auto 옵션 추가 (min_inertia, scale, use_rotation, fallback_diagonal)
#
# [UPDATED: 2-2.1 Advanced Contact options]
# - mechanical.contact rolling/spinning/compliance/damping/stick_slip 옵션 허용
# - 바인딩/접촉모델(NSC/SMC)에서 지원 안 하면 sim_builder에서 "무시"하는 설계를 전제로 함
#
# [UPDATED: 2-3.1 Joint Limits schema]
# - joints.limits 기본형 추가: { enable, lower, upper }
#   - revolute: rad, prismatic: m (단위는 사용처에서 해석)
#   - lower/upper는 optional (한쪽만 있어도 됨)

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

        # offset은 pos/rot 부분 생략이 가능해야 함
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
            return CollisionAuto(strategy=strategy)

        raise ValueError(f"collision auto must be 'auto' or object, got: {type(v)}")

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "auto", "strategy": str(self.strategy)}


# collision can be:
# - single primitive object
# - list of primitive objects
# - auto directive
# - none/null directive
CollisionSpec = Optional[Union[CollisionPrimitive, List[CollisionPrimitive], CollisionAuto]]


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

        # (0) none / null
        if col_raw is None or col_raw == "none":
            collision: CollisionSpec = None
            return Geometry(visual=visual, collision=collision)

        # (3) auto
        if col_raw == "auto" or (isinstance(col_raw, dict) and col_raw.get("kind") == "auto"):
            collision = CollisionAuto.from_any(col_raw)
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

        raise ValueError(
            f"geometry.collision must be object | list | 'auto' | 'none' | null, got: {type(col_raw)}"
        )

    def to_dict(self) -> Dict[str, Any]:
        if self.collision is None:
            col = None
        elif isinstance(self.collision, list):
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
class AutoInertiaFromCollision:
    """
    auto_from_collision 관성 자동추정 옵션(선택).

    - min_inertia: 각 축(Ixx/Iyy/Izz) 최소값(절대값). 너무 작으면 solver 불안정해질 수 있어 클램프용.
    - scale: 계산된 inertia에 곱할 스케일(튜닝용).
    - use_rotation: primitive.offset.rot 을 inertia 회전에 반영할지 여부.
      v1 권장: False (대각 유지/보수적)
    - fallback_diagonal: 계산 실패 시 대체 대각 성분 계수(질량에 비례).
      예) I = fallback_diagonal * mass
    """
    min_inertia: float = 0.0
    scale: float = 1.0
    use_rotation: bool = False
    fallback_diagonal: float = 1e-3

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AutoInertiaFromCollision":
        if not isinstance(d, dict):
            raise ValueError(f"inertia.auto must be object, got: {type(d)}")
        return AutoInertiaFromCollision(
            min_inertia=float(d.get("min_inertia", 0.0)),
            scale=float(d.get("scale", 1.0)),
            use_rotation=bool(d.get("use_rotation", False)),
            fallback_diagonal=float(d.get("fallback_diagonal", 1e-3)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_inertia": float(self.min_inertia),
            "scale": float(self.scale),
            "use_rotation": bool(self.use_rotation),
            "fallback_diagonal": float(self.fallback_diagonal),
        }


@dataclass(frozen=True)
class Inertia:
    mode: InertiaMode
    Ixx: Optional[float] = None
    Iyy: Optional[float] = None
    Izz: Optional[float] = None

    # ✅ NEW (only for auto_from_collision)
    auto: Optional[AutoInertiaFromCollision] = None

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
                auto=None,
            )

        auto_cfg = d.get("auto", None)
        auto = AutoInertiaFromCollision.from_dict(auto_cfg) if isinstance(auto_cfg, dict) else None
        return Inertia(mode="auto_from_collision", auto=auto)

    def to_dict(self) -> Dict[str, Any]:
        if self.mode == "explicit":
            return {
                "mode": "explicit",
                "Ixx": float(self.Ixx or 0.0),
                "Iyy": float(self.Iyy or 0.0),
                "Izz": float(self.Izz or 0.0),
            }

        out: Dict[str, Any] = {"mode": "auto_from_collision"}
        if self.auto is not None:
            out["auto"] = self.auto.to_dict()
        return out


# =========================
# Mechanical / Contact extras (NEW: 2-2.1)
# =========================

@dataclass(frozen=True)
class StickSlipDef:
    """
    Stick-slip 완화용 교육용 가드레일 옵션.
    - enabled: False면 무시
    - static_friction_scale: 정지 마찰 계수 스케일 (mu_s = mu * scale)
    - min_slip_speed: slip speed 임계값(근사 스무딩에 활용)
    - vel_smooth: 추가 스무딩/감쇠 계수 (0~0.2 권장)
    """
    enabled: bool = True
    static_friction_scale: float = 1.0
    min_slip_speed: float = 0.01
    vel_smooth: float = 0.0

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "StickSlipDef":
        if not isinstance(d, dict):
            raise ValueError(f"stick_slip must be object, got: {type(d)}")

        enabled = bool(d.get("enabled", True))
        sfs = float(d.get("static_friction_scale", 1.0))
        mss = float(d.get("min_slip_speed", 0.01))
        vs = float(d.get("vel_smooth", 0.0))

        # 가드레일(너무 공격적이면 solver 흔들림)
        sfs = max(0.0, min(2.0, sfs))
        mss = max(0.0, mss)
        vs = max(0.0, min(0.2, vs))

        return StickSlipDef(
            enabled=enabled,
            static_friction_scale=sfs,
            min_slip_speed=mss,
            vel_smooth=vs,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "static_friction_scale": float(self.static_friction_scale),
            "min_slip_speed": float(self.min_slip_speed),
            "vel_smooth": float(self.vel_smooth),
        }


@dataclass(frozen=True)
class Contact:
    # 기존 유지
    friction: float
    restitution: float

    # NEW(옵션) - 지원 안 되면 sim_builder에서 무시 가능
    rolling_friction: Optional[float] = None
    spinning_friction: Optional[float] = None
    compliance: Optional[float] = None   # 주로 SMC에서 의미
    damping: Optional[float] = None      # 주로 SMC에서 의미

    # NEW(옵션) - stick-slip 완화
    stick_slip: Optional[StickSlipDef] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Contact":
        if not isinstance(d, dict):
            raise ValueError(f"contact must be object, got: {type(d)}")

        mu = float(d.get("friction", 0.4))
        e = float(d.get("restitution", 0.05))

        # (선택) 고급 마찰/재질 파라미터
        rf = d.get("rolling_friction", None)
        sf = d.get("spinning_friction", None)
        comp = d.get("compliance", None)
        damp = d.get("damping", None)

        # (선택) stick-slip 완화
        ss_raw = d.get("stick_slip", None)
        ss = StickSlipDef.from_dict(ss_raw) if isinstance(ss_raw, dict) else None

        # 가드레일(음수 방지)
        if rf is not None:
            rf = max(0.0, float(rf))
        if sf is not None:
            sf = max(0.0, float(sf))
        if comp is not None:
            comp = max(0.0, float(comp))
        if damp is not None:
            damp = max(0.0, float(damp))

        return Contact(
            friction=max(0.0, mu),
            restitution=max(0.0, min(1.0, e)),
            rolling_friction=rf,
            spinning_friction=sf,
            compliance=comp,
            damping=damp,
            stick_slip=ss,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "friction": float(self.friction),
            "restitution": float(self.restitution),
        }
        if self.rolling_friction is not None:
            out["rolling_friction"] = float(self.rolling_friction)
        if self.spinning_friction is not None:
            out["spinning_friction"] = float(self.spinning_friction)
        if self.compliance is not None:
            out["compliance"] = float(self.compliance)
        if self.damping is not None:
            out["damping"] = float(self.damping)
        if self.stick_slip is not None:
            out["stick_slip"] = self.stick_slip.to_dict()
        return out


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
    # ✅ UPDATED (2-3.1): 기본형 { enable, lower, upper }
    enable: bool = True
    lower: Optional[float] = None
    upper: Optional[float] = None

    # ✅ NEW (2-3.3): hard stop 옵션 (가능한 경우 Chrono에 best-effort 적용)
    stop_restitution: Optional[float] = None
    stop_damping: Optional[float] = None

    # ✅ NEW (2-3.4): soft limit (spring/damper) 옵션 (가능한 경우 Chrono에 best-effort 적용)
    spring_k: Optional[float] = None
    damper_c: Optional[float] = None
    spring_equilibrium: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JointLimits":
        if not isinstance(d, dict):
            raise ValueError(f"limits must be object, got: {type(d)}")

        enable = bool(d.get("enable", True))

        lower_raw = d.get("lower", None)
        upper_raw = d.get("upper", None)

        lower = float(lower_raw) if lower_raw is not None else None
        upper = float(upper_raw) if upper_raw is not None else None

        # ✅ NEW fields
        sr_raw = d.get("stop_restitution", None)
        sd_raw = d.get("stop_damping", None)

        sk_raw = d.get("spring_k", None)
        dc_raw = d.get("damper_c", None)
        se_raw = d.get("spring_equilibrium", None)

        stop_restitution = float(sr_raw) if sr_raw is not None else None
        stop_damping = float(sd_raw) if sd_raw is not None else None

        spring_k = float(sk_raw) if sk_raw is not None else None
        damper_c = float(dc_raw) if dc_raw is not None else None
        spring_equilibrium = float(se_raw) if se_raw is not None else None

        # 최소한의 입력 sanity: enable인데 bounds가 둘 다 없으면 실수 가능성이 높음
        if enable and (lower is None) and (upper is None):
            raise ValueError("limits.enable=true requires at least one of 'lower' or 'upper'")

        # ✅ NEW: very small guardrails (schema-level)
        if stop_restitution is not None:
            stop_restitution = max(0.0, min(1.0, float(stop_restitution)))
        if stop_damping is not None:
            stop_damping = max(0.0, float(stop_damping))

        if spring_k is not None:
            spring_k = max(0.0, float(spring_k))
        if damper_c is not None:
            damper_c = max(0.0, float(damper_c))
        # spring_equilibrium: 음수도 물리적으로 가능(중립점), clamp 하지 않음

        return JointLimits(
            enable=enable,
            lower=lower,
            upper=upper,
            stop_restitution=stop_restitution,
            stop_damping=stop_damping,
            spring_k=spring_k,
            damper_c=damper_c,
            spring_equilibrium=spring_equilibrium,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"enable": bool(self.enable)}
        if self.lower is not None:
            out["lower"] = float(self.lower)
        if self.upper is not None:
            out["upper"] = float(self.upper)

        # ✅ NEW
        if self.stop_restitution is not None:
            out["stop_restitution"] = float(self.stop_restitution)
        if self.stop_damping is not None:
            out["stop_damping"] = float(self.stop_damping)

        if self.spring_k is not None:
            out["spring_k"] = float(self.spring_k)
        if self.damper_c is not None:
            out["damper_c"] = float(self.damper_c)
        if self.spring_equilibrium is not None:
            out["spring_equilibrium"] = float(self.spring_equilibrium)

        return out


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
    """
    3-1.1: GearPair 동작 보정용 속성(근사 모델용).

    - enabled: False면 gear pair 보정(효율/백래시/손실토크)을 적용하지 않음 (제약 자체는 유지될 수 있음)
    - efficiency: (0~1] 권장. 전달 효율 (출력 토크 = 입력 토크 * efficiency)
    - backlash: (>=0) 백래시(유격) 크기. 단위는 "각도(rad)"로 해석하는 것을 기본으로 추천.
    - max_torque: (>=0) 손실/보정 적용 시 클램프 상한(옵션)
    """
    enabled: bool = True
    efficiency: float = 1.0
    backlash: float = 0.0
    max_torque: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearPairProps":
        if not isinstance(d, dict):
            raise ValueError(f"gearPair.props must be object, got: {type(d)}")

        enabled = bool(d.get("enabled", True))
        eff = float(d.get("efficiency", 1.0))
        bl = float(d.get("backlash", 0.0))
        mt_raw = d.get("max_torque", None)
        mt = float(mt_raw) if mt_raw is not None else None

        # 기본값/가드레일(clamp)
        # - efficiency는 [0,1] 범위로 클램프(음수/과대 방지)
        # - backlash/max_torque는 음수 방지
        eff = max(0.0, min(1.0, eff))
        bl = max(0.0, bl)
        if mt is not None:
            mt = max(0.0, mt)

        return GearPairProps(
            enabled=enabled,
            efficiency=eff,
            backlash=bl,
            max_torque=mt,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "enabled": bool(self.enabled),
            "efficiency": float(self.efficiency),
            "backlash": float(self.backlash),
        }
        if self.max_torque is not None:
            out["max_torque"] = float(self.max_torque)
        return out


@dataclass(frozen=True)
class GearPairDef:
    name: str
    gearA: str
    gearB: str
    ratio_sign: int = -1
    enforcePhase: bool = False
    meshFrame: Optional[Pose] = None   # NOTE: 의미는 "WORLD frame"

    # 3-1.1: props(신규). (호환성: legacy gearProps도 읽어주되, 저장은 props로)
    props: Optional[GearPairProps] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearPairDef":
        if not isinstance(d, dict):
            raise ValueError(f"gearPair must be object, got: {type(d)}")
        if "name" not in d or "gearA" not in d or "gearB" not in d:
            raise ValueError("gearPair requires name, gearA, gearB")

        props_raw = None
        if "props" in d:
            props_raw = d.get("props", None)
        elif "gearProps" in d:
            # legacy 지원
            props_raw = d.get("gearProps", None)

        return GearPairDef(
            name=str(d["name"]),
            gearA=str(d["gearA"]),
            gearB=str(d["gearB"]),
            ratio_sign=int(d.get("ratio_sign", -1)),
            enforcePhase=bool(d.get("enforcePhase", False)),
            meshFrame=Pose.from_dict(d["meshFrame"]) if "meshFrame" in d else None,
            props=GearPairProps.from_dict(props_raw) if isinstance(props_raw, dict) else None,
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
        if self.props is not None:
            out["props"] = self.props.to_dict()
        return out

# =========================
# Assembly Guides (NEW: 3-2.1)
# =========================

AssemblyGuideMode = Literal["assist", "snap"]
_ALLOWED_ASSEMBLY_GUIDE_MODES = {"assist", "snap"}

AssemblyAlignAxis = Literal["x", "y", "z", "any"]
_ALLOWED_ASSEMBLY_ALIGN_AXES = {"x", "y", "z", "any"}


@dataclass(frozen=True)
class AssemblyGuideDef:
    """
    3-2.1: 조립 시나리오 보조용 메타데이터.

    개념:
    - movingBody 의 movingLocalPose 를
      targetBody 의 targetLocalPose 에 맞춰가도록
      런타임(main.py)에서 "보조힘/보조토크"를 줄 수 있게 하는 선언형 guide.

    필드 의미:
    - name: guide 이름
    - movingBody: 사용자가 움직이는 쪽 body
    - targetBody: 맞춰 들어갈 기준 body
    - movingLocalPose: movingBody 로컬 기준 pose
    - targetLocalPose: targetBody 로컬 기준 pose
    - enabled: 비활성화 가능
    - mode:
        * "assist" = 유도/정렬 보조 위주
        * "snap"   = 나중에 hard snap까지 확장 가능한 모드 표시
      (3-2.1에서는 선언만 하고 실제 차등 적용은 3-2.4에서)
    - positionTolerance: 위치 오차 허용치 (m)
    - angleTolerance: 각도 오차 허용치 (rad)
    - snapStrength: 보조 강도 스칼라 (0 이상)
    - alignAxis:
        * "any" = 전체 회전 정렬
        * "x"/"y"/"z" = 특정 축 정렬 중심
      (실제 해석은 3-2.4 main.py에서)
    """
    name: str
    movingBody: str
    targetBody: str
    movingLocalPose: Pose
    targetLocalPose: Pose

    enabled: bool = True
    mode: AssemblyGuideMode = "assist"

    positionTolerance: float = 0.02
    angleTolerance: float = 0.2617993877991494  # 15 deg
    snapStrength: float = 1.0
    alignAxis: AssemblyAlignAxis = "any"

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AssemblyGuideDef":
        if not isinstance(d, dict):
            raise ValueError(f"assemblyGuide must be object, got: {type(d)}")

        if "name" not in d:
            raise ValueError("assemblyGuide.name is required")
        if "movingBody" not in d:
            raise ValueError(f"assemblyGuide '{d.get('name','?')}' requires movingBody")
        if "targetBody" not in d:
            raise ValueError(f"assemblyGuide '{d.get('name','?')}' requires targetBody")

        moving_local_pose_raw = d.get("movingLocalPose", None)
        target_local_pose_raw = d.get("targetLocalPose", None)

        if moving_local_pose_raw is None:
            raise ValueError(f"assemblyGuide '{d.get('name','?')}' requires movingLocalPose")
        if target_local_pose_raw is None:
            raise ValueError(f"assemblyGuide '{d.get('name','?')}' requires targetLocalPose")

        mode = str(d.get("mode", "assist"))
        if mode not in _ALLOWED_ASSEMBLY_GUIDE_MODES:
            raise ValueError(
                f"assemblyGuide.mode must be one of {sorted(_ALLOWED_ASSEMBLY_GUIDE_MODES)}, got: {mode}"
            )

        align_axis = str(d.get("alignAxis", "any"))
        if align_axis not in _ALLOWED_ASSEMBLY_ALIGN_AXES:
            raise ValueError(
                f"assemblyGuide.alignAxis must be one of {sorted(_ALLOWED_ASSEMBLY_ALIGN_AXES)}, got: {align_axis}"
            )

        position_tolerance = float(d.get("positionTolerance", 0.02))
        angle_tolerance = float(d.get("angleTolerance", 0.2617993877991494))
        snap_strength = float(d.get("snapStrength", 1.0))

        # schema-level guardrails
        position_tolerance = max(0.0, position_tolerance)
        angle_tolerance = max(0.0, angle_tolerance)
        snap_strength = max(0.0, snap_strength)

        return AssemblyGuideDef(
            name=str(d["name"]),
            movingBody=str(d["movingBody"]),
            targetBody=str(d["targetBody"]),
            movingLocalPose=Pose.from_dict(moving_local_pose_raw),
            targetLocalPose=Pose.from_dict(target_local_pose_raw),
            enabled=bool(d.get("enabled", True)),
            mode=mode,  # type: ignore
            positionTolerance=position_tolerance,
            angleTolerance=angle_tolerance,
            snapStrength=snap_strength,
            alignAxis=align_axis,  # type: ignore
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": str(self.name),
            "movingBody": str(self.movingBody),
            "targetBody": str(self.targetBody),
            "movingLocalPose": self.movingLocalPose.to_dict(),
            "targetLocalPose": self.targetLocalPose.to_dict(),
            "enabled": bool(self.enabled),
            "mode": str(self.mode),
            "positionTolerance": float(self.positionTolerance),
            "angleTolerance": float(self.angleTolerance),
            "snapStrength": float(self.snapStrength),
            "alignAxis": str(self.alignAxis),
        }

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
# Collision Filter Policy (NEW: 1-2)
# =========================

@dataclass(frozen=True)
class CollisionPair:
    """
    충돌 필터 pair.
    허용 입력 형태:
      - ["a","b"]
      - {"a":"...","b":"..."}  (alias: bodyA/bodyB도 허용)
    """
    a: str
    b: str

    @staticmethod
    def from_any(v: Any) -> "CollisionPair":
        if isinstance(v, list):
            if len(v) != 2:
                raise ValueError(f"CollisionPair list must be [a,b], got len={len(v)}: {v}")
            return CollisionPair(a=str(v[0]), b=str(v[1]))

        if isinstance(v, dict):
            a = v.get("a", v.get("bodyA", None))
            b = v.get("b", v.get("bodyB", None))
            if a is None or b is None:
                raise ValueError(f"CollisionPair dict must have a/b (or bodyA/bodyB), got keys={list(v.keys())}")
            # ✅ BUGFIX: 잘못된 return (tuple 생성/필드 누락) 수정
            return CollisionPair(a=str(a), b=str(b))

        raise ValueError(f"CollisionPair must be list or dict, got: {type(v)}")

    def normalized(self) -> "CollisionPair":
        # 순서 무관하게 비교/중복 제거를 쉽게 하려고 정렬
        if self.a <= self.b:
            return self
        return CollisionPair(a=self.b, b=self.a)

    def to_list(self) -> List[str]:
        return [str(self.a), str(self.b)]


@dataclass(frozen=True)
class CollisionFilter:
    """
    collision filtering 정책 (Scene-level 운영 정책).
    - ignoreJoints: joint로 연결된 body pair는 충돌 끔
    - ignoreGearPairs: gearPair로 연결된 gearA/gearB는 충돌 끔
    - ignorePairs: 추가로 끌 pair 목록
    - onlyPairs: 이 pair만 충돌 허용(나머지 모두 ignore로 간주)  ※ 고급/선택
    """
    ignoreJoints: bool = True
    ignoreGearPairs: bool = True
    ignorePairs: List[CollisionPair] = field(default_factory=list)
    onlyPairs: Optional[List[CollisionPair]] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CollisionFilter":
        if not isinstance(d, dict):
            raise ValueError(f"collisionFilter must be object, got: {type(d)}")

        ignore_joints = bool(d.get("ignoreJoints", True))
        ignore_gears = bool(d.get("ignoreGearPairs", True))

        raw_ignore = d.get("ignorePairs", [])
        if raw_ignore is None:
            raw_ignore = []
        if not isinstance(raw_ignore, list):
            raise ValueError("collisionFilter.ignorePairs must be list")

        ignore_pairs = [CollisionPair.from_any(x).normalized() for x in raw_ignore]

        raw_only = d.get("onlyPairs", None)
        only_pairs: Optional[List[CollisionPair]] = None
        if raw_only is not None:
            if not isinstance(raw_only, list):
                raise ValueError("collisionFilter.onlyPairs must be list")
            only_pairs = [CollisionPair.from_any(x).normalized() for x in raw_only]

        return CollisionFilter(
            ignoreJoints=ignore_joints,
            ignoreGearPairs=ignore_gears,
            ignorePairs=ignore_pairs,
            onlyPairs=only_pairs,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ignoreJoints": bool(self.ignoreJoints),
            "ignoreGearPairs": bool(self.ignoreGearPairs),
            "ignorePairs": [p.to_list() for p in self.ignorePairs],
        }
        if self.onlyPairs is not None:
            out["onlyPairs"] = [p.to_list() for p in self.onlyPairs]
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

    # NEW: 1-2 collision filter policy
    collisionFilter: Optional[CollisionFilter] = None

    # NEW: 3-2.1 assembly guide metadata
    assemblyGuides: List[AssemblyGuideDef] = field(default_factory=list)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SceneMeta":
        if not isinstance(d, dict):
            raise ValueError(f"SceneMeta must be object, got: {type(d)}")

        bodies = [BodyDef.from_dict(x) for x in d.get("bodies", [])]
        joints = [JointDef.from_dict(x) for x in d.get("joints", [])]
        gearPairs = [GearPairDef.from_dict(x) for x in d.get("gearPairs", [])]
        actuators = [ActuatorDef.from_dict(x) for x in d.get("actuators", [])]

        assembly_guides_raw = d.get("assemblyGuides", [])
        if assembly_guides_raw is None:
            assembly_guides_raw = []
        if not isinstance(assembly_guides_raw, list):
            raise ValueError("SceneMeta.assemblyGuides must be list")
        assembly_guides = [AssemblyGuideDef.from_dict(x) for x in assembly_guides_raw]

        # 여기서도 최소한의 sanity check는 해두면 디버깅이 빨라짐
        if len(bodies) == 0:
            raise ValueError("SceneMeta.bodies must not be empty")

        cf_raw = d.get("collisionFilter", None)
        cf = CollisionFilter.from_dict(cf_raw) if isinstance(cf_raw, dict) else None

        return SceneMeta(
            sceneName=str(d.get("sceneName", "unnamed_scene")),
            gravity=Vec3.from_any(d.get("gravity", [0.0, -9.81, 0.0])),
            bodies=bodies,
            joints=joints,
            gearPairs=gearPairs,
            actuators=actuators,
            collisionFilter=cf,
            assemblyGuides=assembly_guides,
        )

    @staticmethod
    def from_json_str(json_str: str) -> "SceneMeta":
        return SceneMeta.from_dict(json.loads(json_str))

    @staticmethod
    def from_json_file(path: str, encoding: str = "utf-8") -> "SceneMeta":
        with open(path, "r", encoding=encoding) as f:
            return SceneMeta.from_dict(json.load(f))

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "sceneName": str(self.sceneName),
            "gravity": self.gravity.to_list(),
            "bodies": [b.to_dict() for b in self.bodies],
            "joints": [j.to_dict() for j in self.joints],
            "gearPairs": [g.to_dict() for g in self.gearPairs],
            "actuators": [a.to_dict() for a in self.actuators],
        }
        if self.collisionFilter is not None:
            out["collisionFilter"] = self.collisionFilter.to_dict()
        if self.assemblyGuides:
            out["assemblyGuides"] = [g.to_dict() for g in self.assemblyGuides]
        return out

# =========================
# Minimal validation helpers (optional)
# =========================

def validate_scene(meta: SceneMeta) -> None:
    """기본적인 참조 무결성 검증. (필요 시 확장)"""

    body_names_list = [b.name for b in meta.bodies]
    joint_names_list = [j.name for j in meta.joints]
    gearpair_names_list = [g.name for g in meta.gearPairs]
    actuator_names_list = [a.name for a in meta.actuators]
    assembly_guide_names_list = [g.name for g in getattr(meta, "assemblyGuides", [])]

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
    _assert_unique(assembly_guide_names_list, "assemblyGuide")

    body_names = set(body_names_list)
    joint_names = set(joint_names_list)

    # joints refer to bodies
    for j in meta.joints:
        if j.body1 not in body_names:
            raise ValueError(f"Joint {j.name} refers missing body1: {j.body1}")
        if j.body2 not in body_names:
            raise ValueError(f"Joint {j.name} refers missing body2: {j.body2}")

        # ✅ NEW: joint limits basic sanity (2-3.1)
        lim = getattr(j, "limits", None)
        if isinstance(lim, JointLimits) and bool(lim.enable):
            lo = lim.lower
            hi = lim.upper
            if (lo is not None) and (hi is not None) and (float(lo) > float(hi)):
                raise ValueError(f"Joint {j.name}: limits.lower must be <= limits.upper (got {lo} > {hi})")

            # ✅ NEW: minimal guardrails for extended fields (2-3.3/2-3.4)
            if lim.stop_restitution is not None:
                if not (0.0 <= float(lim.stop_restitution) <= 1.0):
                    raise ValueError(f"Joint {j.name}: limits.stop_restitution must be in [0,1] (got {lim.stop_restitution})")
            if lim.stop_damping is not None and float(lim.stop_damping) < 0.0:
                raise ValueError(f"Joint {j.name}: limits.stop_damping must be >= 0 (got {lim.stop_damping})")
            if lim.spring_k is not None and float(lim.spring_k) < 0.0:
                raise ValueError(f"Joint {j.name}: limits.spring_k must be >= 0 (got {lim.spring_k})")
            if lim.damper_c is not None and float(lim.damper_c) < 0.0:
                raise ValueError(f"Joint {j.name}: limits.damper_c must be >= 0 (got {lim.damper_c})")

    # gearPairs refer to gear bodies + gearProps existence
    for gp in meta.gearPairs:
        if gp.gearA not in body_names or gp.gearB not in body_names:
            raise ValueError(f"GearPair {gp.name} refers missing gear body: {gp.gearA}, {gp.gearB}")

        gearA_def = next((b for b in meta.bodies if b.name == gp.gearA), None)
        gearB_def = next((b for b in meta.bodies if b.name == gp.gearB), None)
        if gearA_def is None or gearB_def is None:
            continue

        # docs 규칙: gearPair가 참조하는 바디는 category="gear" 여야 함
        if gearA_def.category != "gear" or gearB_def.category != "gear":
            raise ValueError(f"GearPair {gp.name}: gearA/gearB must have category='gear'")

        if gearA_def.mechanical.gearProps is None or gearB_def.mechanical.gearProps is None:
            raise ValueError(f"GearPair {gp.name}: gear bodies must have mechanical.gearProps")

        # 3-1.1: GearPair props sanity (없으면 OK)
        if gp.props is not None:
            if float(gp.props.efficiency) < 0.0 or float(gp.props.efficiency) > 1.0:
                raise ValueError(f"GearPair {gp.name}: props.efficiency must be in [0,1] (got {gp.props.efficiency})")
            if float(gp.props.backlash) < 0.0:
                raise ValueError(f"GearPair {gp.name}: props.backlash must be >= 0 (got {gp.props.backlash})")
            if gp.props.max_torque is not None and float(gp.props.max_torque) < 0.0:
                raise ValueError(f"GearPair {gp.name}: props.max_torque must be >= 0 (got {gp.props.max_torque})")

    # actuators refer to joints
    for a in meta.actuators:
        if a.targetJoint not in joint_names:
            raise ValueError(f"Actuator {a.name} refers missing joint: {a.targetJoint}")

    # NEW: collisionFilter validation
    cf = getattr(meta, "collisionFilter", None)
    if isinstance(cf, CollisionFilter):
        # ignorePairs
        for p in cf.ignorePairs:
            if p.a not in body_names or p.b not in body_names:
                raise ValueError(f"collisionFilter.ignorePairs refers missing body: {p.a}, {p.b}")
            if p.a == p.b:
                raise ValueError(f"collisionFilter.ignorePairs contains self-pair: {p.a}")

        # onlyPairs (선택)
        if cf.onlyPairs is not None:
            for p in cf.onlyPairs:
                if p.a not in body_names or p.b not in body_names:
                    raise ValueError(f"collisionFilter.onlyPairs refers missing body: {p.a}, {p.b}")
                if p.a == p.b:
                    raise ValueError(f"collisionFilter.onlyPairs contains self-pair: {p.a}")

    # NEW: assemblyGuides validation (3-2.1)
    for ag in getattr(meta, "assemblyGuides", []):
        if ag.movingBody not in body_names:
            raise ValueError(f"assemblyGuide {ag.name} refers missing movingBody: {ag.movingBody}")
        if ag.targetBody not in body_names:
            raise ValueError(f"assemblyGuide {ag.name} refers missing targetBody: {ag.targetBody}")
        if ag.movingBody == ag.targetBody:
            raise ValueError(f"assemblyGuide {ag.name}: movingBody and targetBody must differ")

        if float(ag.positionTolerance) < 0.0:
            raise ValueError(f"assemblyGuide {ag.name}: positionTolerance must be >= 0")
        if float(ag.angleTolerance) < 0.0:
            raise ValueError(f"assemblyGuide {ag.name}: angleTolerance must be >= 0")
        if float(ag.snapStrength) < 0.0:
            raise ValueError(f"assemblyGuide {ag.name}: snapStrength must be >= 0")

        if str(ag.mode) not in _ALLOWED_ASSEMBLY_GUIDE_MODES:
            raise ValueError(f"assemblyGuide {ag.name}: invalid mode '{ag.mode}'")
        if str(ag.alignAxis) not in _ALLOWED_ASSEMBLY_ALIGN_AXES:
            raise ValueError(f"assemblyGuide {ag.name}: invalid alignAxis '{ag.alignAxis}'")
