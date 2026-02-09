# simulator/sim_builder.py
# Build a PyChrono simulation system from SceneMeta.
#
# Updates:
# - geometry.collision supports:
#   1) single primitive
#   2) multiple primitives (list)
#   3) "auto" (explicit opt-in) -> approximate from OBJ mesh (base=box, shaft=cyl + optional hub cyl)
#
# Target: Project Chrono / PyChrono 8.x
# Notes:
# - No hidden inference by default: auto is allowed ONLY when metadata explicitly says collision == "auto"/{kind:"auto"}.
# - Visual mesh is for visualization only; collision uses primitives.
# - Auto-approx now applies visual.scale and visual.offset to OBJ vertices (mesh-local -> body-local).

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import math as m
import pychrono as chrono

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
)

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


@dataclass
class BuildResult:
    sys: chrono.ChSystemNSC
    bodies: Dict[str, BuiltBody]
    joints: Dict[str, BuiltJoint]
    actuators: Dict[str, BuiltActuator]
    name_to_body: Dict[str, chrono.ChBody]
    name_to_link: Dict[str, chrono.ChLinkBase]


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
# Contact material (NSC)
# ---------------------------------------------------------------------


def _make_contact_material_nsc(mu: float, restitution: float) -> chrono.ChContactMaterialNSC:
    mat = chrono.ChContactMaterialNSC()
    mat.SetFriction(float(mu))
    mat.SetRestitution(float(restitution))
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
    # elementwise multiply
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
    # (w,x,y,z)
    return Quat(
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
    )


def _rotate_vec_by_quat(v: Tuple[float, float, float], q: Quat) -> Tuple[float, float, float]:
    # v' = q * (0,v) * q_conj
    p = Quat(0.0, v[0], v[1], v[2])
    qq = _quat_mul(_quat_mul(q, p), _quat_conj(q))
    return (qq.x, qq.y, qq.z)


# ---------------------------------------------------------------------
# Joint collision policy helper
# ---------------------------------------------------------------------


def _disable_collision_between_linked_bodies(link: chrono.ChLinkBase) -> None:
    """
    Common stability policy:
    - If two bodies are directly connected by a kinematic joint (revolute/prismatic/fixed),
      disable collision between those two bodies.

    Notes:
    - This does NOT disable body collisions globally.
    - Only the linked pair's mutual collision is disabled (Chrono link-side flag).
    - Binding API names can differ across Chrono/PyChrono versions; try multiple options.
    """
    # Most Chrono links expose SetCollide(bool)
    try:
        if hasattr(link, "SetCollide"):
            link.SetCollide(False)
            return
    except Exception:
        pass

    # Some bindings may expose alternate names
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
    """
    OBJ vertices (mesh-local) -> body-local

    v_body = R(offset.rot) * (v_mesh ⊙ scale) + offset.pos
    """
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
    ext = ((mx[0] - mn[0]) * 0.5, (mx[1] - mn[1]) * 0.5, (mx[2] - mn[2]) * 0.5)  # half extents
    return mn, mx, center, ext


def _pca_main_axis(verts: List[Tuple[float, float, float]]) -> Tuple[float, float, float]:
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
    """
    Returns:
      center_c:  AABB center (body-local)
      axis:      main axis unit vector (body-local)
      length:    projected length along axis (full length)
      radius:    baseline shaft radius
      s_center:  center position along axis in coordinate where s=dot(p-c,axis)
      hub:       optional dict {length, radius, s_center}
    """
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
        # fallback: use AABB
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

    k = max(1, int(0.2 * len(med_sorted)))
    baseline = sum(med_sorted[:k]) / k

    thr = baseline * 1.35
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


# ---------------------------------------------------------------------
# Collision shape builders (primitive-only) + offset frame
# ---------------------------------------------------------------------


def _add_collision_box(
    body: chrono.ChBody,
    mat: chrono.ChContactMaterialNSC,
    hx: float,
    hy: float,
    hz: float,
    frame: Optional[chrono.ChFramed] = None,
) -> None:
    fr = frame if frame is not None else chrono.ChFramed()
    shape = chrono.ChCollisionShapeBox(mat, float(hx), float(hy), float(hz))
    body.AddCollisionShape(shape, fr)


def _add_collision_cylinder(
    body: chrono.ChBody,
    mat: chrono.ChContactMaterialNSC,
    radius: float,
    length: float,
    frame: Optional[chrono.ChFramed] = None,
) -> None:
    fr = frame if frame is not None else chrono.ChFramed()
    # Chrono cylinder takes (radius, half_length)
    shape = chrono.ChCollisionShapeCylinder(mat, float(radius), float(0.5 * length))
    body.AddCollisionShape(shape, fr)


def _add_collision_sphere(
    body: chrono.ChBody,
    mat: chrono.ChContactMaterialNSC,
    radius: float,
    frame: Optional[chrono.ChFramed] = None,
) -> None:
    fr = frame if frame is not None else chrono.ChFramed()
    shape = chrono.ChCollisionShapeSphere(mat, float(radius))
    body.AddCollisionShape(shape, fr)


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


