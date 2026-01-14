# simulator/sim_builder.py
# Build a PyChrono simulation system from SimInfo/SceneMeta (strict metadata-only).
# Target: Project Chrono / PyChrono 8.0.0
#
# - No inference from OBJ/CAD. Everything must be specified in metadata.
# - Physics uses simple collision primitives; visuals use mesh (OBJ) with optional local offset.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pychrono as chrono

from simulator.SimInfo import (  # <- 너희가 "공식 계약"으로 쓰는 SimInfo.py에 맞춰 import 경로 조정
    SceneMeta,
    BodyDef,
    JointDef,
    GearPairDef,
    ActuatorDef,
    Vec3,
    Quat,
    Pose,
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
    # convenience mappings
    name_to_body: Dict[str, chrono.ChBody]
    name_to_link: Dict[str, chrono.ChLinkBase]


# ---------------------------------------------------------------------
# Small conversion helpers
# ---------------------------------------------------------------------


def _to_chvec(v: Vec3) -> chrono.ChVector3d:
    return chrono.ChVector3d(float(v.x), float(v.y), float(v.z))


def _to_chquat(q: Quat) -> chrono.ChQuaterniond:
    # Chrono constructor ordering: (e0,e1,e2,e3) == (w,x,y,z)
    return chrono.ChQuaterniond(float(q.w), float(q.x), float(q.y), float(q.z))


def _to_chframe(p: Pose) -> chrono.ChFramed:
    return chrono.ChFramed(_to_chvec(p.pos), _to_chquat(p.rot))


def _pitch_radius_from_gearprops(module_m: float, teeth: int) -> float:
    # pitch radius r = (m * z) / 2
    return 0.5 * float(module_m) * float(teeth)


# ---------------------------------------------------------------------
# Contact material (NSC)
# ---------------------------------------------------------------------


def _make_contact_material_nsc(mu: float, restitution: float) -> chrono.ChContactMaterialNSC:
    mat = chrono.ChContactMaterialNSC()
    mat.SetFriction(float(mu))
    mat.SetRestitution(float(restitution))
    return mat


# ---------------------------------------------------------------------
# Collision shape builders (primitive-only)
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
    # PyChrono 8: preferred API is AddCollisionShape(Shape, Frame)
    shape = chrono.ChCollisionShapeBox(mat, float(hx), float(hy), float(hz))
    body.AddCollisionShape(shape, fr)


def _add_collision_cylinder(
    body: chrono.ChBody,
    mat: chrono.ChContactMaterialNSC,
    radius: float,
    length: float,
    frame: Optional[chrono.ChFramed] = None,
) -> None:
    # Chrono cylinder uses half-length parameter in some contexts,
    # but collision shape constructor here expects (radius, half_length)
    fr = frame if frame is not None else chrono.ChFramed()
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


# ---------------------------------------------------------------------
# Visual shape builders (mesh-only)
# ---------------------------------------------------------------------


def _attach_visual_mesh(
    body: chrono.ChBody,
    mesh_file: str,
    scale: chrono.ChVector3d,
    offset: chrono.ChFramed,
) -> None:
    """
    Attach mesh for visualization only.
    NOTE: Visual offset is BODY-LOCAL (per your schema).
    """
    # Load triangle mesh
    mesh = chrono.ChTriangleMeshConnected()
    mesh.LoadWavefrontMesh(str(mesh_file), False, True)  # (filename, load_normals, flip_yz) - depends on export; keep as earlier prototype

    vshape = chrono.ChVisualShapeTriangleMesh()
    vshape.SetMesh(mesh)
    vshape.SetScale(scale)

    # AddVisualShape(shape, frame) exists in Chrono 8 python bindings
    body.AddVisualShape(vshape, offset)


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
        # basic diagonal inertia
        Ixx = float(inertia.Ixx or 0.0)
        Iyy = float(inertia.Iyy or 0.0)
        Izz = float(inertia.Izz or 0.0)
        body.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))
    else:
        # auto_from_collision (simple placeholder):
        # In Chrono you can compute inertia from collision shapes,
        # but implementing a full auto pipeline is non-trivial.
        # Here we set a conservative diagonal; you can refine later.
        mval = float(bdef.mechanical.mass)
        body.SetInertiaXX(chrono.ChVector3d(1e-3 * mval, 1e-3 * mval, 1e-3 * mval))

    # contact material (NSC)
    c = bdef.mechanical.contact
    mat = _make_contact_material_nsc(c.friction, c.restitution)

    # collision
    col = bdef.geometry.collision
    body.EnableCollision(True)

    if col.kind == "box":
        if col.hx is None or col.hy is None or col.hz is None:
            raise ValueError(f"Body '{bdef.name}': collision.box requires hx,hy,hz")
        _add_collision_box(body, mat, col.hx, col.hy, col.hz)

    elif col.kind == "cylinder":
        if col.radius is None or col.length is None:
            raise ValueError(f"Body '{bdef.name}': collision.cylinder requires radius,length")
        _add_collision_cylinder(body, mat, col.radius, col.length)

    elif col.kind == "sphere":
        # schema uses r or radius? (your metadata_types uses r but from_dict uses d["radius"])
        r = col.r if col.r is not None else getattr(col, "radius", None)
        if r is None:
            raise ValueError(f"Body '{bdef.name}': collision.sphere requires radius")
        _add_collision_sphere(body, mat, float(r))

    else:
        raise NotImplementedError(f"Body '{bdef.name}': unsupported collision kind '{col.kind}'")

    # visual mesh
    vis = bdef.geometry.visual
    if vis.kind == "mesh":
        scale = _to_chvec(vis.scale)
        offset = _to_chframe(vis.offset)  # BODY-LOCAL by convention (schema)
        _attach_visual_mesh(body, vis.file, scale, offset)

    sys.AddBody(body)
    return body


