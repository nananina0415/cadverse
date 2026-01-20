## 시뮬레이션 엔진을 만들기 위한 연습용 코드
## 메타데이터 기반으로 바디/조인트/엑추에이터를 생성
## 특정 CAD 모델의 물리용 충돌 형상을 단순 실린더로 근사
## 근사한 충돌 형상에 시각화용 메쉬(OBJ)를 덧씌움

import math as m
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

import pychrono as chrono
import pychrono.irrlicht as chronoirr


# =========================
# 1. 데이터 구조 정의
# =========================

@dataclass
class GearProps:
    module: float      # [m]
    teeth: int
    face_width: float  # [m]
    pressure_angle_deg: float = 20.0
    helix_angle_deg: float = 0.0
    backlash: float = 0.0

    @property
    def pitch_radius(self) -> float:
        return 0.5 * self.module * self.teeth


@dataclass
class BodyHandle:
    name: str
    category: str
    body: chrono.ChBody
    gearProps: Optional[GearProps] = None
    raw_meta: Dict[str, Any] = None


@dataclass
class JointHandle:
    name: str
    type: str
    joint: chrono.ChLinkBase


@dataclass
class ActuatorHandle:
    name: str
    type: str
    link: chrono.ChLinkBase


@dataclass
class SimHandle:
    sys: chrono.ChSystemNSC
    bodies: Dict[str, BodyHandle]
    joints: Dict[str, JointHandle]
    actuators: Dict[str, ActuatorHandle]


# =========================
# 2. 유틸: material / visual / collision
# =========================

def _make_contact_material(sys: chrono.ChSystemNSC, contact_meta: Dict[str, Any]):
    """NSC/SMC에 맞춰 contact material 생성 (없으면 기본값)."""
    mu = float(contact_meta.get("friction", 0.4))
    cr = float(contact_meta.get("restitution", 0.0))

    # 네 코드는 ChSystemNSC 고정이므로 NSC 기준으로 만듦.
    # (나중에 SMC로 바꾸면 여기에서 분기)
    try:
        mat = chrono.ChContactMaterialNSC()
        mat.SetFriction(mu)
        mat.SetRestitution(cr)
        return mat
    except Exception:
        return None


def _add_visual_mesh(body: chrono.ChBody, vdef: Dict[str, Any]):
    """
    OBJ/mesh를 시각화로만 붙임.
    vdef 예:
      {"kind":"mesh","file":"gear_A_scaled.obj","scale":[1,1,1],"offset":{"pos":[...],"rot":[...]}}
    """
    if not vdef:
        return
    if vdef.get("kind", "mesh") != "mesh":
        return

    mesh_file = vdef.get("file")
    if not mesh_file:
        return

    # offset (visual frame)
    off = vdef.get("offset", {})
    ox, oy, oz = off.get("pos", [0.0, 0.0, 0.0])
    oqw, oqx, oqy, oqz = off.get("rot", [1.0, 0.0, 0.0, 0.0])
    vframe = chrono.ChFramed(chrono.ChVector3d(ox, oy, oz),
                            chrono.ChQuaterniond(oqw, oqx, oqy, oqz))

    # scale
    sc = vdef.get("scale", [1.0, 1.0, 1.0])
    sx, sy, sz = float(sc[0]), float(sc[1]), float(sc[2])

    # PyChrono 버전별로 shape class 이름이 다를 수 있어 try/except로 흡수
    try:
        shape = chrono.ChVisualShapeModelFile(mesh_file)
        shape.SetScale(chrono.ChVector3d(sx, sy, sz))
        body.AddVisualShape(shape, vframe)
    except Exception:
        # fallback: triangle mesh shape
        try:
            trimesh = chrono.ChTriangleMeshConnected()
            trimesh.LoadWavefrontMesh(mesh_file, True, True)
            shape = chrono.ChVisualShapeTriangleMesh()
            shape.SetMesh(trimesh)
            shape.SetScale(chrono.ChVector3d(sx, sy, sz))
            body.AddVisualShape(shape, vframe)
        except Exception as e:
            print(f"[sim] visual mesh attach 실패: {mesh_file} ({e})")