def _apply_collision_primitive(
    body: chrono.ChBody,
    mat: chrono.ChContactMaterialNSC,
    prim: CollisionPrimitive,
) -> None:
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


def _attach_visual_mesh(
    body: chrono.ChBody,
    mesh_file: str,
    scale: chrono.ChVector3d,
    offset: chrono.ChFramed,
) -> None:
    mesh = chrono.ChTriangleMeshConnected()
    mesh.LoadWavefrontMesh(str(mesh_file), False, True)

    vshape = chrono.ChVisualShapeTriangleMesh()
    vshape.SetMesh(mesh)
    vshape.SetScale(scale)

    body.AddVisualShape(vshape, offset)


# ---------------------------------------------------------------------
# Auto collision (from OBJ) -> list[CollisionPrimitive]
# ---------------------------------------------------------------------


def _auto_collision_from_obj(bdef: BodyDef, auto: CollisionAuto) -> List[CollisionPrimitive]:
    vis = bdef.geometry.visual
    if vis.kind != "mesh" or not getattr(vis, "file", None):
        raise ValueError(f"Body '{bdef.name}': collision.auto requires geometry.visual.kind='mesh' and visual.file")

    obj_file = str(vis.file)

    # 1) load mesh-local vertices
    verts_mesh = _load_obj_vertices(obj_file)

    # 2) mesh-local -> body-local (apply visual.scale + visual.offset)
    verts = _apply_visual_to_vertices(
        verts_mesh,
        scale=vis.scale,
        offset=vis.offset,
    )

    strategy = str(auto.strategy)
    cat = str(getattr(bdef, "category", "generic"))

    # ---- strategy overrides ----
    if strategy in ("aabb_box", "base_aabb"):
        _, _, center, half_ext = _compute_aabb(verts)
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

    if strategy == "shaft_pca_hub2cyl":
        c, axis, L, R, s_center, hub = _approx_shaft_with_hub_from_obj(verts)
        q = _quat_from_two_vectors((0.0, 0.0, 1.0), (axis[0], axis[1], axis[2]))

        center_main = _add(c, _mul(axis, float(s_center)))
        prims = [
            CollisionPrimitive(
                kind="cylinder",
                radius=float(R),
                length=float(L),
                offset=_pose_from_center_rot(center_main, q),
            )
        ]

        if hub and float(hub.get("length", 0.0)) > 1e-5 and float(hub.get("radius", 0.0)) > float(R) * 1.2:
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

    # ---- default behavior (category-based) ----
    if cat == "base":
        center, size = _approx_base_from_obj(verts)
        hx, hy, hz = 0.5 * size[0], 0.5 * size[1], 0.5 * size[2]
        off = _pose_from_center_rot(center, Quat(1.0, 0.0, 0.0, 0.0))
        return [CollisionPrimitive(kind="box", hx=float(hx), hy=float(hy), hz=float(hz), offset=off)]

    if cat == "shaft":
        c, axis, L, R, s_center, hub = _approx_shaft_with_hub_from_obj(verts)
        q = _quat_from_two_vectors((0.0, 0.0, 1.0), (axis[0], axis[1], axis[2]))

        center_main = _add(c, _mul(axis, float(s_center)))
        prims = [
            CollisionPrimitive(
                kind="cylinder",
                radius=float(R),
                length=float(L),
                offset=_pose_from_center_rot(center_main, q),
            )
        ]
        if hub and float(hub.get("length", 0.0)) > 1e-5 and float(hub.get("radius", 0.0)) > float(R) * 1.2:
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

    # fallback: aabb box
    _, _, center, half_ext = _compute_aabb(verts)
    off = _pose_from_center_rot(center, Quat(1.0, 0.0, 0.0, 0.0))
    return [CollisionPrimitive(kind="box", hx=float(half_ext[0]), hy=float(half_ext[1]), hz=float(half_ext[2]), offset=off)]


# ---------------------------------------------------------------------
# Body creation
# ---------------------------------------------------------------------


