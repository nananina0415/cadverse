# extract.py

import adsk.core
import importlib
import os
import json
import traceback

from . import extract_mesh
from . import extract_meta


def _safe_scene_name(output_path: str) -> str:
    """
    output_path 마지막 폴더명을 sceneName으로 사용.
    실패하면 cad_export_scene 사용.
    """
    try:
        name = os.path.basename(os.path.normpath(output_path))
        if name:
            return str(name).replace(" ", "_").replace(":", "_")
    except Exception:
        pass

    return "cad_export_scene"


def _collect_warnings(mesh_data, meta_data):
    warnings = []

    try:
        if isinstance(mesh_data, dict):
            for body_name, entry in mesh_data.items():
                for w in entry.get("warnings", []) or []:
                    warnings.append(f"[mesh:{body_name}] {w}")
    except Exception:
        warnings.append("[extract] Failed to collect mesh warnings.")
        warnings.append(traceback.format_exc())

    try:
        if isinstance(meta_data, dict):
            for w in meta_data.get("warnings", []) or []:
                warnings.append(f"[meta] {w}")
    except Exception:
        warnings.append("[extract] Failed to collect metadata warnings.")
        warnings.append(traceback.format_exc())

    return warnings


def _build_metadata(scene_name: str, meta_data: dict, warnings: list):
    """
    simulator/metadata_types.py의 SceneMeta가 읽을 수 있는 최종 JSON 구조 생성.
    """
    bodies = meta_data.get("bodies", []) if isinstance(meta_data, dict) else []
    joints = meta_data.get("joints", []) if isinstance(meta_data, dict) else []
    gear_pairs = meta_data.get("gearPairs", []) if isinstance(meta_data, dict) else []
    actuators = meta_data.get("actuators", []) if isinstance(meta_data, dict) else []
    transforms = meta_data.get("transforms", {}) if isinstance(meta_data, dict) else {}

    metadata = {
        "sceneName": scene_name,

        # 기구학 교육용/AR interaction 테스트에서는 중력 간섭을 피하기 위해 기본 0으로 둔다.
        # 실제 중력 테스트가 필요하면 [0.0, -9.81, 0.0]로 바꾸면 됨.
        "gravity": [0.0, 0.0, 0.0],

        # Legacy ARScene / 현재 server loader 호환용 transform dict.
        # 값 생성은 extract_meta.run()이 담당하고, 여기서는 최종 metadata.json에 포함만 한다.
        "transforms": transforms,

        "bodies": bodies,
        "joints": joints,
        "gearPairs": gear_pairs,
        "actuators": actuators,

        # 조인트로 직접 연결된 body끼리 collision을 끄는 정책.
        # 폐루프 기구에서 불필요한 충돌 간섭을 줄이기 위해 기본 true 권장.
        "collisionFilter": {
            "ignoreJoints": True,
            "ignoreGearPairs": True,
            "ignorePairs": []
        }
    }

    # 엔진이 모르는 top-level 필드는 SceneMeta.from_dict에서 무시되지만,
    # 디버깅용으로 남겨두면 CAD export 문제 찾기에 도움이 됨.
    if warnings:
        metadata["exportWarnings"] = warnings

    return metadata


def run(context, output_path: str):
    """
    CADverse simulator metadata exporter.

    실행 순서:
    1. meshes/ 폴더에 OBJ export
    2. mesh_data 기반으로 bodies 생성
    3. Fusion joints 기반으로 simulator joints 생성
    4. simulator가 바로 읽을 수 있는 metadata.json 저장

    반환:
    - 최종 metadata dict
    """
    importlib.reload(extract_mesh)
    importlib.reload(extract_meta)

    os.makedirs(output_path, exist_ok=True)

    metadata_path = os.path.join(output_path, "metadata.json")

    try:
        # 1) OBJ mesh export + transform 정보 수집
        mesh_data = extract_mesh.run(context, output_path)

        # 2) bodies / joints / gearPairs / actuators 생성
        meta_data = extract_meta.run(context, mesh_data)

        # 3) warnings 취합
        warnings = _collect_warnings(mesh_data, meta_data)

        # 4) 최종 simulator metadata 구성
        scene_name = _safe_scene_name(output_path)
        metadata = _build_metadata(scene_name, meta_data, warnings)

        # 5) metadata.json 저장
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata

    except Exception:
        # 실패해도 원인 확인용 metadata_export_error.json 저장
        error_data = {
            "ok": False,
            "error": traceback.format_exc()
        }

        error_path = os.path.join(output_path, "metadata_export_error.json")

        try:
            with open(error_path, "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        raise