def _enable_collision_primitive(body: chrono.ChBody,
                               sys: chrono.ChSystemNSC,
                               cdef: Dict[str, Any],
                               mat):
    """
    단순 충돌형상(physics) 생성.
    cdef 예:
      {"kind":"cylinder","axis":"Z","radius":0.02,"length":0.02,"offset":{...}}
      {"kind":"box","hx":0.05,"hy":0.05,"hz":0.01}
      {"kind":"sphere","radius":0.05}
    """
    if not cdef:
        body.EnableCollision(False)
        return

    kind = cdef.get("kind", "").lower()
    if not kind:
        body.EnableCollision(False)
        return

    off = cdef.get("offset", {})
    ox, oy, oz = off.get("pos", [0.0, 0.0, 0.0])
    oqw, oqx, oqy, oqz = off.get("rot", [1.0, 0.0, 0.0, 0.0])
    cframe = chrono.ChFramed(chrono.ChVector3d(ox, oy, oz),
                            chrono.ChQuaterniond(oqw, oqx, oqy, oqz))

    # collision API는 Chrono 버전별로 다르니, 가장 많이 쓰이는 패턴 2개를 try로 커버
    # (A) body.AddCollisionShape(shape, mat, frame)
    # (B) body.GetCollisionModel().ClearModel(); AddXXX; BuildModel()

    body.EnableCollision(True)

    try:
        # 패턴 A
        if kind == "sphere":
            r = float(cdef.get("radius", 0.05))
            shape = chrono.ChCollisionShapeSphere(mat, r) if mat else chrono.ChCollisionShapeSphere(r)
            body.AddCollisionShape(shape, cframe)

        elif kind == "box":
            hx = float(cdef.get("hx", 0.05))
            hy = float(cdef.get("hy", 0.05))
            hz = float(cdef.get("hz", 0.05))
            shape = chrono.ChCollisionShapeBox(mat, hx, hy, hz) if mat else chrono.ChCollisionShapeBox(hx, hy, hz)
            body.AddCollisionShape(shape, cframe)

        elif kind == "cylinder":
            axis = cdef.get("axis", "Z").upper()
            r = float(cdef.get("radius", 0.02))
            length = float(cdef.get("length", 0.02))
            # Chrono collision cylinder는 대개 axis 기반이 아니라 local frame 기반이라
            # 여기선 "Z축 실린더" 기준 + frame 회전으로 대응한다고 생각하면 됨.
            shape = chrono.ChCollisionShapeCylinder(mat, r, length) if mat else chrono.ChCollisionShapeCylinder(r, length)
            body.AddCollisionShape(shape, cframe)

        else:
            print(f"[sim] 경고: collision.kind={kind} 미지원 → collision off")
            body.EnableCollision(False)

        return
    except Exception:
        pass

    try:
        # 패턴 B (구식 CollisionModel API)
        cm = body.GetCollisionModel()
        cm.ClearModel()

        if kind == "sphere":
            r = float(cdef.get("radius", 0.05))
            cm.AddSphere(r, cframe)

        elif kind == "box":
            hx = float(cdef.get("hx", 0.05))
            hy = float(cdef.get("hy", 0.05))
            hz = float(cdef.get("hz", 0.05))
            cm.AddBox(hx, hy, hz, cframe)

        elif kind == "cylinder":
            r = float(cdef.get("radius", 0.02))
            length = float(cdef.get("length", 0.02))
            cm.AddCylinder(r, r, length * 0.5, cframe)  # half-length 방식인 경우가 많음

        else:
            print(f"[sim] 경고: collision.kind={kind} 미지원 → collision off")
            body.EnableCollision(False)
            return

        cm.BuildModel()
        return
    except Exception as e:
        print(f"[sim] collision 생성 실패(kind={kind}): {e}")
        body.EnableCollision(False)


# =========================
# 3. 바디 / 조인트 / 액추에이터 생성
# =========================

