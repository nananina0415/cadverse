# simulator/scene_loader.py
# metadata.json → PyChrono 8.0.x 월드 빌드
#
# metadata.json 구조:
#   info: { version, coordinate_system, units }
#   transforms: { part_name: [16 floats, row-major 4x4, cm] }
#   joints: [{ name, type, connected_parts: {parent, child}, axis, origin, limits }]

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import sys
import numpy as np

# Windows Python 3.8+: DLL 검색 정책 변경으로 os.add_dll_directory() 필요
# pychrono의 _core.pyd가 Library/bin의 ChronoEngine.dll에 의존
# 주의: PyO3 임베디드 환경에서 sys.executable은 호스트 exe를 가리키므로
#       sys.prefix (= PYTHONHOME)를 사용해야 conda 환경 루트를 얻을 수 있음
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    _env_root = sys.prefix  # conda 환경 루트 (e.g. C:\...\anaconda3\envs\cadverse_dev)
    _lib_bin = os.path.join(_env_root, "Library", "bin")
    if os.path.isdir(_lib_bin):
        os.add_dll_directory(_lib_bin)
    # site-packages 루트 추가 (_core.pyd 위치)
    _site_pkg = os.path.join(_env_root, "Lib", "site-packages")
    if os.path.isdir(_site_pkg):
        os.add_dll_directory(_site_pkg)
    print(f"[scene_loader] DLL dirs: lib_bin={_lib_bin} (exists={os.path.isdir(_lib_bin)}), "
          f"site_pkg={_site_pkg} (exists={os.path.isdir(_site_pkg)})")

import pychrono as chrono


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    system: Any                          # chrono.ChSystemNSC
    bodies: Dict[str, Any]               # name -> ChBodyAuxRef
    joints: Dict[str, Any]               # name -> ChLinkLockRevolute (or similar)
    body_order: List[str]                 # ordered part names for output


# ---------------------------------------------------------------------------
# 4×4 matrix decomposition
# ---------------------------------------------------------------------------

