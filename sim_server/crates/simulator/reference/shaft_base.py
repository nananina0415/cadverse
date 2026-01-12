## 시뮬레이션 엔진을 만들기 위한 연습용 코드
## 메타데이터 기반으로 바디/조인트/엑추에이터를 생성
## 메타데이터에 근사 도형 정보가 있으면 그걸 사용하고,
## 없으면 OBJ에서 치수/축을 뽑아 자동으로 근사하는 기능 구현
## 샤프트 중앙에 기어가 있기에 그에 맞는 충돌 형상을 근사
## 시각화는 OBJ를 붙이고, 물리는 단순 도형으로 돌리도록 

import math as m
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

import pychrono as chrono
import pychrono.irrlicht as chronoirr


# ============================================================
# 0) OBJ 유틸: vertex 로딩 + PCA 축 추정 + bounding box
# ============================================================

def load_obj_vertices(obj_path: str) -> List[Tuple[float, float, float]]:
    verts = []
    with open(obj_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                    verts.append((x, y, z))
    if not verts:
        raise ValueError(f"[obj] '{obj_path}'에서 vertex(v ...)를 찾지 못했습니다.")
    return verts


def compute_aabb(verts: List[Tuple[float, float, float]]):
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    mn = (min(xs), min(ys), min(zs))
    mx = (max(xs), max(ys), max(zs))
    center = ((mn[0] + mx[0]) * 0.5, (mn[1] + mx[1]) * 0.5, (mn[2] + mx[2]) * 0.5)
    ext = ((mx[0] - mn[0]) * 0.5, (mx[1] - mn[1]) * 0.5, (mx[2] - mn[2]) * 0.5)  # half extents
    return mn, mx, center, ext


def pca_main_axis(verts: List[Tuple[float, float, float]]) -> Tuple[float, float, float]:
    # 아주 가벼운 PCA(공분산 3x3의 최대 고유벡터) - numpy 없이 구현
    # (정밀도보다 “대강 축 방향”이 목적)
    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)
    cz = sum(v[2] for v in verts) / len(verts)

    # 공분산
    sxx = syy = szz = sxy = sxz = syz = 0.0
    for x, y, z in verts:
        dx, dy, dz = x - cx, y - cy, z - cz
        sxx += dx * dx
        syy += dy * dy
        szz += dz * dz
        sxy += dx * dy
        sxz += dx * dz
        syz += dy * dz

    # 파워 이터레이션으로 최대 고유벡터 근사
    vx, vy, vz = 1.0, 0.3, 0.2
    for _ in range(30):
        nx = sxx * vx + sxy * vy + sxz * vz
        ny = sxy * vx + syy * vy + syz * vz
        nz = sxz * vx + syz * vy + szz * vz
        norm = m.sqrt(nx * nx + ny * ny + nz * nz) + 1e-12
        vx, vy, vz = nx / norm, ny / norm, nz / norm

    return (vx, vy, vz)


def dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def sub(a, b):
    return (a[0]-b[0], a[1]-b[1], a[2]-b[2])


def mul(a, s):
    return (a[0]*s, a[1]*s, a[2]*s)


def norm(a):
    return m.sqrt(dot(a, a))


def normalize(a):
    n = norm(a) + 1e-12
    return (a[0]/n, a[1]/n, a[2]/n)


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def quat_from_two_vectors(v_from: Tuple[float, float, float], v_to: Tuple[float, float, float]) -> chrono.ChQuaterniond:
    # v_from을 v_to로 회전시키는 quaternion (대략 안정형)
    a = normalize(v_from)
    b = normalize(v_to)
    c = cross(a, b)
    w = 1.0 + dot(a, b)
    if w < 1e-8:
        # 거의 반대 방향인 경우: 임의 축 선택
        axis = cross(a, (1.0, 0.0, 0.0))
        if norm(axis) < 1e-6:
            axis = cross(a, (0.0, 1.0, 0.0))
        axis = normalize(axis)
        return chrono.ChQuaterniond(0.0, axis[0], axis[1], axis[2])
    q = chrono.ChQuaterniond(w, c[0], c[1], c[2])
    # normalize
    qn = m.sqrt(q.e0*q.e0 + q.e1*q.e1 + q.e2*q.e2 + q.e3*q.e3) + 1e-12
    return chrono.ChQuaterniond(q.e0/qn, q.e1/qn, q.e2/qn, q.e3/qn)


