# simulator/sim_builder.py
# (FULL FILE) with critical fixes:
# 1) FIXED: _quat_to_R() last element (proper rotation matrix)
# 2) FIXED: cylinder fallback ChCollisionShapeCylinder ctor signatures (radius,radius,half_len vs radius,half_len)
#
# ✅ PATCH (B settle 안정화) - revised:
# - ❌ REMOVE sleeping (system/body). It can "freeze" dynamics on some PyChrono bindings.
# - ✅ KEEP mild body damping for dynamic bodies (best-effort across bindings)
# - ✅ RESTORE ROBUST preset collision envelope/margin to sane defaults (avoid "no contact / weird" binding behavior)
# - ✅ Keep NSC max penetration recovery speed moderately conservative (avoid pumping/jitter)
#
# ✅ NEW PATCH (A-style base floor primitive, without changing metadata):
# - If a body is category=="base" and collision=="auto":
#     -> keep existing AABB box auto-collider
#     -> AND add an extra thin "floor patch" box at TOP surface (y_max in body-local)
#        to prevent catastrophic fall-through / tunneling in headless tests.
# - This is intentionally conservative & deterministic.
# - Can be disabled via options.auto_base_add_floor = False (if such field exists).
#
# ✅ HOTFIX (your "before/after" request):
# - floor patch hx/hz gets a hard minimum "catcher-grade" size:
#     hx = max(min_half_xz, hx0*(1+expand))
#     hz = max(min_half_xz, hz0*(1+expand))
# - Controlled by cfg key: auto_base_floor_min_half_xz (default 2.0m)
#
# ✅ NEW (2-2.2):
# - Contact material 생성부에 "고급 마찰" 적용:
#   rolling_friction / spinning_friction / compliance / damping 을
#   SMC material에서 가능한 경우 best-effort로 적용
# - NSC material은 API가 없으면 조용히 무시 (2-2.3 근사 준비)
#
# ✅ NEW (2-2.3):
# - NSC에서도 “stick-slip/떨림 완화” 근사 가드레일:
#   (A) preset/옵션 파라미터 묶음 추가: friction_static_scale, stick_slip_min_speed, stick_slip_friction_scale_low
#   (B) NSC material friction에 "정지마찰 약화" 근사 적용: effective_mu = mu * clamp(scale, [0.6,1.0])
#   (C) slip velocity threshold 류 API가 있으면 best-effort로 호출(없으면 조용히 무시)
#   - 본 파일만 수정해도 동작 가능(옵션 필드는 getattr로 안전 처리)
#
# ✅ NEW (F hotfix / binding-compat):
# - Material 생성 시 바인딩별 class 차이를 흡수:
#   ChContactMaterialSMC/NSC 우선, 없으면 ChMaterialSurfaceSMC/NSC fallback.
# - rolling/spinning friction setter 후보 확장:
#   SetRollingFrictionCoeff/Mu, SetSpinningFrictionCoeff/Mu 등 best-effort
#
# ✅ NEW (3-1.2):
# - GearPair props를 읽어서 BuildResult에 gear 설정 정보를 저장
#   (여기서는 물리 보정 토크 적용 안 함: "메타 읽기 + 런타임 전달"까지만)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set

import math as m
try:
    import pychrono.core as chrono  # ✅ most common layout (has ChSystemNSC)
except Exception:
    import pychrono as chrono       # fallback for other layouts

from .metadata_types import (
    SceneMeta,
    BodyDef,
    JointDef,
    GearPairDef,
    ActuatorDef,
    Vec3,
    Quat,
    Pose,
    CollisionPrimitive,
    CollisionAuto,
    CollisionFilter,
    CollisionPair,
    AutoInertiaFromCollision,  # ✅ 2-1.2
    Contact as MetaContact,    # ✅ 2-2.2 (advanced friction fields live here)
)

# NOTE: options is passed from SimInfo.options (SimOptions),
# but we intentionally avoid hard-importing SimOptions here to prevent coupling.
# We use getattr(...) to remain tolerant.


# ---------------------------------------------------------------------
# Runtime handles (builder output)
# ---------------------------------------------------------------------


@dataclass
class BuiltBody:
    name: str
    meta: BodyDef
    body: chrono.ChBody


@dataclass
class BuiltJoint:
    name: str
    meta: JointDef
    link: chrono.ChLinkBase


@dataclass
class BuiltActuator:
    name: str
    meta: ActuatorDef
    link: chrono.ChLinkBase  # motor or torque link


# ✅ NEW (3-1.2): gear settings info for runtime (main.py) usage
@dataclass
class GearBuildInfo:
    """
    Gear pair settings captured at build-time (no physics applied here).
    - name: gearPair name (also link name if created)
    - gearA/gearB: body names
    - ratio: transmission ratio used by ChLinkLockGear
    - enabled/efficiency/backlash/max_torque: runtime knobs from metadata (guardrailed here too)
    """
    name: str
    gearA: str
    gearB: str
    ratio: float
    enabled: bool = True
    efficiency: float = 1.0
    backlash: float = 0.0
    max_torque: Optional[float] = None

# ✅ NEW (3-2.2): assembly guide info for runtime usage
@dataclass
class AssemblyGuideInfo:
    name: str
    partA: str
    partB: str
    snapTargets: List[str] = field(default_factory=list)

    alignAxis: Optional[Vec3] = None

    positionTolerance: float = 0.0
    angleTolerance: float = 0.0

    snapStrength: float = 0.0

    enabled: bool = True

@dataclass
class BuildResult:
    # sys can be NSC or SMC depending on preset
    sys: Any
    bodies: Dict[str, BuiltBody]
    joints: Dict[str, BuiltJoint]
    actuators: Dict[str, BuiltActuator]
    name_to_body: Dict[str, chrono.ChBody]
    name_to_link: Dict[str, chrono.ChLinkBase]
    warnings: List[str] = field(default_factory=list)

    # ✅ NEW (3-1.2): gearPair name -> build info (for runtime correction)
    gear_pairs: Dict[str, GearBuildInfo] = field(default_factory=dict)
    # ✅ NEW (3-2.2)
    assembly_guides: Dict[str, AssemblyGuideInfo] = field(default_factory=dict)

# ---------------------------------------------------------------------
# Small conversion helpers
# ---------------------------------------------------------------------


def _to_chvec(v: Vec3) -> chrono.ChVector3d:
    return chrono.ChVector3d(float(v.x), float(v.y), float(v.z))


def _to_chquat(q: Quat) -> chrono.ChQuaterniond:
    return chrono.ChQuaterniond(float(q.w), float(q.x), float(q.y), float(q.z))


def _to_chframe(p: Pose) -> chrono.ChFramed:
    return chrono.ChFramed(_to_chvec(p.pos), _to_chquat(p.rot))


def _pitch_radius_from_gearprops(module_m: float, teeth: int) -> float:
    return 0.5 * float(module_m) * float(teeth)


def _pose_from_center_rot(center: Tuple[float, float, float], rot: Quat) -> Pose:
    return Pose(pos=Vec3(float(center[0]), float(center[1]), float(center[2])), rot=rot)


# ---------------------------------------------------------------------
# PhysicsPreset / system configuration helpers
# ---------------------------------------------------------------------


def _normalize_contact_method(x: Any) -> str:
    s = str(x or "NSC").strip().upper()
    if s in ("NSC", "SMC"):
        return s
    return "NSC"


def _get_solver_type_enum(name: str) -> Optional[Any]:
    """
    Try to map a human string to chrono solver type enum across bindings.

    Supported names (case-insensitive):
      - "PSOR", "PSSOR", "SOR", "APGD", "MINRES", "BARZILAI"
    """
    n = str(name or "").strip().upper()
    if not n:
        return None

    # Many bindings expose: chrono.ChSolver.Type_XXX
    cls = getattr(chrono, "ChSolver", None)
    if cls is not None:
        for cand in (f"Type_{n}", f"Type_{n.replace('-', '_')}"):
            if hasattr(cls, cand):
                return getattr(cls, cand)

    # Some bindings expose: chrono.ChSolverType_XXX
    for cand in (f"ChSolverType_{n}", f"ChSolverType_{n.replace('-', '_')}"):
        if hasattr(chrono, cand):
            return getattr(chrono, cand)

    return None


def _apply_solver_settings(sys: Any, *, solver_name: Optional[str], max_iters: Optional[int], tol: Optional[float]) -> None:
    """
    Apply solver type / iterations / tolerance with broad compatibility.
    """
    # 1) solver type
    if solver_name:
        enum_val = _get_solver_type_enum(solver_name)
        if enum_val is not None:
            try:
                if hasattr(sys, "SetSolverType"):
                    sys.SetSolverType(enum_val)
            except Exception:
                pass

    # 2) max iterations + tolerance
    try:
        slv = sys.GetSolver() if hasattr(sys, "GetSolver") else None
    except Exception:
        slv = None

    if slv is not None:
        if max_iters is not None:
            for fn in ("SetMaxIterations", "SetMaxIters", "SetIterations"):
                try:
                    if hasattr(slv, fn):
                        getattr(slv, fn)(int(max_iters))
                        break
                except Exception:
                    pass
        if tol is not None:
            for fn in ("SetTolerance", "SetTol"):
                try:
                    if hasattr(slv, fn):
                        getattr(slv, fn)(float(tol))
                        break
                except Exception:
                    pass

    if max_iters is not None:
        for fn in ("SetMaxItersSolver", "SetSolverMaxIterations", "SetMaxIterations"):
            try:
                if hasattr(sys, fn):
                    getattr(sys, fn)(int(max_iters))
                    break
            except Exception:
                pass

    if tol is not None:
        for fn in ("SetSolverTolerance", "SetTolerance"):
            try:
                if hasattr(sys, fn):
                    getattr(sys, fn)(float(tol))
                    break
            except Exception:
                pass


def _apply_nsc_contact_stability(sys: Any, *, min_bounce_speed: Optional[float], max_penetration_recovery_speed: Optional[float]) -> None:
    """
    NSC-specific stability knobs (bounce threshold, penetration recovery).
    """
    if min_bounce_speed is not None:
        for fn in ("SetMinBounceSpeed", "SetMinBounceSpeedThreshold"):
            try:
                if hasattr(sys, fn):
                    getattr(sys, fn)(float(min_bounce_speed))
                    break
            except Exception:
                pass

    if max_penetration_recovery_speed is not None:
        for fn in ("SetMaxPenetrationRecoverySpeed", "SetMaxPenetrationRecoverySpeedThreshold"):
            try:
                if hasattr(sys, fn):
                    getattr(sys, fn)(float(max_penetration_recovery_speed))
                    break
            except Exception:
                pass


def _apply_collision_model_defaults(*, envelope: Optional[float], margin: Optional[float]) -> None:
    """
    Set global collision 'suggested envelope/margin' if exposed by binding.
    """
    targets: List[Any] = []

    try:
        col_mod = getattr(chrono, "collision", None)
        if col_mod is not None:
            cm = getattr(col_mod, "ChCollisionModel", None)
            if cm is not None:
                targets.append(cm)
    except Exception:
        pass

    try:
        cm = getattr(chrono, "ChCollisionModel", None)
        if cm is not None:
            targets.append(cm)
    except Exception:
        pass

    if not targets:
        return

    for t in targets:
        if envelope is not None:
            for fn in ("SetDefaultSuggestedEnvelope", "SetDefaultEnvelope", "SetSuggestedEnvelope"):
                try:
                    if hasattr(t, fn):
                        getattr(t, fn)(float(envelope))
                        break
                except Exception:
                    pass
        if margin is not None:
            for fn in ("SetDefaultSuggestedMargin", "SetDefaultMargin", "SetSuggestedMargin"):
                try:
                    if hasattr(t, fn):
                        getattr(t, fn)(float(margin))
                        break
                except Exception:
                    pass


# ✅ PATCH: damping best-effort helpers (sleep removed)
def _apply_body_damping(body: chrono.ChBody, *, lin: float, ang: float) -> None:
    """
    Best-effort damping on ChBody.
    """
    try:
        if hasattr(body, "SetLinearDamping"):
            body.SetLinearDamping(float(lin))
    except Exception:
        pass
    try:
        if hasattr(body, "SetAngularDamping"):
            body.SetAngularDamping(float(ang))
    except Exception:
        pass
    # Some bindings expose SetDamping(lin, ang)
    try:
        if hasattr(body, "SetDamping"):
            body.SetDamping(float(lin), float(ang))
    except Exception:
        pass