# ---------------------------------------------------------------------
# Joint creation
# ---------------------------------------------------------------------


def _build_joint(sys: chrono.ChSystemNSC, jdef: JointDef, bodyA: chrono.ChBody, bodyB: chrono.ChBody) -> chrono.ChLinkBase:
    fr = _to_chframe(jdef.frame)  # WORLD frame, local Z is DOF axis by convention

    if jdef.type == "revolute":
        link = chrono.ChLinkLockRevolute()
        link.Initialize(bodyA, bodyB, fr)
        sys.AddLink(link)
        return link

    if jdef.type == "prismatic":
        link = chrono.ChLinkLockPrismatic()
        link.Initialize(bodyA, bodyB, fr)
        sys.AddLink(link)
        return link

    if jdef.type == "fixed":
        link = chrono.ChLinkLockLock()
        link.Initialize(bodyA, bodyB, fr)
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

    # pitch radii from gearProps on bodies (required per schema)
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

    # meshFrame: WORLD frame. If not provided, use identity.
    if gp.meshFrame is not None:
        fr = _to_chframe(gp.meshFrame)
    else:
        fr = chrono.ChFramed()

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
) -> chrono.ChLinkBase:
    """
    Actuators target a joint frame Z-axis by design.
    For speed motor: we create a motor link between the same two bodies as the joint,
    and initialize it with the joint's frame.
    """
    if adef.targetJoint not in joints:
        raise ValueError(f"Actuator '{adef.name}': targetJoint '{adef.targetJoint}' not found")

    target_joint = joints[adef.targetJoint]
    jmeta = target_joint.meta

    # recover bodies from the joint link
    # ChLinkLockRevolute etc. expose GetBody1/GetBody2 in Chrono
    body1 = target_joint.link.GetBody1()
    body2 = target_joint.link.GetBody2()
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
        # 현실적 토크 모델: simplest approach is to apply a torque via a link (if available)
        # In Chrono, a common approach is ChLinkMotorRotationTorque (torque motor),
        # or apply torque directly to a body each step.
        #
        # We'll use ChLinkMotorRotationTorque if present in PyChrono 8.
        if adef.torqueModel is None:
            raise ValueError(f"Actuator '{adef.name}': rotation_torque requires torqueModel")

        # only const supported in schema right now
        const_model = adef.torqueModel
        tau = float(getattr(const_model, "value", 0.0))

        if hasattr(chrono, "ChLinkMotorRotationTorque"):
            motor = chrono.ChLinkMotorRotationTorque()
            motor.Initialize(body1, body2, fr)
            motor.SetTorqueFunction(chrono.ChFunctionConst(tau))
            sys.AddLink(motor)
            return motor

        # fallback: raise and let caller implement per-step torque application
        raise NotImplementedError(
            "PyChrono build does not expose ChLinkMotorRotationTorque. "
            "Use per-step body torque application in Simulator.step instead."
        )

    raise NotImplementedError(f"Actuator '{adef.name}': unsupported type '{adef.type}'")


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------


def build_system_from_scene(meta: SceneMeta) -> BuildResult:
    """
    Build a Chrono system from metadata.
    Returns registries for easy lookups.
    """
    # system
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

    # 3) gearPairs (as links too; store under joints registry or separate? we keep separate by name_to_link)
    for gp in meta.gearPairs:
        if gp.name in joints:
            raise ValueError(f"GearPair name collides with joint name: {gp.name}")
        link = _build_gear_pair(sys, gp, bodies, joints)
        if hasattr(link, "SetName"):
            link.SetName(gp.name)
        # store in name_to_link only (not in joints dict to keep joint types strict)
        # (if you prefer, you can store as BuiltJoint too)

    # 4) actuators
    for a in meta.actuators:
        if a.name in actuators:
            raise ValueError(f"Duplicate actuator name: {a.name}")
        link = _build_actuator(sys, a, joints)
        if hasattr(link, "SetName"):
            link.SetName(a.name)
        actuators[a.name] = BuiltActuator(name=a.name, meta=a, link=link)

    # convenience maps
    name_to_body = {k: v.body for k, v in bodies.items()}

    # collect all links: joints + gear links + actuators (gear links not stored separately above)
    name_to_link: Dict[str, chrono.ChLinkBase] = {}
    for k, v in joints.items():
        name_to_link[k] = v.link
    for k, v in actuators.items():
        name_to_link[k] = v.link

    # gear links were added to system but not stored; optionally enumerate sys links
    # Here we add any named links not yet in name_to_link.
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
