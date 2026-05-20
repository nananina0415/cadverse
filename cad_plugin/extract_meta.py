# extract_meta.py

import adsk.core
import adsk.fusion
import traceback
import math
import re
import os


# Fusion internal length unit is generally mm.
# Simulator metadata should use meters.
FUSION_MM_TO_M = 0.001

# Integrated export policy:
# Joint origins must come from Fusion/CAD data.
# Demo-only geometric fallback is disabled by default.

IDENTITY_QUAT = [1.0, 0.0, 0.0, 0.0]
IDENTITY_TRANSFORM = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]


# ---------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------

def sanitize_name(name: str) -> str:
    s = str(name or "unnamed")
    s = s.replace(" ", "_").replace(":", "_")
    s = re.sub(r"[^A-Za-z0-9가-힣_\-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unnamed"


def make_unique_name(base_name: str, used_names: set) -> str:
    base = sanitize_name(base_name)
    name = base
    idx = 2

    while name in used_names:
        name = f"{base}_{idx}"
        idx += 1

    used_names.add(name)
    return name


def safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def vec_norm(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def vec_normalize(v):
    n = vec_norm(v)
    if n < 1e-12:
        return [0.0, 0.0, 1.0]
    return [v[0] / n, v[1] / n, v[2] / n]


def vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def quat_normalize(q):
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    if n < 1e-12:
        return IDENTITY_QUAT[:]
    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n]


def quat_from_two_vectors(v_from, v_to):
    """
    v_from 방향을 v_to 방향으로 보내는 quaternion [w,x,y,z].
    Joint frame에서는 local Z축 [0,0,1]을 Fusion joint axis로 맞추는 데 사용한다.
    """
    a = vec_normalize(v_from)
    b = vec_normalize(v_to)

    dot = vec_dot(a, b)

    if dot > 0.999999:
        return IDENTITY_QUAT[:]

    if dot < -0.999999:
        # 180도 회전. a와 수직인 임의 축 선택.
        axis = vec_cross(a, [1.0, 0.0, 0.0])
        if vec_norm(axis) < 1e-8:
            axis = vec_cross(a, [0.0, 1.0, 0.0])
        axis = vec_normalize(axis)
        return [0.0, axis[0], axis[1], axis[2]]

    c = vec_cross(a, b)
    q = [1.0 + dot, c[0], c[1], c[2]]
    return quat_normalize(q)


def quat_from_rotation_matrix(m):
    """
    3x3 rotation matrix -> quaternion [w,x,y,z].
    m은 row-major 3x3 형태:
    [
      [r00,r01,r02],
      [r10,r11,r12],
      [r20,r21,r22]
    ]
    """
    r00, r01, r02 = m[0]
    r10, r11, r12 = m[1]
    r20, r21, r22 = m[2]

    tr = r00 + r11 + r22

    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (r21 - r12) / s
        y = (r02 - r20) / s
        z = (r10 - r01) / s
    elif r00 > r11 and r00 > r22:
        s = math.sqrt(1.0 + r00 - r11 - r22) * 2.0
        w = (r21 - r12) / s
        x = 0.25 * s
        y = (r01 + r10) / s
        z = (r02 + r20) / s
    elif r11 > r22:
        s = math.sqrt(1.0 + r11 - r00 - r22) * 2.0
        w = (r02 - r20) / s
        x = (r01 + r10) / s
        y = 0.25 * s
        z = (r12 + r21) / s
    else:
        s = math.sqrt(1.0 + r22 - r00 - r11) * 2.0
        w = (r10 - r01) / s
        x = (r02 + r20) / s
        y = (r12 + r21) / s
        z = 0.25 * s

    return quat_normalize([w, x, y, z])


# ---------------------------------------------------------------------
# Transform / pose helpers
# ---------------------------------------------------------------------

def _safe_transform_array_from_occ(occ):
    try:
        arr = occ.transform.asArray()
        return [float(x) for x in arr]
    except Exception:
        return IDENTITY_TRANSFORM[:]


def _pose_from_transform_array(arr, unit_scale=FUSION_MM_TO_M):
    """
    Fusion Matrix3D.asArray()를 simulator pose로 변환한다.

    현재 정책:
    - translation은 arr[12], arr[13], arr[14] 우선 사용
    - rotation basis는
        X axis = arr[0:3]
        Y axis = arr[4:7]
        Z axis = arr[8:11]
      로 해석한다.

    만약 Fusion export 결과에서 pose가 틀어지면,
    여기의 index 정책만 수정하면 된다.
    """
    if not isinstance(arr, (list, tuple)) or len(arr) < 16:
        arr = IDENTITY_TRANSFORM[:]

    # Fusion Matrix3D.asArray는 보통 basis vector와 origin이 함께 들어간다.
    # 기존 팀원 주석에서도 index 0,1,2가 X-axis vector라고 되어 있었으므로
    # origin은 12,13,14로 우선 해석한다.
    px = safe_float(arr[12], 0.0) * unit_scale
    py = safe_float(arr[13], 0.0) * unit_scale
    pz = safe_float(arr[14], 0.0) * unit_scale

    # 일부 환경에서 row-major translation이 3,7,11에 들어가는 경우 대비.
    # 12~14가 모두 0인데 3/7/11이 유의미하면 fallback 사용.
    if abs(px) < 1e-12 and abs(py) < 1e-12 and abs(pz) < 1e-12:
        alt = [
            safe_float(arr[3], 0.0) * unit_scale,
            safe_float(arr[7], 0.0) * unit_scale,
            safe_float(arr[11], 0.0) * unit_scale,
        ]
        if vec_norm(alt) > 1e-12:
            px, py, pz = alt

    x_axis = vec_normalize([safe_float(arr[0], 1.0), safe_float(arr[1], 0.0), safe_float(arr[2], 0.0)])
    y_axis = vec_normalize([safe_float(arr[4], 0.0), safe_float(arr[5], 1.0), safe_float(arr[6], 0.0)])
    z_axis = vec_normalize([safe_float(arr[8], 0.0), safe_float(arr[9], 0.0), safe_float(arr[10], 1.0)])

    # Fusion Matrix3D.asArray()의 0,1,2 / 4,5,6 / 8,9,10은
    # 현재 추출 결과 기준으로 "row 방향 basis"처럼 써야 Chrono body pose와 OBJ local mesh가 맞는다.
    #
    # 기존처럼 column으로 재배치하면 회전 부호가 반대로 들어가서
    # local OBJ가 body에 90도 가까이 틀어진 것처럼 붙는다.
    rot_m = [
        [x_axis[0], x_axis[1], x_axis[2]],
        [y_axis[0], y_axis[1], y_axis[2]],
        [z_axis[0], z_axis[1], z_axis[2]],
    ]

    q = quat_from_rotation_matrix(rot_m)

    return {
        "pos": [px, py, pz],
        "rot": q,
    }


# ---------------------------------------------------------------------
# Legacy AR metadata compatibility helpers
# ---------------------------------------------------------------------

LEGACY_AR_VISUAL_SCALE = 500.0


def _quat_wxyz_to_rot3(q):
    """
    quaternion [w, x, y, z] -> row-major 3x3 rotation matrix.

    This is used only for legacy Unity APK compatibility.
    It does not change the simulator metadata flow.
    """
    if not q or len(q) < 4:
        return [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]

    w, x, y, z = [safe_float(v, 0.0) for v in q[:4]]

    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-12:
        return [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]

    w, x, y, z = w / n, x / n, y / n, z / n

    return [
        [
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y - z * w),
            2.0 * (x * z + y * w),
        ],
        [
            2.0 * (x * y + z * w),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z - x * w),
        ],
        [
            2.0 * (x * z - y * w),
            2.0 * (y * z + x * w),
            1.0 - 2.0 * (x * x + y * y),
        ],
    ]