def _clamp(x: float, lo: float, hi: float) -> float:
    xx = float(x)
    if xx < lo:
        return lo
    if xx > hi:
        return hi
    return xx


def _preset_table() -> Dict[str, Dict[str, Any]]:
    return {
        "FAST": {
            "contact_method": "NSC",
            "solver": "PSOR",
            "max_iters": 40,
            "tol": 1e-8,
            "collision_envelope": 0.005,
            "collision_margin": 0.002,
            "min_bounce_speed": 0.2,
            "max_penetration_recovery_speed": 2.0,
            # ✅ damping only
            "body_linear_damping": 0.02,
            "body_angular_damping": 0.02,
            # ✅ base safety floor (auto)
            "auto_base_add_floor": True,
            "auto_base_floor_thickness": 0.10,    # full thickness (m); hy = thickness/2
            "auto_base_floor_expand": 0.50,       # +50% on hx/hz vs AABB
            "auto_base_floor_min_half_y": 0.02,   # minimum hy
            "auto_base_floor_inset": 0.0,         # (optional) inset into top surface
            "auto_base_floor_min_half_xz": 2.0,   # ✅ NEW: catcher-grade minimum half-extent in x/z

            # ✅ 2-2.3 (NSC stick-slip 완화 근사)
            "friction_static_scale": 0.90,         # effective_mu = mu * clamp(scale, [0.6,1.0])
            "stick_slip_min_speed": 0.02,          # best-effort: slip velocity threshold 계열 API가 있으면 적용
            "stick_slip_friction_scale_low": 0.85, # best-effort: 저속에서 더 약화시키는 API가 있으면 적용
        },
        "DEFAULT": {
            "contact_method": "NSC",
            "solver": "PSOR",
            "max_iters": 80,
            "tol": 1e-10,
            "collision_envelope": 0.008,
            "collision_margin": 0.003,
            "min_bounce_speed": 0.1,
            "max_penetration_recovery_speed": 1.5,
            # ✅ damping only
            "body_linear_damping": 0.03,
            "body_angular_damping": 0.03,
            # ✅ base safety floor (auto)
            "auto_base_add_floor": True,
            "auto_base_floor_thickness": 0.10,
            "auto_base_floor_expand": 0.50,
            "auto_base_floor_min_half_y": 0.02,
            "auto_base_floor_inset": 0.0,
            "auto_base_floor_min_half_xz": 2.0,   # ✅ NEW

            # ✅ 2-2.3 (NSC stick-slip 완화 근사)
            "friction_static_scale": 0.92,
            "stick_slip_min_speed": 0.02,
            "stick_slip_friction_scale_low": 0.88,
        },
        "ROBUST": {
            "contact_method": "NSC",
            "solver": "PSSOR",
            "max_iters": 260,
            "tol": 1e-12,
            # ✅ RESTORED: safe defaults (avoid "no contact/weird" across bindings)
            "collision_envelope": 0.010,
            "collision_margin": 0.004,
            "min_bounce_speed": 0.02,
            # ✅ keep conservative but not extreme
            "max_penetration_recovery_speed": 0.20,
            # ✅ damping only (stronger settle)
            "body_linear_damping": 0.14,
            "body_angular_damping": 0.14,
            # ✅ base safety floor (auto)
            "auto_base_add_floor": True,
            "auto_base_floor_thickness": 0.10,
            "auto_base_floor_expand": 0.60,       # ROBUST a bit wider (more safety)
            "auto_base_floor_min_half_y": 0.02,
            "auto_base_floor_inset": 0.0,
            "auto_base_floor_min_half_xz": 2.0,   # ✅ NEW

            # ✅ 2-2.3 (NSC stick-slip 완화 근사)
            "friction_static_scale": 0.96,         # ROBUST는 너무 미끄덩하면 안 돼서 약하게만
            "stick_slip_min_speed": 0.01,
            "stick_slip_friction_scale_low": 0.92,
        },
        "SMC_DEFAULT": {
            "contact_method": "SMC",
            "solver": None,
            "max_iters": None,
            "tol": None,
            "collision_envelope": 0.008,
            "collision_margin": 0.003,
            "min_bounce_speed": None,
            "max_penetration_recovery_speed": None,
            # ✅ damping only
            "body_linear_damping": 0.04,
            "body_angular_damping": 0.04,
            # ✅ base safety floor (auto)
            "auto_base_add_floor": True,
            "auto_base_floor_thickness": 0.10,
            "auto_base_floor_expand": 0.50,
            "auto_base_floor_min_half_y": 0.02,
            "auto_base_floor_inset": 0.0,
            "auto_base_floor_min_half_xz": 2.0,   # ✅ NEW

            # ✅ 2-2.3 (SMC에선 기본적으로 material law가 달라서 "근사"는 보수적으로 off에 가깝게)
            "friction_static_scale": 1.00,
            "stick_slip_min_speed": 0.00,
            "stick_slip_friction_scale_low": 1.00,
        },
    }


def _resolve_physics_config(options: Optional[Any]) -> Dict[str, Any]:
    tbl = _preset_table()

    preset_key = "DEFAULT"
    if options is not None:
        p = getattr(options, "physics_preset", None)
        if isinstance(p, str) and p.strip():
            preset_key = p.strip().upper()
        elif isinstance(p, dict):
            cfg = dict(tbl["DEFAULT"])
            cfg.update(p)
            return cfg

    base = dict(tbl["DEFAULT"])
    if preset_key in tbl:
        base.update(tbl[preset_key])

    if options is not None:
        if getattr(options, "contact_method", None) is not None:
            base["contact_method"] = getattr(options, "contact_method")

        if getattr(options, "solver", None) is not None:
            base["solver"] = getattr(options, "solver")

        if getattr(options, "solver_max_iters", None) is not None:
            base["max_iters"] = int(getattr(options, "solver_max_iters"))
        if getattr(options, "solver_tolerance", None) is not None:
            base["tol"] = float(getattr(options, "solver_tolerance"))

        if getattr(options, "collision_envelope", None) is not None:
            base["collision_envelope"] = float(getattr(options, "collision_envelope"))
        if getattr(options, "collision_margin", None) is not None:
            base["collision_margin"] = float(getattr(options, "collision_margin"))

        if getattr(options, "min_bounce_speed", None) is not None:
            base["min_bounce_speed"] = float(getattr(options, "min_bounce_speed"))
        if getattr(options, "max_penetration_recovery_speed", None) is not None:
            base["max_penetration_recovery_speed"] = float(getattr(options, "max_penetration_recovery_speed"))

        # ✅ allow overriding damping via options if present
        for k in ("body_linear_damping", "body_angular_damping"):
            if getattr(options, k, None) is not None:
                base[k] = getattr(options, k)

        # ✅ allow overriding base safety floor knobs via options if present (optional fields)
        for k in (
            "auto_base_add_floor",
            "auto_base_floor_thickness",
            "auto_base_floor_expand",
            "auto_base_floor_min_half_y",
            "auto_base_floor_inset",
            "auto_base_floor_min_half_xz",   # ✅ NEW
        ):
            if getattr(options, k, None) is not None:
                base[k] = getattr(options, k)

        # ✅ 2-2.3 stick-slip/정지마찰 완화 파라미터 (옵션 필드가 있으면 오버라이드)
        for k in (
            "friction_static_scale",
            "stick_slip_min_speed",
            "stick_slip_friction_scale_low",
        ):
            if getattr(options, k, None) is not None:
                base[k] = getattr(options, k)

    base["contact_method"] = _normalize_contact_method(base.get("contact_method"))
    if isinstance(base.get("solver"), str):
        base["solver"] = str(base["solver"]).strip()

    # ✅ guardrails
    base["friction_static_scale"] = _clamp(float(base.get("friction_static_scale", 1.0)), 0.6, 1.0)
    base["stick_slip_min_speed"] = max(0.0, float(base.get("stick_slip_min_speed", 0.0)))
    base["stick_slip_friction_scale_low"] = _clamp(float(base.get("stick_slip_friction_scale_low", 1.0)), 0.6, 1.0)

    return base


def _create_system_by_contact_method(contact_method: str) -> Any:
    cm = _normalize_contact_method(contact_method)
    if cm == "SMC":
        try:
            return chrono.ChSystemSMC()
        except Exception:
            return chrono.ChSystemNSC()
    return chrono.ChSystemNSC()


def _apply_physics_preset_to_system(sys: Any, cfg: Dict[str, Any]) -> None:
    _apply_collision_model_defaults(
        envelope=cfg.get("collision_envelope"),
        margin=cfg.get("collision_margin"),
    )

    _apply_solver_settings(
        sys,
        solver_name=cfg.get("solver"),
        max_iters=cfg.get("max_iters"),
        tol=cfg.get("tol"),
    )

    if _normalize_contact_method(cfg.get("contact_method")) == "NSC":
        _apply_nsc_contact_stability(
            sys,
            min_bounce_speed=cfg.get("min_bounce_speed"),
            max_penetration_recovery_speed=cfg.get("max_penetration_recovery_speed"),
        )


# ---------------------------------------------------------------------
# Contact material
# ---------------------------------------------------------------------


def _new_contact_material(*, is_smc: bool) -> Any:
    """
    ✅ 바인딩별 material class 차이를 흡수:
      - ChContactMaterialSMC/NSC 우선 (최근 계열에서 흔함)
      - 없으면 ChMaterialSurfaceSMC/NSC fallback (구/다른 바인딩에서 흔함)
    """
    if is_smc:
        for cls_name in ("ChContactMaterialSMC", "ChMaterialSurfaceSMC"):
            try:
                cls = getattr(chrono, cls_name, None)
                if cls is not None:
                    return cls()
            except Exception:
                pass
        raise RuntimeError("No SMC material class found (ChContactMaterialSMC/ChMaterialSurfaceSMC).")

    for cls_name in ("ChContactMaterialNSC", "ChMaterialSurfaceNSC"):
        try:
            cls = getattr(chrono, cls_name, None)
            if cls is not None:
                return cls()
        except Exception:
            pass
    raise RuntimeError("No NSC material class found (ChContactMaterialNSC/ChMaterialSurfaceNSC).")


def _apply_contact_material_extras_best_effort(mat: Any, c: MetaContact, *, is_smc: bool) -> None:
    """
    ✅ 2-2.2 핵심:
    - SMC material이면 rolling/spinning/compliance/damping을 가능한 API로 적용
    - NSC material이면 기본은 무시(지원 없으면 조용히)
    """
    if mat is None or c is None:
        return

    # rolling friction
    if getattr(c, "rolling_friction", None) is not None:
        v = float(c.rolling_friction)  # type: ignore
        for fn in (
            "SetRollingFriction",
            "SetRollingFrictionCoefficient",
            "SetRollingFrictionCoeff",
            "SetRollingFrictionMu",
        ):
            try:
                if hasattr(mat, fn):
                    getattr(mat, fn)(v)
                    break
            except Exception:
                pass

    # spinning friction
    if getattr(c, "spinning_friction", None) is not None:
        v = float(c.spinning_friction)  # type: ignore
        for fn in (
            "SetSpinningFriction",
            "SetSpinningFrictionCoefficient",
            "SetSpinningFrictionCoeff",
            "SetSpinningFrictionMu",
        ):
            try:
                if hasattr(mat, fn):
                    getattr(mat, fn)(v)
                    break
            except Exception:
                pass

    # compliance / damping: 주로 SMC에서만 의미
    if is_smc:
        if getattr(c, "compliance", None) is not None:
            v = float(c.compliance)  # type: ignore
            for fn in ("SetCompliance", "SetComplianceNormal", "SetComplianceN", "SetComplianceTangential", "SetComplianceT"):
                try:
                    if hasattr(mat, fn):
                        getattr(mat, fn)(v)
                except Exception:
                    pass
            try:
                if hasattr(mat, "SetComplianceNormal"):
                    mat.SetComplianceNormal(v)
            except Exception:
                pass
            try:
                if hasattr(mat, "SetComplianceTangential"):
                    mat.SetComplianceTangential(v)
            except Exception:
                pass

        if getattr(c, "damping", None) is not None:
            v = float(c.damping)  # type: ignore
            for fn in ("SetDampingF", "SetDampingNormal", "SetDampingN", "SetDampingTangential", "SetDampingT"):
                try:
                    if hasattr(mat, fn):
                        getattr(mat, fn)(v)
                except Exception:
                    pass
            try:
                if hasattr(mat, "SetDampingNormal"):
                    mat.SetDampingNormal(v)
            except Exception:
                pass
            try:
                if hasattr(mat, "SetDampingTangential"):
                    mat.SetDampingTangential(v)
            except Exception:
                pass