def _build_body(sys: chrono.ChSystemNSC, bdef: BodyDef) -> chrono.ChBody:
    body = chrono.ChBody()
    body.SetName(bdef.name)

    # pose (WORLD)
    body.SetPos(_to_chvec(bdef.pose.pos))
    body.SetRot(_to_chquat(bdef.pose.rot))

    # fixed / mass
    body.SetFixed(bool(bdef.mechanical.fixed))
    body.SetMass(float(bdef.mechanical.mass))

    # inertia
    inertia = bdef.mechanical.inertia
    if inertia.mode == "explicit":
        Ixx = float(inertia.Ixx or 0.0)
        Iyy = float(inertia.Iyy or 0.0)
        Izz = float(inertia.Izz or 0.0)
        body.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))
    else:
        mval = float(bdef.mechanical.mass)
        body.SetInertiaXX(chrono.ChVector3d(1e-3 * mval, 1e-3 * mval, 1e-3 * mval))

    # contact material (NSC)
    c = bdef.mechanical.contact
    mat = _make_contact_material_nsc(c.friction, c.restitution)

    # collision
    body.EnableCollision(True)
    _reset_collision_model(body)

    col = bdef.geometry.collision

    if isinstance(col, CollisionAuto):
        prims = _auto_collision_from_obj(bdef, col)
        for p in prims:
            _apply_collision_primitive(body, mat, p)
    elif isinstance(col, list):
        if not col:
            raise ValueError(f"Body '{bdef.name}': collision list is empty")
        for prim in col:
            _apply_collision_primitive(body, mat, prim)
    else:
        _apply_collision_primitive(body, mat, col)

    _finalize_collision_model(body)

    # visual mesh (visual offset is BODY-LOCAL by schema)
    vis = bdef.geometry.visual
    if vis.kind == "mesh":
        scale = _to_chvec(vis.scale)
        offset = _to_chframe(vis.offset)
        _attach_visual_mesh(body, vis.file, scale, offset)

    sys.AddBody(body)
    return body


# ---------------------------------------------------------------------
# Joint creation
# ---------------------------------------------------------------------


def _build_joint(sys: chrono.ChSystemNSC, jdef: JointDef, bodyA: chrono.ChBody, bodyB: chrono.ChBody) -> chrono.ChLinkBase:
    fr = _to_chframe(jdef.frame)  # WORLD frame, local Z is DOF axis

    if jdef.type == "revolute":
        link = chrono.ChLinkLockRevolute()
        link.Initialize(bodyA, bodyB, fr)
        # ✅ stability: disable collision between joint-linked bodies
        _disable_collision_between_linked_bodies(link)
        sys.AddLink(link)
        return link

    if jdef.type == "prismatic":
        link = chrono.ChLinkLockPrismatic()
        link.Initialize(bodyA, bodyB, fr)
        # ✅ stability: disable collision between joint-linked bodies
        _disable_collision_between_linked_bodies(link)
        sys.AddLink(link)
        return link

    if jdef.type == "fixed":
        link = chrono.ChLinkLockLock()
        link.Initialize(bodyA, bodyB, fr)
        # ✅ stability: disable collision between joint-linked bodies
        _disable_collision_between_linked_bodies(link)
        sys.AddLink(link)
        return link

    raise NotImplementedError(f"Joint '{jdef.name}': unsupported type '{jdef.type}'")


# ---------------------------------------------------------------------
# Gear pair creation (ideal constraint)
# ---------------------------------------------------------------------


def _build_gear_pair(
    sys: chrono.ChSystemNSC,
    gp: GearPairDef,
    bodies: Dict[str, BuiltBody],
    joints: Dict[str, BuiltJoint],
) -> chrono.ChLinkBase:
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

    ratio = (rA / rB) * float(gp.ratio_sign)

    link = chrono.ChLinkLockGear()
    fr = _to_chframe(gp.meshFrame) if gp.meshFrame is not None else _to_chframe(bodies[gp.gearA].meta.pose)

    link.Initialize(gearA, gearB, fr)
    link.SetTransmissionRatio(float(ratio))
    link.SetEnforcePhase(bool(gp.enforcePhase))
    sys.AddLink(link)
    return link


# ---------------------------------------------------------------------
# Actuators
# ---------------------------------------------------------------------


def _build_actuator(
    sys: chrono.ChSystemNSC,
    adef: ActuatorDef,
    joints: Dict[str, BuiltJoint],
    bodies: Dict[str, BuiltBody],
) -> chrono.ChLinkBase:
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


def build_system_from_scene(meta: SceneMeta) -> BuildResult:
    sys = chrono.ChSystemNSC()
    sys.SetGravitationalAcceleration(_to_chvec(meta.gravity))

    bodies: Dict[str, BuiltBody] = {}
    joints: Dict[str, BuiltJoint] = {}
    actuators: Dict[str, BuiltActuator] = {}

    # 1) bodies
    for b in meta.bodies:
        if b.name in bodies:
            raise ValueError(f"Duplicate body name: {b.name}")
        cb = _build_body(sys, b)
        bodies[b.name] = BuiltBody(name=b.name, meta=b, body=cb)

    # 2) joints
    for j in meta.joints:
        if j.name in joints:
            raise ValueError(f"Duplicate joint name: {j.name}")
        if j.body1 not in bodies or j.body2 not in bodies:
            raise ValueError(f"Joint '{j.name}' refers missing bodies: {j.body1}, {j.body2}")
        link = _build_joint(sys, j, bodies[j.body1].body, bodies[j.body2].body)
        if hasattr(link, "SetName"):
            link.SetName(j.name)
        joints[j.name] = BuiltJoint(name=j.name, meta=j, link=link)

    # 3) gearPairs
    for gp in meta.gearPairs:
        if gp.name in joints:
            raise ValueError(f"GearPair name collides with joint name: {gp.name}")
        link = _build_gear_pair(sys, gp, bodies, joints)
        if hasattr(link, "SetName"):
            link.SetName(gp.name)

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
    )