def _build_legacy_ar_transforms(bodies):
    """
    Build legacy metadata["transforms"] for the already-built Unity APK.

    Existing phone APK behavior:
    - reads metadata.json["transforms"]
    - requests /meshes/{bodyName}.obj
    - treats transform translation as Fusion cm
    - ObjParser also converts OBJ vertices as cm -> m using *0.01

    Current CADverse simulator metadata:
    - body.pose.pos is already meters
    - mesh OBJ is expected to be simulation-scale

    Therefore:
    - translation uses meters -> cm by multiplying pose by 100
    - basis vectors are scaled by LEGACY_AR_VISUAL_SCALE to compensate
      for the legacy Unity OBJ parser shrinking vertices by 0.01
    """
    transforms = {}

    for body in bodies:
        name = body.get("name")
        if not name:
            continue

        visual = body.get("geometry", {}).get("visual", {})
        mesh_file = visual.get("file", "")

        # Legacy ARScene requests /meshes/{name}.obj.
        # Only include bodies whose visual mesh follows that convention.
        expected_file = f"meshes/{name}.obj"
        if mesh_file.replace("\\", "/") != expected_file:
            continue

        pose = body.get("pose", {})
        pos = pose.get("pos", [0.0, 0.0, 0.0])
        rot = pose.get("rot", IDENTITY_QUAT[:])

        if not pos or len(pos) < 3:
            pos = [0.0, 0.0, 0.0]

        r = _quat_wxyz_to_rot3(rot)
        s = LEGACY_AR_VISUAL_SCALE

        tx = safe_float(pos[0], 0.0) * s
        ty = safe_float(pos[1], 0.0) * s
        tz = safe_float(pos[2], 0.0) * s

        transforms[name] = [
            r[0][0] * s, r[0][1] * s, r[0][2] * s, tx,
            r[1][0] * s, r[1][1] * s, r[1][2] * s, ty,
            r[2][0] * s, r[2][1] * s, r[2][2] * s, tz,
            0.0, 0.0, 0.0, 1.0,
        ]

    return transforms


def _point3d_to_m_list(pt, unit_scale=FUSION_MM_TO_M):
    if pt is None:
        return [0.0, 0.0, 0.0]
    return [
        safe_float(getattr(pt, "x", 0.0), 0.0) * unit_scale,
        safe_float(getattr(pt, "y", 0.0), 0.0) * unit_scale,
        safe_float(getattr(pt, "z", 0.0), 0.0) * unit_scale,
    ]


def _vector3d_to_list(vec):
    if vec is None:
        return [0.0, 0.0, 1.0]
    return vec_normalize([
        safe_float(getattr(vec, "x", 0.0), 0.0),
        safe_float(getattr(vec, "y", 0.0), 0.0),
        safe_float(getattr(vec, "z", 1.0), 1.0),
    ])


# ---------------------------------------------------------------------
# Body metadata helpers
# ---------------------------------------------------------------------
def _is_visual_only_body_name(name: str) -> bool:
    """
    MVP policy:
    pin류는 현재 별도 물리 body로 두면 floating/over-constraint 문제가 생기기 쉬우므로
    일단 metadata body에서 제외한다.
    """
    n = str(name or "").lower()
    return n.startswith("pin_") or "_pin_" in n or n.startswith("pin")