def _apply_nsc_stick_slip_guardrails_best_effort(mat: Any, cfg: Optional[Dict[str, Any]]) -> None:
    """
    ✅ 2-2.3:
    NSC에서 stick-slip/채터링 완화를 위해 "있으면" 적용하는 API들.
    (바인딩마다 유무가 다르므로 전부 best-effort)

    대표적으로 기대하는 류:
    - SetSlipVelocityThreshold(v)
    - SetFrictionMin / SetFrictionMax / SetFrictionCoefficientLowSpeed ...
    - SetStribeckVelocity / SetStribeckFriction ...
    """
    if mat is None or not cfg:
        return

    vmin = float(cfg.get("stick_slip_min_speed", 0.0) or 0.0)
    low_scale = float(cfg.get("stick_slip_friction_scale_low", 1.0) or 1.0)

    # slip velocity threshold
    if vmin > 0.0:
        for fn in ("SetSlipVelocityThreshold", "SetMinSlipVelocity", "SetSlipVelocity", "SetStribeckVelocity"):
            try:
                if hasattr(mat, fn):
                    getattr(mat, fn)(float(vmin))
                    break
            except Exception:
                pass

    # low-speed friction scaling (if API exists)
    # NOTE: 우리는 "있으면"만 적용. 없으면 조용히 무시.
    for fn in (
        "SetFrictionCoefficientLowSpeed",
        "SetFrictionLow",
        "SetFrictionMin",
        "SetStribeckFriction",
        "SetStribeckFrictionCoefficient",
    ):
        try:
            if hasattr(mat, fn) and 0.0 < low_scale < 1.0:
                getattr(mat, fn)(float(low_scale))
        except Exception:
            pass


def _effective_mu_for_nsc(c: MetaContact, cfg: Optional[Dict[str, Any]]) -> float:
    """
    ✅ 2-2.3 (B) 정지마찰 약화 근사:
    - metadata(Contact)에 static_friction_scale 같은 필드가 있으면 사용 (없으면 1.0)
    - cfg.friction_static_scale도 곱해서 적용
    - 전체 scale은 [0.6, 1.0]로 클램프
    """
    mu = float(getattr(c, "friction", 0.0) or 0.0)

    meta_scale = 1.0
    try:
        if getattr(c, "static_friction_scale", None) is not None:
            meta_scale = float(getattr(c, "static_friction_scale"))
    except Exception:
        meta_scale = 1.0

    cfg_scale = 1.0
    if cfg is not None:
        try:
            cfg_scale = float(cfg.get("friction_static_scale", 1.0))
        except Exception:
            cfg_scale = 1.0

    scale = _clamp(float(meta_scale) * float(cfg_scale), 0.6, 1.0)
    return float(mu) * float(scale)


def _make_contact_material_nsc(c: MetaContact, *, cfg: Optional[Dict[str, Any]] = None) -> Any:
    mat = _new_contact_material(is_smc=False)

    # ✅ 2-2.3: effective friction (static friction weakening approximation)
    eff_mu = _effective_mu_for_nsc(c, cfg)
    try:
        if hasattr(mat, "SetFriction"):
            mat.SetFriction(float(eff_mu))
    except Exception:
        pass
    try:
        if hasattr(mat, "SetRestitution"):
            mat.SetRestitution(float(c.restitution))
    except Exception:
        pass

    # NSC에서 rolling/spinning/compliance/damping API가 있는 경우도 "혹시" 있으니 best-effort.
    _apply_contact_material_extras_best_effort(mat, c, is_smc=False)

    # ✅ 2-2.3: if NSC material exposes slip/stribeck-like knobs, apply best-effort
    _apply_nsc_stick_slip_guardrails_best_effort(mat, cfg)

    return mat


def _make_contact_material_smc(c: MetaContact) -> Any:
    mat = _new_contact_material(is_smc=True)
    try:
        if hasattr(mat, "SetFriction"):
            mat.SetFriction(float(c.friction))
    except Exception:
        pass
    try:
        if hasattr(mat, "SetRestitution"):
            mat.SetRestitution(float(c.restitution))
    except Exception:
        pass

    # ✅ SMC 고급 옵션 적용(best-effort)
    _apply_contact_material_extras_best_effort(mat, c, is_smc=True)
    return mat


# ---------------------------------------------------------------------
# Basic math helpers (tuples)
# ---------------------------------------------------------------------


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s: float):
    return (a[0] * s, a[1] * s, a[2] * s)


def _hadamard(a, b):
    return (a[0] * b[0], a[1] * b[1], a[2] * b[2])


def _norm(a) -> float:
    return m.sqrt(_dot(a, a))


def _normalize(a):
    n = _norm(a) + 1e-12
    return (a[0] / n, a[1] / n, a[2] / n)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _quat_conj(q: Quat) -> Quat:
    return Quat(q.w, -q.x, -q.y, -q.z)


def _quat_mul(a: Quat, b: Quat) -> Quat:
    return Quat(
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
    )


def _rotate_vec_by_quat(v: Tuple[float, float, float], q: Quat) -> Tuple[float, float, float]:
    p = Quat(0.0, v[0], v[1], v[2])
    qq = _quat_mul(_quat_mul(q, p), _quat_conj(q))
    return (qq.x, qq.y, qq.z)


# ---------------------------------------------------------------------
# 2-1.2 Auto inertia from collision primitives
# ---------------------------------------------------------------------


def _quat_to_R(q: Quat) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]:
    """
    Convert quaternion(wxyz) to 3x3 rotation matrix.
    ✅ FIXED: correct last element (1 - 2*(xx+yy))
    """
    w, x, y, z = float(q.w), float(q.x), float(q.y), float(q.z)
    n = m.sqrt(w * w + x * x + y * y + z * z) + 1e-12
    w, x, y, z = w / n, x / n, y / n, z / n

    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz),       2.0 * (xz + wy)),
        (2.0 * (xy + wz),       1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy),       2.0 * (yz + wx),       1.0 - 2.0 * (xx + yy)),
    )


def _rotate_diag_inertia_keep_diag(I_diag: Tuple[float, float, float], q: Quat) -> Tuple[float, float, float]:
    R = _quat_to_R(q)
    Ixx, Iyy, Izz = float(I_diag[0]), float(I_diag[1]), float(I_diag[2])

    r00, r01, r02 = R[0]
    r10, r11, r12 = R[1]
    r20, r21, r22 = R[2]

    oxx = (r00 * r00) * Ixx + (r01 * r01) * Iyy + (r02 * r02) * Izz
    oyy = (r10 * r10) * Ixx + (r11 * r11) * Iyy + (r12 * r12) * Izz
    ozz = (r20 * r20) * Ixx + (r21 * r21) * Iyy + (r22 * r22) * Izz
    return (oxx, oyy, ozz)


def _primitive_volume(p: CollisionPrimitive) -> float:
    if p.kind == "box":
        if p.hx is None or p.hy is None or p.hz is None:
            return 0.0
        return 8.0 * float(p.hx) * float(p.hy) * float(p.hz)
    if p.kind == "cylinder":
        if p.radius is None or p.length is None:
            return 0.0
        r = float(p.radius)
        L = float(p.length)
        return m.pi * r * r * L
    if p.kind == "sphere":
        if p.radius is None:
            return 0.0
        r = float(p.radius)
        return (4.0 / 3.0) * m.pi * r * r * r
    return 0.0


def _primitive_inertia_diag_about_its_cm(p: CollisionPrimitive, mass: float) -> Tuple[float, float, float]:
    mm = float(mass)

    if p.kind == "box":
        if p.hx is None or p.hy is None or p.hz is None:
            return (0.0, 0.0, 0.0)
        hx, hy, hz = float(p.hx), float(p.hy), float(p.hz)
        Ixx = (1.0 / 3.0) * mm * (hy * hy + hz * hz)
        Iyy = (1.0 / 3.0) * mm * (hx * hx + hz * hz)
        Izz = (1.0 / 3.0) * mm * (hx * hx + hy * hy)
        return (Ixx, Iyy, Izz)

    if p.kind == "cylinder":
        if p.radius is None or p.length is None:
            return (0.0, 0.0, 0.0)
        r = float(p.radius)
        L = float(p.length)
        Izz = 0.5 * mm * r * r
        Ixx = (1.0 / 12.0) * mm * (3.0 * r * r + L * L)
        Iyy = Ixx
        return (Ixx, Iyy, Izz)

    if p.kind == "sphere":
        if p.radius is None:
            return (0.0, 0.0, 0.0)
        r = float(p.radius)
        I = (2.0 / 5.0) * mm * r * r
        return (I, I, I)

    return (0.0, 0.0, 0.0)


def _estimate_inertia_from_primitives(
    prims: List[CollisionPrimitive],
    total_mass: float,
    cfg: Optional[AutoInertiaFromCollision],
) -> Tuple[float, float, float]:
    m_total = max(0.0, float(total_mass))
    if m_total <= 0.0 or not prims:
        fb = float(cfg.fallback_diagonal) if cfg is not None else 1e-3
        val = max(0.0, fb * m_total)
        return (val, val, val)

    min_I = float(cfg.min_inertia) if cfg is not None else 0.0
    scale = float(cfg.scale) if cfg is not None else 1.0
    use_rot = bool(cfg.use_rotation) if cfg is not None else False
    fb = float(cfg.fallback_diagonal) if cfg is not None else 1e-3

    vols = [max(0.0, _primitive_volume(p)) for p in prims]
    v_sum = sum(vols)

    if v_sum > 1e-12:
        masses = [m_total * (v / v_sum) for v in vols]
    else:
        masses = [m_total / len(prims) for _ in prims]

    # COM in body-local
    com = (0.0, 0.0, 0.0)
    for p, mi in zip(prims, masses):
        cp = p.offset.pos
        com = _add(com, _mul((float(cp.x), float(cp.y), float(cp.z)), float(mi)))
    invm = 1.0 / (m_total + 1e-12)
    com = _mul(com, invm)

    Ixx = Iyy = Izz = 0.0
    for p, mi in zip(prims, masses):
        if mi <= 0.0:
            continue

        I_diag = _primitive_inertia_diag_about_its_cm(p, mi)

        if use_rot:
            I_diag = _rotate_diag_inertia_keep_diag(I_diag, p.offset.rot)

        cp = p.offset.pos
        dx = float(cp.x) - float(com[0])
        dy = float(cp.y) - float(com[1])
        dz = float(cp.z) - float(com[2])

        Ixx += float(I_diag[0]) + float(mi) * (dy * dy + dz * dz)
        Iyy += float(I_diag[1]) + float(mi) * (dx * dx + dz * dz)
        Izz += float(I_diag[2]) + float(mi) * (dx * dx + dy * dy)

    if not (m.isfinite(Ixx) and m.isfinite(Iyy) and m.isfinite(Izz)):
        val = max(0.0, fb * m_total)
        return (val, val, val)

    Ixx *= scale
    Iyy *= scale
    Izz *= scale

    Ixx = max(min_I, float(Ixx))
    Iyy = max(min_I, float(Iyy))
    Izz = max(min_I, float(Izz))

    floor = max(min_I, fb * m_total)
    Ixx = max(Ixx, floor)
    Iyy = max(Iyy, floor)
    Izz = max(Izz, floor)

    return (Ixx, Iyy, Izz)


# ---------------------------------------------------------------------
# Joint collision policy helper
# ---------------------------------------------------------------------


