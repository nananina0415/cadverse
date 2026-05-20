# extract_mesh.py

import adsk.core
import adsk.fusion
import traceback
import os
import re
import json
import math


# ---------------------------------------------------------------------
# Unit / OBJ bake policy
# ---------------------------------------------------------------------

# Fusion 360 API 내부 단위는 항상 cm (display 설정 무관).
# Simulator metadata / Chrono 쪽은 m 기준으로 사용한다.
FUSION_CM_TO_M = 0.01

# OBJ vertex도 최종적으로 m 단위로 bake한다.
OBJ_VERTEX_CM_TO_M = 0.01

# 중요:
# Fusion OBJ export가 occurrence/world 좌표를 포함한다고 보고,
# OBJ vertex를 occurrence local 좌표로 되돌린다.
#
# 만약 이 설정 후 mesh가 더 이상해지면,
# 아래 값을 "local"로 바꿔서 재추출하면 된다.
#
# "world": OBJ vertex가 world 좌표라고 보고 inverse occurrence transform 적용
# "local": OBJ vertex가 이미 local 좌표라고 보고 단위 변환만 적용
OBJ_EXPORT_COORDINATE_MODE = "local"


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


def _safe_transform_array_from_occ(occ):
    try:
        arr = occ.transform.asArray()
        return [float(x) for x in arr]
    except Exception:
        return IDENTITY_TRANSFORM[:]


def _decompose_fusion_transform(arr, unit_scale=FUSION_CM_TO_M):
    """
    Fusion Matrix3D.asArray()를 다음 형태로 분해한다.

    현재 프로젝트 기준 해석:
    - X axis = arr[0:3]
    - Y axis = arr[4:7]
    - Z axis = arr[8:11]
    - origin = arr[12:15]

    반환:
    {
        "pos": [px, py, pz] in meters,
        "x_axis": normalized world x axis,
        "y_axis": normalized world y axis,
        "z_axis": normalized world z axis,
    }
    """
    if not isinstance(arr, (list, tuple)) or len(arr) < 16:
        arr = IDENTITY_TRANSFORM[:]

    px = safe_float(arr[12], 0.0) * unit_scale
    py = safe_float(arr[13], 0.0) * unit_scale
    pz = safe_float(arr[14], 0.0) * unit_scale

    # 일부 환경 fallback: translation이 3,7,11에 들어가는 경우 대비
    if abs(px) < 1e-12 and abs(py) < 1e-12 and abs(pz) < 1e-12:
        alt = [
            safe_float(arr[3], 0.0) * unit_scale,
            safe_float(arr[7], 0.0) * unit_scale,
            safe_float(arr[11], 0.0) * unit_scale,
        ]
        if vec_norm(alt) > 1e-12:
            px, py, pz = alt

    x_axis = vec_normalize([
        safe_float(arr[0], 1.0),
        safe_float(arr[1], 0.0),
        safe_float(arr[2], 0.0),
    ])

    y_axis = vec_normalize([
        safe_float(arr[4], 0.0),
        safe_float(arr[5], 1.0),
        safe_float(arr[6], 0.0),
    ])

    z_axis = vec_normalize([
        safe_float(arr[8], 0.0),
        safe_float(arr[9], 0.0),
        safe_float(arr[10], 1.0),
    ])

    return {
        "pos": [px, py, pz],
        "x_axis": x_axis,
        "y_axis": y_axis,
        "z_axis": z_axis,
    }


def _world_point_to_occ_local(p_world_m, transform_info):
    """
    world 좌표의 점을 occurrence local 좌표로 변환한다.

    p_local = R^-1 * (p_world - body_pos)

    transform_info의 x/y/z axis는 world 좌표계에서의 occurrence local basis로 본다.
    따라서 inverse rotation은 각 axis와 dot product로 계산 가능하다.
    """
    pos = transform_info["pos"]
    d = [
        p_world_m[0] - pos[0],
        p_world_m[1] - pos[1],
        p_world_m[2] - pos[2],
    ]

    return [
        vec_dot(d, transform_info["x_axis"]),
        vec_dot(d, transform_info["y_axis"]),
        vec_dot(d, transform_info["z_axis"]),
    ]


def _world_vector_to_occ_local(v_world, transform_info):
    """
    world 방향 벡터를 occurrence local 방향 벡터로 변환한다.
    normal에는 translation이 없고 rotation inverse만 적용한다.
    """
    return vec_normalize([
        vec_dot(v_world, transform_info["x_axis"]),
        vec_dot(v_world, transform_info["y_axis"]),
        vec_dot(v_world, transform_info["z_axis"]),
    ])


def _bbox_from_points(points):
    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]

    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
        "center": [
            0.5 * (min(xs) + max(xs)),
            0.5 * (min(ys) + max(ys)),
            0.5 * (min(zs) + max(zs)),
        ],
        "size": [
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
        ],
    }


# ---------------------------------------------------------------------
# OBJ post-process
# ---------------------------------------------------------------------