def _infer_fixed_body_from_name(name: str, category: str) -> bool:
    """
    MVP policy:
    Fusion fixed joint를 Chrono fixed constraint로 넘기지 않고,
    고정 구조물은 body 자체를 fixed=True로 처리한다.

    주의:
    slider_guide_frame에는 'slider'가 들어가지만 고정 가이드이므로 fixed=True여야 한다.
    그래서 guide/frame/mount/motor/base 계열을 먼저 고정 판정한다.
    """
    n = str(name or "").lower()
    c = str(category or "").lower()

    if c == "base":
        return True

    # 명확한 고정 구조물 우선 판정
    static_keywords = [
        "base",
        "ground",
        "frame",
        "guide",
        "mount",
        "motor",
        "support",
        "stand",
        "floor",
    ]

    for key in static_keywords:
        if key in n:
            return True

    # 명확한 운동 부품
    dynamic_keywords = [
        "crank",
        "connecting_rod",
        "rod",
        "link",
        "slider_block",
        "coupler",
        "rocker",
    ]

    for key in dynamic_keywords:
        if key in n:
            return False

    return False


def _infer_category(name: str) -> str:
    n = sanitize_name(name).lower()

    if any(k in n for k in ["ground", "base", "fixed", "frame", "stand", "floor"]):
        return "base"

    if any(k in n for k in ["gear", "pinion", "spur"]):
        return "gear"

    if any(k in n for k in ["shaft", "axis", "axle"]):
        return "shaft"

    if any(k in n for k in ["link", "rod", "bar", "crank", "coupler", "rocker", "slider"]):
        return "link"

    return "generic"


def _infer_fixed(occ, body_name: str) -> bool:
    n = sanitize_name(body_name).lower()

    if any(k in n for k in ["ground", "base", "fixed", "frame", "stand", "floor"]):
        return True

    try:
        if hasattr(occ, "isGrounded") and bool(occ.isGrounded):
            return True
    except Exception:
        pass

    return False


def _safe_physical_properties(occ):
    """
    Fusion physical properties를 최대한 가져온다.
    실패하면 None.
    """
    try:
        if hasattr(occ, "getPhysicalProperties"):
            return occ.getPhysicalProperties(adsk.fusion.CalculationAccuracy.HighCalculationAccuracy)
    except Exception:
        pass

    try:
        if hasattr(occ, "physicalProperties"):
            return occ.physicalProperties
    except Exception:
        pass

    try:
        comp = occ.component
        if hasattr(comp, "physicalProperties"):
            return comp.physicalProperties
    except Exception:
        pass

    return None


def _extract_mass_kg(occ, fixed=False) -> float:
    props = _safe_physical_properties(occ)

    try:
        mass = float(props.mass)
        if mass > 1e-9:
            return mass
    except Exception:
        pass

    return 1000.0 if fixed else 1.0


def _try_get_inertia_candidates(props):
    """
    Fusion API 버전마다 inertia 접근 방식이 다를 수 있어서 후보들을 best-effort로 확인한다.
    반환 단위는 Fusion 기준일 수 있으므로, 호출부에서 kg*mm^2 -> kg*m^2 변환을 적용한다.
    """
    if props is None:
        return None

    # 1) principalMomentsOfInertia가 Vector3D류로 존재하는 경우
    try:
        v = getattr(props, "principalMomentsOfInertia", None)
        if v is not None:
            return [
                safe_float(getattr(v, "x", None), None),
                safe_float(getattr(v, "y", None), None),
                safe_float(getattr(v, "z", None), None),
            ]
    except Exception:
        pass

    # 2) getXYZMomentsOfInertia() 형태가 있는 경우
    try:
        if hasattr(props, "getXYZMomentsOfInertia"):
            vals = props.getXYZMomentsOfInertia()
            if vals is not None and len(vals) >= 3:
                return [safe_float(vals[0], None), safe_float(vals[1], None), safe_float(vals[2], None)]
    except Exception:
        pass

    # 3) momentsOfInertia가 Vector3D류로 존재하는 경우
    try:
        v = getattr(props, "momentsOfInertia", None)
        if v is not None:
            return [
                safe_float(getattr(v, "x", None), None),
                safe_float(getattr(v, "y", None), None),
                safe_float(getattr(v, "z", None), None),
            ]
    except Exception:
        pass

    return None


def _extract_inertia_kg_m2(occ, mass_kg: float, fixed=False):
    """
    가능한 경우 Fusion physical properties에서 inertia를 가져온다.
    실패하면 solver 안정성을 위한 fallback diagonal inertia를 생성한다.

    Fusion inertia 단위는 일반적으로 kg*mm^2 계열일 가능성이 높아
    kg*m^2 변환 계수 1e-6를 적용한다.
    """
    props = _safe_physical_properties(occ)
    cand = _try_get_inertia_candidates(props)

    if cand is not None:
        try:
            ixx = float(cand[0]) * 1e-4
            iyy = float(cand[1]) * 1e-4
            izz = float(cand[2]) * 1e-4

            if ixx > 1e-12 and iyy > 1e-12 and izz > 1e-12:
                return {
                    "mode": "explicit",
                    "Ixx": ixx,
                    "Iyy": iyy,
                    "Izz": izz,
                }
        except Exception:
            pass

    # fallback
    if fixed:
        val = 1.0
    else:
        # 너무 작으면 Chrono solver가 불안정할 수 있으므로 하한을 둔다.
        val = max(1e-4, float(mass_kg) * 1e-3)

    return {
        "mode": "explicit",
        "Ixx": val,
        "Iyy": val,
        "Izz": val,
    }


def _default_contact():
    return {
        "friction": 0.4,
        "restitution": 0.05,
    }


def _default_damping(fixed=False):
    if fixed:
        return {
            "type": "viscous_torque",
            "coef": 0.0,
        }

    return {
        "type": "viscous_torque",
        "coef": 0.02,
    }


