# simulator/SimInfo.py
# -----------------------------------------------------------------------------
# SimInfo = "metadata_types.SceneMeta + runtime options" wrapper
#
# 목표:
# - 스키마(01~07) 계약은 metadata_types.py가 단독으로 가진다.
# - SimInfo는 메타(SceneMeta)를 들고, dt 등 운영 옵션만 추가한다.
# - builder(sim_builder.py)는 SceneMeta를 받으므로 info.scene을 넘긴다.
# -----------------------------------------------------------------------------
#
# [UPDATED]
# - schema-06/07의 PartIndex 안정성을 위해 partNames(=part_index_to_name) 제공을 더 명확히 함
# - body_order가 None이면 scene.bodies 순서 사용(기존 유지)
# - (선택) 출력 메시지에 partNames를 항상 포함할지 정책 플래그 추가 (기본 False: 기존 호환)
#   -> main.py에서 SimState(partNames=...)를 넣고 싶으면 이 플래그를 True로 두면 됨
#
# [UPDATED: 1-1 PhysicsPreset]
# - SimOptions에 physics preset(접촉/솔버/스텝) 옵션을 추가하고, builder/system에 적용되게 수정
#
# [UPDATED: 1-3 Contact Telemetry controls]
# - SimOptions에 enable_contact_telemetry / max_contact_points_report 추가
#
# [UPDATED: 2-1.3 Auto inertia guardrails]
# - SimOptions에 auto inertia 운영 스위치/가드레일/디버그 플래그 추가
#
# [UPDATED: 2-3.4 Ops guardrails/logging]
# - SimOptions에 debug_joint_limits / debug_warnings 추가
#   -> main.py에서 "joint limit 적용 실패/미지원" 경고를 사용자 친화적으로 요약 출력할 때 사용
# - (선택) joint_limits_soft_enable: 소프트 리미트(spring/damper) 적용을 운영 레벨에서 기본 OFF로 유지
#   (구 문서/코드에서 enable_soft_joint_limits라는 이름을 썼다면 alias로 지원)
#
# [UPDATED: Event Feedback]
# - SimOptions에 이벤트 기반 피드백 옵션 추가
#   -> main.py에서 telemetry/diagnostics를 사용자용 eventFeedback으로 변환할 때 사용
# - 실제 오디오 재생은 Python 엔진이 하지 않고,
#   soundId / soundType / volume / pitch를 SimState로 내보내 클라이언트가 처리한다.

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Union

# ✅ 스키마/타입 정의는 여기서 절대 재정의하지 않는다.
from .metadata_types import SceneMeta, validate_scene


# -----------------------------------------------------------------------------
# PhysicsPreset (운영 프리셋 컨테이너)
# -----------------------------------------------------------------------------

@dataclass
class PhysicsPreset:
    """
    1단계(안정성)용 '운영 프리셋' 컨테이너.

    ⚠️ 중요:
    - sim_builder는 SimOptions.physics_preset을
      (1) 문자열("FAST"/"DEFAULT"/"ROBUST"/"SMC_DEFAULT")
      (2) dict(오버라이드)
      로 받아 처리한다.
    - 따라서 PhysicsPreset 객체를 직접 넘길 거라면,
      SimOptions.physics_preset에는 넣지 말고(권장 X),
      SimOptions의 개별 override 필드들을 직접 채우는 쪽이 안전하다.

    그래도 문서화/구조화를 위해, 아래처럼 "한 곳에 모아두는 용도"로는 유용.
    """
    name: str = "DEFAULT"
    contact_method: Optional[str] = None  # "NSC"/"SMC"
    solver: Optional[str] = None          # e.g., "PSOR", "PSSOR"
    solver_max_iters: Optional[int] = None
    solver_tolerance: Optional[float] = None

    collision_envelope: Optional[float] = None
    collision_margin: Optional[float] = None
    min_bounce_speed: Optional[float] = None
    max_penetration_recovery_speed: Optional[float] = None

    # (선택) 미래 확장(바인딩 있으면 적용 가능)
    warm_start: Optional[bool] = None
    enable_system_logging: Optional[bool] = None

    def to_overrides_dict(self) -> Dict[str, Any]:
        """sim_builder가 읽을 수 있는 dict 오버라이드로 변환."""
        out: Dict[str, Any] = {}
        if self.contact_method is not None:
            out["contact_method"] = self.contact_method
        if self.solver is not None:
            out["solver"] = self.solver
        if self.solver_max_iters is not None:
            out["max_iters"] = int(self.solver_max_iters)
        if self.solver_tolerance is not None:
            out["tol"] = float(self.solver_tolerance)
        if self.collision_envelope is not None:
            out["collision_envelope"] = float(self.collision_envelope)
        if self.collision_margin is not None:
            out["collision_margin"] = float(self.collision_margin)
        if self.min_bounce_speed is not None:
            out["min_bounce_speed"] = float(self.min_bounce_speed)
        if self.max_penetration_recovery_speed is not None:
            out["max_penetration_recovery_speed"] = float(self.max_penetration_recovery_speed)
        return out