def _decompose_matrix(flat16: List[float]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Row-major 4×4 → (rotation 3×3, translation [x,y,z] in metres).
    Plugin exports cm, so we convert translation to metres.
    """
    mat = np.array(flat16, dtype=float).reshape(4, 4)
    R = mat[:3, :3].copy()
    t = mat[:3, 3].copy() * 0.01  # cm → m
    return R, t


def _rotation_matrix_to_quat_wxyz(R: np.ndarray) -> Tuple[float, float, float, float]:
    """
    3×3 rotation matrix → quaternion (w, x, y, z).
    Uses Shepperd's method for numerical stability.
    """
    trace = R[0, 0] + R[1, 1] + R[2, 2]

    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (R[2, 1] - R[1, 2]) * s
        y = (R[0, 2] - R[2, 0]) * s
        z = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s

    return (w, x, y, z)


def _rotation_to_chrono_quat(R: np.ndarray) -> chrono.ChQuaterniond:
    """3×3 rotation → Chrono quaternion (e0=w, e1=x, e2=y, e3=z)."""
    w, x, y, z = _rotation_matrix_to_quat_wxyz(R)
    return chrono.ChQuaterniond(w, x, y, z)


# ---------------------------------------------------------------------------
# Joint frame: align Z-axis to desired rotation axis
# ---------------------------------------------------------------------------

def _axis_to_chrono_frame(
    axis: List[float],
    origin_m: np.ndarray,
) -> chrono.ChFramed:
    """
    Build a ChFramed whose Z-axis is aligned to `axis`, located at `origin_m` (metres).
    ChLinkLockRevolute uses Z-axis as the rotation axis.
    """
    z = np.array(axis, dtype=float)
    norm = np.linalg.norm(z)
    if norm < 1e-12:
        raise ValueError(f"Joint axis is zero-length: {axis}")
    z = z / norm

    # Pick an arbitrary perpendicular vector
    up = np.array([0.0, 1.0, 0.0])
    if abs(np.dot(z, up)) > 0.9:
        up = np.array([1.0, 0.0, 0.0])

    x = np.cross(up, z)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)

    R = np.column_stack([x, y, z])
    q = _rotation_to_chrono_quat(R)
    pos = chrono.ChVector3d(float(origin_m[0]), float(origin_m[1]), float(origin_m[2]))
    return chrono.ChFramed(pos, q)


# ---------------------------------------------------------------------------
# Determine which bodies should be fixed
# ---------------------------------------------------------------------------

def _find_fixed_bodies(
    part_names: List[str],
    joints_data: List[Dict[str, Any]],
) -> Set[str]:
    """
    Determine which bodies should be fixed (immovable).

    Rules:
    1. If no joints exist, all bodies are fixed.
    2. Bodies not connected to any joint are fixed (isolated → no reason to move).
    3. Bodies that are a joint parent but never a child are fixed (base/ground).
    4. Fallback: fix the first body.
    """
    if not joints_data:
        return set(part_names)

    parents: Set[str] = set()
    children: Set[str] = set()
    for j in joints_data:
        cp = j.get("connected_parts", {})
        parents.add(cp.get("parent", ""))
        children.add(cp.get("child", ""))

    connected = parents | children

    # Bodies not connected to any joint → fixed
    fixed = {name for name in part_names if name not in connected}

    # Bodies that are parents but never children → fixed (base/ground)
    fixed |= parents - children

    if not fixed:
        fixed = {part_names[0]} if part_names else set()

    return fixed


# ---------------------------------------------------------------------------
# OBJ mesh loading helper
# ---------------------------------------------------------------------------

def _try_load_obj_mesh(obj_dir: str, part_name: str) -> Optional[Any]:
    """
    Try to find and load an OBJ mesh for the given part.
    Looks for <part_name>.obj in obj_dir.
    Returns a ChVisualShapeTriangleMesh or None.
    """
    obj_path = os.path.join(obj_dir, f"{part_name}.obj")
    if not os.path.isfile(obj_path):
        return None

    try:
        mesh = chrono.ChTriangleMeshConnected()
        mesh.LoadWavefrontMesh(obj_path, True, True)
        # Scale from cm to m (OBJ is exported in cm like everything else)
        tr = chrono.ChVector3d(0, 0, 0)
        mesh.Transform(tr, chrono.ChMatrix33d(0.01))

        vis_shape = chrono.ChVisualShapeTriangleMesh()
        vis_shape.SetMesh(mesh)
        vis_shape.SetVisible(True)
        return vis_shape
    except Exception as e:
        print(f"[scene_loader] Warning: failed to load OBJ '{obj_path}': {e}")
        return None


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_chrono_system(
    metadata: Dict[str, Any],
    obj_dir: str,
) -> BuildResult:
    """
    Build a PyChrono system from metadata.json content.

    Parameters
    ----------
    metadata : parsed metadata.json dict
    obj_dir  : directory containing .obj files (same dir as metadata.json)

    Returns
    -------
    BuildResult with system, bodies dict, joints dict, body_order
    """
    transforms: Dict[str, List[float]] = metadata.get("transforms", {})
    joints_data: List[Dict[str, Any]] = metadata.get("joints", [])

    part_names = list(transforms.keys())
    fixed_set = _find_fixed_bodies(part_names, joints_data)

    # --- 1. Create system ---
    system = chrono.ChSystemNSC()
    system.SetGravitationalAcceleration(chrono.ChVector3d(0, 0, -9.81))

    # --- 2. Create bodies ---
    bodies: Dict[str, Any] = {}

    for name in part_names:
        flat16 = transforms[name]
        R, t = _decompose_matrix(flat16)
        q = _rotation_to_chrono_quat(R)

        body = chrono.ChBodyAuxRef()
        body.SetName(name)
        body.SetPos(chrono.ChVector3d(float(t[0]), float(t[1]), float(t[2])))
        body.SetRot(q)

        if name in fixed_set:
            body.SetFixed(True)
        else:
            body.SetMass(1.0)
            inertia = chrono.ChVector3d(0.01, 0.01, 0.01)
            body.SetInertiaXX(inertia)

        # Try to attach OBJ visual mesh
        vis = _try_load_obj_mesh(obj_dir, name)
        if vis is not None:
            body.AddVisualShape(vis)

        system.AddBody(body)
        bodies[name] = body

    # --- 3. Create joints ---
    built_joints: Dict[str, Any] = {}

    for jdef in joints_data:
        jname = jdef.get("name", "unnamed_joint")
        jtype = jdef.get("type", "").lower()
        cp = jdef.get("connected_parts", {})
        parent_name = cp.get("parent", "")
        child_name = cp.get("child", "")

        if parent_name not in bodies or child_name not in bodies:
            print(f"[scene_loader] Warning: joint '{jname}' references unknown body "
                  f"(parent='{parent_name}', child='{child_name}'). Skipping.")
            continue

        parent_body = bodies[parent_name]
        child_body = bodies[child_name]

        if jtype == "revolute":
            # Origin: cm → m
            origin_cm = np.array(jdef.get("origin", [0, 0, 0]), dtype=float)
            origin_m = origin_cm * 0.01
            axis = jdef.get("axis", [0, 0, 1])

            joint_frame = _axis_to_chrono_frame(axis, origin_m)

            link = chrono.ChLinkLockRevolute()
            link.SetName(jname)
            link.Initialize(parent_body, child_body, joint_frame)

            # Apply limits if specified
            limits = jdef.get("limits", {})
            limit_min = limits.get("min")
            limit_max = limits.get("max")
            if limit_min is not None or limit_max is not None:
                limit_rz = link.GetLimit_Rz()
                limit_rz.SetActive(True)
                if limit_min is not None:
                    limit_rz.SetMin(math.radians(float(limit_min)))
                if limit_max is not None:
                    limit_rz.SetMax(math.radians(float(limit_max)))

            system.AddLink(link)
            built_joints[jname] = link
        else:
            print(f"[scene_loader] Warning: unsupported joint type '{jtype}' "
                  f"for joint '{jname}'. Skipping.")

    return BuildResult(
        system=system,
        bodies=bodies,
        joints=built_joints,
        body_order=part_names,
    )