def _infer_collision(category: str, fixed: bool, has_joints: bool):
    """
    MVP collision policy.

    - base 계열만 auto
    - 움직이는 링크/핀/모터/로드/슬라이더는 none
    - 충돌이 기구학 조인트를 방해하지 않도록 보수적으로 둔다.
    """
    cat = str(category or "generic").lower()

    if cat == "base":
        return "auto"

    return "none"


def _build_body_from_mesh_entry(body_name: str, entry: dict, has_joints: bool, warnings: list):
    transform = entry.get("transform", IDENTITY_TRANSFORM[:])
    unit_scale = safe_float(entry.get("unit_scale", FUSION_MM_TO_M), FUSION_MM_TO_M)

    pose = _pose_from_transform_array(transform, unit_scale=unit_scale)

    # occurrence 객체는 mesh_data에 없으므로 mass/inertia 추출은 run()에서 occ map으로 보강한다.
    category = _infer_category(body_name)
    fixed = False

    body = {
        "name": body_name,
        "category": category,
        "geometry": {
            "visual": {
                "kind": "mesh",
                "file": entry.get("mesh_file", f"meshes/{body_name}.obj"),
                "scale": [1.0, 1.0, 1.0],
                "offset": {
                    "pos": [0.0, 0.0, 0.0],
                    "rot": IDENTITY_QUAT[:],
                },
            },
            "collision": "none",
        },
        "mechanical": {
            "mass": 1.0,
            "fixed": fixed,
            "inertia": {
                "mode": "explicit",
                "Ixx": 0.001,
                "Iyy": 0.001,
                "Izz": 0.001,
            },
            "contact": _default_contact(),
            "damping": _default_damping(fixed=fixed),
        },
        "pose": pose,
    }

    return body


def _create_root_body_if_needed():
    """
    joint가 Root에 연결되는 경우 validate_scene에서 missing body가 나지 않도록
    synthetic Root body를 만든다.

    visual file은 placeholder 경로를 넣는다.
    실제 mesh가 없을 수 있으므로, 가능하면 Fusion assembly에서는 Root 직접 연결보다
    grounded occurrence를 두는 편이 더 안정적이다.
    """
    return {
        "name": "Root",
        "category": "base",
        "geometry": {
            "visual": {
                "kind": "mesh",
                "file": "meshes/__root_placeholder.obj",
                "scale": [1.0, 1.0, 1.0],
                "offset": {
                    "pos": [0.0, 0.0, 0.0],
                    "rot": IDENTITY_QUAT[:],
                },
            },
            "collision": "none",
        },
        "mechanical": {
            "mass": 1000.0,
            "fixed": True,
            "inertia": {
                "mode": "explicit",
                "Ixx": 1.0,
                "Iyy": 1.0,
                "Izz": 1.0,
            },
            "contact": _default_contact(),
            "damping": _default_damping(fixed=True),
        },
        "pose": {
            "pos": [0.0, 0.0, 0.0],
            "rot": IDENTITY_QUAT[:],
        },
    }


def _maybe_write_root_placeholder_obj(mesh_data: dict, warnings: list):
    """
    Root body가 필요한 경우 placeholder OBJ 파일을 가능하면 생성한다.
    mesh_data의 mesh_abs_path를 이용해 output folder를 추정한다.
    """
    try:
        any_entry = next(iter(mesh_data.values()))
        any_abs = any_entry.get("mesh_abs_path", "")
        if not any_abs:
            return

        mesh_folder = os.path.dirname(any_abs)
        root_obj = os.path.join(mesh_folder, "__root_placeholder.obj")

        if os.path.exists(root_obj):
            return

        with open(root_obj, "w", encoding="utf-8") as f:
            f.write("# CADverse root placeholder mesh\n")
            f.write("v -0.001 -0.001 0.0\n")
            f.write("v  0.001 -0.001 0.0\n")
            f.write("v  0.001  0.001 0.0\n")
            f.write("v -0.001  0.001 0.0\n")
            f.write("f 1 2 3\n")
            f.write("f 1 3 4\n")
    except Exception:
        warnings.append("Root placeholder OBJ 생성 실패")
        warnings.append(traceback.format_exc())


# ---------------------------------------------------------------------
# Occurrence mapping helpers
# ---------------------------------------------------------------------

def _build_occurrence_maps(root, mesh_data: dict):
    """
    mesh_data의 body_name과 Fusion occurrence를 연결하기 위한 map 생성.
    extract_mesh.py가 occurrence_name을 우선 body_name으로 썼다는 전제에 맞춘다.
    """
    by_occ_name = {}
    by_comp_name = {}
    by_body_name = {}

    # mesh_data 기준 map
    mesh_by_occ = {}
    mesh_by_comp = {}

    for body_name, entry in mesh_data.items():
        occ_name = sanitize_name(entry.get("occurrence_name", ""))
        comp_name = sanitize_name(entry.get("component_name", ""))

        if occ_name:
            mesh_by_occ.setdefault(occ_name, []).append(body_name)
        if comp_name:
            mesh_by_comp.setdefault(comp_name, []).append(body_name)

    for occ in root.allOccurrences:
        occ_name = sanitize_name(occ.name)
        comp_name = sanitize_name(occ.component.name)

        body_name = None

        if occ_name in mesh_by_occ and len(mesh_by_occ[occ_name]) == 1:
            body_name = mesh_by_occ[occ_name][0]
        elif comp_name in mesh_by_comp and len(mesh_by_comp[comp_name]) == 1:
            body_name = mesh_by_comp[comp_name][0]
        elif occ_name in mesh_data:
            body_name = occ_name
        elif comp_name in mesh_data:
            body_name = comp_name

        if body_name:
            by_occ_name[occ_name] = body_name
            by_comp_name.setdefault(comp_name, []).append(body_name)
            by_body_name[body_name] = occ

    return by_occ_name, by_comp_name, by_body_name