# -----------------------------------------------------------------------------
# Runtime options (운영 옵션)
# -----------------------------------------------------------------------------

@dataclass
class SimOptions:
    """
    엔진 빌드/런타임 정책(메타데이터가 아닌 '운영 옵션')
    """
    dt: float = 1e-3
    allow_obj_auto_approx: bool = False
    strict_no_inference: bool = True
    emit_part_names: bool = False

    # --- telemetry control (1-3) ---
    enable_contact_telemetry: bool = False
    max_contact_points_report: int = 256

    # --- event feedback control ---
    # telemetry / diagnostics를 사용자용 메시지·알림음 이벤트로 변환할지 여부
    enable_event_feedback: bool = True

    # 한 step에서 eventFeedback이 너무 많이 쌓이지 않도록 제한
    event_feedback_max_items: int = 16

    # 같은 이벤트가 매 step 반복 출력되지 않도록 하는 최소 간격(sec)
    # 실제 cooldown 적용은 main.py에서 수행
    event_feedback_cooldown_sec: float = 0.5

    # True면 EventFeedback에 soundId / soundType / volume / pitch를 포함
    # False면 메시지 이벤트만 내보내는 식으로 main.py에서 처리 가능
    event_feedback_enable_sound: bool = True

    # --- preset selector / overrides ---
    physics_preset: Optional[Union[str, Dict[str, Any], PhysicsPreset]] = "DEFAULT"

    # --- explicit overrides (highest priority in sim_builder) ---
    contact_method: Optional[str] = None  # "NSC"/"SMC" (overrides preset)
    solver: Optional[str] = None          # "PSOR"/"PSSOR"/...
    solver_max_iters: Optional[int] = None
    solver_tolerance: Optional[float] = None

    collision_envelope: Optional[float] = None
    collision_margin: Optional[float] = None

    min_bounce_speed: Optional[float] = None
    max_penetration_recovery_speed: Optional[float] = None

    # --- auto inertia guardrails (2-1.3) ---
    auto_inertia_enabled: bool = True
    auto_inertia_min_inertia: float = 0.0
    auto_inertia_scale: float = 1.0
    auto_inertia_use_rotation: bool = False
    auto_inertia_fallback_diagonal: float = 1e-3
    debug_auto_inertia: bool = False

    # --- joint limits ops guardrails (2-3.4) ---
    # ✅ main.py에서 limits 관련 경고/적용상태를 "요약/상세"로 출력할지 토글
    debug_joint_limits: bool = False

    # ✅ 공통 경고 출력 토글(기본 True = 기존 print 경고 유지)
    debug_warnings: bool = True

    # ✅ (선택) 소프트 리미트(spring/damper) 운영 레벨에서 기본 OFF 유지용 (canonical)
    # - True여도 metadata에 spring_k/damper_c가 None이면 당연히 미적용
    # - False면 spring/damper 관련 값이 있어도 "운영 정책상" 적용을 스킵하도록
    #   sim_builder에서 getattr(options, "joint_limits_soft_enable", False)로 확인해 사용할 수 있다.
    joint_limits_soft_enable: bool = False

    # ✅ (선택) 과거/문서 호환 alias (enable_soft_joint_limits)
    # - 어떤 코드/문서에서 enable_soft_joint_limits를 쓴 경우를 대비
    enable_soft_joint_limits: Optional[bool] = None

    def __post_init__(self) -> None:
        # basic sanity for dt + telemetry knobs
        if float(self.dt) <= 0.0:
            raise ValueError(f"SimOptions.dt must be > 0, got: {self.dt}")

        if int(self.max_contact_points_report) <= 0:
            raise ValueError(
                f"SimOptions.max_contact_points_report must be > 0, got: {self.max_contact_points_report}"
            )

        # event feedback knobs sanity
        if int(self.event_feedback_max_items) <= 0:
            raise ValueError(
                f"SimOptions.event_feedback_max_items must be > 0, got: {self.event_feedback_max_items}"
            )

        if float(self.event_feedback_cooldown_sec) < 0.0:
            raise ValueError(
                f"SimOptions.event_feedback_cooldown_sec must be >= 0, got: {self.event_feedback_cooldown_sec}"
            )

        # auto inertia knobs sanity
        if float(self.auto_inertia_min_inertia) < 0.0:
            raise ValueError(f"SimOptions.auto_inertia_min_inertia must be >= 0, got: {self.auto_inertia_min_inertia}")
        if float(self.auto_inertia_scale) <= 0.0:
            raise ValueError(f"SimOptions.auto_inertia_scale must be > 0, got: {self.auto_inertia_scale}")
        if float(self.auto_inertia_fallback_diagonal) < 0.0:
            raise ValueError(
                f"SimOptions.auto_inertia_fallback_diagonal must be >= 0, got: {self.auto_inertia_fallback_diagonal}"
            )

        # 2-3.4 toggles sanity (bool coercion-like; no strict required)
        self.debug_joint_limits = bool(self.debug_joint_limits)
        self.debug_warnings = bool(self.debug_warnings)

        # event feedback toggles sanity
        self.enable_event_feedback = bool(self.enable_event_feedback)
        self.event_feedback_enable_sound = bool(self.event_feedback_enable_sound)

        # alias -> canonical (if explicitly provided)
        if self.enable_soft_joint_limits is not None:
            self.joint_limits_soft_enable = bool(self.enable_soft_joint_limits)

        self.joint_limits_soft_enable = bool(self.joint_limits_soft_enable)

    def as_builder_options(self) -> "SimOptions":
        """
        sim_builder가 기대하는 형태로 '정규화'한 options를 돌려준다.

        ✅ 핵심 수정:
        - physics_preset이 PhysicsPreset 객체일 때,
          (A) preset 이름은 str로 유지해서 sim_builder preset table이 그대로 적용되게 하고
          (B) preset의 세부 값들은 SimOptions의 개별 override 필드로 "펼쳐서" 반영한다.
        """
        opt = replace(self)

        if isinstance(opt.physics_preset, PhysicsPreset):
            pp = opt.physics_preset

            # (A) base preset key는 문자열로 유지
            opt.physics_preset = str(pp.name or "DEFAULT").strip().upper()

            # (B) preset 값을 개별 override로 펼침(이미 사용자가 override를 줬으면 유지)
            if opt.contact_method is None and pp.contact_method is not None:
                opt.contact_method = pp.contact_method
            if opt.solver is None and pp.solver is not None:
                opt.solver = pp.solver
            if opt.solver_max_iters is None and pp.solver_max_iters is not None:
                opt.solver_max_iters = int(pp.solver_max_iters)
            if opt.solver_tolerance is None and pp.solver_tolerance is not None:
                opt.solver_tolerance = float(pp.solver_tolerance)

            if opt.collision_envelope is None and pp.collision_envelope is not None:
                opt.collision_envelope = float(pp.collision_envelope)
            if opt.collision_margin is None and pp.collision_margin is not None:
                opt.collision_margin = float(pp.collision_margin)

            if opt.min_bounce_speed is None and pp.min_bounce_speed is not None:
                opt.min_bounce_speed = float(pp.min_bounce_speed)
            if opt.max_penetration_recovery_speed is None and pp.max_penetration_recovery_speed is not None:
                opt.max_penetration_recovery_speed = float(pp.max_penetration_recovery_speed)

        # alias normalize again (in case replace() copied None/values)
        if opt.enable_soft_joint_limits is not None:
            opt.joint_limits_soft_enable = bool(opt.enable_soft_joint_limits)
        opt.joint_limits_soft_enable = bool(opt.joint_limits_soft_enable)

        return opt


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
        # dt sanity
        if float(self.options.dt) <= 0.0:
            raise ValueError(f"SimOptions.dt must be > 0, got: {self.options.dt}")

        # 메타 참조 무결성 검증(바로 fail)
        validate_scene(self.scene)
        self._rebuild_part_index()

        # options normalization (PhysicsPreset object -> (preset name + overrides))
        try:
            self.options = self.options.as_builder_options()
        except Exception:
            # normalization 실패해도 시뮬 자체는 돌 수 있게(단, preset 객체 직접 사용은 비권장)
            pass

    # -----------------------------------------------------------------
    # Convenience properties
    # -----------------------------------------------------------------
    @property
    def dt(self) -> float:
        return float(self.options.dt)

    @property
    def part_names(self) -> List[str]:
        """schema-07 optional의 partNames로 그대로 내보내기 좋은 "고정 순서 이름 배열"."""
        return list(self.part_index_to_name)

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
        return cls(scene=scene, options=opt, body_order=body_order)

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

        if self.body_order is not None:
            order = list(self.body_order)

            if len(order) == 0:
                raise ValueError(
                    "body_order is provided but empty. "
                    "Use body_order=None to follow scene.bodies order."
                )

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
            order = existing_list

        self.part_index_to_name = order
        self.part_name_to_index = {name: i for i, name in enumerate(order)}

    # -----------------------------------------------------------------
    # Optional helpers
    # -----------------------------------------------------------------
    def resolve_part_name(self, part_index: int) -> Optional[str]:
        """partIndex -> name (범위 밖이면 None)"""
        i = int(part_index)
        if 0 <= i < len(self.part_index_to_name):
            return self.part_index_to_name[i]
        return None

    def resolve_part_index(self, part_name: str) -> Optional[int]:
        """name -> partIndex (없으면 None)"""
        return self.part_name_to_index.get(str(part_name))