# simulator/SimInfo.py
# -----------------------------------------------------------------------------
# SimInfo = "metadata_types.SceneMeta + runtime options" wrapper
#
# 목표:
# - 스키마(01~07) 계약은 metadata_types.py가 단독으로 가진다.
# - SimInfo는 메타(SceneMeta)를 들고, dt 등 운영 옵션만 추가한다.
# - builder(sim_builder.py)는 SceneMeta를 받으므로 info.scene을 넘긴다.
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

# ✅ 스키마/타입 정의는 여기서 절대 재정의하지 않는다.
from .metadata_types import SceneMeta, validate_scene


# -----------------------------------------------------------------------------
# Runtime options (운영 옵션)
# -----------------------------------------------------------------------------

@dataclass
class SimOptions:
    """
    엔진 빌드/런타임 정책(메타데이터가 아닌 '운영 옵션')
    - dt: integration timestep [s]
    - allow_obj_auto_approx: collision이 비었을 때 OBJ로 근사 허용(디버그용)
    - strict_no_inference: 메타에 없는 정보는 추론하지 않음(프로덕션 원칙)
    """
    dt: float = 1e-3
    allow_obj_auto_approx: bool = False
    strict_no_inference: bool = True


# -----------------------------------------------------------------------------
# SimInfo (외부 계약용 래퍼)
# -----------------------------------------------------------------------------

@dataclass
class SimInfo:
    """
    서버/AR이 사용하는 "상위 인터페이스용 데이터" 컨테이너.

    - scene: metadata_types.SceneMeta (스키마 계약)
    - options: dt 등 운영 옵션
    - body_order: PartIndex 순서를 고정하고 싶을 때 선택적으로 사용
    """
    scene: SceneMeta
    options: SimOptions = field(default_factory=SimOptions)

    # 출력 순서(PartIndex 고정). None이면 scene.bodies 순서를 그대로 사용.
    body_order: Optional[List[str]] = None

    # derived mapping
    part_name_to_index: Dict[str, int] = field(init=False, default_factory=dict)
    part_index_to_name: List[str] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        # 메타 참조 무결성 검증(바로 fail)
        validate_scene(self.scene)
        self._rebuild_part_index()

    # -----------------------------------------------------------------
    # Convenience properties
    # -----------------------------------------------------------------
    @property
    def dt(self) -> float:
        return float(self.options.dt)

    # -----------------------------------------------------------------
    # Constructors
    # -----------------------------------------------------------------
    @staticmethod
    def _apply_dt_override(options: Optional[SimOptions], dt: Optional[float]) -> SimOptions:
        # 외부에서 전달된 options를 mutate하지 않도록 복사해서 사용
        opt = replace(options) if options is not None else SimOptions()
        if dt is not None:
            opt.dt = float(dt)
        return opt

    @classmethod
    def from_dict(
        cls,
        meta: Dict[str, Any],
        *,
        options: Optional[SimOptions] = None,
        dt: Optional[float] = None,
        body_order: Optional[List[str]] = None,
    ) -> "SimInfo":
        opt = cls._apply_dt_override(options, dt)
        scene = SceneMeta.from_dict(meta)
        info = cls(scene=scene, options=opt, body_order=body_order)
        # __post_init__에서 validate_scene + index rebuild 수행됨
        return info

    @classmethod
    def from_json_string(
        cls,
        s: str,
        *,
        options: Optional[SimOptions] = None,
        dt: Optional[float] = None,
        body_order: Optional[List[str]] = None,
    ) -> "SimInfo":
        meta = json.loads(s)
        return cls.from_dict(meta, options=options, dt=dt, body_order=body_order)

    @classmethod
    def from_json_file(
        cls,
        path: str,
        *,
        options: Optional[SimOptions] = None,
        dt: Optional[float] = None,
        body_order: Optional[List[str]] = None,
        encoding: str = "utf-8",
    ) -> "SimInfo":
        with open(path, "r", encoding=encoding) as f:
            meta = json.load(f)
        return cls.from_dict(meta, options=options, dt=dt, body_order=body_order)

    # -----------------------------------------------------------------
    # Derived mappings (PartIndex order)
    # -----------------------------------------------------------------
    def _rebuild_part_index(self) -> None:
        existing_list = [b.name for b in self.scene.bodies]
        existing_set = set(existing_list)

        if self.body_order:
            order = list(self.body_order)

            # 유효성: body_order가 있으면
            # - 모든 name이 실제 bodies에 존재해야 하고
            # - 중복이 없어야 하며
            # - 기본적으로 전체 body를 1번씩 포함하는 것을 권장(PartIndex 안정성)
            dup = set()
            seen = set()
            for n in order:
                if n in seen:
                    dup.add(n)
                seen.add(n)
                if n not in existing_set:
                    raise ValueError(f"body_order contains unknown body name: {n}")
            if dup:
                raise ValueError(f"body_order contains duplicate body name(s): {sorted(dup)}")

            if len(order) != len(existing_list):
                raise ValueError(
                    f"body_order must include all bodies exactly once. "
                    f"(got {len(order)} items, expected {len(existing_list)})"
                )
            if set(order) != existing_set:
                missing = sorted(existing_set - set(order))
                extra = sorted(set(order) - existing_set)
                raise ValueError(f"body_order mismatch. missing={missing}, extra={extra}")

        else:
            # 기본: 메타데이터 bodies 순서가 PartIndex 기준
            order = existing_list

        self.part_index_to_name = order
        self.part_name_to_index = {name: i for i, name in enumerate(order)}