def _body_name_for_occ(occ, by_occ_name: dict, by_comp_name: dict):
    if occ is None:
        return "Root"

    occ_name = sanitize_name(occ.name)
    comp_name = sanitize_name(occ.component.name)

    if occ_name in by_occ_name:
        return by_occ_name[occ_name]

    comp_matches = by_comp_name.get(comp_name, [])
    if len(comp_matches) == 1:
        return comp_matches[0]

    # fallback: occurrence name
    return occ_name or comp_name or "Root"


# ---------------------------------------------------------------------
# Joint metadata helpers
# ---------------------------------------------------------------------
def _collect_all_fusion_joints(root, warnings: list):
    """
    Fusion의 일반 Joint와 As-Built Joint를 모두 수집한다.

    - 일반 조인트: root.allJoints
    - 현재 위치에서 접합 / As-Built Joint: root.allAsBuiltJoints

    우리가 Fusion에서 Shift+J로 만든 조인트는 보통 allAsBuiltJoints에 들어간다.
    """
    result = []

    try:
        for j in root.allJoints:
            result.append(j)
    except Exception:
        warnings.append("root.allJoints 수집 실패")
        warnings.append(traceback.format_exc())

    try:
        for j in root.allAsBuiltJoints:
            result.append(j)
    except Exception:
        warnings.append("root.allAsBuiltJoints 수집 실패")
        warnings.append(traceback.format_exc())

    warnings.append(
        f"Fusion joints collected: total={len(result)} "
        "(root.allJoints + root.allAsBuiltJoints)"
    )

    return result


def _try_read_origin_from_obj(obj):
    """
    Fusion Joint / JointGeometry / JointOrigin 후보 객체에서 origin point를 읽는다.
    성공하면 [x,y,z] in meters, 실패하면 None.
    """
    if obj is None:
        return None

    try:
        if hasattr(obj, "origin"):
            o = getattr(obj, "origin", None)
            if o is not None:
                return _point3d_to_m_list(o)
    except Exception:
        pass

    try:
        if hasattr(obj, "geometry"):
            g = getattr(obj, "geometry", None)
            if g is not None and hasattr(g, "origin"):
                o = getattr(g, "origin", None)
                if o is not None:
                    return _point3d_to_m_list(o)
    except Exception:
        pass

    try:
        if hasattr(obj, "point"):
            p = getattr(obj, "point", None)
            if p is not None:
                return _point3d_to_m_list(p)
    except Exception:
        pass

    try:
        if hasattr(obj, "x") and hasattr(obj, "y") and hasattr(obj, "z"):
            return _point3d_to_m_list(obj)
    except Exception:
        pass

    return None


def _joint_origin_m(joint):
    """
    Fusion joint의 origin을 최대한 안정적으로 추출한다.

    핵심:
    - 일부 Joint/AsBuiltJoint의 geometry는 현재 timeline 위치에서는 접근이 실패한다.
    - Fusion 오류 메시지가 "roll back timeline to before joint creation"을 요구하므로,
      joint.timelineObject.rollTo(True)를 시도한 뒤 geometry를 읽는다.
    - 그래도 실패하면 [0,0,0]을 반환하고, 호출부에서 skip 처리한다.
    """
    def _read_candidates():
        for attr in [
            "geometryOrOriginOne",
            "geometryOrOriginTwo",
            "origin",
            "geometry",
            "jointGeometry",
            "geometryOne",
            "geometryTwo",
        ]:
            try:
                c = getattr(joint, attr, None)
            except Exception:
                c = None

            p = _try_read_origin_from_obj(c)
            if p is not None:
                return p

        return None

    # 1) 현재 timeline 위치에서 먼저 시도
    p = _read_candidates()
    if p is not None:
        return p

    # 2) timeline rollback 후 다시 시도
    rolled = False
    try:
        tl = getattr(joint, "timelineObject", None)
        if tl is not None:
            tl.rollTo(True)
            rolled = True
    except Exception:
        rolled = False

    try:
        if rolled:
            p = _read_candidates()
            if p is not None:
                return p
    finally:
        # timeline을 다시 끝으로 돌려놓는다.
        # 실패해도 export 자체가 죽지 않도록 조용히 넘긴다.
        try:
            app = adsk.core.Application.get()
            design = app.activeProduct if app is not None else None
            timeline = getattr(design, "timeline", None)
            if timeline is not None:
                timeline.moveToEnd()
        except Exception:
            pass

    return [0.0, 0.0, 0.0]


