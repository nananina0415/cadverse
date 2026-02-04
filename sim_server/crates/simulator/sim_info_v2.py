# simulator/sim_info_v2.py
# metadata.json (Fusion 360 plugin export) 을 직접 읽는 SimInfo 래퍼.
# 기존 SceneMeta 기반 SimInfo를 대체한다.

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SimInfoV2:
    metadata_path: str
    metadata: Dict[str, Any]
    obj_dir: str
    dt: float = 1e-3

    @classmethod
    def from_json_file(
        cls,
        path: str,
        *,
        dt: Optional[float] = None,
        **kwargs: Any,
    ) -> "SimInfoV2":
        with open(path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        obj_dir = os.path.dirname(os.path.abspath(path))

        return cls(
            metadata_path=str(path),
            metadata=metadata,
            obj_dir=obj_dir,
            dt=float(dt) if dt is not None else 1e-3,
        )