def _make_body_from_meta(sys: chrono.ChSystemNSC,
                         bdef: Dict[str, Any]) -> BodyHandle:
    """
    (PATCH 핵심)
    - 물리용 단순 충돌형상(geometry.collision)
    - 시각화용 OBJ 덧씌우기(geometry.visual)
    - 기존 geometry.kind/geometry.file도 호환 처리
    """
    name = bdef["name"]
    category = bdef.get("category", "unknown")

    geom = bdef.get("geometry", {})
    mech = bdef.get("mechanical", {})
    pose = bdef.get("pose", {})

    # --- body 생성: 이제 EasyMesh로 물리를 만들지 않고, 그냥 ChBody로 만든다.
    body = chrono.ChBody()
    body.SetName(name)

    # --- 질량/관성
    mass = float(mech.get("mass", 1.0))
    body.SetMass(mass)

    # inertia가 들어오면 사용, 없으면 대충 등방성으로 둠(테스트용)
    inertia = mech.get("inertia", None)
    if inertia:
        Ixx = float(inertia.get("Ixx", 1e-3))
        Iyy = float(inertia.get("Iyy", 1e-3))
        Izz = float(inertia.get("Izz", 1e-3))
        body.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))
    else:
        # 너무 작으면 폭주하기도 해서, 테스트용 기본값을 조금 크게
        body.SetInertiaXX(chrono.ChVector3d(1e-2, 1e-2, 1e-2))

    fixed = bool(mech.get("fixed", False))
    body.SetFixed(fixed)

    # --- pose (월드 기준)
    px, py, pz = pose.get("pos", [0.0, 0.0, 0.0])
    qw, qx, qy, qz = pose.get("rot", [1.0, 0.0, 0.0, 0.0])
    body.SetPos(chrono.ChVector3d(px, py, pz))
    body.SetRot(chrono.ChQuaterniond(qw, qx, qy, qz))

    # --- 기어 gearProps 파싱
    gearProps = None
    if category == "gear":
        gp = mech.get("gearProps")
        if gp is not None:
            gearProps = GearProps(
                module=float(gp["module"]),
                teeth=int(gp["teeth"]),
                face_width=float(gp.get("face_width", 0.01)),
                pressure_angle_deg=float(gp.get("pressure_angle_deg", 20.0)),
                helix_angle_deg=float(gp.get("helix_angle_deg", 0.0)),
                backlash=float(gp.get("backlash", 0.0)),
            )

    # --- contact material
    contact_meta = mech.get("contact", {})
    mat = _make_contact_material(sys, contact_meta)

    # --- geometry 파싱: 새 스키마 우선, 없으면 기존 스키마 호환
    vdef = None
    cdef = None

    if "visual" in geom or "collision" in geom:
        vdef = geom.get("visual", None)
        cdef = geom.get("collision", None)
    else:
        # 구 버전: geometry.kind / geometry.file
        kind = geom.get("kind", "mesh")
        if kind == "mesh":
            vdef = {"kind": "mesh", "file": geom.get("file")}
            cdef = geom.get("collision", None)  # 없으면 아래에서 auto 처리 가능
        elif kind == "cylinder":
            # 구버전 cylinder를 collision로 해석
            vdef = None
            cdef = {
                "kind": "cylinder",
                "radius": float(geom.get("radius", 0.02)),
                "length": float(geom.get("length", 0.02)),
                "axis": "Z",
            }
        else:
            vdef = None
            cdef = None

    # --- collision이 없으면(또는 auto) gear는 자동 근사 가능
    if (not cdef) or (str(cdef.get("kind", "")).lower() == "auto"):
        if gearProps is not None:
            # 기어는 "실린더"로 근사: 반지름은 피치 반지름 근처, 두께는 face_width
            # (너가 가진 gear_*_scaled.obj가 피치원과 정확히 일치하지 않을 수 있어 1.1 정도 여유)
            r = gearProps.pitch_radius * 1.10
            L = max(gearProps.face_width, 0.005)
            cdef = {"kind": "cylinder", "axis": "Z", "radius": r, "length": L}
        else:
            # 기타 바디는 collision 없이 시작(2단계에서는 “근사 정보”를 메타로 넣는 걸 권장)
            cdef = None

    # --- collision 생성
    _enable_collision_primitive(body, sys, cdef, mat)

    # --- visual mesh 덧씌우기
    _add_visual_mesh(body, vdef)

    sys.Add(body)

    return BodyHandle(
        name=name,
        category=category,
        body=body,
        gearProps=gearProps,
        raw_meta=bdef,
    )


def _make_joint_from_meta(sys: chrono.ChSystemNSC,
                          jdef: Dict[str, Any],
                          bodies: Dict[str, BodyHandle]) -> JointHandle:
    jtype = jdef["type"]
    name = jdef["name"]

    b1_name = jdef["body1"]
    b2_name = jdef["body2"]

    body1 = bodies[b1_name].body
    body2 = bodies[b2_name].body

    frame = jdef.get("frame", {})
    fx, fy, fz = frame.get("pos", [0.0, 0.0, 0.0])
    qw, qx, qy, qz = frame.get("rot", [1.0, 0.0, 0.0, 0.0])

    center = chrono.ChVector3d(fx, fy, fz)
    q = chrono.ChQuaterniond(qw, qx, qy, qz)
    fr = chrono.ChFramed(center, q)

    if jtype == "revolute":
        joint = chrono.ChLinkLockRevolute()
        joint.Initialize(body1, body2, fr)
    elif jtype == "prismatic":
        joint = chrono.ChLinkLockPrismatic()
        joint.Initialize(body1, body2, fr)
    elif jtype == "fixed":
        joint = chrono.ChLinkLockLock()
        joint.Initialize(body1, body2, fr)
    else:
        raise NotImplementedError(f"[sim] joint type={jtype} 는 아직 지원 안 함")

    if hasattr(joint, "SetName"):
        joint.SetName(name)

    sys.AddLink(joint)
    return JointHandle(name=name, type=jtype, joint=joint)