def _debug_joint_origin_candidates(joint, warnings: list):
    """
    진단용:
    Fusion Joint / As-Built Joint 객체 안에 origin 후보가 어디 들어있는지 exportWarnings에 출력한다.
    metadata 값은 바꾸지 않는다.
    """
    joint_name = getattr(joint, "name", "?")

    warnings.append(f"--- Joint origin candidate dump: {joint_name} ---")
    warnings.append(f"{joint_name}.objectType = {getattr(joint, 'objectType', '?')}")

    candidate_attrs = [
        "geometryOrOriginOne",
        "geometryOrOriginTwo",
        "origin",
        "geometry",
        "jointGeometry",
        "geometryOne",
        "geometryTwo",
        "jointMotion",
    ]

    for attr in candidate_attrs:
        try:
            obj = getattr(joint, attr, None)

            if obj is None:
                warnings.append(f"{joint_name}.{attr}: None")
                continue

            warnings.append(
                f"{joint_name}.{attr}: type={getattr(obj, 'objectType', type(obj).__name__)}"
            )

            # obj.origin
            try:
                o = getattr(obj, "origin", None)
                if o is not None:
                    warnings.append(
                        f"{joint_name}.{attr}.origin = "
                        f"({safe_float(getattr(o, 'x', None), 0.0):+.6f}, "
                        f"{safe_float(getattr(o, 'y', None), 0.0):+.6f}, "
                        f"{safe_float(getattr(o, 'z', None), 0.0):+.6f})"
                    )
            except Exception:
                pass

            # obj.point
            try:
                p = getattr(obj, "point", None)
                if p is not None:
                    warnings.append(
                        f"{joint_name}.{attr}.point = "
                        f"({safe_float(getattr(p, 'x', None), 0.0):+.6f}, "
                        f"{safe_float(getattr(p, 'y', None), 0.0):+.6f}, "
                        f"{safe_float(getattr(p, 'z', None), 0.0):+.6f})"
                    )
            except Exception:
                pass

            # obj.geometry.origin
            try:
                g = getattr(obj, "geometry", None)
                if g is not None:
                    warnings.append(
                        f"{joint_name}.{attr}.geometry: type={getattr(g, 'objectType', type(g).__name__)}"
                    )

                    go = getattr(g, "origin", None)
                    if go is not None:
                        warnings.append(
                            f"{joint_name}.{attr}.geometry.origin = "
                            f"({safe_float(getattr(go, 'x', None), 0.0):+.6f}, "
                            f"{safe_float(getattr(go, 'y', None), 0.0):+.6f}, "
                            f"{safe_float(getattr(go, 'z', None), 0.0):+.6f})"
                        )
            except Exception:
                pass

        except Exception as e:
            warnings.append(f"{joint_name}.{attr}: ERROR {e}")

    warnings.append(f"--- End joint origin candidate dump: {joint_name} ---")


def _vec_to_list(v):
    try:
        return [float(v.x), float(v.y), float(v.z)]
    except Exception:
        return None


def _normalize_vec3(v, fallback=(0.0, 0.0, 1.0)):
    try:
        x, y, z = float(v[0]), float(v[1]), float(v[2])
        n = math.sqrt(x * x + y * y + z * z)
        if n < 1e-12:
            return [float(fallback[0]), float(fallback[1]), float(fallback[2])]
        return [x / n, y / n, z / n]
    except Exception:
        return [float(fallback[0]), float(fallback[1]), float(fallback[2])]


def _quat_from_local_z_to_axis(axis):
    """
    metadata 규칙:
    frame.local Z축이 joint 자유도 방향이 되어야 함.

    따라서 기본 local Z = (0,0,1)을 주어진 world axis로 보내는 quaternion을 만든다.
    반환 형식: [w, x, y, z]
    """
    z0 = [0.0, 0.0, 1.0]
    a = _normalize_vec3(axis, fallback=(0.0, 0.0, 1.0))

    dot = z0[0] * a[0] + z0[1] * a[1] + z0[2] * a[2]

    # 이미 같은 방향
    if dot > 0.999999:
        return [1.0, 0.0, 0.0, 0.0]

    # 정반대 방향: X축 기준 180도 회전
    if dot < -0.999999:
        return [0.0, 1.0, 0.0, 0.0]

    # cross(z0, a)
    cx = z0[1] * a[2] - z0[2] * a[1]
    cy = z0[2] * a[0] - z0[0] * a[2]
    cz = z0[0] * a[1] - z0[1] * a[0]

    s = math.sqrt((1.0 + dot) * 2.0)
    inv_s = 1.0 / s

    q = [
        0.5 * s,
        cx * inv_s,
        cy * inv_s,
        cz * inv_s,
    ]

    # normalize quaternion
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    if n < 1e-12:
        return [1.0, 0.0, 0.0, 0.0]

    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n]


def _joint_axis_world(joint, j_type: str, warnings: list):
    """
    Fusion Joint / As-Built Joint에서 자유도 축을 최대한 추출한다.

    revolute  -> rotationAxisVector
    prismatic -> slideDirectionVector

    실패하면:
    - revolute 기본값: Z축
    - prismatic 기본값: X축
    """
    motion = None

    try:
        motion = getattr(joint, "jointMotion", None)
    except Exception:
        motion = None

    axis = None

    if motion is not None:
        if j_type == "revolute":
            for attr in ["rotationAxisVector", "axisVector", "jointAxisVector"]:
                try:
                    v = getattr(motion, attr, None)
                    axis = _vec_to_list(v)
                    if axis is not None:
                        break
                except Exception:
                    pass

        elif j_type == "prismatic":
            for attr in ["slideDirectionVector", "axisVector", "jointAxisVector"]:
                try:
                    v = getattr(motion, attr, None)
                    axis = _vec_to_list(v)
                    if axis is not None:
                        break
                except Exception:
                    pass

    # 일부 Fusion 객체는 joint 자체나 geometry 쪽에 axis가 있을 수도 있음
    if axis is None:
        for attr in [
            "axisVector",
            "rotationAxisVector",
            "slideDirectionVector",
        ]:
            try:
                v = getattr(joint, attr, None)
                axis = _vec_to_list(v)
                if axis is not None:
                    break
            except Exception:
                pass

    if axis is None:
        if j_type == "prismatic":
            axis = [1.0, 0.0, 0.0]
        else:
            axis = [0.0, 0.0, 1.0]

        warnings.append(
            f"Joint axis fallback used: {getattr(joint, 'name', '?')} "
            f"type={j_type} axis={axis}"
        )

    axis = _normalize_vec3(axis)

    warnings.append(
        f"Joint axis: {getattr(joint, 'name', '?')} "
        f"type={j_type} axis=({axis[0]:+.6f}, {axis[1]:+.6f}, {axis[2]:+.6f})"
    )

    return axis