# ============================================================
# 1) 데이터 구조 정의 (형식 유지)
# ============================================================

@dataclass
class BodyHandle:
    name: str
    category: str
    body: chrono.ChBody
    raw_meta: Dict[str, Any] = None


@dataclass
class JointHandle:
    name: str
    type: str
    joint: chrono.ChLinkBase


@dataclass
class SimHandle:
    sys: chrono.ChSystemNSC
    bodies: Dict[str, BodyHandle]
    joints: Dict[str, JointHandle]


# ============================================================
# 2) “근사 도형 생성 규칙”
#    - base: AABB 박스
#    - shaft: PCA축 기반 원통 + (중간 radius가 커지는 구간이 있으면) 추가 원통
# ============================================================

def approx_base_from_obj(obj_path: str):
    verts = load_obj_vertices(obj_path)
    _, _, center, half_ext = compute_aabb(verts)
    # 박스 half extents -> full size
    size = (half_ext[0]*2, half_ext[1]*2, half_ext[2]*2)
    return center, size


def approx_shaft_with_hub_from_obj(obj_path: str):
    verts = load_obj_vertices(obj_path)
    mn, mx, center, _ = compute_aabb(verts)

    axis = normalize(pca_main_axis(verts))  # 샤프트의 주축
    c = center

    # 주축으로의 투영 좌표 s, 그리고 축에 수직인 반지름 r 추정
    # 1) 각 vertex에 대해 s = (p-c)·axis
    # 2) r = |(p-c) - axis*s|
    ss = []
    rs = []
    for p in verts:
        d = (p[0]-c[0], p[1]-c[1], p[2]-c[2])
        s = dot(d, axis)
        perp = sub(d, mul(axis, s))
        r = norm(perp)
        ss.append(s)
        rs.append(r)

    smin, smax = min(ss), max(ss)
    length = smax - smin
    if length < 1e-6:
        # 거의 점/구에 가까움 -> fallback: AABB 기반
        _, _, cc, half_ext = compute_aabb(verts)
        # 가장 긴 축을 길이로, 나머지 최대를 반지름으로
        lx, ly, lz = half_ext[0]*2, half_ext[1]*2, half_ext[2]*2
        L = max(lx, ly, lz)
        R = max(min(lx, ly), min(max(lx, ly), lz)) * 0.5
        return cc, (0.0, 0.0, 1.0), L, R, None

    # binning으로 s-방향 radius profile 만들기
    nbins = 40
    bins = [[] for _ in range(nbins)]
    for s, r in zip(ss, rs):
        t = (s - smin) / (length + 1e-12)
        i = int(t * nbins)
        i = max(0, min(nbins-1, i))
        bins[i].append(r)

    med = []
    for b in bins:
        if not b:
            med.append(0.0)
        else:
            bb = sorted(b)
            med.append(bb[len(bb)//2])

    # baseline radius = 전체 med 중 작은 쪽(하위 20%의 평균)로 추정
    med_sorted = sorted([v for v in med if v > 1e-9])
    if not med_sorted:
        # fallback
        R = sorted(rs)[int(0.5*len(rs))]
        return center, axis, length, R, None

    k = max(1, int(0.2 * len(med_sorted)))
    baseline = sum(med_sorted[:k]) / k

    # hub(기어/허브) 후보: baseline보다 충분히 큰 구간(예: 1.35배 이상)
    thr = baseline * 1.35
    hub_idx = [i for i, v in enumerate(med) if v > thr]

    hub = None
    if hub_idx:
        # 가장 긴 연속 구간을 hub로 잡음
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

        # bin -> s 범위로 변환
        i0, i1 = best
        hs0 = smin + (i0 / nbins) * length
        hs1 = smin + ((i1 + 1) / nbins) * length
        hub_len = max(0.0, hs1 - hs0)

        # hub radius는 해당 구간 med 최대값
        hub_r = max(med[i0:i1+1])

        # hub center s
        hub_sc = 0.5 * (hs0 + hs1)
        hub_center = (
            c[0] + axis[0] * hub_sc,
            c[1] + axis[1] * hub_sc,
            c[2] + axis[2] * hub_sc,
        )
        hub = {"center": hub_center, "length": hub_len, "radius": hub_r}

    # shaft radius는 baseline을 약간 보수적으로 사용 (mesh 노이즈 대비)
    shaft_r = max(1e-4, baseline)

    return center, axis, length, shaft_r, hub


# ============================================================
# 3) Chrono 바디 생성: collision(근사 도형) + visual(OBJ)
# ============================================================

def _ensure_collision_api(body: chrono.ChBody):
    # Chrono 버전에 따라 collision 모델 접근 방식이 다를 수 있어서 방어적으로 처리
    if hasattr(body, "GetCollisionModel"):
        cm = body.GetCollisionModel()
        if cm is not None:
            try:
                cm.ClearModel()
                return ("collisionmodel", cm)
            except Exception:
                pass
    return ("none", None)


def _try_add_cylinder_collision(body: chrono.ChBody,
                                mat: Any,
                                radius: float,
                                half_length: float,
                                pos: chrono.ChVector3d,
                                rot: chrono.ChQuaterniond) -> bool:
    # 1) New API: body.AddCollisionShape(shape, frame)
    try:
        if hasattr(chrono, "ChCollisionShapeCylinder") and hasattr(body, "AddCollisionShape"):
            shape = chrono.ChCollisionShapeCylinder(mat, radius, half_length)
            body.AddCollisionShape(shape, chrono.ChFramed(pos, rot))
            return True
    except Exception:
        pass

    # 2) Old API: body.GetCollisionModel().AddCylinder(...)
    try:
        if hasattr(body, "GetCollisionModel"):
            cm = body.GetCollisionModel()
            # 다양한 시그니처가 있어서 여러 형태를 시도
            try:
                cm.AddCylinder(mat, radius, radius, half_length, chrono.ChFramed(pos, rot))
                return True
            except Exception:
                try:
                    cm.AddCylinder(radius, radius, half_length, chrono.ChFramed(pos, rot))
                    return True
                except Exception:
                    pass
    except Exception:
        pass

    return False


def _try_add_box_collision(body: chrono.ChBody,
                           mat: Any,
                           hx: float, hy: float, hz: float,
                           pos: chrono.ChVector3d,
                           rot: chrono.ChQuaterniond) -> bool:
    try:
        if hasattr(chrono, "ChCollisionShapeBox") and hasattr(body, "AddCollisionShape"):
            shape = chrono.ChCollisionShapeBox(mat, hx, hy, hz)
            body.AddCollisionShape(shape, chrono.ChFramed(pos, rot))
            return True
    except Exception:
        pass

    try:
        if hasattr(body, "GetCollisionModel"):
            cm = body.GetCollisionModel()
            try:
                cm.AddBox(mat, hx, hy, hz, chrono.ChFramed(pos, rot))
                return True
            except Exception:
                try:
                    cm.AddBox(hx, hy, hz, chrono.ChFramed(pos, rot))
                    return True
                except Exception:
                    pass
    except Exception:
        pass

    return False


def _finalize_collision(body: chrono.ChBody):
    if hasattr(body, "GetCollisionModel"):
        cm = body.GetCollisionModel()
        try:
            cm.BuildModel()
            # 최신 pychrono에서는 SetCollide 필요 없음
        except Exception:
            pass


def _attach_obj_visual(body: chrono.ChBody, obj_path: str):
    # mesh를 "시각화 shape"로 붙임 (물리에는 사용 X)
    try:
        mesh = chrono.ChTriangleMeshConnected()
        mesh.LoadWavefrontMesh(obj_path, False, True)
        vshape = chrono.ChVisualShapeTriangleMesh()
        vshape.SetMesh(mesh)
        body.AddVisualShape(vshape)
        return
    except Exception:
        # 버전별로 LoadWavefrontMesh 경로가 다를 수 있으니 fallback:
        try:
            vshape = chrono.ChVisualShapeModelFile()
            vshape.SetFilename(obj_path)
            body.AddVisualShape(vshape)
        except Exception:
            print(f"[warn] OBJ 시각화 부착 실패: {obj_path}")


# ============================================================
# 4) 메타 기반 생성(형식 유지) + “collision 없으면 OBJ에서 추정”
# ============================================================

def _make_body_from_meta(sys: chrono.ChSystemNSC, bdef: Dict[str, Any]) -> BodyHandle:
    name = bdef["name"]
    category = bdef.get("category", "unknown")

    geom = bdef.get("geometry", {})
    mech = bdef.get("mechanical", {})
    pose = bdef.get("pose", {})

    # Chrono body 생성 (EasyMesh 말고 ChBody로 통일: 충돌/시각화를 우리가 컨트롤)
    body = chrono.ChBody()
    body.SetName(name)

    fixed = bool(mech.get("fixed", False))
    body.SetFixed(fixed)

    mass = float(mech.get("mass", 1.0))
    body.SetMass(mass)

    # inertia가 있으면 사용, 없으면 간단히 대각(아주 대충) 값 부여
    inertia = mech.get("inertia", None)
    if inertia:
        Ixx = float(inertia.get("Ixx", 1e-3))
        Iyy = float(inertia.get("Iyy", 1e-3))
        Izz = float(inertia.get("Izz", 1e-3))
        body.SetInertiaXX(chrono.ChVector3d(Ixx, Iyy, Izz))
    else:
        body.SetInertiaXX(chrono.ChVector3d(1e-3, 1e-3, 1e-3))

    # pose
    px, py, pz = pose.get("pos", [0.0, 0.0, 0.0])
    qw, qx, qy, qz = pose.get("rot", [1.0, 0.0, 0.0, 0.0])
    body.SetPos(chrono.ChVector3d(px, py, pz))
    body.SetRot(chrono.ChQuaterniond(qw, qx, qy, qz))

    # contact material (간단)
    # NSC에서는 ChContactMaterialNSC, SMC에서는 ChContactMaterialSMC
    # 여기서는 NSC 기준으로 NSC material 생성
    mat = chrono.ChContactMaterialNSC()
    contact = mech.get("contact", {})
    mat.SetFriction(float(contact.get("friction", 0.4)))
    mat.SetRestitution(float(contact.get("restitution", 0.05)))

    # collision 만들기: meta.geometry.collision 우선, 없으면 OBJ 추정
    collision = None
    if isinstance(geom, dict):
        collision = geom.get("collision", None)

    # visual: meta.geometry.visual.kind=mesh,file
    visual = None
    if isinstance(geom, dict):
        visual = geom.get("visual", None)

    # collision shape 세팅
    _ensure_collision_api(body)

    if collision:
        ckind = collision.get("kind", None)
        if ckind == "box":
            hx, hy, hz = collision.get("hx", None), collision.get("hy", None), collision.get("hz", None)
            if hx is None or hy is None or hz is None:
                # full size 제공했다면 half로 변환
                sx, sy, sz = collision.get("sx", 1.0), collision.get("sy", 1.0), collision.get("sz", 1.0)
                hx, hy, hz = 0.5 * float(sx), 0.5 * float(sy), 0.5 * float(sz)
            _try_add_box_collision(body, mat, float(hx), float(hy), float(hz),
                                   chrono.ChVector3d(0, 0, 0),
                                   chrono.ChQuaterniond(1, 0, 0, 0))

        elif ckind == "cylinder":
            radius = float(collision.get("radius", 0.01))
            length = float(collision.get("length", 0.1))
            axis = collision.get("axis", [0, 0, 1])  # 월드 or 바디? 여기서는 바디 local 기준으로 가정
            axis = normalize((float(axis[0]), float(axis[1]), float(axis[2])))

            # Chrono cylinder는 기본이 Z축 방향이라고 가정하고, axis로 회전시킴
            q = quat_from_two_vectors((0.0, 0.0, 1.0), axis)

            _try_add_cylinder_collision(body, mat, radius, 0.5 * length,
                                        chrono.ChVector3d(0, 0, 0), q)

        else:
            print(f"[warn] body '{name}': collision.kind='{ckind}' 미지원 -> 자동추정으로 대체")
            collision = None

    if not collision:
        # 자동 추정 (category 별 규칙)
        if visual and visual.get("kind") == "mesh" and visual.get("file"):
            obj_file = visual["file"]

            if category == "base":
                cc, size = approx_base_from_obj(obj_file)
                # base는 보통 "고정"이니까 박스 collision이면 충분
                _try_add_box_collision(body, mat,
                                       0.5*size[0], 0.5*size[1], 0.5*size[2],
                                       chrono.ChVector3d(0, 0, 0),
                                       chrono.ChQuaterniond(1, 0, 0, 0))

            elif category == "shaft":
                cc, axis, L, R, hub = approx_shaft_with_hub_from_obj(obj_file)
                # 바디 local에서 Z축 원통을 axis로 돌려 씀 (회전만 바디에 넣는게 아니라 collision shape에 적용)
                q_axis = quat_from_two_vectors((0.0, 0.0, 1.0), axis)

                # 주 샤프트 원통
                _try_add_cylinder_collision(body, mat, R, 0.5 * L,
                                            chrono.ChVector3d(0, 0, 0),
                                            q_axis)

                # 허브(기어 박힌 부분) 검출되면 추가 원통
                if hub and hub["length"] > 1e-5 and hub["radius"] > R * 1.2:
                    # 허브 중심은 mesh 기준(center + axis*hub_sc)였는데,
                    # 여기서는 "바디 local 원점"을 body COM(초기 pose)로 두는 구조라
                    # 정확한 상대 위치를 잡기 어렵다.
                    #
                    # => 테스트 목적상 '축 중앙'에 허브를 놓는 방식(가장 안전)으로 둠.
                    hub_len = float(hub["length"])
                    hub_r = float(hub["radius"])
                    _try_add_cylinder_collision(body, mat, hub_r, 0.5 * hub_len,
                                                chrono.ChVector3d(0, 0, 0),
                                                q_axis)

            else:
                # 기타 카테고리: AABB 박스로 fallback
                verts = load_obj_vertices(obj_file)
                _, _, _, half_ext = compute_aabb(verts)
                _try_add_box_collision(body, mat, half_ext[0], half_ext[1], half_ext[2],
                                       chrono.ChVector3d(0, 0, 0),
                                       chrono.ChQuaterniond(1, 0, 0, 0))

        else:
            # mesh도 없으면 최소 박스
            _try_add_box_collision(body, mat, 0.05, 0.05, 0.05,
                                   chrono.ChVector3d(0, 0, 0),
                                   chrono.ChQuaterniond(1, 0, 0, 0))

    _finalize_collision(body)

    # visual 붙이기 (OBJ)
    if visual and visual.get("kind") == "mesh" and visual.get("file"):
        _attach_obj_visual(body, visual["file"])
    else:
        # visual이 없으면 collision과 같은 primitive를 대충 붙이기 (가시화용)
        # base는 box, shaft는 cylinder 비슷하게
        if category == "base":
            vs = chrono.ChVisualShapeBox(0.2, 0.02, 0.2)
            body.AddVisualShape(vs)
        elif category == "shaft":
            vs = chrono.ChVisualShapeCylinder(0.02, 0.2)
            body.AddVisualShape(vs)

    sys.AddBody(body)

    return BodyHandle(name=name, category=category, body=body, raw_meta=bdef)


def _make_joint_from_meta(sys: chrono.ChSystemNSC, jdef: Dict[str, Any], bodies: Dict[str, BodyHandle]) -> JointHandle:
    jtype = jdef["type"]
    name = jdef["name"]

    b1_name = jdef["body1"]
    b2_name = jdef["body2"]
    body1 = bodies[b1_name].body
    body2 = bodies[b2_name].body

    frame = jdef.get("frame", {})
    fx, fy, fz = frame.get("pos", [0.0, 0.0, 0.0])
    qw, qx, qy, qz = frame.get("rot", [1.0, 0.0, 0.0, 0.0])
    fr = chrono.ChFramed(chrono.ChVector3d(fx, fy, fz), chrono.ChQuaterniond(qw, qx, qy, qz))

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


def build_sim_from_meta(model_meta: Dict[str, Any]) -> SimHandle:
    sys = chrono.ChSystemNSC()
    gx, gy, gz = model_meta.get("gravity", [0.0, -9.81, 0.0])
    sys.SetGravitationalAcceleration(chrono.ChVector3d(gx, gy, gz))

    bodies: Dict[str, BodyHandle] = {}
    joints: Dict[str, JointHandle] = {}

    bodies_meta = model_meta.get("bodies", [])
    joints_meta = model_meta.get("joints", [])

    for bdef in bodies_meta:
        bh = _make_body_from_meta(sys, bdef)
        bodies[bh.name] = bh

    for jdef in joints_meta:
        jh = _make_joint_from_meta(sys, jdef, bodies)
        joints[jh.name] = jh

    print(f"[sim] build_sim_from_meta 완료 → bodies={len(bodies)}, joints={len(joints)}")
    return SimHandle(sys=sys, bodies=bodies, joints=joints)


# ============================================================
# 5) 테스트 메타 (기어 제외, base + shaft만)
#    - collision을 일부러 비워서(없애서) OBJ 자동추정을 타게 하는 예시
# ============================================================

def make_test_meta() -> Dict[str, Any]:
    c = m.sqrt(0.5)
    rot_x_axis = [c, 0.0, -c, 0.0]
    meta = {
        "sceneName": "base_shaft_test_autoapprox",
        "gravity": [0.0, -9.81, 0.0],

        "bodies": [
            {
                "name": "base",
                "category": "base",
                "geometry": {
                    "visual": {"kind": "mesh", "file": "base_scaled.obj"},
                    # "collision": { ... }  # <= 일부러 비워둠 (OBJ로 자동추정)
                },
                "mechanical": {
                    "mass": 1000.0,
                    "fixed": True,
                    "contact": {"friction": 0.4, "restitution": 0.05},
                },
                "pose": {"pos": [0.0, 0.0, 0.0], "rot": [1.0, 0.0, 0.0, 0.0]},
            },
            {
                "name": "shaft",
                "category": "shaft",
                "geometry": {
                    "visual": {"kind": "mesh", "file": "shaft_scaled.obj"},
                    # "collision": { ... }  # <= 일부러 비워둠 (OBJ로 자동추정: shaft+hub 2중 원통 시도)
                },
                "mechanical": {
                    "mass": 10.0,
                    "fixed": False,
                    "contact": {"friction": 0.4, "restitution": 0.05},
                    # inertia는 없으면 대충 들어감(테스트용)
                },
                # base 앞쪽에 적당히 배치 (너 환경에 맞게 조정)
                "pose": {"pos": [0.0, 0.0, 0.03], "rot": [1.0, 0.0, 0.0, 0.0]},
            },
        ],

        "joints": [
            # 샤프트를 base에 revolute로 붙여 회전 가능하게
            # frame의 로컬 Z축이 회전축.
            {
                "name": "rev_shaft_base",
                "type": "revolute",
                "body1": "shaft",
                "body2": "base",
                "frame": {
                    # 샤프트 중심 근처로 (일단 pose와 동일하게 맞춤)
                    "pos": [0.0, 0.0, 0.03],
                    "rot": rot_x_axis
                },
            },
        ],
    }
    return meta


# ============================================================
# 6) 메인
# ============================================================

def main():
    model_meta = make_test_meta()
    handle = build_sim_from_meta(model_meta)
    sys = handle.sys

    # (선택) 초기 각속도 부여로 회전 확인
    shaft = handle.bodies["shaft"].body
    shaft.SetAngVelLocal(chrono.ChVector3d(10.0, 0.0, 0.0))

    # Irrlicht
    vis = chronoirr.ChVisualSystemIrrlicht()
    vis.AttachSystem(sys)
    vis.SetWindowSize(1024, 768)
    vis.SetWindowTitle("Base + Shaft (auto collision approx from OBJ)")
    vis.Initialize()
    vis.AddSkyBox()
    vis.AddTypicalLights()
    vis.AddCamera(chrono.ChVector3d(0.4, 0.3, 0.3))

    dt = 0.005
    sim_time = 0.0
    end_time = 10.0

    print("[sim] start")
    while vis.Run() and sim_time < end_time:
        vis.BeginScene()
        vis.Render()
        chronoirr.drawAllCOGs(vis, 1.0)
        vis.EndScene()

        sys.DoStepDynamics(dt)
        sim_time += dt

        time.sleep(0.002)

    print("[sim] end")


if __name__ == "__main__":
    main()