def _find_joint_meta_by_name(joints_meta: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for j in joints_meta:
        if j.get("name") == name:
            return j
    return None


def _make_actuator_from_meta(sys: chrono.ChSystemNSC,
                             adef: Dict[str, Any],
                             joints: Dict[str, JointHandle],
                             bodies: Dict[str, BodyHandle],
                             joints_meta: List[Dict[str, Any]]) -> ActuatorHandle:
    atype = adef["type"]
    name = adef["name"]

    if atype == "rotation_speed":
        target_joint_name = adef["targetJoint"]
        speed = float(adef.get("speed", 0.0))

        jh = joints[target_joint_name]
        rev = jh.joint  # ChLinkLockRevolute 로 가정

        jmeta = _find_joint_meta_by_name(joints_meta, target_joint_name)
        if jmeta is None:
            raise ValueError(f"[sim] actuator {name}: joint meta '{target_joint_name}'를 찾을 수 없습니다.")

        frame = jmeta.get("frame", {})
        fx, fy, fz = frame.get("pos", [0.0, 0.0, 0.0])
        qw, qx, qy, qz = frame.get("rot", [1.0, 0.0, 0.0, 0.0])

        center = chrono.ChVector3d(fx, fy, fz)
        q = chrono.ChQuaterniond(qw, qx, qy, qz)
        fr = chrono.ChFramed(center, q)

        body1 = rev.GetBody1()
        body2 = rev.GetBody2()

        motor = chrono.ChLinkMotorRotationSpeed()
        motor.Initialize(body1, body2, fr)

        func = chrono.ChFunctionConst(speed)
        motor.SetSpeedFunction(func)

        if hasattr(motor, "SetName"):
            motor.SetName(name)

        sys.AddLink(motor)
        return ActuatorHandle(name=name, type=atype, link=motor)

    else:
        raise NotImplementedError(f"[sim] actuator type={atype} 는 아직 지원 안 함")


def _build_gear_pairs(sys: chrono.ChSystemNSC,
                      model_meta: Dict[str, Any],
                      bodies: Dict[str, BodyHandle]):
    gear_pairs_meta = model_meta.get("gearPairs", [])
    for gp in gear_pairs_meta:
        name = gp["name"]
        gearA_name = gp["gearA"]
        gearB_name = gp["gearB"]

        hA = bodies[gearA_name]
        hB = bodies[gearB_name]

        if not (hA.gearProps and hB.gearProps):
            print(f"[sim] 경고: 기어 {gearA_name} 또는 {gearB_name} 의 gearProps가 없음")
            continue

        rA = hA.gearProps.pitch_radius
        rB = hB.gearProps.pitch_radius

        gear_link = chrono.ChLinkLockGear()
        gear_link.Initialize(hA.body, hB.body, chrono.ChFramed())
        ratio = rA / rB
        gear_link.SetTransmissionRatio(ratio)
        gear_link.SetEnforcePhase(False)
        sys.AddLink(gear_link)

        print(f"[sim] gear pair '{name}' 생성: rA={rA:.4f}, rB={rB:.4f}, ratio={ratio:.3f}")


# =========================
# 4. 전체 시스템 빌더
# =========================

def build_sim_from_meta(model_meta: Dict[str, Any]) -> SimHandle:
    sys = chrono.ChSystemNSC()
    gx, gy, gz = model_meta.get("gravity", [0.0, -9.81, 0.0])
    sys.SetGravitationalAcceleration(chrono.ChVector3d(gx, gy, gz))

    bodies: Dict[str, BodyHandle] = {}
    joints: Dict[str, JointHandle] = {}
    actuators: Dict[str, ActuatorHandle] = {}

    bodies_meta = model_meta.get("bodies", [])
    joints_meta = model_meta.get("joints", [])
    actuators_meta = model_meta.get("actuators", [])

    for bdef in bodies_meta:
        bh = _make_body_from_meta(sys, bdef)
        bodies[bh.name] = bh

    _build_gear_pairs(sys, model_meta, bodies)

    for jdef in joints_meta:
        jh = _make_joint_from_meta(sys, jdef, bodies)
        joints[jh.name] = jh

    for adef in actuators_meta:
        ah = _make_actuator_from_meta(sys, adef, joints, bodies, joints_meta)
        actuators[ah.name] = ah

    print(f"[sim] build_sim_from_meta 완료 → bodies={len(bodies)}, joints={len(joints)}, actuators={len(actuators)}")
    return SimHandle(sys=sys, bodies=bodies, joints=joints, actuators=actuators)


# =========================
# 5. 테스트용 메타 데이터 (기어 2개 + 고정 base)
# =========================

def make_test_meta() -> Dict[str, Any]:
    module_m = 0.002  # m=2mm
    zA = 20
    zB = 40
    rA = 0.5 * module_m * zA
    rB = 0.5 * module_m * zB
    center_distance = rA + rB

    # 충돌 근사용 실린더 두께(기어 face width)
    face = 0.02

    meta = {
        "sceneName": "gear_pair_only_test",
        "gravity": [0.0, -9.81, 0.0],

        "bodies": [
            {
                "name": "base",
                "category": "base",
                "geometry": {
                    "collision": {"kind": "box", "hx": 0.2, "hy": 0.02, "hz": 0.2},
                },
                "mechanical": {"mass": 1000.0, "fixed": True},
                "pose": {"pos": [0.0, 0.0, 0.0], "rot": [1.0, 0.0, 0.0, 0.0]},
            },
            {
                "name": "gear_A",
                "category": "gear",
                "geometry": {
                    "visual": {"kind": "mesh", "file": "gear_A_scaled.obj"},
                    # 물리용 충돌은 실린더로 근사
                    "collision": {"kind": "cylinder", "axis": "Z", "radius": rA * 1.10, "length": face},
                },
                "mechanical": {
                    "mass": 5.0,
                    "fixed": False,
                    "gearProps": {"module": module_m, "teeth": zA, "face_width": face},
                    "contact": {"friction": 0.4, "restitution": 0.0},
                },
                "pose": {"pos": [0.0, 0.03, 0.03], "rot": [1.0, 0.0, 0.0, 0.0]},
            },
            {
                "name": "gear_B",
                "category": "gear",
                "geometry": {
                    "visual": {"kind": "mesh", "file": "gear_B_scaled.obj"},
                    "collision": {"kind": "cylinder", "axis": "Z", "radius": rB * 1.10, "length": face},
                },
                "mechanical": {
                    "mass": 7.0,
                    "fixed": False,
                    "gearProps": {"module": module_m, "teeth": zB, "face_width": face},
                    "contact": {"friction": 0.4, "restitution": 0.0},
                },
                "pose": {"pos": [center_distance, 0.03, 0.03], "rot": [1.0, 0.0, 0.0, 0.0]},
            },
        ],

        "joints": [
            {
                "name": "rev_gearA_base",
                "type": "revolute",
                "body1": "gear_A",
                "body2": "base",
                "frame": {"pos": [0.0, 0.03, 0.03], "rot": [1.0, 0.0, 0.0, 0.0]},  # Z축 회전
            },
            {
                "name": "rev_gearB_base",
                "type": "revolute",
                "body1": "gear_B",
                "body2": "base",
                "frame": {"pos": [center_distance, 0.03, 0.03], "rot": [1.0, 0.0, 0.0, 0.0]},
            },
        ],

        "gearPairs": [
            {"name": "gear_pair_1", "gearA": "gear_A", "gearB": "gear_B"}
        ],

        "actuators": [
            {"name": "gearA_motor", "type": "rotation_speed", "targetJoint": "rev_gearA_base", "speed": 5.0}
        ],
    }

    return meta


# =========================
# 6. 메인: 시뮬레이션 + 시각화
# =========================

def main():
    model_meta = make_test_meta()
    handle = build_sim_from_meta(model_meta)
    sys = handle.sys

    # Irrlicht 시각화
    vis = chronoirr.ChVisualSystemIrrlicht()
    vis.AttachSystem(sys)
    vis.SetWindowSize(1024, 768)
    vis.SetWindowTitle("Meta-driven Gear Pair (primitive collision + mesh visual)")
    vis.Initialize()
    vis.AddSkyBox()
    vis.AddTypicalLights()
    vis.AddCamera(chrono.ChVector3d(0.15, 0.15, 0.25))

    dt = 0.005
    sim_time = 0.0
    end_time = 10.0

    print("[sim] 시뮬레이션 시작")

    while vis.Run() and sim_time < end_time:
        sys.DoStepDynamics(dt)
        sim_time += dt

        vis.BeginScene()
        vis.Render()
        vis.EndScene()

        time.sleep(0.002)

    print("[sim] 시뮬레이션 종료")


if __name__ == "__main__":
    main()