def _limits_for_revolute(motion):
    try:
        lim = motion.rotationLimits
        lower = None
        upper = None

        # 엔진은 revolute limit을 rad 기준으로 사용.
        if lim.isMinimumValueEnabled:
            lower = float(lim.minimumValue)
        if lim.isMaximumValueEnabled:
            upper = float(lim.maximumValue)

        if lower is None and upper is None:
            return None

        out = {"enable": True}
        if lower is not None:
            out["lower"] = lower
        if upper is not None:
            out["upper"] = upper
        return out

    except Exception:
        return None


def _limits_for_slider(motion):
    try:
        lim = motion.slideLimits
        lower = None
        upper = None

        # Fusion length value는 mm 기준으로 보고 m로 변환.
        if lim.isMinimumValueEnabled:
            lower = float(lim.minimumValue) * FUSION_MM_TO_M
        if lim.isMaximumValueEnabled:
            upper = float(lim.maximumValue) * FUSION_MM_TO_M

        if lower is None and upper is None:
            return None

        out = {"enable": True}
        if lower is not None:
            out["lower"] = lower
        if upper is not None:
            out["upper"] = upper
        return out

    except Exception:
        return None


def _joint_name(joint, used_joint_names: set):
    raw = sanitize_name(getattr(joint, "name", "joint"))
    return make_unique_name(raw or "joint", used_joint_names)


def _extract_joint_meta(joint, by_occ_name: dict, by_comp_name: dict, used_joint_names: set, warnings: list, body_pose_by_name: dict):
    motion = joint.jointMotion
    motion_type = motion.objectType

    body1 = _body_name_for_occ(joint.occurrenceOne, by_occ_name, by_comp_name)
    body2 = _body_name_for_occ(joint.occurrenceTwo, by_occ_name, by_comp_name)

    name = _joint_name(joint, used_joint_names)

    joint_type = None
    limits = None

    if motion_type == adsk.fusion.RevoluteJointMotion.classType():
        joint_type = "revolute"
        limits = _limits_for_revolute(motion)

    elif motion_type == adsk.fusion.SliderJointMotion.classType():
        joint_type = "prismatic"
        limits = _limits_for_slider(motion)

    elif motion_type == adsk.fusion.RigidJointMotion.classType():
        warnings.append(
            f"Fixed joint skipped by MVP policy: {name} "
            f"({body1} - {body2})"
        )
        return None

    else:
        warnings.append(
            f"Unsupported joint motion skipped: joint='{getattr(joint, 'name', '?')}', "
            f"motionType='{motion_type}'"
        )
        return None

    frame_pos = _joint_origin_m(joint)

    if (
        abs(frame_pos[0]) < 1e-12
        and abs(frame_pos[1]) < 1e-12
        and abs(frame_pos[2]) < 1e-12
        and joint_type in ["revolute", "prismatic"]
    ):
        _debug_joint_origin_candidates(joint, warnings)

    if (
        abs(frame_pos[0]) < 1e-12
        and abs(frame_pos[1]) < 1e-12
        and abs(frame_pos[2]) < 1e-12
        and joint_type in ["revolute", "prismatic"]
    ):
        warnings.append(
            f"Joint skipped because origin extraction returned zero: "
            f"{name} type={joint_type} body1={body1} body2={body2}. "
            "Please define this joint with an explicit CAD joint origin."
        )
        return None


    # Engine rule:
    # frame.local Z-axis = DOF direction
    #
    # fixed joint는 자유도 축이 의미 없으므로 identity 유지.
    # revolute/prismatic은 Fusion에서 추출한 axis를 frame.rot에 반영한다.
    if joint_type in ["revolute", "prismatic"]:
        axis = _joint_axis_world(joint, joint_type, warnings)
        frame_rot = quat_from_two_vectors([0.0, 0.0, 1.0], axis)
    else:
        axis = [0.0, 0.0, 1.0]
        frame_rot = IDENTITY_QUAT[:]

    warnings.append(
        f"Joint frame: {name} "
        f"type={joint_type} "
        f"body1={body1} body2={body2} "
        f"pos=({frame_pos[0]:+.6f}, {frame_pos[1]:+.6f}, {frame_pos[2]:+.6f}) "
        f"axis=({axis[0]:+.6f}, {axis[1]:+.6f}, {axis[2]:+.6f}) "
        f"rot=({frame_rot[0]:+.6f}, {frame_rot[1]:+.6f}, {frame_rot[2]:+.6f}, {frame_rot[3]:+.6f})"
    )

    out = {
        "name": name,
        "type": joint_type,
        "body1": body1,
        "body2": body2,
        "frame": {
            "pos": frame_pos,
            "rot": frame_rot,
        },
    }

    if limits is not None:
        out["limits"] = limits

    return out


# ---------------------------------------------------------------------
# Gear / actuator placeholder helpers
# ---------------------------------------------------------------------

def _try_infer_gear_props(body: dict):
    """
    이름 기반으로 gear category는 추정하지만,
    teeth/module은 CAD geometry만으로 안정 추출하기 어렵다.
    그래서 자동 기입하지 않는다.
    """
    return None


# ---------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------