def _bake_obj_vertices_to_m_and_local(obj_path: str, transform_array: list, mode: str = OBJ_EXPORT_COORDINATE_MODE):
    """
    Fusion에서 export된 OBJ를 simulator용으로 후처리한다.

    처리 정책:
    1. v 라인 좌표를 mm -> m로 변환
    2. mode == "world"이면 occurrence inverse transform을 적용해서 body-local 좌표로 변환
    3. vn 라인도 mode == "world"이면 inverse rotation을 적용
    4. vt / f / g / mtllib 등은 그대로 유지

    반환:
    debug 정보 dict
    """
    if not os.path.exists(obj_path):
        return {
            "ok": False,
            "reason": "obj_path_not_found",
            "obj_path": obj_path,
        }

    transform_info = _decompose_fusion_transform(transform_array, unit_scale=FUSION_CM_TO_M)

    original_points_m = []
    baked_points = []

    new_lines = []
    vertex_count = 0
    normal_count = 0

    with open(obj_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    for line in lines:
        # vertex position
        if line.startswith("v "):
            parts = line.strip().split()

            if len(parts) >= 4:
                try:
                    # Fusion OBJ vertex를 mm 값으로 보고 m로 변환
                    p_m = [
                        float(parts[1]) * OBJ_VERTEX_CM_TO_M,
                        float(parts[2]) * OBJ_VERTEX_CM_TO_M,
                        float(parts[3]) * OBJ_VERTEX_CM_TO_M,
                    ]

                    original_points_m.append(p_m)

                    if mode == "world":
                        p_out = _world_point_to_occ_local(p_m, transform_info)
                    else:
                        p_out = p_m

                    baked_points.append(p_out)
                    vertex_count += 1

                    # vertex color 등 추가 값 보존
                    rest = parts[4:]
                    if rest:
                        new_line = (
                            f"v {p_out[0]:.9f} {p_out[1]:.9f} {p_out[2]:.9f} "
                            + " ".join(rest)
                            + "\n"
                        )
                    else:
                        new_line = f"v {p_out[0]:.9f} {p_out[1]:.9f} {p_out[2]:.9f}\n"

                    new_lines.append(new_line)
                    continue

                except Exception:
                    # 파싱 실패 시 원본 유지
                    new_lines.append(line)
                    continue

        # vertex normal
        elif line.startswith("vn "):
            parts = line.strip().split()

            if len(parts) >= 4:
                try:
                    n = vec_normalize([
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                    ])

                    if mode == "world":
                        n_out = _world_vector_to_occ_local(n, transform_info)
                    else:
                        n_out = n

                    normal_count += 1
                    new_lines.append(f"vn {n_out[0]:.9f} {n_out[1]:.9f} {n_out[2]:.9f}\n")
                    continue

                except Exception:
                    new_lines.append(line)
                    continue

        new_lines.append(line)

    with open(obj_path, "w", encoding="utf-8", errors="ignore") as f:
        f.writelines(new_lines)

    original_bbox = _bbox_from_points(original_points_m)
    baked_bbox = _bbox_from_points(baked_points)

    return {
        "ok": True,
        "obj_path": obj_path,
        "mode": mode,
        "vertex_count": vertex_count,
        "normal_count": normal_count,
        "occurrence_pos_m": transform_info["pos"],
        "original_bbox_m": original_bbox,
        "baked_bbox_m": baked_bbox,
    }


# ---------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------

def run(context, save_folder):
    """
    Fusion active design에서 occurrence별 OBJ mesh를 저장하고,
    simulator metadata 생성을 위한 mesh_data를 반환한다.

    반환 예:
    {
        "body_name": {
            "body_name": "body_name",
            "mesh_file": "meshes/body_name.obj",
            "mesh_abs_path": "...",
            "transform": [...],
            "unit_scale": 0.001,
            "occurrence_name": "...",
            "component_name": "...",
            "obj_bake": {...debug...}
        }
    }
    """
    app = adsk.core.Application.get()
    if app is None:
        raise RuntimeError("Fusion Application을 가져오지 못했습니다.")

    design = app.activeProduct
    if design is None:
        raise RuntimeError("활성 Fusion design이 없습니다.")

    if not isinstance(design, adsk.fusion.Design):
        raise RuntimeError("activeProduct가 Fusion Design이 아닙니다.")

    export_mgr = design.exportManager
    root = design.rootComponent

    mesh_folder = os.path.join(save_folder, "meshes")
    os.makedirs(mesh_folder, exist_ok=True)

    mesh_data = {}
    used_names = set()
    debug_records = []

    for occ in root.allOccurrences:
        try:
            occ_name = sanitize_name(occ.name)
            comp_name = sanitize_name(occ.component.name)

            # occurrence 이름을 우선 사용한다.
            # Fusion browser에서 보이는 이름과 metadata body 이름을 맞추기 위함.
            body_name = make_unique_name(occ_name or comp_name, used_names)

            mesh_rel_path = f"meshes/{body_name}.obj"
            mesh_abs_path = os.path.join(mesh_folder, f"{body_name}.obj")

            transform_array = _safe_transform_array_from_occ(occ)

            # 1) Fusion OBJ export
            obj_opt = export_mgr.createOBJExportOptions(occ, mesh_abs_path)
            export_mgr.execute(obj_opt)

            # 2) OBJ 후처리
            #    - mm -> m
            #    - world OBJ라고 보고 occurrence-local로 변환
            bake_debug = _bake_obj_vertices_to_m_and_local(
                obj_path=mesh_abs_path,
                transform_array=transform_array,
                mode=OBJ_EXPORT_COORDINATE_MODE,
            )

            debug_records.append({
                "body_name": body_name,
                "occurrence_name": occ_name,
                "component_name": comp_name,
                "mesh_file": mesh_rel_path,
                "transform": transform_array,
                "obj_bake": bake_debug,
            })

            mesh_data[body_name] = {
                "body_name": body_name,
                "mesh_file": mesh_rel_path,
                "mesh_abs_path": mesh_abs_path,
                "transform": transform_array,
                "unit_scale": FUSION_CM_TO_M,
                "occurrence_name": occ_name,
                "component_name": comp_name,
                "obj_bake": bake_debug,
            }

        except Exception:
            # 특정 occurrence 하나 실패해도 전체 export가 죽지 않게 한다.
            debug_records.append({
                "body_name": getattr(occ, "name", "?"),
                "error": traceback.format_exc(),
            })


    return mesh_data