def _disable_collision_between_linked_bodies(link: chrono.ChLinkBase) -> None:
    try:
        if hasattr(link, "SetCollide"):
            link.SetCollide(False)
            return
    except Exception:
        pass

    for fn_name, arg in (
        ("SetCollisionDisabled", True),
        ("SetDisableCollision", True),
        ("SetCollideBodies", False),
    ):
        try:
            fn = getattr(link, fn_name, None)
            if callable(fn):
                fn(arg)
                return
        except Exception:
            pass


# ---------------------------------------------------------------------
# Collision filter (SceneMeta.collisionFilter) application helpers
# ---------------------------------------------------------------------


def _get_collision_model(body: chrono.ChBody) -> Any:
    try:
        if hasattr(body, "GetCollisionModel"):
            return body.GetCollisionModel()
    except Exception:
        pass
    return None


def _set_family(cm: Any, fam: int) -> bool:
    try:
        if cm is not None and hasattr(cm, "SetFamily"):
            cm.SetFamily(int(fam))
            return True
    except Exception:
        pass
    return False


def _mask_no_with(cm: Any, fam: int) -> bool:
    for fn in ("SetFamilyMaskNoCollisionWithFamily", "SetFamilyMaskNoCollideWithFamily"):
        try:
            if cm is not None and hasattr(cm, fn):
                getattr(cm, fn)(int(fam))
                return True
        except Exception:
            pass
    return False


def _mask_do_with(cm: Any, fam: int) -> bool:
    for fn in ("SetFamilyMaskDoCollisionWithFamily", "SetFamilyMaskDoCollideWithFamily"):
        try:
            if cm is not None and hasattr(cm, fn):
                getattr(cm, fn)(int(fam))
                return True
        except Exception:
            pass
    return False


def _pair_key(a: str, b: str) -> Tuple[str, str]:
    aa = str(a)
    bb = str(b)
    return (aa, bb) if aa <= bb else (bb, aa)


def _apply_collision_filter_policy(*, meta: SceneMeta, bodies: Dict[str, BuiltBody]) -> None:
    cf = getattr(meta, "collisionFilter", None)
    if not isinstance(cf, CollisionFilter):
        return

    allow_pairs: Optional[Set[Tuple[str, str]]] = None
    only_pairs = getattr(cf, "onlyPairs", None)
    if only_pairs is not None:
        allow_pairs = set()
        for p in only_pairs:
            try:
                allow_pairs.add(_pair_key(p.a, p.b))
            except Exception:
                pass

    deny_pairs: Set[Tuple[str, str]] = set()

    if bool(getattr(cf, "ignoreJoints", True)):
        for j in getattr(meta, "joints", []):
            try:
                deny_pairs.add(_pair_key(str(j.body1), str(j.body2)))
            except Exception:
                pass

    if bool(getattr(cf, "ignoreGearPairs", True)):
        for gp in getattr(meta, "gearPairs", []):
            try:
                deny_pairs.add(_pair_key(str(gp.gearA), str(gp.gearB)))
            except Exception:
                pass

    for p in getattr(cf, "ignorePairs", []):
        try:
            deny_pairs.add(_pair_key(p.a, p.b))
        except Exception:
            pass

    cm_by_name: Dict[str, Any] = {}
    fam_by_name: Dict[str, int] = {}

    MAX_FAMILY_SAFE = 15
    if len(bodies) > MAX_FAMILY_SAFE:
        if (allow_pairs is not None) or (len(deny_pairs) > 0):
            print(
                f"[WARN] collisionFilter pair policy skipped: too many bodies for safe family mask "
                f"(bodies={len(bodies)} > {MAX_FAMILY_SAFE})."
            )
        return

    fam = 1
    for name, bb in bodies.items():
        cm = _get_collision_model(bb.body)
        cm_by_name[name] = cm
        if cm is None:
            continue
        if not _set_family(cm, fam):
            cm_by_name = {}
            fam_by_name = {}
            break
        fam_by_name[name] = fam
        fam += 1

    if not fam_by_name:
        if (allow_pairs is not None) or (len(deny_pairs) > 0):
            print("[WARN] collisionFilter pair policy could not be applied (family/mask API not available in this binding).")
        return

    def _disable_pair_raw(a: str, b: str) -> None:
        if a not in fam_by_name or b not in fam_by_name:
            return
        fa = fam_by_name[a]
        fb = fam_by_name[b]
        cma = cm_by_name.get(a)
        cmb = cm_by_name.get(b)
        _mask_no_with(cma, fb)
        _mask_no_with(cmb, fa)

    def _enable_pair_raw(a: str, b: str) -> None:
        if a not in fam_by_name or b not in fam_by_name:
            return
        fa = fam_by_name[a]
        fb = fam_by_name[b]
        cma = cm_by_name.get(a)
        cmb = cm_by_name.get(b)
        _mask_do_with(cma, fb)
        _mask_do_with(cmb, fa)

    if allow_pairs is not None:
        all_fams = list(fam_by_name.values())
        for name, cm in cm_by_name.items():
            if cm is None:
                continue
            myfam = fam_by_name.get(name, None)
            for f in all_fams:
                if myfam is not None and f == myfam:
                    continue
                _mask_no_with(cm, f)

        for (a, b) in allow_pairs:
            _enable_pair_raw(a, b)

    for (a, b) in deny_pairs:
        _disable_pair_raw(a, b)


# ---------------------------------------------------------------------
# OBJ auto-approx utilities
# ---------------------------------------------------------------------