def run(context, mesh_data=None):
    """
    extract_mesh.py 결과를 받아 simulator metadata의 중간 구조를 만든다.

    반환 구조:

    {
        "bodies": [...],
        "joints": [...],
        "gearPairs": [],
        "actuators": [],
        "warnings": [...]
    }
    """
    warnings = []

    if mesh_data is None:
        mesh_data = {}

    app = adsk.core.Application.get()
    if app is None:
        raise RuntimeError("Fusion Application을 가져오지 못했습니다.")

    design = app.activeProduct
    if design is None:
        raise RuntimeError("활성 Fusion design이 없습니다.")

    if not isinstance(design, adsk.fusion.Design):
        raise RuntimeError("activeProduct가 Fusion Design이 아닙니다.")

    root = design.rootComponent

    # joint 유무에 따라 collision 기본 정책을 다르게 둔다.
    # Fusion collection의 count 속성이 환경에 따라 불안정할 수 있으므로,
    # 직접 순회해서 개수를 판단한다.
    try:
        joint_count = 0

        try:
            for _ in root.allJoints:
                joint_count += 1
        except Exception:
            pass

        try:
            for _ in root.allAsBuiltJoints:
                joint_count += 1
        except Exception:
            pass

        has_joints = joint_count > 0
        warnings.append(f"Fusion joint count for collision policy: {joint_count}")

    except Exception:
        has_joints = True
        warnings.append("Fusion joint count for collision policy failed. has_joints=True fallback used.")

    by_occ_name, by_comp_name, by_body_name = _build_occurrence_maps(root, mesh_data)

    bodies = []
    used_body_names = set()

    # 1) mesh_data 기반 body 생성
    for body_name, entry in mesh_data.items():
        clean_body_name = sanitize_name(body_name)

        # MVP policy:
        # pin류는 별도 물리 body로 두면 floating/over-constraint 문제가 생기기 쉬우므로 제외한다.
        if _is_visual_only_body_name(clean_body_name):
            warnings.append(f"Visual-only body skipped by MVP policy: {clean_body_name}")
            continue

        final_body_name = make_unique_name(clean_body_name, used_body_names)

        if final_body_name != body_name:
            warnings.append(f"Body name duplicated/renamed: '{body_name}' -> '{final_body_name}'")

        body = _build_body_from_mesh_entry(final_body_name, entry, has_joints, warnings)

        occ = by_body_name.get(body_name, None)
        if occ is None:
            occ = by_body_name.get(final_body_name, None)

        category = _infer_category(final_body_name)

        # 중요:
        # 기존 _infer_fixed()는 frame/base만 고정하고 motor/mount를 dynamic으로 둘 수 있다.
        # MVP에서는 Fusion fixed joint를 constraint로 쓰지 않으므로,
        # 이름/category 정책으로 고정 구조물을 body fixed 처리한다.
        fixed = _infer_fixed_body_from_name(final_body_name, category)

        mass = _extract_mass_kg(occ, fixed=fixed) if occ is not None else (1000.0 if fixed else 1.0)
        inertia = _extract_inertia_kg_m2(occ, mass, fixed=fixed) if occ is not None else {
            "mode": "explicit",
            "Ixx": 1.0 if fixed else max(1e-4, mass * 1e-3),
            "Iyy": 1.0 if fixed else max(1e-4, mass * 1e-3),
            "Izz": 1.0 if fixed else max(1e-4, mass * 1e-3),
        }

        body["name"] = final_body_name
        body["category"] = category
        body["mechanical"]["fixed"] = bool(fixed)
        body["mechanical"]["mass"] = mass
        body["mechanical"]["inertia"] = inertia
        body["mechanical"]["damping"] = _default_damping(fixed=fixed)
        body["geometry"]["collision"] = _infer_collision(category, fixed, has_joints)

        # gear body인 경우 gearProps는 자동 추정이 어렵기 때문에 warning만 남김.
        if category == "gear":
            warnings.append(
                f"Gear-like body detected: '{final_body_name}'. "
                "gearProps(module, teeth, face_width)는 자동 추정하지 않았습니다."
            )

        bodies.append(body)

    body_pose_by_name = {
        b.get("name"): b.get("pose", {})
        for b in bodies
        if b.get("name")
    }

    # 2) joints 생성
    joints = []
    used_joint_names = set()
    needs_root_body = False

    fusion_joints = _collect_all_fusion_joints(root, warnings)

    for joint in fusion_joints:
        try:
            j = _extract_joint_meta(
                joint,
                by_occ_name,
                by_comp_name,
                used_joint_names,
                warnings,
                body_pose_by_name,
            )
            if j is None:
                continue

            if j["body1"] == "Root" or j["body2"] == "Root":
                needs_root_body = True

            joints.append(j)

        except Exception:
            warnings.append(f"Joint extraction failed: '{getattr(joint, 'name', '?')}'")
            warnings.append(traceback.format_exc())

    # 3) Root body가 필요하면 추가
    if needs_root_body:
        existing = set(b["name"] for b in bodies)
        if "Root" not in existing:
            bodies.insert(0, _create_root_body_if_needed())
            _maybe_write_root_placeholder_obj(mesh_data, warnings)
            warnings.append(
                "Synthetic 'Root' body was added because at least one joint is connected to Root. "
                "가능하면 CAD에서 ground/base occurrence를 명시적으로 두는 것을 권장합니다."
            )

    # 4) body 참조 무결성 보정
    body_names = set(b["name"] for b in bodies)
    filtered_joints = []

    for j in joints:
        if j["body1"] not in body_names or j["body2"] not in body_names:
            warnings.append(
                f"Joint skipped due to missing body reference: "
                f"{j['name']} ({j['body1']} - {j['body2']})"
            )
            continue

        if j["body1"] == j["body2"]:
            warnings.append(
                f"Joint skipped because body1 == body2: {j['name']} ({j['body1']})"
            )
            continue

        filtered_joints.append(j)

    # 5) gearPairs / actuators는 현재 Fusion joint만으로 안정 자동 추출이 어려워 빈 배열 유지
    gear_pairs = []
    actuators = []

    return {
        "transforms": _build_legacy_ar_transforms(bodies),
        "bodies": bodies,
        "joints": filtered_joints,
        "gearPairs": gear_pairs,
        "actuators": actuators,
        "warnings": warnings,
    }