def _load_obj_vertices(obj_path: str) -> List[Tuple[float, float, float]]:
    verts: List[Tuple[float, float, float]] = []
    with open(obj_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if not verts:
        raise ValueError(f"[auto] OBJ '{obj_path}'에서 vertex(v ...)를 찾지 못했습니다.")
    return verts


def _apply_visual_to_vertices(
    verts_mesh_local: List[Tuple[float, float, float]],
    *,
    scale: Vec3,
    offset: Pose,
) -> List[Tuple[float, float, float]]:
    s = (float(scale.x), float(scale.y), float(scale.z))
    t = (float(offset.pos.x), float(offset.pos.y), float(offset.pos.z))
    q = offset.rot  # wxyz

    out: List[Tuple[float, float, float]] = []
    for v in verts_mesh_local:
        vs = _hadamard(v, s)
        vr = _rotate_vec_by_quat(vs, q)
        vb = _add(vr, t)
        out.append(vb)
    return out


def _compute_aabb(verts: List[Tuple[float, float, float]]):
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    mn = (min(xs), min(ys), min(zs))
    mx = (max(xs), max(ys), max(zs))
    center = ((mn[0] + mx[0]) * 0.5, (mn[1] + mx[1]) * 0.5, (mn[2] + mx[2]) * 0.5)
    ext = ((mx[0] - mn[0]) * 0.5, (mx[1] - mn[1]) * 0.5, (mx[2] - mn[2]) * 0.5)
    return mn, mx, center, ext


def _pca_main_axis(verts: List[Tuple[float, float, float]]) -> Tuple[float, float, float]:
    """
    ✅ BUGFIX: 공분산(2차 모멘트) 누적이 잘못되어 있던 것을 수정.
    power iteration으로 가장 큰 주성분 방향을 구함.
    """
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    cz = sum(v[2] for v in verts) / len(verts)

    sxx = syy = szz = sxy = sxz = syz = 0.0
    for x, y, z in verts:
        dx, dy, dz = x - cx, y - cy, z - cz
        sxx += dx * dx
        syy += dy * dy
        szz += dz * dz
        sxy += dx * dy
        sxz += dx * dz
        syz += dy * dz

    vx, vy, vz = 1.0, 0.3, 0.2
    for _ in range(30):
        nx = sxx * vx + sxy * vy + sxz * vz
        ny = sxy * vx + syy * vy + syz * vz
        nz = sxz * vx + syz * vy + szz * vz
        nrm = m.sqrt(nx * nx + ny * ny + nz * nz) + 1e-12
        vx, vy, vz = nx / nrm, ny / nrm, nz / nrm
    return (vx, vy, vz)


def _quat_from_two_vectors(v_from: Tuple[float, float, float], v_to: Tuple[float, float, float]) -> Quat:
    a = _normalize(v_from)
    b = _normalize(v_to)
    c = _cross(a, b)
    w = 1.0 + _dot(a, b)
    if w < 1e-8:
        axis = _cross(a, (1.0, 0.0, 0.0))
        if _norm(axis) < 1e-6:
            axis = _cross(a, (0.0, 1.0, 0.0))
        axis = _normalize(axis)
        return Quat(0.0, axis[0], axis[1], axis[2])

    qn = m.sqrt(w * w + c[0] * c[0] + c[1] * c[1] + c[2] * c[2]) + 1e-12
    return Quat(w / qn, c[0] / qn, c[1] / qn, c[2] / qn)


def _approx_base_from_obj(verts_body_local: List[Tuple[float, float, float]]):
    _, _, center, half_ext = _compute_aabb(verts_body_local)
    size = (half_ext[0] * 2, half_ext[1] * 2, half_ext[2] * 2)
    return center, size


def _approx_shaft_with_hub_from_obj(verts_body_local: List[Tuple[float, float, float]]):
    verts = verts_body_local
    _, _, center_c, _ = _compute_aabb(verts)

    axis = _normalize(_pca_main_axis(verts))
    c = center_c

    ss: List[float] = []
    rs: List[float] = []
    for p in verts:
        d = (p[0] - c[0], p[1] - c[1], p[2] - c[2])
        s = _dot(d, axis)
        perp = _sub(d, _mul(axis, s))
        r = _norm(perp)
        ss.append(s)
        rs.append(r)

    smin, smax = min(ss), max(ss)
    length = smax - smin
    s_center = 0.5 * (smin + smax)

    if length < 1e-6:
        _, _, cc, half_ext = _compute_aabb(verts)
        lx, ly, lz = half_ext[0] * 2, half_ext[1] * 2, half_ext[2] * 2
        L = max(lx, ly, lz)
        R = 0.5 * sorted([lx, ly, lz])[1]
        return cc, (0.0, 0.0, 1.0), L, R, 0.0, None

    nbins = 40
    bins: List[List[float]] = [[] for _ in range(nbins)]
    for s, r in zip(ss, rs):
        t = (s - smin) / (length + 1e-12)
        i = int(t * nbins)
        i = max(0, min(nbins - 1, i))
        bins[i].append(r)

    med: List[float] = []
    for b in bins:
        if not b:
            med.append(0.0)
        else:
            bb = sorted(b)
            med.append(bb[len(bb) // 2])

    med_sorted = sorted([v for v in med if v > 1e-9])
    if not med_sorted:
        R = sorted(rs)[int(0.5 * len(rs))]
        return center_c, axis, length, R, s_center, None

    k = max(1, int(0.10 * len(med_sorted)))
    baseline = sum(med_sorted[:k]) / k
    baseline *= 0.92

    thr = baseline * 1.55
    hub_idx = [i for i, v in enumerate(med) if v > thr]

    hub = None
    if hub_idx:
        best = (hub_idx[0], hub_idx[0])
        cur_s = hub_idx[0]
        cur_e = hub_idx[0]
        for i in hub_idx[1:]:
            if i == cur_e + 1:
                cur_e = i
            else:
                if (cur_e - cur_s) > (best[1] - best[0]):
                    best = (cur_s, cur_e)
                cur_s = cur_e = i
        if (cur_e - cur_s) > (best[1] - best[0]):
            best = (cur_s, cur_e)

        i0, i1 = best
        hs0 = smin + (i0 / nbins) * length
        hs1 = smin + ((i1 + 1) / nbins) * length
        hub_len = max(0.0, hs1 - hs0)
        hub_r = max(med[i0 : i1 + 1])
        hub_s_center = 0.5 * (hs0 + hs1)
        hub = {"length": hub_len, "radius": hub_r, "s_center": hub_s_center}

    shaft_r = max(1e-4, baseline)
    return center_c, axis, length, shaft_r, s_center, hub


def _make_base_top_floor_patch(
    *,
    mn: Tuple[float, float, float],
    mx: Tuple[float, float, float],
    center: Tuple[float, float, float],
    half_ext: Tuple[float, float, float],
    thickness: float,
    expand: float,
    min_half_y: float,
    inset: float,
    min_half_xz: float,  # ✅ NEW
) -> CollisionPrimitive:
    """
    Create a thin box at the TOP surface (y_max) in body-local frame.

    - half height hy = max(thickness/2, min_half_y)
    - center y = y_max - inset - hy  (so the top face sits at y_max - inset)
    - hx/hz expanded by (1+expand) BUT clamped by min_half_xz (catcher-grade)
    """
    hx0 = float(half_ext[0])
    hz0 = float(half_ext[2])

    # base floor patch는 너무 과하게 넓어지지 않도록 보수적으로
    min_half_xz = float(min_half_xz)
    hx = max(min_half_xz, hx0 * (1.0 + float(expand) * 0.35))
    hz = max(min_half_xz, hz0 * (1.0 + float(expand) * 0.35))

    hy = max(float(min_half_y), 0.25 * float(thickness))
    y_top = float(mx[1])
    cy = y_top - float(inset) - float(hy)

    off = _pose_from_center_rot((float(center[0]), float(cy), float(center[2])), Quat(1.0, 0.0, 0.0, 0.0))
    return CollisionPrimitive(kind="box", hx=float(hx), hy=float(hy), hz=float(hz), offset=off)


def _auto_collision_from_obj(
    bdef: BodyDef,
    auto: CollisionAuto,
    *,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[CollisionPrimitive]:
    vis = bdef.geometry.visual
    if vis.kind != "mesh" or not getattr(vis, "file", None):
        raise ValueError(f"Body '{bdef.name}': collision.auto requires geometry.visual.kind='mesh' and visual.file")

    obj_file = str(vis.file)

    verts_mesh = _load_obj_vertices(obj_file)
    verts = _apply_visual_to_vertices(verts_mesh, scale=vis.scale, offset=vis.offset)

    strategy = str(auto.strategy)
    cat = str(getattr(bdef, "category", "generic")).strip().lower()

    # default AABB stats reused by base floor patch
    mn, mx, center, half_ext = _compute_aabb(verts)

    # --- base aabb paths ---
    if strategy in ("aabb_box", "base_aabb"):
        off = _pose_from_center_rot(center, Quat(1.0, 0.0, 0.0, 0.0))
        prims = [
            CollisionPrimitive(
                kind="box",
                hx=float(half_ext[0]) * 0.96,
                hy=float(half_ext[1]) * 0.85,
                hz=float(half_ext[2]) * 0.96,
                offset=off,
            )
        ]

        # ✅ NEW: if this is base category, optionally add top floor patch
        if cat == "base" and bool((cfg or {}).get("auto_base_add_floor", True)):
            thickness = float((cfg or {}).get("auto_base_floor_thickness", 0.10))
            expand = float((cfg or {}).get("auto_base_floor_expand", 0.50))
            min_half_y = float((cfg or {}).get("auto_base_floor_min_half_y", 0.02))
            inset = float((cfg or {}).get("auto_base_floor_inset", 0.0))
            min_half_xz = float((cfg or {}).get("auto_base_floor_min_half_xz", 2.0))  # ✅ NEW
            try:
                prims.append(
                    _make_base_top_floor_patch(
                        mn=mn,
                        mx=mx,
                        center=center,
                        half_ext=half_ext,
                        thickness=thickness,
                        expand=expand,
                        min_half_y=min_half_y,
                        inset=inset,
                        min_half_xz=min_half_xz,  # ✅ NEW
                    )
                )
            except Exception:
                # If anything goes wrong, keep original AABB only (fail-safe)
                pass

        return prims

    # --- shaft PCA ---
    if strategy == "shaft_pca_hub2cyl":
        c, axis, L, R, s_center, hub = _approx_shaft_with_hub_from_obj(verts)
        q = _quat_from_two_vectors((0.0, 0.0, 1.0), (axis[0], axis[1], axis[2]))

        center_main = _add(c, _mul(axis, float(s_center)))
        prims = [
            CollisionPrimitive(
                kind="cylinder",
                radius=float(R) * 0.95,
                length=float(L) * 0.96,
                offset=_pose_from_center_rot(center_main, q),
            )
        ]

        if hub and float(hub.get("length", 0.0)) > 0.01 and float(hub.get("radius", 0.0)) > float(R) * 1.35:
            hub_center = _add(c, _mul(axis, float(hub.get("s_center", 0.0))))
            prims.append(
                CollisionPrimitive(
                    kind="cylinder",
                    radius=float(hub["radius"]),
                    length=float(hub["length"]),
                    offset=_pose_from_center_rot(hub_center, q),
                )
            )
        return prims

    # --- gear disc ---
    if strategy == "gear_disc" or cat == "gear":
        _, _, center_g, half_ext_g = _compute_aabb(verts)

        gp = getattr(getattr(bdef, "mechanical", None), "gearProps", None)

        face_width = 0.0
        if gp is not None:
            try:
                face_width = float(getattr(gp, "face_width", 0.0) or 0.0)
            except Exception:
                face_width = 0.0

        # gear는 얇은 disc/cylinder로 근사
        disc_radius = max(float(half_ext_g[0]), float(half_ext_g[2]))

        if face_width > 1e-6:
            disc_length = float(face_width) * 0.95
        else:
            disc_length = min(float(half_ext_g[1]) * 2.0, disc_radius * 0.6)

        disc_radius = max(disc_radius * 0.97, 1e-4)
        disc_length = max(disc_length, 1e-4)

        off = _pose_from_center_rot(center_g, Quat(1.0, 0.0, 0.0, 0.0))
        return [
            CollisionPrimitive(
                kind="cylinder",
                radius=float(disc_radius),
                length=float(disc_length),
                offset=off,
            )
        ]

    # --- category-based fallback ---
    if cat == "base":
        # base: AABB box + (optional) top floor patch
        off = _pose_from_center_rot(center, Quat(1.0, 0.0, 0.0, 0.0))
        prims = [
            CollisionPrimitive(
                kind="box",
                hx=float(half_ext[0]) * 0.96,
                hy=float(half_ext[1]) * 0.85,
                hz=float(half_ext[2]) * 0.96,
                offset=off,
            )
        ]

        if bool((cfg or {}).get("auto_base_add_floor", True)):
            thickness = float((cfg or {}).get("auto_base_floor_thickness", 0.10))
            expand = float((cfg or {}).get("auto_base_floor_expand", 0.50))
            min_half_y = float((cfg or {}).get("auto_base_floor_min_half_y", 0.02))
            inset = float((cfg or {}).get("auto_base_floor_inset", 0.0))
            min_half_xz = float((cfg or {}).get("auto_base_floor_min_half_xz", 2.0))  # ✅ NEW
            try:
                prims.append(
                    _make_base_top_floor_patch(
                        mn=mn,
                        mx=mx,
                        center=center,
                        half_ext=half_ext,
                        thickness=thickness,
                        expand=expand,
                        min_half_y=min_half_y,
                        inset=inset,
                        min_half_xz=min_half_xz,  # ✅ NEW
                    )
                )
            except Exception:
                pass

        return prims

    if cat == "shaft":
        c, axis, L, R, s_center, hub = _approx_shaft_with_hub_from_obj(verts)
        q = _quat_from_two_vectors((0.0, 0.0, 1.0), (axis[0], axis[1], axis[2]))

        center_main = _add(c, _mul(axis, float(s_center)))
        prims = [
            CollisionPrimitive(
                kind="cylinder",
                radius=float(R) * 0.95,
                length=float(L) * 0.96,
                offset=_pose_from_center_rot(center_main, q),
            )
        ]
        if hub and float(hub.get("length", 0.0)) > 0.01 and float(hub.get("radius", 0.0)) > float(R) * 1.35:
            hub_center = _add(c, _mul(axis, float(hub.get("s_center", 0.0))))
            prims.append(
                CollisionPrimitive(
                    kind="cylinder",
                    radius=float(hub["radius"]),
                    length=float(hub["length"]),
                    offset=_pose_from_center_rot(hub_center, q),
                )
            )
        return prims

    # generic fallback: AABB box only
    off = _pose_from_center_rot(center, Quat(1.0, 0.0, 0.0, 0.0))
    return [
        CollisionPrimitive(
            kind="box",
            hx=float(half_ext[0]),
            hy=float(half_ext[1]),
            hz=float(half_ext[2]),
            offset=off,
        )
    ]


# ---------------------------------------------------------------------
# Collision shape builders (primitive-only) + offset frame
# ---------------------------------------------------------------------


def _enable_body_collision(body: chrono.ChBody, enabled: bool = True) -> None:
    """
    ✅ 가장 중요한 안정성 패치:
    - 바인딩마다 EnableCollision이 실질적으로 collide flag를 못 켜는 경우가 있음.
    - 그래서 SetCollide(True)를 최우선으로, 그리고 여러 함수명을 끝까지 시도.
    """
    val = bool(enabled)

    # 1) SetCollide 최우선
    try:
        if hasattr(body, "SetCollide"):
            body.SetCollide(val)
    except Exception:
        pass

    # 2) 바인딩별 다른 이름들
    for fn in ("EnableCollision", "SetCollisionEnabled", "SetEnableCollision"):
        try:
            if hasattr(body, fn):
                getattr(body, fn)(val)
        except Exception:
            pass

    # 3) 어떤 바인딩은 collision model 쪽에도 Enable이 있음
    try:
        cm = body.GetCollisionModel() if hasattr(body, "GetCollisionModel") else None
        if cm is not None:
            for fn in ("SetCollide", "Enable"):
                try:
                    if hasattr(cm, fn):
                        getattr(cm, fn)(val)
                except Exception:
                    pass
    except Exception:
        pass


def _frame_pos_rot(fr: chrono.ChFramed) -> Tuple[chrono.ChVector3d, chrono.ChQuaterniond]:
    try:
        p = fr.GetPos()
    except Exception:
        p = chrono.ChVector3d(0, 0, 0)
    try:
        r = fr.GetRot()
    except Exception:
        r = chrono.ChQuaterniond(1, 0, 0, 0)
    return p, r


def _try_add_box_via_cm(cm: Any, mat: Any, hx: float, hy: float, hz: float, fr: chrono.ChFramed) -> bool:
    if cm is None:
        return False
    p, r = _frame_pos_rot(fr)

    for fn in ("AddBox", "AddBoxShape"):
        if not hasattr(cm, fn):
            continue
        f = getattr(cm, fn)
        for args in (
            (mat, float(hx), float(hy), float(hz), p, r),
            (mat, float(hx), float(hy), float(hz), p),
            (float(hx), float(hy), float(hz), p, r),
            (float(hx), float(hy), float(hz), p),
            (mat, float(hx), float(hy), float(hz)),
            (float(hx), float(hy), float(hz)),
        ):
            try:
                f(*args)
                return True
            except Exception:
                pass
    return False


def _try_add_sphere_via_cm(cm: Any, mat: Any, radius: float, fr: chrono.ChFramed) -> bool:
    if cm is None:
        return False
    p, _ = _frame_pos_rot(fr)

    for fn in ("AddSphere", "AddSphereShape"):
        if not hasattr(cm, fn):
            continue
        f = getattr(cm, fn)
        for args in (
            (mat, float(radius), p),
            (float(radius), p),
            (mat, float(radius)),
            (float(radius),),
        ):
            try:
                f(*args)
                return True
            except Exception:
                pass
    return False


def _try_add_cyl_via_cm(cm: Any, mat: Any, radius: float, length: float, fr: chrono.ChFramed) -> bool:
    if cm is None:
        return False
    p, r = _frame_pos_rot(fr)
    half = float(0.5 * length)
    rad = float(radius)

    for fn in ("AddCylinder", "AddCylinderShape"):
        if not hasattr(cm, fn):
            continue
        f = getattr(cm, fn)
        for args in (
            (mat, rad, rad, half, p, r),
            (mat, rad, rad, half, p),
            (rad, rad, half, p, r),
            (rad, rad, half, p),
            (mat, rad, rad, half),
            (rad, rad, half),
        ):
            try:
                f(*args)
                return True
            except Exception:
                pass
    return False


def _add_collision_box(body: chrono.ChBody, mat: Any, hx: float, hy: float, hz: float, frame: Optional[chrono.ChFramed] = None) -> None:
    fr = frame if frame is not None else chrono.ChFramed()
    cm = _get_collision_model(body)
    if _try_add_box_via_cm(cm, mat, float(hx), float(hy), float(hz), fr):
        return

    try:
        if hasattr(body, "AddCollisionShape"):
            shape = chrono.ChCollisionShapeBox(mat, float(hx), float(hy), float(hz))
            body.AddCollisionShape(shape, fr)
            return
    except Exception:
        pass

    raise RuntimeError("Failed to add box collision shape: no compatible API (AddBox/AddCollisionShape) in this binding")


def _add_collision_cylinder(body: chrono.ChBody, mat: Any, radius: float, length: float, frame: Optional[chrono.ChFramed] = None) -> None:
    fr = frame if frame is not None else chrono.ChFramed()
    cm = _get_collision_model(body)
    if _try_add_cyl_via_cm(cm, mat, float(radius), float(length), fr):
        return

    # ✅ FIXED: fallback ctor signatures differ across bindings
    try:
        if hasattr(body, "AddCollisionShape"):
            shape = None
            half = float(0.5 * length)
            rad = float(radius)

            # Common signature: (mat, rad, rad, half_len)
            try:
                shape = chrono.ChCollisionShapeCylinder(mat, rad, rad, half)
            except Exception:
                # Alternate signature: (mat, rad, half_len)
                shape = chrono.ChCollisionShapeCylinder(mat, rad, half)

            body.AddCollisionShape(shape, fr)
            return
    except Exception:
        pass

    raise RuntimeError("Failed to add cylinder collision shape: no compatible API (AddCylinder/AddCollisionShape) in this binding")


def _add_collision_sphere(body: chrono.ChBody, mat: Any, radius: float, frame: Optional[chrono.ChFramed] = None) -> None:
    fr = frame if frame is not None else chrono.ChFramed()
    cm = _get_collision_model(body)
    if _try_add_sphere_via_cm(cm, mat, float(radius), fr):
        return

    try:
        if hasattr(body, "AddCollisionShape"):
            shape = chrono.ChCollisionShapeSphere(mat, float(radius))
            body.AddCollisionShape(shape, fr)
            return
    except Exception:
        pass

    raise RuntimeError("Failed to add sphere collision shape: no compatible API (AddSphere/AddCollisionShape) in this binding")


def _reset_collision_model(body: chrono.ChBody) -> None:
    try:
        if hasattr(body, "GetCollisionModel"):
            cm = body.GetCollisionModel()
            if cm is not None and hasattr(cm, "ClearModel"):
                cm.ClearModel()
    except Exception:
        pass


def _finalize_collision_model(body: chrono.ChBody) -> None:
    try:
        if hasattr(body, "GetCollisionModel"):
            cm = body.GetCollisionModel()
            if cm is not None and hasattr(cm, "BuildModel"):
                cm.BuildModel()
    except Exception:
        pass


def _collision_primitive_to_chframe(p: CollisionPrimitive) -> chrono.ChFramed:
    return _to_chframe(p.offset)


def _apply_collision_primitive(body: chrono.ChBody, mat: Any, prim: CollisionPrimitive) -> None:
    fr = _collision_primitive_to_chframe(prim)

    if prim.kind == "box":
        if prim.hx is None or prim.hy is None or prim.hz is None:
            raise ValueError("collision.box requires hx,hy,hz")
        _add_collision_box(body, mat, float(prim.hx), float(prim.hy), float(prim.hz), fr)
        return

    if prim.kind == "cylinder":
        if prim.radius is None or prim.length is None:
            raise ValueError("collision.cylinder requires radius,length")
        _add_collision_cylinder(body, mat, float(prim.radius), float(prim.length), fr)
        return

    if prim.kind == "sphere":
        if prim.radius is None:
            raise ValueError("collision.sphere requires radius")
        _add_collision_sphere(body, mat, float(prim.radius), fr)
        return

    raise NotImplementedError(f"unsupported collision kind '{prim.kind}'")


# ---------------------------------------------------------------------
# Visual shape builders (mesh-only)
# ---------------------------------------------------------------------


def _attach_visual_mesh(body: chrono.ChBody, mesh_file: str, scale: chrono.ChVector3d, offset: chrono.ChFramed) -> None:
    mesh = chrono.ChTriangleMeshConnected()
    mesh.LoadWavefrontMesh(str(mesh_file), False, True)

    vshape = chrono.ChVisualShapeTriangleMesh()
    vshape.SetMesh(mesh)
    vshape.SetScale(scale)

    body.AddVisualShape(vshape, offset)


# ---------------------------------------------------------------------
# Body creation
# ---------------------------------------------------------------------


def _make_contact_material(sys: Any, c: MetaContact, *, cfg: Optional[Dict[str, Any]] = None) -> Any:
    """
    sys가 SMC면 SMC material + 고급 옵션(best-effort) 적용
    sys가 NSC면 NSC material(+있다면 best-effort + 2-2.3 stick-slip 근사) 적용
    """
    # ✅ isinstance가 바인딩에서 깨질 수 있어서 "class name"도 같이 본다
    is_smc = False
    try:
        if isinstance(sys, getattr(chrono, "ChSystemSMC", ())):
            is_smc = True
    except Exception:
        pass
    try:
        if "SMC" in sys.__class__.__name__.upper():
            is_smc = True
    except Exception:
        pass

    if is_smc:
        return _make_contact_material_smc(c)
    return _make_contact_material_nsc(c, cfg=cfg)


def _coerce_collision_to_primitives(bdef: BodyDef, col_any: Any, *, cfg: Optional[Dict[str, Any]] = None) -> List[CollisionPrimitive]:
    """
    ✅ 아주 중요:
    - metadata 파서가 collision:"auto"를 CollisionAuto로 바꿔주지 않는 경우가 있음.
    - 그래서 여기서 str/dict 형태도 방어적으로 처리.

    ✅ NEW:
    - auto collision 생성 시 cfg(옵션) 기반의 base floor patch를 적용할 수 있게 cfg 전달.
    """
    # 0) none / null
    if col_any is None:
        return []

    # 1) already CollisionAuto
    if isinstance(col_any, CollisionAuto):
        return _auto_collision_from_obj(bdef, col_any, cfg=cfg)

    # 2) list primitives
    if isinstance(col_any, list):
        prims: List[CollisionPrimitive] = []
        for it in col_any:
            if isinstance(it, CollisionPrimitive):
                prims.append(it)
            elif isinstance(it, CollisionAuto):
                prims.extend(_auto_collision_from_obj(bdef, it, cfg=cfg))
            else:
                raise ValueError(f"Body '{bdef.name}': collision list has unsupported item type: {type(it)}")
        return prims

    # 3) string "auto" / "none"
    if isinstance(col_any, str):
        s = col_any.strip().lower()
        if s == "none":
            return []
        if s == "auto":
            cat = str(getattr(bdef, "category", "generic")).strip().lower()
            if cat == "shaft":
                strategy = "shaft_pca_hub2cyl"
            elif cat == "gear":
                strategy = "gear_disc"
            else:
                strategy = "base_aabb"
            return _auto_collision_from_obj(bdef, CollisionAuto(strategy=strategy), cfg=cfg)
        raise ValueError(f"Body '{bdef.name}': unsupported collision string: {col_any}")

    # 4) dict {kind:"auto"} / {kind:"none"}
    if isinstance(col_any, dict):
        kind = str(col_any.get("kind", "")).strip().lower()
        if kind == "none":
            return []
        if kind == "auto":
            cat = str(getattr(bdef, "category", "generic")).strip().lower()
            strategy = str(col_any.get("strategy", "")).strip()
            if not strategy:
                if cat == "shaft":
                    strategy = "shaft_pca_hub2cyl"
                elif cat == "gear":
                    strategy = "gear_disc"
                else:
                    strategy = "base_aabb"
            return _auto_collision_from_obj(bdef, CollisionAuto(strategy=strategy), cfg=cfg)
        raise ValueError(
            f"Body '{bdef.name}': unsupported collision dict (expected kind='auto' or 'none'): keys={list(col_any.keys())}"
        )

    # 5) single primitive
    if isinstance(col_any, CollisionPrimitive):
        return [col_any]

    raise ValueError(f"Body '{bdef.name}': unsupported collision type: {type(col_any)}")


def _build_body(sys: Any, bdef: BodyDef, *, cfg: Optional[Dict[str, Any]] = None) -> chrono.ChBody:
    body = chrono.ChBody()
    body.SetName(bdef.name)

    body.SetPos(_to_chvec(bdef.pose.pos))
    body.SetRot(_to_chquat(bdef.pose.rot))

    body.SetFixed(bool(bdef.mechanical.fixed))
    body.SetMass(float(bdef.mechanical.mass))
    print(f"[DEBUG mass] {bdef.name} mass = {float(bdef.mechanical.mass):.6f}")

    # ✅ PATCH: apply damping only for dynamic bodies (best-effort across bindings)
    if (not bool(bdef.mechanical.fixed)) and cfg is not None:
        try:
            _apply_body_damping(
                body,
                lin=float(cfg.get("body_linear_damping", 0.0) or 0.0),
                ang=float(cfg.get("body_angular_damping", 0.0) or 0.0),
            )
        except Exception:
            pass

    # contact material (✅ 2-2.2 advanced options included + ✅ 2-2.3 NSC stick-slip guardrail)
    c = bdef.mechanical.contact
    mat = _make_contact_material(sys, c, cfg=cfg)

    # determine collision primitives (single/list/auto/"auto"/"none"/null)
    col_any = bdef.geometry.collision
    prims: List[CollisionPrimitive] = _coerce_collision_to_primitives(bdef, col_any, cfg=cfg)
    print(f"[DEBUG prims] {bdef.name} prim_count = {len(prims)}")

    # inertia
    inertia = bdef.mechanical.inertia
    if inertia.mode == "explicit":
        Ixx = float(inertia.Ixx or 0.0)
        Iyy = float(inertia.Iyy or 0.0)
        Izz = float(inertia.Izz or 0.0)

        # explicit inertia가 0/비정상이면 auto 추정으로 fallback
        if Ixx < 1e-8 or Iyy < 1e-8 or Izz < 1e-8:
            cfg_in = getattr(inertia, "auto", None)
            mval = float(bdef.mechanical.mass)
            print(f"[WARN] {bdef.name} explicit inertia invalid -> fallback to auto")
            Ixx, Iyy, Izz = _estimate_inertia_from_primitives(prims, mval, cfg_in)

        body.SetInertiaXX(chrono.ChVector3d(float(Ixx), float(Iyy), float(Izz)))
        print(f"[DEBUG inertia] {bdef.name} explicit/fallback inertia = ({float(Ixx):.6e}, {float(Iyy):.6e}, {float(Izz):.6e})")
    else:
        cfg_in = getattr(inertia, "auto", None)  # AutoInertiaFromCollision | None
        mval = float(bdef.mechanical.mass)
        Ixx, Iyy, Izz = _estimate_inertia_from_primitives(prims, mval, cfg_in)
        body.SetInertiaXX(chrono.ChVector3d(float(Ixx), float(Iyy), float(Izz)))
        print(f"[DEBUG inertia] {bdef.name} auto inertia = ({float(Ixx):.6e}, {float(Iyy):.6e}, {float(Izz):.6e})")
    # collision shapes
    should_collide = (prims is not None) and (len(prims) > 0)

    _enable_body_collision(body, bool(should_collide))
    _reset_collision_model(body)

    if should_collide:
        for p in prims:
            _apply_collision_primitive(body, mat, p)

    _finalize_collision_model(body)

    # ✅ 여기서 “진짜로” collide 플래그를 다시 강제 (바인딩별 이슈 대응)
    _enable_body_collision(body, bool(should_collide))

    # visual mesh (visual only)
    vis = bdef.geometry.visual
    if vis.kind == "mesh":
        scale = _to_chvec(vis.scale)
        offset = _to_chframe(vis.offset)
        _attach_visual_mesh(body, vis.file, scale, offset)

    sys.AddBody(body)
    return body

# ---------------------------------------------------------------------
# Joint limits - best-effort application across bindings
# ---------------------------------------------------------------------

_WARNED_LIMIT_APPLY: Set[str] = set()


def _warn_once(
    key: str,
    msg: str,
    *,
    warnings: Optional[List[str]] = None,
    also_print: bool = True,
) -> None:
    """
    - key 단위로 1회만 경고
    - warnings 리스트에 쌓아 main.py에서 요약/출력 가능하게 함
    """
    if key in _WARNED_LIMIT_APPLY:
        return
    _WARNED_LIMIT_APPLY.add(key)

    if also_print:
        try:
            print(msg)
        except Exception:
            pass

    if warnings is not None:
        try:
            # main.py가 key별 카운트를 낼 수 있도록 "key: ..." 형태로 남김
            warnings.append(f"{key}: {msg}")
        except Exception:
            pass


def _try_call(obj: Any, fn_name: str, *args: Any) -> bool:
    try:
        fn = getattr(obj, fn_name, None)
        if callable(fn):
            fn(*args)
            return True
    except Exception:
        return False
    return False


def _as_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _set_limit_obj_best_effort(limit_obj: Any, lower: Optional[float], upper: Optional[float]) -> bool:
    """
    Chrono limit object(ChLinkLimit 등)로 보이는 객체에 하한/상한을 best-effort로 주입.
    """
    if limit_obj is None:
        return False

    ok = False

    # 활성화
    for fn in ("SetActive", "Set_enabled", "SetEnabled", "SetActiveFlag", "SetEnable"):
        ok = _try_call(limit_obj, fn, True) or ok

    # 하한/상한
    if lower is not None:
        for fn in ("SetMin", "SetLowerLimit", "SetLo", "Set_min", "SetLower"):
            ok = _try_call(limit_obj, fn, float(lower)) or ok
    if upper is not None:
        for fn in ("SetMax", "SetUpperLimit", "SetHi", "Set_max", "SetUpper"):
            ok = _try_call(limit_obj, fn, float(upper)) or ok

    return ok


def _set_stop_params_best_effort(limit_obj: Any, stop_restitution: Optional[float], stop_damping: Optional[float]) -> bool:
    if limit_obj is None:
        return False

    ok = False

    if stop_restitution is not None:
        for fn in ("SetRestitution", "Set_restitution", "SetKrestitution", "SetBounce"):
            ok = _try_call(limit_obj, fn, float(stop_restitution)) or ok

    if stop_damping is not None:
        for fn in ("SetDamping", "Set_damping", "SetCdamping", "SetDamp"):
            ok = _try_call(limit_obj, fn, float(stop_damping)) or ok

    return ok


def _set_soft_params_best_effort(limit_obj: Any, k: Optional[float], c: Optional[float], eq: Optional[float]) -> bool:
    """
    소프트 리미트(스프링/댐퍼): 바인딩/버전별 편차가 커서 best-effort.
    """
    if limit_obj is None:
        return False

    ok = False

    if k is not None:
        for fn in ("SetSpringCoefficient", "SetK", "SetStiffness", "Set_spring", "SetSpringK"):
            ok = _try_call(limit_obj, fn, float(k)) or ok

    if c is not None:
        for fn in ("SetDampingCoefficient", "SetC", "SetDamping", "Set_damper", "SetDamperC"):
            ok = _try_call(limit_obj, fn, float(c)) or ok

    if eq is not None:
        for fn in ("SetSpringRestLength", "SetEquilibrium", "SetNeutral", "Set_spring_equilibrium"):
            ok = _try_call(limit_obj, fn, float(eq)) or ok

    return ok


def _find_limit_object_candidates(link: Any, joint_type: str) -> List[Any]:
    """
    Chrono link에서 limit object 후보를 최대한 찾는다.
    pychrono binding 편차를 고려한 aggressive 탐색.
    """

    cand: List[Any] = []
    jt = str(joint_type or "").lower()

    # -----------------------------
    # 1. revolute / prismatic 전용 탐색
    # -----------------------------

    if jt in ("revolute", "hinge"):
        for fn in (
            "GetLimit_Rz",
            "GetLimitRz",
            "GetRotLimit",
            "GetLimit",
        ):
            try:
                if hasattr(link, fn):
                    obj = getattr(link, fn)()
                    if obj is not None:
                        cand.append(obj)
            except Exception:
                pass

        for attr in (
            "limit_Rz",
            "limitRz",
            "Limit_Rz",
            "LimitRz",
        ):
            try:
                if hasattr(link, attr):
                    obj = getattr(link, attr)
                    if obj is not None:
                        cand.append(obj)
            except Exception:
                pass

    elif jt in ("prismatic", "slider"):
        for fn in (
            "GetLimit_Z",
            "GetLimitZ",
            "GetLinLimit",
            "GetLimit",
        ):
            try:
                if hasattr(link, fn):
                    obj = getattr(link, fn)()
                    if obj is not None:
                        cand.append(obj)
            except Exception:
                pass

        for attr in (
            "limit_Z",
            "limitZ",
            "Limit_Z",
            "LimitZ",
        ):
            try:
                if hasattr(link, attr):
                    obj = getattr(link, attr)
                    if obj is not None:
                        cand.append(obj)
            except Exception:
                pass

    # -----------------------------
    # 2. 전체 attribute 스캔
    # -----------------------------

    try:
        for name in dir(link):
            if "limit" in name.lower():
                try:
                    obj = getattr(link, name)
                    if obj is None:
                        continue
                    if callable(obj):
                        obj = obj()
                    cand.append(obj)
                except Exception:
                    pass
    except Exception:
        pass

    # -----------------------------
    # 3. 중복 제거
    # -----------------------------

    uniq: List[Any] = []
    seen: Set[int] = set()

    for o in cand:
        try:
            oid = id(o)
        except Exception:
            oid = -1

        if oid in seen:
            continue

        if oid != -1:
            seen.add(oid)

        uniq.append(o)

    return uniq


def _soft_limits_enabled_from_options(options: Optional[Any]) -> bool:
    """
    soft-limit 토글 호환:
    - options.joint_soft_limits_enabled
    - options.enable_joint_soft_limits
    - options.joint_soft_limits
    - options.soft_limits
    중 하나라도 True면 enabled로 간주.
    """
    if options is None:
        return False
    for k in (
        "joint_soft_limits_enabled",
        "enable_joint_soft_limits",
        "joint_soft_limits",
        "soft_limits",
    ):
        try:
            v = getattr(options, k, None)
            if isinstance(v, bool):
                return bool(v)
        except Exception:
            pass
    return False


def _apply_joint_limits_best_effort(
    link: Any,
    jdef: Any,
    *,
    options: Optional[Any] = None,                 # ✅ 호출부(options=...) 호환
    warnings: Optional[List[str]] = None,
) -> None:
    """
    JointDef.limits를 Chrono link에 best-effort로 적용.
    - revolute: rad
    - prismatic: m
    """
    lim = getattr(jdef, "limits", None)
    if lim is None:
        return

    enable = bool(getattr(lim, "enable", True))
    if not enable:
        # disable 요청
        _try_call(link, "SetLimitActive", False)
        _try_call(link, "SetLimitsActive", False)
        _try_call(link, "SetLimitEnabled", False)
        _try_call(link, "SetLimitsEnabled", False)
        return

    lower = _as_float(getattr(lim, "lower", None))
    upper = _as_float(getattr(lim, "upper", None))

    stop_restitution = _as_float(getattr(lim, "stop_restitution", None))
    stop_damping = _as_float(getattr(lim, "stop_damping", None))

    spring_k = _as_float(getattr(lim, "spring_k", None))
    damper_c = _as_float(getattr(lim, "damper_c", None))
    spring_eq = _as_float(getattr(lim, "spring_equilibrium", None))

    jtype = str(getattr(jdef, "type", "") or "").lower()

    # ------------------------------------------------------------
    # (0) soft-limit 토글 (옵션이 꺼져있으면 spring/damper는 무시)
    # ------------------------------------------------------------
    soft_req = (spring_k is not None) or (damper_c is not None) or (spring_eq is not None)
    soft_enabled = _soft_limits_enabled_from_options(options)

    if soft_req and (not soft_enabled):
        _warn_once(
            "joint_soft_limits_disabled",
            f"[WARN] Joint '{getattr(jdef,'name','?')}': soft-limit params present but soft-limits are disabled by options. Ignored spring/damper params.",
            warnings=warnings,
        )
        spring_k = None
        damper_c = None
        spring_eq = None

    # ------------------------------------------------------------
    # (A) “직접 설정” 계열 API 후보
    # ------------------------------------------------------------
    direct_ok = False

    # lower/upper를 한 번에 받는 형태
    if lower is not None and upper is not None:
        for fn in ("SetLimits", "SetLimit", "SetJointLimits", "SetLimitRange"):
            direct_ok = _try_call(link, fn, float(lower), float(upper)) or direct_ok

    # 활성화/enable 형태
    for fn in ("SetLimitActive", "SetLimitsActive", "SetLimitEnabled", "SetLimitsEnabled"):
        direct_ok = _try_call(link, fn, True) or direct_ok

    # 어떤 바인딩은 축을 지정 (0/1) 하거나, lower/upper를 따로 받기도 함 → best-effort
    # (축 인덱스는 바인딩마다 의미가 달라서 "되면 좋은" 수준)
    if lower is not None:
        for fn in ("SetLimitMin", "SetMinLimit", "SetLowerLimit"):
            direct_ok = _try_call(link, fn, float(lower)) or direct_ok
    if upper is not None:
        for fn in ("SetLimitMax", "SetMaxLimit", "SetUpperLimit"):
            direct_ok = _try_call(link, fn, float(upper)) or direct_ok

    # ------------------------------------------------------------
    # (B) limit object 찾아서 주입 (Chrono에서 가장 흔한 경로)
    # ------------------------------------------------------------
    obj_ok_bounds = False
    obj_ok_stop = False
    obj_ok_soft = False

    cands = _find_limit_object_candidates(link, jtype)
    for lo in cands:
        obj_ok_bounds = _set_limit_obj_best_effort(lo, lower, upper) or obj_ok_bounds
        obj_ok_stop = _set_stop_params_best_effort(lo, stop_restitution, stop_damping) or obj_ok_stop
        if (spring_k is not None) or (damper_c is not None) or (spring_eq is not None):
            obj_ok_soft = _set_soft_params_best_effort(lo, spring_k, damper_c, spring_eq) or obj_ok_soft

    ok_bounds = bool(direct_ok or obj_ok_bounds)

    if (lower is not None or upper is not None) and (not ok_bounds):
        _warn_once(
            "joint_limits_bounds_unsupported",
            f"[WARN] Joint '{getattr(jdef,'name','?')}': bounds limits requested but no compatible limit API found in this binding. Ignored.",
            warnings=warnings,
        )

    if (stop_restitution is not None or stop_damping is not None) and (not obj_ok_stop):
        _warn_once(
            "joint_limits_stop_unsupported",
            f"[WARN] Joint '{getattr(jdef,'name','?')}': stop_* requested but no compatible stop API found. Ignored stop params.",
            warnings=warnings,
        )

    if ((spring_k is not None) or (damper_c is not None) or (spring_eq is not None)) and (not obj_ok_soft):
        _warn_once(
            "joint_limits_soft_unsupported",
            f"[WARN] Joint '{getattr(jdef,'name','?')}': soft-limit spring/damper requested but no compatible API found. Ignored soft params.",
            warnings=warnings,
        )
# ---------------------------------------------------------------------
# Joint creation
# ---------------------------------------------------------------------

def _build_joint(
    sys: Any,
    jdef: JointDef,
    bodyA: chrono.ChBody,
    bodyB: chrono.ChBody,
    *,
    options: Optional[Any] = None,
    warnings: Optional[List[str]] = None,
) -> chrono.ChLinkBase:
    fr = _to_chframe(jdef.frame)

    if jdef.type == "revolute":
        link = chrono.ChLinkLockRevolute()
        link.Initialize(bodyA, bodyB, fr)
        _apply_joint_limits_best_effort(link, jdef, options=options, warnings=warnings)
        _disable_collision_between_linked_bodies(link)
        sys.AddLink(link)
        return link

    if jdef.type == "prismatic":
        link = chrono.ChLinkLockPrismatic()
        link.Initialize(bodyA, bodyB, fr)
        _apply_joint_limits_best_effort(link, jdef, options=options, warnings=warnings)
        _disable_collision_between_linked_bodies(link)
        sys.AddLink(link)
        return link

    if jdef.type == "fixed":
        link = chrono.ChLinkLockLock()
        link.Initialize(bodyA, bodyB, fr)
        _apply_joint_limits_best_effort(link, jdef, options=options, warnings=warnings)  # 내부에서 스킵됨
        _disable_collision_between_linked_bodies(link)
        sys.AddLink(link)
        return link

    raise NotImplementedError(f"Joint '{jdef.name}': unsupported type '{jdef.type}'")

# ---------------------------------------------------------------------
# Gear pair creation (ideal constraint)
# ---------------------------------------------------------------------


def _compute_gear_ratio(gp: GearPairDef, bodies: Dict[str, BuiltBody]) -> float:
    propsA = bodies[gp.gearA].meta.mechanical.gearProps
    propsB = bodies[gp.gearB].meta.mechanical.gearProps
    if propsA is None or propsB is None:
        raise ValueError(f"GearPair '{gp.name}': gear bodies must have mechanical.gearProps")

    rA = _pitch_radius_from_gearprops(propsA.module, propsA.teeth)
    rB = _pitch_radius_from_gearprops(propsB.module, propsB.teeth)
    if abs(rB) < 1e-12:
        raise ValueError(f"GearPair '{gp.name}': invalid pitch radius for gearB")

    ratio = (rA / rB) * float(getattr(gp, "ratio_sign", -1))
    return float(ratio)


def _resolve_gear_pair_props_guardrailed(gp: GearPairDef) -> Tuple[bool, float, float, Optional[float]]:
    """
    ✅ NEW (3-1.2):
    metadata에서 gearPair props를 best-effort로 읽고, runtime 안정용 최소 clamp를 한 번 더 적용.
    - 최신 스키마: gp.props
    - 구 스키마(호환): gp.gearProps
    """
    raw = getattr(gp, "props", None)
    if raw is None:
        raw = getattr(gp, "gearProps", None)

    enabled = True
    eff = 1.0
    backlash = 0.0
    max_torque: Optional[float] = None

    if raw is not None:
        try:
            enabled = bool(getattr(raw, "enabled", True))
        except Exception:
            enabled = True
        try:
            eff = float(getattr(raw, "efficiency", 1.0))
        except Exception:
            eff = 1.0
        try:
            backlash = float(getattr(raw, "backlash", 0.0))
        except Exception:
            backlash = 0.0
        try:
            mt = getattr(raw, "max_torque", None)
            max_torque = float(mt) if mt is not None else None
        except Exception:
            max_torque = None

    # guardrails (runtime safety)
    eff = _clamp(float(eff), 0.0, 1.0)
    backlash = max(0.0, float(backlash))
    if max_torque is not None:
        max_torque = max(0.0, float(max_torque))

    return enabled, eff, backlash, max_torque


def _build_gear_pair(sys: Any, gp: GearPairDef, bodies: Dict[str, BuiltBody], joints: Dict[str, BuiltJoint]) -> chrono.ChLinkBase:
    gearA = bodies[gp.gearA].body
    gearB = bodies[gp.gearB].body

    propsA = bodies[gp.gearA].meta.mechanical.gearProps
    propsB = bodies[gp.gearB].meta.mechanical.gearProps
    if propsA is None or propsB is None:
        raise ValueError(f"GearPair '{gp.name}': gear bodies must have mechanical.gearProps")

    rA = _pitch_radius_from_gearprops(propsA.module, propsA.teeth)
    rB = _pitch_radius_from_gearprops(propsB.module, propsB.teeth)
    if abs(rB) < 1e-12:
        raise ValueError(f"GearPair '{gp.name}': invalid pitch radius for gearB")

    ratio = (rA / rB) * float(getattr(gp, "ratio_sign", -1))

    link = chrono.ChLinkLockGear()
    fr = _to_chframe(gp.meshFrame) if gp.meshFrame is not None else _to_chframe(bodies[gp.gearA].meta.pose)

    link.Initialize(gearA, gearB, fr)
    link.SetTransmissionRatio(float(ratio))
    link.SetEnforcePhase(bool(getattr(gp, "enforcePhase", False)))
    sys.AddLink(link)
    return link


# ---------------------------------------------------------------------
# Actuators
# ---------------------------------------------------------------------


def _build_actuator(sys: Any, adef: ActuatorDef, joints: Dict[str, BuiltJoint], bodies: Dict[str, BuiltBody]) -> chrono.ChLinkBase:
    if adef.targetJoint not in joints:
        raise ValueError(f"Actuator '{adef.name}': targetJoint '{adef.targetJoint}' not found")

    target_joint = joints[adef.targetJoint]
    jmeta = target_joint.meta

    if jmeta.body1 not in bodies or jmeta.body2 not in bodies:
        raise ValueError(f"Actuator '{adef.name}': joint refers missing bodies: {jmeta.body1}, {jmeta.body2}")
    body1 = bodies[jmeta.body1].body
    body2 = bodies[jmeta.body2].body

    fr = _to_chframe(jmeta.frame)

    if adef.type == "rotation_speed":
        if adef.speed is None:
            raise ValueError(f"Actuator '{adef.name}': rotation_speed requires speed")
        motor = chrono.ChLinkMotorRotationSpeed()
        motor.Initialize(body1, body2, fr)
        motor.SetSpeedFunction(chrono.ChFunctionConst(float(adef.speed)))
        sys.AddLink(motor)
        return motor

    if adef.type == "rotation_torque":
        if adef.torqueModel is None:
            raise ValueError(f"Actuator '{adef.name}': rotation_torque requires torqueModel")

        tau = float(getattr(adef.torqueModel, "value", 0.0))

        if hasattr(chrono, "ChLinkMotorRotationTorque"):
            motor = chrono.ChLinkMotorRotationTorque()
            motor.Initialize(body1, body2, fr)
            motor.SetTorqueFunction(chrono.ChFunctionConst(tau))
            sys.AddLink(motor)
            return motor

        raise NotImplementedError(
            "PyChrono build does not expose ChLinkMotorRotationTorque. "
            "Use per-step body torque application in Simulator.step instead."
        )

    raise NotImplementedError(f"Actuator '{adef.name}': unsupported type '{adef.type}'")


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------

def build_system_from_scene(meta: SceneMeta, options: Optional[Any] = None) -> BuildResult:
    # 0) resolve physics config
    cfg = _resolve_physics_config(options)
    sys = _create_system_by_contact_method(cfg.get("contact_method", "NSC"))

    # collision backend 강제 (바인딩/버전별 기본값 불안정 대비)
    try:
        cs = getattr(chrono, "ChCollisionSystem", None)
        if cs is not None and hasattr(cs, "Type_BULLET") and hasattr(sys, "SetCollisionSystemType"):
            sys.SetCollisionSystemType(cs.Type_BULLET)
    except Exception:
        pass

    # apply preset knobs to system
    _apply_physics_preset_to_system(sys, cfg)

    # gravity (best-effort across bindings)
    g = _to_chvec(meta.gravity)
    _applied_g = False
    for fn in ("SetGravitationalAcceleration", "Set_G_acc", "SetGravAcceleration", "SetGravity"):
        try:
            if hasattr(sys, fn):
                getattr(sys, fn)(g)
                _applied_g = True
                break
        except Exception:
            pass

    if not _applied_g:
        try:
            print("[WARN] Could not set gravity: no compatible gravity API found on this Chrono binding.")
        except Exception:
            pass

    bodies: Dict[str, BuiltBody] = {}
    joints: Dict[str, BuiltJoint] = {}
    actuators: Dict[str, BuiltActuator] = {}
    gear_links: Dict[str, chrono.ChLinkBase] = {}

    # ✅ NEW: collect warnings for main.py to summarize
    warnings: List[str] = []

    # ✅ NEW (3-1.2): gear build infos for runtime
    gear_infos: Dict[str, GearBuildInfo] = {}
    # ✅ NEW
    guide_infos: Dict[str, AssemblyGuideInfo] = {}

    # 1) bodies
    for b in meta.bodies:
        if b.name in bodies:
            raise ValueError(f"Duplicate body name: {b.name}")
        cb = _build_body(sys, b, cfg=cfg)
        bodies[b.name] = BuiltBody(name=b.name, meta=b, body=cb)

    # 2) joints
    for j in meta.joints:
        if j.name in joints:
            raise ValueError(f"Duplicate joint name: {j.name}")
        if j.body1 not in bodies or j.body2 not in bodies:
            raise ValueError(f"Joint '{j.name}' refers missing bodies: {j.body1}, {j.body2}")

        link = _build_joint(
            sys,
            j,
            bodies[j.body1].body,
            bodies[j.body2].body,
            options=options,
            warnings=warnings,
        )
        if hasattr(link, "SetName"):
            link.SetName(j.name)
        joints[j.name] = BuiltJoint(name=j.name, meta=j, link=link)

    # 3) gearPairs (ideal constraint)
    for gp in meta.gearPairs:
        if gp.name in joints:
            raise ValueError(f"GearPair name collides with joint name: {gp.name}")

        # ✅ NEW (3-1.2): capture gear settings (no physics applied here)
        ratio = _compute_gear_ratio(gp, bodies)
        enabled, eff, backlash, max_torque = _resolve_gear_pair_props_guardrailed(gp)

        gear_infos[str(gp.name)] = GearBuildInfo(
            name=str(gp.name),
            gearA=str(gp.gearA),
            gearB=str(gp.gearB),
            ratio=float(ratio),
            enabled=bool(enabled),
            efficiency=float(eff),
            backlash=float(backlash),
            max_torque=float(max_torque) if max_torque is not None else None,
        )

        link = _build_gear_pair(sys, gp, bodies, joints)
        if hasattr(link, "SetName"):
            link.SetName(gp.name)
        try:
            gear_links[str(gp.name)] = link
        except Exception:
            pass
    # 3-2: assembly guides (runtime only, no physics)
    for g in getattr(meta, "assemblyGuides", []):
        try:
            guide_infos[str(g.name)] = AssemblyGuideInfo(
                name=str(g.name),
                partA=str(g.partA),
                partB=str(g.partB),
                snapTargets=list(getattr(g, "snapTargets", [])),

                alignAxis=getattr(g, "alignAxis", None),

                positionTolerance=float(getattr(g, "positionTolerance", 0.0)),
                angleTolerance=float(getattr(g, "angleTolerance", 0.0)),

                snapStrength=float(getattr(g, "snapStrength", 0.0)),

                enabled=bool(getattr(g, "enabled", True)),
            )
        except Exception:
            pass

    # 1-2: apply collision filtering policy
    _apply_collision_filter_policy(meta=meta, bodies=bodies)

    # 4) actuators
    for a in meta.actuators:
        if a.name in actuators:
            raise ValueError(f"Duplicate actuator name: {a.name}")
        link = _build_actuator(sys, a, joints, bodies)
        if hasattr(link, "SetName"):
            link.SetName(a.name)
        actuators[a.name] = BuiltActuator(name=a.name, meta=a, link=link)

    name_to_body = {k: v.body for k, v in bodies.items()}

    name_to_link: Dict[str, chrono.ChLinkBase] = {}
    for k, v in joints.items():
        name_to_link[k] = v.link
    for k, v in actuators.items():
        name_to_link[k] = v.link
    for k, v in gear_links.items():
        if k not in name_to_link:
            name_to_link[k] = v

    try:
        for link in sys.GetLinks():
            if hasattr(link, "GetName"):
                nm = link.GetName()
                if nm and nm not in name_to_link:
                    name_to_link[nm] = link
    except Exception:
        pass

    return BuildResult(
        sys=sys,
        bodies=bodies,
        joints=joints,
        actuators=actuators,
        name_to_body=name_to_body,
        name_to_link=name_to_link,
        warnings=warnings,
        gear_pairs=gear_infos,
        assembly_guides=guide_infos,
    )