# simulator/main.py
#
# "시뮬레이션 엔진의 외부 인터페이스" 역할
# - 서버/AR 쪽에서 Simulator를 가져다 쓰는 진입점
# - 내부 Chrono 구성은 sim_builder.py로 위임
#
# [UPDATED: Hybrid Interaction]
# - ROTATE: 명확한 revolute 축 → "증분 드래그" 토크 + 토크 기반 감쇠
# - SPRING: 그 외 → 가상 스프링-댐퍼 힘
#
# ✅ 핵심 변경 요약 (이번 안정화/감쇠 이슈 해결)
# - ROTATE 드래그 입력을 "start vs current" 방식에서 "prev vs current(증분)" 방식으로 변경
#   -> 같은 위치를 반복 수신해도 토크가 누적되지 않아 과가속/발산 방지
# - ROTATE 감쇠 토크를 명확히 정의: tau = -Cw * ω_along * axis (그리고 tau_max로 클램프)
# - 속도/각속도(SetVel/SetAngVel) overwrite 제거 유지 (물리 엔진 적분을 존중)
# - TouchStart 중에는 기존 drive actuator(속도/토크 모터)를 중립화(neutralize)하여 AR 제어 우선
# - Simulator.close() 제공: sys.Clear()로 세션 종료/재시작 시 리소스 정리
#
# ✅ 추가 보강 1 (바인딩 호환/디버그)
# - _get_angvel_world(): GetAngVel이 world/local 중 무엇인지 바인딩별로 달라서,
#   가능한 getter 조합을 통해 "world angvel"을 최대한 일관되게 획득
# - _infer_revolute_axis_world_for_body(): 가능하면 실제 링크(ChLink...) 프레임에서
#   world revolute 축을 추출하고, 실패 시 메타데이터/바디 회전으로 fallback
#
# ✅ 추가 보강 2 (폭주/펌핑 원인 제거)
# - 일부 PyChrono 바인딩에서 AccumulateForce/Torque가 step마다 자동 초기화되지 않을 수 있음
#   -> Simulator.step()에서 DoStepDynamics 전에 EmptyAccumulators(우선)로 누적값을 clear
#
# ✅ 추가 보강 3 (이번 “덜컹/부호반전” 해결 핵심)
# - anti-flip clamp가 제대로 동작하려면 Ieff(축 등가 관성)가 필요함
# - PyChrono 바인딩에 따라 GetInertiaXX 등이 없을 수 있으므로,
#   Simulator.__init__에서 Scene metadata의 explicit inertia(Ixx,Iyy,Izz)를 body에 캐시(_inertia_diag_local)로 부착
#   -> 작은 관성에서 damping 토크가 “한 스텝에 속도를 뒤집지 않도록” 정확히 제한 가능
#
# ✅ (1-3) Contact telemetry
# - enable_contact_telemetry=False면 telemetry 계산 스킵
# - True면 max_contact_points_report 만큼만 contact reporter를 순회해서:
#   - contact_count (cap 적용된 "보고한 contact 수")
#   - max_contact_force (N)
#   - max_pair(optional; bodyA/bodyB)
#   를 계산해서 SimState.telemetry에 포함
#
# ✅ (2) Engine internal handles exposure (for tests/debug)
# - self.build_result, self.name_to_body, self.name_to_link 노출
#
# ✅ (2-3.3) Joint limit headless 검증 케이스 추가
# - 별도 파일 추가 없이 main.py의 __main__에서 실행 가능
# - python -m simulator.main --joint-limit-test
#
# ✅ (3-1.4) Gear efficiency/backlash 근사 보정
# - sim_builder.py에서 전달된 gear 설정(또는 scene metadata fallback)을 읽어서
#   per-step에서 효율 손실 / backlash deadband를 "근사 토크"로 반영
# - 폭주 방지를 위해 phase/speed 기반 PD + max_torque clamp + loss torque 분산 적용
# - SimState.gearTelemetry 에 gear별 applied_efficiency / loss_torque / backlash_deadband 기록
#
# ✅ Event Feedback
# - telemetry / diagnostics를 사용자용 eventFeedback으로 변환하는 _build_event_feedback() 추가
# - 실제 소리 재생은 Python 엔진이 하지 않고, soundId / soundType / volume / pitch만 출력한다.
# - STEP 3에서는 함수만 추가하고, SimState 연결은 STEP 4에서 수행한다.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

import math as m
import time
import sys
import pychrono as chrono

from .SimInfo import SimInfo

from . import runtime_types as rt
from .runtime_types import (
    UserInput,
    SimState,
    PartState,
    InteractionTelemetry,
    TouchStartEvent,
    TouchingEvent,
    TouchEndEvent,
    resolve_target_part_name,
)

from .sim_builder import build_system_from_scene


def _summarize_build_warnings(warnings: List[str]) -> Dict[str, Any]:
    """
    sim_builder(BuildResult.warnings)에서 모인 warning 문자열들을
    사용자 친화적으로 요약하기 위한 분류/카운팅.

    반환:
      {
        "total": int,
        "by_tag": {tag: count},
        "samples": {tag: [sample...]}  # 각 tag별 최대 2개 샘플
      }
    """
    def _tag(w: str) -> str:
        s = str(w or "").lower()

        # joint limit 관련
        if "joint" in s and "limit" in s:
            if "noapi_soft" in s or "soft" in s or "spring" in s or "damper" in s:
                return "joint_limits_soft_unsupported"
            if "noapi_stop" in s or "stop_" in s or "restitution" in s or "damping" in s:
                return "joint_limits_stop_unsupported"
            if "noapi_bounds" in s or "bounds" in s or "lower" in s or "upper" in s:
                return "joint_limits_bounds_unsupported"
            return "joint_limits_other"

        # collision filter 관련
        if "collisionfilter" in s or ("collision" in s and "filter" in s):
            return "collision_filter"

        # material/friction 관련
        if "friction" in s or "material" in s or "stribeck" in s or "slip" in s:
            return "contact_material"

        # 일반
        return "other"

    out_total = 0
    by_tag: Dict[str, int] = {}
    samples: Dict[str, List[str]] = {}

    for w in (warnings or []):
        t = _tag(w)
        out_total += 1
        by_tag[t] = by_tag.get(t, 0) + 1
        if t not in samples:
            samples[t] = []
        if len(samples[t]) < 2:
            samples[t].append(str(w))

    return {"total": out_total, "by_tag": by_tag, "samples": samples}


def _print_build_warnings_user_friendly(
    *,
    warnings: List[str],
    debug_print_all: bool,
    debug_print_limits: bool,
    soft_limits_enabled: Optional[bool] = None,
) -> None:
    """
    2-3.4의 '운영 가드레일/로그' 최종 형태:
    - 기본: 요약만 (카테고리/개수 + 조치 가이드)
    - debug_joint_limits/debug_warnings가 켜지면 상세 출력
    - soft-limit 토글 상태도 같이 안내
    """
    if not warnings:
        return

    summ = _summarize_build_warnings(warnings)
    total = int(summ.get("total", 0))
    by_tag = dict(summ.get("by_tag", {}) or {})
    samples = dict(summ.get("samples", {}) or {})

    # --- header ---
    print(f"[WARN] build warnings: {total}")

    # --- soft toggle hint ---
    if soft_limits_enabled is not None:
        print(f"[WARN] joint soft-limits enabled = {bool(soft_limits_enabled)}")
        if not bool(soft_limits_enabled):
            # soft 관련 경고가 있으면 “꺼져있어서 적용 안 됨”을 더 친절하게 안내
            if by_tag.get("joint_limits_soft_unsupported", 0) > 0:
                print("[WARN] note: soft-limit 관련 경고가 보이지만, 현재 설정에서 soft-limit 적용은 꺼져있을 수 있어요.")

    # --- summary lines ---
    # 보기 좋게 우선순위 정렬
    order = [
        "joint_limits_bounds_unsupported",
        "joint_limits_stop_unsupported",
        "joint_limits_soft_unsupported",
        "joint_limits_other",
        "collision_filter",
        "contact_material",
        "other",
    ]
    for k in order:
        c = int(by_tag.get(k, 0) or 0)
        if c <= 0:
            continue
        print(f" - {k}: {c}")

    # --- next actions guidance ---
    if by_tag.get("joint_limits_bounds_unsupported", 0) > 0:
        print("[HINT] 이 바인딩에서 joint limits(bounds)가 적용 API를 못 찾았을 수 있어요. (limit이 실제로 안 걸릴 수 있음)")
    if by_tag.get("joint_limits_stop_unsupported", 0) > 0:
        print("[HINT] stop_* (hard stop 파라미터) 지원 API가 없어서 무시됐을 수 있어요.")
    if by_tag.get("joint_limits_soft_unsupported", 0) > 0:
        print("[HINT] spring/damper(soft limit) 지원 API가 없어서 무시됐을 수 있어요.")
    if by_tag.get("collision_filter", 0) > 0:
        print("[HINT] collisionFilter는 바인딩/바디 수 제한으로 적용이 스킵될 수 있어요.")
    if by_tag.get("contact_material", 0) > 0:
        print("[HINT] rolling/spinning/compliance 같은 고급 마찰 옵션은 바인딩에 따라 일부 무시될 수 있어요.")

    # --- details ---
    if debug_print_all or debug_print_limits:
        print("[WARN] build warnings (details):")
        for w in warnings:
            try:
                print(" -", str(w))
            except Exception:
                pass
    else:
        # 샘플 1~2개만 보여주고, 토글 안내
        shown_any = False
        for k in order:
            ss = samples.get(k, [])
            if ss:
                shown_any = True
                for s in ss:
                    print(" -", s)
        if shown_any:
            print("[WARN] (showing only a few samples)")
        print("[HINT] 상세를 보려면 options.debug_joint_limits=True 또는 options.debug_warnings=True")


# ============================================================
# Small math helpers (Chrono vector)
# ============================================================

def _dot(a: chrono.ChVector3d, b: chrono.ChVector3d) -> float:
    return float(a.x * b.x + a.y * b.y + a.z * b.z)


def _cross(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(
        float(a.y * b.z - a.z * b.y),
        float(a.z * b.x - a.x * b.z),
        float(a.x * b.y - a.y * b.x),
    )


def _norm(a: chrono.ChVector3d) -> float:
    return float(m.sqrt(_dot(a, a)))


def _normalize(a: chrono.ChVector3d, eps: float = 1e-12) -> chrono.ChVector3d:
    n = _norm(a)
    if n < eps:
        return chrono.ChVector3d(0.0, 0.0, 0.0)
    inv = 1.0 / n
    return chrono.ChVector3d(float(a.x * inv), float(a.y * inv), float(a.z * inv))


def _sub(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(float(a.x - b.x), float(a.y - b.y), float(a.z - b.z))


def _add(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    return chrono.ChVector3d(float(a.x + b.x), float(a.y + b.y), float(a.z + b.z))


def _mul(a: chrono.ChVector3d, s: float) -> chrono.ChVector3d:
    return chrono.ChVector3d(float(a.x * s), float(a.y * s), float(a.z * s))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _quat_rotate(q: chrono.ChQuaterniond, v0: chrono.ChVector3d) -> chrono.ChVector3d:
    # Chrono에 QRotate가 있으면 그걸 우선 사용
    try:
        if hasattr(chrono, "QRotate"):
            return chrono.QRotate(q, v0)
    except Exception:
        pass

    # fallback: 직접 구현 (wxyz)
    w, x, y, z = float(q.e0), float(q.e1), float(q.e2), float(q.e3)
    vx, vy, vz = float(v0.x), float(v0.y), float(v0.z)

    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)

    cx = (y * tz - z * ty)
    cy = (z * tx - x * tz)
    cz = (x * ty - y * tx)

    return chrono.ChVector3d(
        float(vx + w * tx + cx),
        float(vy + w * ty + cy),
        float(vz + w * tz + cz),
    )


def _quat_conjugate(q: chrono.ChQuaterniond) -> chrono.ChQuaterniond:
    # (w, x, y, z) -> (w, -x, -y, -z)
    return chrono.ChQuaterniond(float(q.e0), float(-q.e1), float(-q.e2), float(-q.e3))


def _vec_close(a: chrono.ChVector3d, b: chrono.ChVector3d, tol: float = 1e-6) -> bool:
    return (abs(float(a.x - b.x)) < tol) and (abs(float(a.y - b.y)) < tol) and (abs(float(a.z - b.z)) < tol)


def _get_angvel_world(body: chrono.ChBody) -> chrono.ChVector3d:
    """
    가능한 한 WORLD angvel을 반환.
    - GetWvel_par / GetAngVelWorld / GetWvel 우선
    - GetAngVel()은 바인딩마다 world/local이 달라서,
      GetAngVelLocal()이 있으면 비교해서 local 여부를 판정한 뒤 처리
    """
    for name in ("GetWvel_par", "GetAngVelWorld", "GetWvel"):
        try:
            if hasattr(body, name):
                w = getattr(body, name)()
                if isinstance(w, chrono.ChVector3d):
                    return w
        except Exception:
            pass

    try:
        if hasattr(body, "GetAngVel"):
            w = body.GetAngVel()
            if isinstance(w, chrono.ChVector3d):
                if hasattr(body, "GetAngVelLocal"):
                    try:
                        wloc = body.GetAngVelLocal()
                        if isinstance(wloc, chrono.ChVector3d):
                            if _vec_close(w, wloc, tol=1e-6):
                                q = body.GetRot()
                                return _quat_rotate(q, wloc)
                            return w
                    except Exception:
                        pass
                return w
    except Exception:
        pass

    for name in ("GetAngVelLocal", "GetWvel_loc"):
        try:
            if hasattr(body, name):
                wloc = getattr(body, name)()
                if isinstance(wloc, chrono.ChVector3d):
                    q = body.GetRot()
                    return _quat_rotate(q, wloc)
        except Exception:
            pass

    return chrono.ChVector3d(0.0, 0.0, 0.0)


def _get_linvel_world(body: chrono.ChBody) -> chrono.ChVector3d:
    for name in ("GetPos_dt", "GetPosDt", "GetVel", "GetPosDt_par"):
        try:
            if hasattr(body, name):
                v = getattr(body, name)()
                if isinstance(v, chrono.ChVector3d):
                    return v
        except Exception:
            pass
    return chrono.ChVector3d(0.0, 0.0, 0.0)

def _set_angvel_world_best_effort(body: chrono.ChBody, w_world: chrono.ChVector3d) -> bool:
    # 1) world 계열 setter 우선
    for fn in ("SetWvel_par", "SetAngVelWorld", "SetWvel"):
        try:
            if hasattr(body, fn):
                getattr(body, fn)(w_world)
                return True
        except Exception:
            pass

    # 2) ambiguous SetAngVel
    try:
        if hasattr(body, "SetAngVel"):
            body.SetAngVel(w_world)
            return True
    except Exception:
        pass

    # 3) local setter만 있으면 world -> local 변환
    try:
        if hasattr(body, "SetAngVelLocal") and hasattr(body, "GetRot"):
            qinv = _quat_conjugate(body.GetRot())
            w_local = _quat_rotate(qinv, w_world)
            body.SetAngVelLocal(w_local)
            return True
    except Exception:
        pass

    return False


def _set_linvel_world_best_effort(body: chrono.ChBody, v_world: chrono.ChVector3d) -> bool:
    for fn in ("SetPos_dt", "SetPosDt", "SetVel", "SetPosDt_par"):
        try:
            if hasattr(body, fn):
                getattr(body, fn)(v_world)
                return True
        except Exception:
            pass
    return False

def _apply_torque_world(body: chrono.ChBody, tau_world: chrono.ChVector3d) -> None:
    try:
        if hasattr(body, "AccumulateTorque"):
            try:
                body.AccumulateTorque(tau_world, False)  # world
            except Exception:
                body.AccumulateTorque(tau_world, True)
            return
    except Exception:
        pass


def _apply_force_at_point_world(body: chrono.ChBody, force_world: chrono.ChVector3d, point_world: chrono.ChVector3d) -> None:
    try:
        if hasattr(body, "AccumulateForce"):
            try:
                body.AccumulateForce(force_world, point_world, False)  # world
                return
            except Exception:
                body.AccumulateForce(force_world, point_world, True)
                return
    except Exception:
        pass

    try:
        if hasattr(body, "ApplyForce"):
            try:
                body.ApplyForce(force_world, point_world, False)
                return
            except Exception:
                body.ApplyForce(force_world, point_world, True)
                return
    except Exception:
        pass

    try:
        com = body.GetPos()
        r = _sub(point_world, com)
        tau = _cross(r, force_world)
        _apply_torque_world(body, tau)
    except Exception:
        pass


def _apply_force_world(body: chrono.ChBody, force_world: chrono.ChVector3d) -> None:
    try:
        _apply_force_at_point_world(body, force_world, body.GetPos())
    except Exception:
        pass


def _world_point_from_local(body: chrono.ChBody, p_local: chrono.ChVector3d) -> chrono.ChVector3d:
    for fn in ("TransformPointLocalToParent", "TransformPointLocalToWorld", "Point_Body2World"):
        try:
            if hasattr(body, fn):
                out = getattr(body, fn)(p_local)
                if isinstance(out, chrono.ChVector3d):
                    return out
        except Exception:
            pass

    try:
        q = body.GetRot()
        p_rot = _quat_rotate(q, p_local)
        return _add(body.GetPos(), p_rot)
    except Exception:
        return _add(body.GetPos(), p_local)


def _point_velocity_world(body: chrono.ChBody, p_world: chrono.ChVector3d) -> chrono.ChVector3d:
    v = _get_linvel_world(body)
    w = _get_angvel_world(body)
    com = body.GetPos()
    r = _sub(p_world, com)
    return _add(v, _cross(w, r))


def _is_fixed_body(body: chrono.ChBody) -> bool:
    try:
        if hasattr(body, "GetFixed"):
            return bool(body.GetFixed())
    except Exception:
        pass
    return False


def _clear_body_accumulators(body: chrono.ChBody) -> bool:
    if hasattr(body, "EmptyAccumulators"):
        try:
            body.EmptyAccumulators()
            return True
        except Exception:
            pass

    if hasattr(body, "RemoveAllForces"):
        try:
            body.RemoveAllForces()
            return True
        except Exception:
            pass

    return False


def _get_body_inertia_diag_local(body: chrono.ChBody) -> Optional[chrono.ChVector3d]:
    """
    body 좌표계(local)에서의 관성 대각(Ixx,Iyy,Izz) 추정.
    바인딩 차이를 흡수하기 위해 여러 후보 API를 시도한다.

    ✅ 보강:
    - 일부 바인딩은 inertia getter가 거의 없음
    - Simulator.__init__에서 scene metadata explicit inertia를 body에 _inertia_diag_local로 캐시해두면
      여기서 그 값을 우선 사용한다.
    """
    # ✅ (1) metadata cache (가장 신뢰도 높음: 우리가 넣어준 값)
    try:
        cached = getattr(body, "_inertia_diag_local", None)
        if isinstance(cached, chrono.ChVector3d):
            return cached
    except Exception:
        pass

    # (2) 흔한 API: GetInertiaXX() -> ChVector3d(Ixx,Iyy,Izz)
    for fn in ("GetInertiaXX", "GetInertiaDiag", "GetInertiaDiagonal"):
        try:
            if hasattr(body, fn):
                out = getattr(body, fn)()
                if isinstance(out, chrono.ChVector3d):
                    return out
        except Exception:
            pass

    # (3) 어떤 버전은 GetInertia() -> ChMatrix33
    try:
        if hasattr(body, "GetInertia"):
            I = body.GetInertia()
            if I is not None and hasattr(I, "GetElement"):
                Ixx = float(I.GetElement(0, 0))
                Iyy = float(I.GetElement(1, 1))
                Izz = float(I.GetElement(2, 2))
                return chrono.ChVector3d(Ixx, Iyy, Izz)
    except Exception:
        pass

    return None


def _effective_inertia_about_axis_world(body: chrono.ChBody, axis_world: chrono.ChVector3d) -> float:
    """
    축(axis_world)에 대한 등가 관성 I_eff를 '대략' 구한다.
    - body local 대각 관성(Ixx,Iyy,Izz)을 얻고
    - axis_world를 local로 회전시킨 뒤
      I_eff = Ixx*ax^2 + Iyy*ay^2 + Izz*az^2
    실패 시 1.0으로 fallback (anti-flip clamp가 너무 약해지지 않게)
    """
    try:
        axis_n = _normalize(axis_world)
        if _norm(axis_n) < 1e-12:
            return 1.0

        Idiag = _get_body_inertia_diag_local(body)
        if Idiag is None:
            return 1.0

        q = body.GetRot()
        qinv = _quat_conjugate(q)
        axis_local = _quat_rotate(qinv, axis_n)

        ax = float(axis_local.x)
        ay = float(axis_local.y)
        az = float(axis_local.z)

        Ieff = float(Idiag.x * ax * ax + Idiag.y * ay * ay + Idiag.z * az * az)
        if not (Ieff > 1e-12):
            return 1.0
        return Ieff
    except Exception:
        return 1.0


# ============================================================
# (3-1.4) Gear runtime states / helpers
# ============================================================

@dataclass
class _AssemblyRuntimeState:
    name: str
    moving_body: str
    target_body: str
    moving_local_pos: chrono.ChVector3d
    target_local_pos: chrono.ChVector3d
    align_axis: str
    mode: str
    enabled: bool
    position_tolerance: float
    angle_tolerance: float
    snap_strength: float

    last_active: bool = False
    last_candidate: Optional[str] = None
    last_error_pos: float = 0.0
    last_error_angle: float = 0.0

def _quat_to_wxyz_tuple(q: chrono.ChQuaterniond) -> tuple[float, float, float, float]:
    return (float(q.e0), float(q.e1), float(q.e2), float(q.e3))


def _quat_dot_abs(q1: chrono.ChQuaterniond, q2: chrono.ChQuaterniond) -> float:
    a = _quat_to_wxyz_tuple(q1)
    b = _quat_to_wxyz_tuple(q2)
    d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    return abs(float(d))


def _quat_angle_error(q1: chrono.ChQuaterniond, q2: chrono.ChQuaterniond) -> float:
    d = _clamp(_quat_dot_abs(q1, q2), 0.0, 1.0)
    return float(2.0 * m.acos(d))


def _safe_body_local_point_from_any(v: Any) -> chrono.ChVector3d:
    if v is None:
        return chrono.ChVector3d(0.0, 0.0, 0.0)

    try:
        if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z"):
            x = getattr(v, "x")
            y = getattr(v, "y")
            z = getattr(v, "z")
            if callable(x):
                return chrono.ChVector3d(float(x()), float(y()), float(z()))
            return chrono.ChVector3d(float(x), float(y), float(z))
    except Exception:
        pass

    try:
        if isinstance(v, dict):
            return chrono.ChVector3d(float(v.get("x", 0.0)), float(v.get("y", 0.0)), float(v.get("z", 0.0)))
    except Exception:
        pass

    return chrono.ChVector3d(0.0, 0.0, 0.0)

@dataclass
class _GearRuntimeState:
    name: str
    gearA: str
    gearB: str
    ratio: float
    enabled: bool
    efficiency: float
    backlash: float
    max_torque: float
    phase_a: float = 0.0
    phase_b: float = 0.0


def _float_attr_any(obj: Any, names: List[str], default: float) -> float:
    for nm in names:
        try:
            if isinstance(obj, dict):
                if nm in obj and obj[nm] is not None:
                    return float(obj[nm])
            else:
                v = getattr(obj, nm, None)
                if v is not None:
                    return float(v)
        except Exception:
            pass
    return float(default)


def _str_attr_any(obj: Any, names: List[str], default: str = "") -> str:
    for nm in names:
        try:
            if isinstance(obj, dict):
                if nm in obj and obj[nm] is not None:
                    return str(obj[nm])
            else:
                v = getattr(obj, nm, None)
                if v is not None:
                    return str(v)
        except Exception:
            pass
    return str(default)


def _bool_attr_any(obj: Any, names: List[str], default: bool) -> bool:
    for nm in names:
        try:
            if isinstance(obj, dict):
                if nm in obj and obj[nm] is not None:
                    return bool(obj[nm])
            else:
                v = getattr(obj, nm, None)
                if v is not None:
                    return bool(v)
        except Exception:
            pass
    return bool(default)


def _compute_signed_gear_ratio_from_scene(scene: Any, gp: Any) -> Optional[float]:
    try:
        gearA_name = getattr(gp, "gearA", None)
        gearB_name = getattr(gp, "gearB", None)
        ratio_sign = int(getattr(gp, "ratio_sign", -1))
    except Exception:
        return None

    if gearA_name is None or gearB_name is None:
        return None

    try:
        bodies = list(getattr(scene, "bodies", []) or [])
        bodyA = next((b for b in bodies if getattr(b, "name", None) == gearA_name), None)
        bodyB = next((b for b in bodies if getattr(b, "name", None) == gearB_name), None)
        if bodyA is None or bodyB is None:
            return None

        gpA = getattr(getattr(bodyA, "mechanical", None), "gearProps", None)
        gpB = getattr(getattr(bodyB, "mechanical", None), "gearProps", None)
        if gpA is None or gpB is None:
            return None

        module_a = float(getattr(gpA, "module", 0.0))
        teeth_a = int(getattr(gpA, "teeth", 0))
        module_b = float(getattr(gpB, "module", 0.0))
        teeth_b = int(getattr(gpB, "teeth", 0))

        rA = 0.5 * module_a * float(teeth_a)
        rB = 0.5 * module_b * float(teeth_b)
        if abs(rB) < 1e-12:
            return None

        return float((rA / rB) * float(ratio_sign))
    except Exception:
        return None


# ============================================================
# (2-3.3) Joint limit headless tests
# ============================================================

def _yaw_from_quat(q: chrono.ChQuaterniond) -> float:
    """
    Z축(yaw) 회전각(라디안) 추정.
    - 우리가 테스트 시스템을 z-회전만 하도록 만들기 때문에 yaw로 충분.
    """
    w = float(q.e0)
    x = float(q.e1)
    y = float(q.e2)
    z = float(q.e3)
    # yaw (Z)
    s = 2.0 * (w * z + x * y)
    c = 1.0 - 2.0 * (y * y + z * z)
    return float(m.atan2(s, c))


def _try_enable_limit_on_link_best_effort(link: Any, *, lower: float, upper: float) -> None:
    """
    sim_builder의 best-effort 스타일과 비슷하게,
    여기서도 최대한 여러 후보를 시도해서 limit을 켠다.
    (실패해도 테스트가 크래시 나면 안 됨)
    """
    # direct set
    for fn in ("SetLimitActive", "SetLimitsActive", "SetLimitOn", "SetLimitsOn"):
        try:
            if hasattr(link, fn):
                getattr(link, fn)(True)
        except Exception:
            pass

    for fn in ("SetLimits", "SetLimit", "SetLimitRange", "SetMotionLimits"):
        try:
            if hasattr(link, fn):
                getattr(link, fn)(float(lower), float(upper))
                return
        except Exception:
            pass

    # limit object patterns
    for attr in ("limit_Rz", "limit_rz", "limit_Z", "limit_z", "limit"):
        try:
            if hasattr(link, attr):
                lim = getattr(link, attr)
                if lim is None:
                    continue
                for fn in ("SetActive", "SetEnabled", "SetEnable", "SetOn"):
                    try:
                        if hasattr(lim, fn):
                            getattr(lim, fn)(True)
                    except Exception:
                        pass
                for fn in ("SetMin", "SetMinLimit", "SetLowerLimit", "SetLower", "SetMinValue"):
                    try:
                        if hasattr(lim, fn):
                            getattr(lim, fn)(float(lower))
                            break
                    except Exception:
                        pass
                for fn in ("SetMax", "SetMaxLimit", "SetUpperLimit", "SetUpper", "SetMaxValue"):
                    try:
                        if hasattr(lim, fn):
                            getattr(lim, fn)(float(upper))
                            break
                    except Exception:
                        pass
                return
        except Exception:
            pass

    # getter patterns
    for fn in ("GetLimit_Rz", "GetLimitRz", "GetLimit_Z", "GetLimitZ", "GetLimit"):
        try:
            if hasattr(link, fn):
                lim = getattr(link, fn)()
                if lim is None:
                    continue
                for f in ("SetActive", "SetEnabled", "SetEnable", "SetOn"):
                    try:
                        if hasattr(lim, f):
                            getattr(lim, f)(True)
                    except Exception:
                        pass
                for f in ("SetMin", "SetMinLimit", "SetLowerLimit", "SetLower", "SetMinValue"):
                    try:
                        if hasattr(lim, f):
                            getattr(lim, f)(float(lower))
                            break
                    except Exception:
                        pass
                for f in ("SetMax", "SetMaxLimit", "SetUpperLimit", "SetUpper", "SetMaxValue"):
                    try:
                        if hasattr(lim, f):
                            getattr(lim, f)(float(upper))
                            break
                    except Exception:
                        pass
                return
        except Exception:
            pass


def _run_joint_limit_test_revolute(*, dt: float = 1e-3, steps: int = 4000) -> bool:
    """
    revolute: 모터로 돌리다가 upper에 걸려서 더 못 넘어가는지 확인
    - ground(고정) + body(동적)
    - revolute(z축) + limit [0, upper]
    - rotation speed motor로 +속도 구동
    """
    print("\n[2-3.3] Revolute limit test: start")

    sys_ = chrono.ChSystemNSC()
    sys_.SetGravitationalAcceleration(chrono.ChVector3d(0, -9.81, 0))

    # ground
    ground = chrono.ChBody()
    ground.SetFixed(True)
    ground.SetPos(chrono.ChVector3d(0, 0, 0))
    ground.SetRot(chrono.ChQuaterniond(1, 0, 0, 0))
    ground.SetName("ground")
    sys_.AddBody(ground)

    # rotating body
    body = chrono.ChBody()
    body.SetFixed(False)
    body.SetPos(chrono.ChVector3d(0, 0, 0))
    body.SetRot(chrono.ChQuaterniond(1, 0, 0, 0))
    body.SetMass(1.0)
    # inertia 대충 (z축 회전 테스트)
    try:
        body.SetInertiaXX(chrono.ChVector3d(0.05, 0.05, 0.05))
    except Exception:
        pass
    body.SetName("rotor")
    sys_.AddBody(body)

    # revolute link at origin, z axis (Chrono lock revolute uses link frame z as axis)
    rev = chrono.ChLinkLockRevolute()
    fr = chrono.ChFramed(chrono.ChVector3d(0, 0, 0), chrono.ChQuaterniond(1, 0, 0, 0))
    rev.Initialize(ground, body, fr)

    upper = float(m.pi / 6.0)  # 30deg
    _try_enable_limit_on_link_best_effort(rev, lower=0.0, upper=upper)

    # add to system
    sys_.AddLink(rev)

    # motor: prefer rotation speed motor if available
    motor = None
    if hasattr(chrono, "ChLinkMotorRotationSpeed"):
        try:
            motor = chrono.ChLinkMotorRotationSpeed()
            motor.Initialize(ground, body, fr)
            motor.SetSpeedFunction(chrono.ChFunctionConst(2.0))  # rad/s
            sys_.AddLink(motor)
        except Exception:
            motor = None

    if motor is None:
        # fallback: torque drive (apply torque each step)
        print("[2-3.3][revolute] WARN: ChLinkMotorRotationSpeed not available. Using torque drive fallback.")

    # simulate
    hit_upper_count = 0
    last_yaw = _yaw_from_quat(body.GetRot())

    for i in range(int(steps)):
        if motor is None:
            # push +z torque
            _apply_torque_world(body, chrono.ChVector3d(0, 0, 0.2))

        sys_.DoStepDynamics(float(dt))

        yaw = _yaw_from_quat(body.GetRot())
        w = _get_angvel_world(body)
        wz = float(w.z)

        # unwrap-ish: keep near 0..pi range for this test
        # (초기 0에서 +로만 올라가도록 구성)
        if yaw < 0.0:
            yaw += 2.0 * m.pi

        # "upper 근처에서 멈추는지" 근사 판정
        if yaw >= upper - 0.02:
            hit_upper_count += 1

        if (i % 400) == 0:
            print(f"[revolute] step={i:5d} yaw={yaw:+.3f} rad  wz={wz:+.3f} rad/s")

        last_yaw = yaw

    # 성공 판정(보수적):
    # - 충분히 여러 스텝 동안 upper 근처(yaw >= upper-0.02)에 머물렀다
    ok = hit_upper_count > int(0.25 * steps)
    print(f"[2-3.3] Revolute limit test: {'PASS' if ok else 'FAIL'} (hit_upper_count={hit_upper_count}/{steps})")
    return ok


def _run_joint_limit_test_prismatic(*, dt: float = 1e-3, steps: int = 4000) -> bool:
    """
    prismatic: 일정 속도로 미는 actuator를 걸고 upper에서 위치가 더 안 늘어나는지 확인
    - ground(고정) + slider(동적)
    - prismatic(z축) + limit [0, upper]
    - linear speed motor가 있으면 사용, 없으면 힘으로 민다
    """
    print("\n[2-3.3] Prismatic limit test: start")

    sys_ = chrono.ChSystemNSC()
    sys_.SetGravitationalAcceleration(chrono.ChVector3d(0, -9.81, 0))

    ground = chrono.ChBody()
    ground.SetFixed(True)
    ground.SetPos(chrono.ChVector3d(0, 0, 0))
    ground.SetRot(chrono.ChQuaterniond(1, 0, 0, 0))
    ground.SetName("ground")
    sys_.AddBody(ground)

    slider = chrono.ChBody()
    slider.SetFixed(False)
    slider.SetPos(chrono.ChVector3d(0, 0, 0))
    slider.SetRot(chrono.ChQuaterniond(1, 0, 0, 0))
    slider.SetMass(1.0)
    try:
        slider.SetInertiaXX(chrono.ChVector3d(0.02, 0.02, 0.02))
    except Exception:
        pass
    slider.SetName("slider")
    sys_.AddBody(slider)

    pri = chrono.ChLinkLockPrismatic()
    fr = chrono.ChFramed(chrono.ChVector3d(0, 0, 0), chrono.ChQuaterniond(1, 0, 0, 0))
    pri.Initialize(ground, slider, fr)

    upper = 0.25  # meters along z
    _try_enable_limit_on_link_best_effort(pri, lower=0.0, upper=float(upper))
    sys_.AddLink(pri)

    motor = None
    # linear speed motor (binding마다 존재/이름이 다를 수 있음)
    for cls_name in ("ChLinkMotorLinearSpeed", "ChLinkMotorLinearSpeedDriveline"):
        if hasattr(chrono, cls_name):
            try:
                motor = getattr(chrono, cls_name)()
                motor.Initialize(ground, slider, fr)
                motor.SetSpeedFunction(chrono.ChFunctionConst(0.2))  # m/s
                sys_.AddLink(motor)
                break
            except Exception:
                motor = None

    if motor is None:
        print("[2-3.3][prismatic] WARN: Linear speed motor not available. Using force drive fallback (+Z force).")

    hit_upper_count = 0

    for i in range(int(steps)):
        if motor is None:
            _apply_force_world(slider, chrono.ChVector3d(0, 0, 3.0))

        sys_.DoStepDynamics(float(dt))

        z = float(slider.GetPos().z)
        vz = float(_get_linvel_world(slider).z)

        if z >= upper - 0.01:
            hit_upper_count += 1

        if (i % 400) == 0:
            print(f"[prismatic] step={i:5d} z={z:+.3f} m  vz={vz:+.3f} m/s")

    ok = hit_upper_count > int(0.25 * steps)
    print(f"[2-3.3] Prismatic limit test: {'PASS' if ok else 'FAIL'} (hit_upper_count={hit_upper_count}/{steps})")
    return ok


def run_joint_limit_tests_headless() -> None:
    """
    (2-3.3) 한 번에 두 케이스 실행.
    - FAIL 해도 프로세스 크래시는 안 나게 하고, 결과만 출력.
    """
    try:
        ok1 = _run_joint_limit_test_revolute(dt=1e-3, steps=4000)
    except Exception as e:
        ok1 = False
        print("[2-3.3] Revolute limit test crashed:", e)

    try:
        ok2 = _run_joint_limit_test_prismatic(dt=1e-3, steps=4000)
    except Exception as e:
        ok2 = False
        print("[2-3.3] Prismatic limit test crashed:", e)

    print("\n[2-3.3] Joint limit tests summary:")
    print(" - revolute:", "PASS" if ok1 else "FAIL")
    print(" - prismatic:", "PASS" if ok2 else "FAIL")


# ============================================================
# dict -> UserInput(Event) coercion
# ============================================================

def _coerce_user_input_any(user_input_any: Any) -> Optional[UserInput]:
    if user_input_any is None:
        return None

    if isinstance(user_input_any, (TouchStartEvent, TouchingEvent, TouchEndEvent)):
        return user_input_any

    if isinstance(user_input_any, dict):
        # ✅ runtime_types의 단일 엔트리 함수를 우선 사용
        try:
            out = rt.user_input_from_dict(user_input_any)
            if isinstance(out, (TouchStartEvent, TouchingEvent, TouchEndEvent)):
                return out
        except Exception:
            pass

        # 호환/확장 시도 (예전 함수명들 fallback)
        for fn_name in ("parse_user_input", "parse", "from_dict"):
            try:
                fn = getattr(rt, fn_name, None)
                if callable(fn):
                    out = fn(user_input_any)
                    if isinstance(out, (TouchStartEvent, TouchingEvent, TouchEndEvent)):
                        return out
            except Exception:
                pass

        # 마지막: type 보고 직접 파싱 시도
        t = str(user_input_any.get("type", "")).strip()
        try:
            if t == "TouchStart" and hasattr(TouchStartEvent, "from_dict"):
                return TouchStartEvent.from_dict(user_input_any)  # type: ignore[attr-defined]
            if t == "Touching" and hasattr(TouchingEvent, "from_dict"):
                return TouchingEvent.from_dict(user_input_any)  # type: ignore[attr-defined]
            if t == "TouchEnd" and hasattr(TouchEndEvent, "from_dict"):
                return TouchEndEvent.from_dict(user_input_any)  # type: ignore[attr-defined]
        except Exception:
            pass

        print("[WARN] userInput dict -> Event 변환 실패. dict keys:", list(user_input_any.keys()))
        return None

    print("[WARN] Unsupported userInput type:", type(user_input_any))
    return None

# ============================================================
# Metadata validation diagnostics
# ============================================================

def validate_metadata(scene: Any) -> List[rt.DiagnosticItem]:
    """
    시뮬레이션 시작 전 메타데이터를 검사하여 교육용 진단 메시지를 생성한다.

    검사 항목:
    - mass <= 0
    - inertia <= 0
    - joint가 존재하지 않는 body를 참조
    - fixed body가 하나도 없음
    """
    diagnostics: List[rt.DiagnosticItem] = []

    bodies = list(getattr(scene, "bodies", []) or [])
    joints = list(getattr(scene, "joints", []) or [])

    body_names = set()
    fixed_count = 0

    for body in bodies:
        name = str(getattr(body, "name", "") or "")
        if not name:
            continue

        body_names.add(name)

        mechanical = getattr(body, "mechanical", None)

        try:
            if mechanical is not None and bool(getattr(mechanical, "fixed", False)):
                fixed_count += 1
        except Exception:
            pass

        # mass 검사
        try:
            mass = float(getattr(mechanical, "mass", 0.0)) if mechanical is not None else 0.0
            if mass <= 0.0 and not bool(getattr(mechanical, "fixed", False)):
                diagnostics.append(
                    rt.DiagnosticItem(
                        code="INVALID_MASS",
                        severity="warn",
                        message=f"Body '{name}'의 mass 값이 0 이하입니다. 동역학 계산이 불안정할 수 있습니다.",
                        target=name,
                    )
                )
        except Exception:
            diagnostics.append(
                rt.DiagnosticItem(
                    code="MASS_CHECK_FAILED",
                    severity="info",
                    message=f"Body '{name}'의 mass 값을 확인하지 못했습니다.",
                    target=name,
                )
            )

        # inertia 검사
        try:
            inertia = getattr(mechanical, "inertia", None) if mechanical is not None else None

            if inertia is not None:
                ixx = float(getattr(inertia, "Ixx", 0.0))
                iyy = float(getattr(inertia, "Iyy", 0.0))
                izz = float(getattr(inertia, "Izz", 0.0))

                if (ixx <= 0.0 or iyy <= 0.0 or izz <= 0.0) and not bool(getattr(mechanical, "fixed", False)):
                    diagnostics.append(
                        rt.DiagnosticItem(
                            code="INVALID_INERTIA",
                            severity="warn",
                            message=f"Body '{name}'의 inertia 값 중 0 이하인 항목이 있습니다. 회전 응답이 비정상적일 수 있습니다.",
                            target=name,
                        )
                    )
        except Exception:
            diagnostics.append(
                rt.DiagnosticItem(
                    code="INERTIA_CHECK_FAILED",
                    severity="info",
                    message=f"Body '{name}'의 inertia 값을 확인하지 못했습니다.",
                    target=name,
                )
            )

    # fixed body 없음 검사
    if fixed_count <= 0:
        diagnostics.append(
            rt.DiagnosticItem(
                code="NO_FIXED_BODY",
                severity="warn",
                message="fixed body가 하나도 없습니다. 기준 body가 없으면 전체 기구가 떠다니거나 불안정할 수 있습니다.",
                target=None,
            )
        )

    # joint body 참조 검사
    for joint in joints:
        joint_name = str(getattr(joint, "name", "") or "")
        body1 = getattr(joint, "body1", None)
        body2 = getattr(joint, "body2", None)

        if body1 is not None and str(body1) not in body_names:
            diagnostics.append(
                rt.DiagnosticItem(
                    code="JOINT_BODY_NOT_FOUND",
                    severity="error",
                    message=f"Joint '{joint_name}'가 존재하지 않는 body1 '{body1}'를 참조합니다.",
                    target=joint_name,
                )
            )

        if body2 is not None and str(body2) not in body_names:
            diagnostics.append(
                rt.DiagnosticItem(
                    code="JOINT_BODY_NOT_FOUND",
                    severity="error",
                    message=f"Joint '{joint_name}'가 존재하지 않는 body2 '{body2}'를 참조합니다.",
                    target=joint_name,
                )
            )

    return diagnostics

# ============================================================
# AR Interaction Controller (schema-06) - Hybrid
# ============================================================
@dataclass
class _TouchContext:
    active: bool = False
    target_name: Optional[str] = None
    action_point_local: Optional[chrono.ChVector3d] = None  # BODY-LOCAL
    start_finger_world: Optional[chrono.ChVector3d] = None
    last_finger_world: Optional[chrono.ChVector3d] = None
    camera_forward_world: Optional[chrono.ChVector3d] = None

    # rotate mode에서 TouchStart 시점에 고정해서 쓰는 기준
    rotate_axis_world: Optional[chrono.ChVector3d] = None
    rotate_pivot_world: Optional[chrono.ChVector3d] = None

    # TouchEnd 직후 free-phase 안정화용 카운터
    rotate_release_step_count: int = 0

    # free-phase에서 사용할 "명령된 축방향 각속도"
    # post-step sanitize가 현재 측정치를 따라가지 않고, 이 값을 단조감쇠시킨다.
    rotate_free_w_cmd: float = 0.0

    # 폐루프 기구에서 실제 torque를 줄 body
    # 예: target=coupler_link여도 drive_body=input_link로 바꿔서 구동
    drive_body_name: Optional[str] = None

class _ARInteractionController:
    MODE_ROTATE = "rotate"
    MODE_SPRING = "spring"

    # ---- Rotate drag (inertia-aware) ----
    DRAG_ALPHA_MAX = 35.0          # 최대 각가속도
    DRAG_ALPHA_MIN_LOW = 4.0       # 저속에서 최소 각가속도
    DRAG_ANGLE_REF = m.pi / 28.0
    DRAG_ANGLE_EPS = 1e-4

    ROT_DRAG_SPEED_SOFT = 8.0
    ROT_DRAG_SPEED_HARD = 12.0
    ROT_DRAG_LOW_SPEED_REF = 0.80
    ROT_DRAG_TARGET_SPEED_GAIN = 1.0
    ROT_DRAG_SPEED_KP_ALPHA = 10.0
    ROT_DRAG_SPEED_TAU_MAX_ALPHA = 6.0

    # drag 중 damping (alpha 기반)
    ROT_DRAG_CW_ALPHA = 0.25

    # ---- Rotate damping (inertia-aware torque-based) ----
    # 기존 tau = Cw * w  대신
    # tau = Cw_alpha * Ieff * w  형태로 써서
    # 관성이 달라도 비슷한 각감속(alpha)이 나오게 만든다.
    ROT_DAMP_CW_ALPHA = 0.90          # [1/s]
    VEL_EPS_SNAP_ROT = 0.03
    ROT_DAMP_TAU_MAX_ALPHA = 1.80     # [rad/s^2] * Ieff 로 환산
    ROT_DAMP_NOFLIP_SAFETY = 0.95

    # TouchEnd 직후 free phase 제어 파라미터
    ROT_RELEASE_HOLD_STEPS = 3
    ROT_FREE_LOW_SPEED_REF = 0.8

    # ---- Spring ----
    SPRING_K = 80.0
    SPRING_C = 8.0
    SPRING_F_MAX = 200.0

    # ---- Free damping in spring mode (force/torque-based) ----
    FREE_DAMP_CV = 1.0
    FREE_DAMP_CW = 1.0

    def __init__(self) -> None:
        self.ctx = _TouchContext()
        self._last_dynamic_target: Optional[str] = None
        self._mode: str = self.MODE_ROTATE
        self._prev_finger_world: Optional[chrono.ChVector3d] = None
        self._prev_rotate_finger_world: Optional[chrono.ChVector3d] = None

    def _find_single_revolute_joint_meta(self, sim: "Simulator", target_body_name: str):
        revs = []
        try:
            for j in sim.joints.values():
                jm = j.meta
                if getattr(jm, "type", None) != "revolute":
                    continue

                b1 = getattr(jm, "body1", None)
                b2 = getattr(jm, "body2", None)
                if b1 == target_body_name or b2 == target_body_name:
                    revs.append(jm)
        except Exception:
            return None

        if len(revs) == 1:
            return revs[0]
        return None

    def _find_drive_revolute_joint_meta(self, sim: "Simulator", target_body_name: str):
        """
        폐루프/다중 조인트 기구에서 AR rotate 기준이 될 revolute joint를 찾는다.

        우선순위:
        1) target body가 fixed/ground body와 직접 연결된 revolute joint
        2) target body에서 joint graph를 따라가며 가장 가까운 fixed/ground 연결 revolute joint
        3) 그래도 없으면 target body에 직접 연결된 revolute joint 중 첫 번째

        예:
        - input_link  -> rev_ground_input
        - rocker_link -> rev_rocker_ground
        - coupler_link -> 가까운 ground-side revolute를 찾아서 선택
        """
        if not target_body_name:
            return None

        # -----------------------------------------
        # 1) revolute joint 목록 + body graph 구성
        # -----------------------------------------
        revs = []
        graph: dict[str, list[tuple[str, Any]]] = {}

        try:
            for j in sim.joints.values():
                jm = j.meta
                if getattr(jm, "type", None) != "revolute":
                    continue

                b1 = getattr(jm, "body1", None)
                b2 = getattr(jm, "body2", None)

                if not b1 or not b2:
                    continue

                revs.append(jm)

                graph.setdefault(str(b1), []).append((str(b2), jm))
                graph.setdefault(str(b2), []).append((str(b1), jm))
        except Exception:
            return None

        if target_body_name not in graph:
            return None

        def _is_fixed_name(name: str) -> bool:
            # 1) Chrono body 기준
            try:
                body = sim.bodies[name].body
                if _is_fixed_body(body):
                    return True
            except Exception:
                pass

            # 2) metadata 기준 fallback
            try:
                for bm in getattr(sim.info.scene, "bodies", []):
                    if getattr(bm, "name", None) != name:
                        continue

                    mech = getattr(bm, "mechanical", None)
                    if mech is not None and bool(getattr(mech, "fixed", False)):
                        return True
            except Exception:
                pass

            # 3) 이름 기준 fallback
            if str(name).lower() in ("ground", "base", "fixed", "world"):
                return True

            return False

        # -----------------------------------------
        # 2) 직접 fixed/ground에 연결된 revolute 우선
        # -----------------------------------------
        direct_revs = []
        try:
            for other_name, jm in graph.get(target_body_name, []):
                if _is_fixed_name(other_name):
                    direct_revs.append(jm)
        except Exception:
            pass

        if direct_revs:
            return direct_revs[0]

        # -----------------------------------------
        # 3) BFS로 가장 가까운 fixed/ground 연결 revolute 찾기
        # -----------------------------------------
        from collections import deque

        visited = set([target_body_name])
        q = deque()

        # (현재 body, 현재 body까지 들어올 때 사용한 joint, depth)
        for other_name, jm in graph.get(target_body_name, []):
            q.append((other_name, jm, 1))
            visited.add(other_name)

        best = None

        while q:
            body_name, incoming_joint, depth = q.popleft()

            # 현재 body가 fixed/ground면,
            # 그 fixed body와 직접 연결된 incoming_joint가 진짜 drive joint
            if _is_fixed_name(body_name):
                best = incoming_joint
                break

            for next_name, next_joint in graph.get(body_name, []):
                if next_name in visited:
                    continue

                visited.add(next_name)

                # 핵심:
                # first_joint가 아니라, 다음 body로 들어갈 때의 next_joint를 넘긴다.
                q.append((next_name, next_joint, depth + 1))

        if best is not None:
            return best

        # -----------------------------------------
        # 4) fallback: target에 직접 연결된 revolute 중 첫 번째
        # -----------------------------------------
        try:
            direct_any = graph.get(target_body_name, [])
            if direct_any:
                return direct_any[0][1]
        except Exception:
            pass

        return None

    def _resolve_drive_body_name(self, sim: "Simulator", target_body_name: str) -> str:
        """
        AR target이 coupler처럼 직접 구동하기 어려운 링크일 때,
        실제 torque를 줄 drive body를 결정한다.

        원칙:
        - fixed body는 절대 drive body로 선택하지 않는다.
        - target body가 fixed가 아니고, drive joint에 포함되어 있으면 target을 우선 사용한다.
        - coupler처럼 fixed와 직접 연결되지 않은 경우에는 joint 반대편 non-fixed body를 사용한다.
        """
        if not target_body_name:
            return target_body_name

        try:
            target_body = sim.bodies[target_body_name].body
            if _is_fixed_body(target_body):
                return target_body_name
        except Exception:
            return target_body_name

        jm = self._find_drive_revolute_joint_meta(sim, target_body_name)
        if jm is None:
            return target_body_name

        try:
            b1 = str(getattr(jm, "body1", ""))
            b2 = str(getattr(jm, "body2", ""))

            b1_fixed = False
            b2_fixed = False

            try:
                b1_fixed = _is_fixed_body(sim.bodies[b1].body)
            except Exception:
                pass
            if str(b1).lower() in ("ground", "base", "fixed", "world"):
                b1_fixed = True

            try:
                b2_fixed = _is_fixed_body(sim.bodies[b2].body)
            except Exception:
                pass
            if str(b2).lower() in ("ground", "base", "fixed", "world"):
                b2_fixed = True

            # fixed body는 절대 drive body로 쓰지 않는다.
            if b1_fixed and not b2_fixed:
                return b2

            if b2_fixed and not b1_fixed:
                return b1

            # target이 drive joint에 포함되어 있고 fixed가 아니면 target 우선
            if b1 == target_body_name and not b1_fixed:
                return b1

            if b2 == target_body_name and not b2_fixed:
                return b2

            # coupler 케이스: target이 포함되지 않은 joint가 잡혔거나 애매하면 non-fixed 후보 선택
            if b1 and not b1_fixed:
                return b1

            if b2 and not b2_fixed:
                return b2

        except Exception:
            pass

        return target_body_name

    def _resolve_rotate_reference(self, sim: "Simulator", target_body_name: str) -> tuple[chrono.ChVector3d, chrono.ChVector3d]:
        """
        rotate mode에서 사용할 axis/pivot 기준을 TouchStart 시점에 고정한다.
        - axis: 기존 infer 함수 사용
        - pivot: 가능하면 revolute joint meta.frame.pos (world) 사용
        - 실패 시 body.GetPos() fallback
        """
        axis_world = _normalize(sim._infer_revolute_axis_world_for_body(target_body_name))
        if _norm(axis_world) < 1e-9:
            axis_world = chrono.ChVector3d(1.0, 0.0, 0.0)

        pivot_world = chrono.ChVector3d(0.0, 0.0, 0.0)

        jm = self._find_drive_revolute_joint_meta(sim, target_body_name)
        if jm is None:
            jm = self._find_single_revolute_joint_meta(sim, target_body_name)
        if jm is not None:
            try:
                fr = getattr(jm, "frame", None)
                if fr is not None:
                    pos = getattr(fr, "pos", None)
                    if pos is not None:
                        pivot_world = chrono.ChVector3d(float(pos.x), float(pos.y), float(pos.z))
                        return axis_world, pivot_world
            except Exception:
                pass

        try:
            b = sim.bodies[target_body_name].body
            pivot_world = b.GetPos()
        except Exception:
            pivot_world = chrono.ChVector3d(0.0, 0.0, 0.0)

        return axis_world, pivot_world

    def ingest(self, user_input: UserInput, *, part_names: List[str], sim: "Simulator") -> None:
        if isinstance(user_input, TouchStartEvent):
            target_name = user_input.payload.target.partName
            if not target_name:
                target_name = resolve_target_part_name(user_input, part_names)

            self.ctx.active = True
            self.ctx.target_name = target_name
            self.ctx.drive_body_name = target_name

            ap = user_input.payload.actionPointLocal
            fp = user_input.payload.fingerPointWorld
            cf = user_input.payload.cameraForwardWorld

            self.ctx.action_point_local = chrono.ChVector3d(ap.x, ap.y, ap.z)
            self.ctx.start_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self.ctx.last_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self.ctx.camera_forward_world = chrono.ChVector3d(cf.x, cf.y, cf.z)

            self._prev_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self._prev_rotate_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self.ctx.rotate_release_step_count = 0
            self.ctx.rotate_free_w_cmd = 0.0

            self._mode = self._auto_select_mode(sim, target_name)

            # rotate mode 기준은 TouchStart 시점에 고정
            self.ctx.rotate_axis_world = None
            self.ctx.rotate_pivot_world = None
            if self._mode == self.MODE_ROTATE and target_name:
                try:
                    drive_body_name = self._resolve_drive_body_name(sim, target_name)
                    self.ctx.drive_body_name = drive_body_name

                    ax, pv = self._resolve_rotate_reference(sim, drive_body_name)

                    print(
                        f"[AR DEBUG] target={target_name} "
                        f"drive_body={drive_body_name} "
                        f"axis=({ax.x:+.3f},{ax.y:+.3f},{ax.z:+.3f}) "
                        f"pivot=({pv.x:+.3f},{pv.y:+.3f},{pv.z:+.3f})"
                    )
                    self.ctx.rotate_axis_world = ax
                    self.ctx.rotate_pivot_world = pv
                except Exception:
                    self.ctx.drive_body_name = target_name
                    self.ctx.rotate_axis_world = None
                    self.ctx.rotate_pivot_world = None

            sim._maybe_release_drive_actuators_for_target(target_name)

            print(f"[AR] TouchStart target={target_name} mode={self._mode}")
            return

        if isinstance(user_input, TouchingEvent):
            fp = user_input.payload.fingerPointWorld
            cf = user_input.payload.cameraForwardWorld

            new_fp = chrono.ChVector3d(fp.x, fp.y, fp.z)

            if self.ctx.last_finger_world is None:
                self.ctx.last_finger_world = new_fp
            else:
                alpha = 0.35
                old = self.ctx.last_finger_world

                self.ctx.last_finger_world = chrono.ChVector3d(
                    old.x * (1.0 - alpha) + new_fp.x * alpha,
                    old.y * (1.0 - alpha) + new_fp.y * alpha,
                    old.z * (1.0 - alpha) + new_fp.z * alpha,
                )

            self.ctx.camera_forward_world = chrono.ChVector3d(cf.x, cf.y, cf.z)
            return

        if isinstance(user_input, TouchEndEvent):
            self.ctx.active = False
            self.ctx.start_finger_world = None
            self.ctx.drive_body_name = None
            self._prev_finger_world = None
            self._prev_rotate_finger_world = None
            self.ctx.rotate_release_step_count = 0

            # ✅ TouchEnd에서는 각속도 overwrite / 강제 캡을 하지 않는다.
            #    현재 물리 상태를 그대로 이어받고, 이후 free phase에서 damping torque만 적용되게 둔다.
            self.ctx.rotate_free_w_cmd = 0.0

            print("[AR] TouchEnd")
            return

    def _auto_select_mode(self, sim: "Simulator", target_body_name: str) -> str:
        if target_body_name not in sim.bodies:
            return self.MODE_SPRING

        body = sim.bodies[target_body_name].body
        if _is_fixed_body(body):
            return self.MODE_ROTATE

        revolute_joints = []
        other_joints = []

        try:
            for j in sim.joints.values():
                jm = j.meta
                jtype = getattr(jm, "type", None)

                b1 = getattr(jm, "body1", None)
                b2 = getattr(jm, "body2", None)
                if b1 != target_body_name and b2 != target_body_name:
                    continue

                if jtype == "revolute":
                    revolute_joints.append(jm)
                else:
                    other_joints.append(jm)
        except Exception:
            return self.MODE_SPRING

        # 단순 회전 바디
        if (len(revolute_joints) == 1) and (len(other_joints) == 0):
            axis = sim._infer_revolute_axis_world_for_body(target_body_name)
            if _norm(axis) > 1e-6:
                return self.MODE_ROTATE
            return self.MODE_SPRING

        # 폐루프/다중 조인트 기구:
        # fixed/ground와 연결된 revolute가 있으면 그 joint를 기준으로 rotate 허용
        drive_rev = self._find_drive_revolute_joint_meta(sim, target_body_name)
        if drive_rev is not None:
            axis = sim._infer_revolute_axis_world_for_body(target_body_name)
            if _norm(axis) > 1e-6:
                return self.MODE_ROTATE

        return self.MODE_SPRING

    def make_interaction_telemetry(self, sim: "Simulator") -> Optional[InteractionTelemetry]:
        """
        현재 AR 인터랙션 상태를 SimState로 내보내기 위한 telemetry 생성.
        - 콘솔 print로만 보던 target / drive_body / mode / axis / pivot 정보를 구조화한다.
        """
        target_name = self.ctx.target_name
        drive_body_name = self.ctx.drive_body_name

        if not target_name and not drive_body_name:
            return None

        drive_joint_name = None

        try:
            if drive_body_name:
                jm = self._find_drive_revolute_joint_meta(sim, drive_body_name)
                if jm is None:
                    jm = self._find_single_revolute_joint_meta(sim, drive_body_name)
                if jm is not None:
                    drive_joint_name = str(getattr(jm, "name", "")) or None
        except Exception:
            drive_joint_name = None

        axis = self.ctx.rotate_axis_world
        pivot = self.ctx.rotate_pivot_world

        axis_vec = None
        if axis is not None:
            axis_vec = rt.Vec3(float(axis.x), float(axis.y), float(axis.z))

        pivot_vec = None
        if pivot is not None:
            pivot_vec = rt.Vec3(float(pivot.x), float(pivot.y), float(pivot.z))

        return InteractionTelemetry(
            mode=str(self._mode) if self._mode is not None else None,
            targetBody=str(target_name) if target_name is not None else None,
            driveBody=str(drive_body_name) if drive_body_name is not None else None,
            driveJoint=drive_joint_name,
            axisWorld=axis_vec,
            pivotWorld=pivot_vec,
        )

    def compute_and_apply(self, *, sim: "Simulator", dt: float) -> None:
        target_name = self.ctx.drive_body_name or self.ctx.target_name
        if not target_name:
            target_name = self._last_dynamic_target

        if not target_name or target_name not in sim.bodies:
            return

        target_body = sim.bodies[target_name].body
        if _is_fixed_body(target_body):
            return

        self._last_dynamic_target = target_name
        sim._maybe_release_drive_actuators_for_target(target_name)

        dragging_now = self.ctx.active and (self.ctx.last_finger_world is not None)

        if self._mode == self.MODE_ROTATE:
            self._apply_rotate(sim=sim, body=target_body, body_name=target_name, dt=dt, dragging_now=dragging_now)
        else:
            self._apply_spring(sim=sim, body=target_body, body_name=target_name, dt=dt, dragging_now=dragging_now)

    def _apply_rotate(self, *, sim: "Simulator", body: chrono.ChBody, body_name: str, dt: float, dragging_now: bool) -> None:
        axis_world = self.ctx.rotate_axis_world
        if axis_world is None or _norm(axis_world) < 1e-9:
            axis_world = _normalize(sim._infer_revolute_axis_world_for_body(body_name))

        if _norm(axis_world) < 1e-9:
            self._mode = self.MODE_SPRING
            return

        center_world = self.ctx.rotate_pivot_world
        if center_world is None:
            center_world = body.GetPos()

        axis_world_n = _normalize(axis_world)
        if _norm(axis_world_n) < 1e-9:
            return

        Ieff = _effective_inertia_about_axis_world(body, axis_world_n)
        if not (Ieff > 1e-12):
            Ieff = 1.0

        # ---- Drag 상태 ----
        if dragging_now:
            f_curr = self.ctx.last_finger_world
            f_prev = self._prev_rotate_finger_world

            if f_prev is None:
                self._prev_rotate_finger_world = chrono.ChVector3d(f_curr.x, f_curr.y, f_curr.z)
                return

            v0 = _sub(f_prev, center_world)
            v1 = _sub(f_curr, center_world)

            self._prev_rotate_finger_world = chrono.ChVector3d(f_curr.x, f_curr.y, f_curr.z)

            w_before = _get_angvel_world(body)
            w_along_now = float(_dot(w_before, axis_world_n))
            abs_w = abs(w_along_now)

            tau_drag = chrono.ChVector3d(0.0, 0.0, 0.0)

            if _norm(v0) > 1e-6 and _norm(v1) > 1e-6 and dt > 1e-9:
                v0n = _normalize(v0)
                v1n = _normalize(v1)

                c = _clamp(_dot(v0n, v1n), -1.0, 1.0)
                d_ang = m.acos(c)

                if d_ang > self.DRAG_ANGLE_EPS:
                    arc_axis = _cross(v0n, v1n)
                    arc_axis_n = _normalize(arc_axis)

                    if _norm(arc_axis_n) > 1e-6:
                        align = float(_dot(arc_axis_n, axis_world_n))
                        sign = 1.0 if align >= 0.0 else -1.0
                        align_abs = abs(align)

                        # [DEBUG] 회전 방향 진단
                        print(
                            f"[rot-dbg] body={body_name} "
                            f"f_prev=({f_prev.x:+.3f},{f_prev.y:+.3f},{f_prev.z:+.3f}) "
                            f"f_curr=({f_curr.x:+.3f},{f_curr.y:+.3f},{f_curr.z:+.3f}) "
                            f"axis=({axis_world_n.x:+.3f},{axis_world_n.y:+.3f},{axis_world_n.z:+.3f}) "
                            f"arc=({arc_axis_n.x:+.3f},{arc_axis_n.y:+.3f},{arc_axis_n.z:+.3f}) "
                            f"align={align:+.3f} sign={sign:+.1f}"
                        )

                        # 손가락이 pivot 주변에서 만든 각속도(rad/s)
                        w_drag = sign * (d_ang / float(dt))
                        w_drag *= max(0.2, align_abs)
                        w_drag *= float(self.ROT_DRAG_TARGET_SPEED_GAIN)

                        # 너무 큰 순간 입력 방지
                        w_drag = _clamp(
                            w_drag,
                            -float(self.ROT_DRAG_SPEED_HARD),
                            +float(self.ROT_DRAG_SPEED_HARD),
                        )

                        # 현재 축방향 각속도와 목표 각속도의 차이를 줄이는 PD 느낌의 토크
                        w_err = float(w_drag - w_along_now)
                        alpha_cmd = float(self.ROT_DRAG_SPEED_KP_ALPHA) * w_err

                        # 각가속도 제한
                        alpha_cmd = _clamp(
                            alpha_cmd,
                            -float(self.ROT_DRAG_SPEED_TAU_MAX_ALPHA),
                            +float(self.ROT_DRAG_SPEED_TAU_MAX_ALPHA),
                        )

                        # hard speed 근처에서는 더 가속하지 않도록 제한
                        if abs_w >= self.ROT_DRAG_SPEED_HARD and (w_along_now * alpha_cmd) > 0.0:
                            alpha_cmd = 0.0

                        tau_drag = _mul(axis_world_n, Ieff * alpha_cmd)

            # drag 중 축방향 감쇠
            tau_drag_damp_mag = float(self.ROT_DRAG_CW_ALPHA) * Ieff * abs_w
            tau_drag_damp = _mul(axis_world_n, -m.copysign(tau_drag_damp_mag, w_along_now))

            tau_total = _add(tau_drag, tau_drag_damp)
            _apply_torque_world(body, tau_total)
            return

        # ---- TouchEnd 이후 ----
        self._prev_rotate_finger_world = None

        self.ctx.rotate_release_step_count += 1
        if self.ctx.rotate_release_step_count <= self.ROT_RELEASE_HOLD_STEPS:
            return

        if dt <= 1e-9:
            return

        w_world = _get_angvel_world(body)
        w_along = float(_dot(w_world, axis_world_n))
        abs_w = abs(w_along)

        # 아주 작은 속도면 snap-to-rest
        if abs_w < self.VEL_EPS_SNAP_ROT:
            return

        # free phase damping
        tau_mag = float(self.ROT_DAMP_CW_ALPHA) * Ieff * abs_w

        # 저속에서는 linear 하게만 줄여서 tail이 너무 길어지지 않게 함
        low_ref = max(float(self.ROT_FREE_LOW_SPEED_REF), 1e-6)
        if abs_w < low_ref:
            low_scale = max(0.35, abs_w / low_ref)
            tau_mag *= low_scale

        tau_max_alpha = float(self.ROT_DAMP_TAU_MAX_ALPHA) * Ieff
        tau_mag = min(tau_mag, tau_max_alpha)

        tau_noflip = (Ieff * abs_w / float(dt)) * float(self.ROT_DAMP_NOFLIP_SAFETY)
        tau_mag = min(tau_mag, tau_noflip)

        if tau_mag <= 0.0:
            return

        tau_damp = _mul(axis_world_n, -m.copysign(tau_mag, w_along))
        _apply_torque_world(body, tau_damp)
        return

    def _apply_spring(self, *, sim: "Simulator", body: chrono.ChBody, body_name: str, dt: float, dragging_now: bool) -> None:
        ap_local = self.ctx.action_point_local
        if ap_local is None:
            ap_local = chrono.ChVector3d(0.0, 0.0, 0.0)

        p_grab = _world_point_from_local(body, ap_local)

        if dragging_now:
            p_des = self.ctx.last_finger_world

            v_des = chrono.ChVector3d(0.0, 0.0, 0.0)
            if self._prev_finger_world is not None and p_des is not None:
                dp = _sub(p_des, self._prev_finger_world)
                if float(dt) > 1e-9:
                    v_des = _mul(dp, 1.0 / float(dt))
            self._prev_finger_world = chrono.ChVector3d(p_des.x, p_des.y, p_des.z) if p_des is not None else None

            v_grab = _point_velocity_world(body, p_grab)

            x_err = _sub(p_des, p_grab)
            v_err = _sub(v_des, v_grab)

            F = _add(_mul(x_err, self.SPRING_K), _mul(v_err, self.SPRING_C))

            fmag = _norm(F)
            if fmag > self.SPRING_F_MAX:
                F = _mul(_normalize(F), self.SPRING_F_MAX)

            _apply_force_at_point_world(body, F, p_grab)
            return

        v = _get_linvel_world(body)
        w = _get_angvel_world(body)

        _apply_force_world(body, _mul(v, -self.FREE_DAMP_CV))
        _apply_torque_world(body, _mul(w, -self.FREE_DAMP_CW))


# ============================================================
# Simulator
# ============================================================

class Simulator:
    # ---- (3-1.4) gear loss/backlash approximation defaults ----
    GEAR_PHASE_K = 8.0
    GEAR_SPEED_C = 1.2
    GEAR_MAX_TORQUE_DEFAULT = 2.0
    GEAR_MAX_TORQUE_CAP = 100.0
    GEAR_RATIO_REACTION_CAP = 4.0

    # ---- (3-3.4) diagnostics guardrails / prioritization ----
    DIAG_MAX_ITEMS = 5
    DIAG_MIN_PERSIST_STEPS = 2

    DIAG_PRIORITY: Dict[str, int] = {
        "TARGET_FIXED": 100,
        "AT_JOINT_LIMIT": 90,
        "LIKELY_BLOCKED_BY_CONSTRAINT": 80,
        "ACTUATOR_STALLED": 70,
        "HIGH_GEAR_LOSS": 50,
        "ALIGNMENT_IN_PROGRESS": 30,
        "RESTING_CONTACT": 20,
    }

    DIAG_DEFAULT_SEVERITY: Dict[str, str] = {
        "TARGET_FIXED": "warn",
        "AT_JOINT_LIMIT": "warn",
        "LIKELY_BLOCKED_BY_CONSTRAINT": "warn",
        "ACTUATOR_STALLED": "warn",
        "HIGH_GEAR_LOSS": "info",
        "ALIGNMENT_IN_PROGRESS": "info",
        "RESTING_CONTACT": "info",
    }

    def __init__(self, info: SimInfo):
        self.info: SimInfo = info

        # Metadata validation diagnostics
        try:
            self._metadata_diagnostics = validate_metadata(info.scene)
        except Exception as e:
            self._metadata_diagnostics = [
                rt.DiagnosticItem(
                    code="METADATA_VALIDATION_FAILED",
                    severity="warn",
                    message=f"메타데이터 사전 검증 중 오류가 발생했습니다: {e}",
                    target=None,
                )
            ]

        built = build_system_from_scene(info.scene, options=info.options)

        # ✅ NEW (2-3.4): build warnings 사용자 친화 요약/상세 출력
        try:
            warnings = list(getattr(built, "warnings", []) or [])
        except Exception:
            warnings = []

        try:
            dbg_limits = bool(getattr(info.options, "debug_joint_limits", False))
        except Exception:
            dbg_limits = False

        try:
            dbg_warn = bool(getattr(info.options, "debug_warnings", False))
        except Exception:
            dbg_warn = False

        # ✅ soft-limit 적용 토글(옵션명 호환)
        # 지원 이름:
        #  - joint_limits_soft_enable
        #  - enable_soft_joint_limits
        soft_enabled: Optional[bool] = None
        for key in ("joint_limits_soft_enable", "enable_soft_joint_limits"):
            try:
                val = getattr(info.options, key, None)
                if val is not None:
                    soft_enabled = bool(val)
                    break
            except Exception:
                continue

        if warnings:
            _print_build_warnings_user_friendly(
                warnings=warnings,
                debug_print_all=dbg_warn,
                debug_print_limits=dbg_limits,
                soft_limits_enabled=soft_enabled,
            )

        # ✅ (2) 테스트/디버그를 위한 공식 노출 핸들
        self.build_result = built
        self.name_to_body: Dict[str, chrono.ChBody] = dict(getattr(built, "name_to_body", {}) or {})
        self.name_to_link: Dict[str, chrono.ChLinkBase] = dict(getattr(built, "name_to_link", {}) or {})

        self.sys: Any = built.sys
        self.bodies = built.bodies
        self.joints = built.joints
        self.actuators = built.actuators

        self.sim_time: float = 0.0
        self._seq: int = 0

        if getattr(info, "body_order", None):
            self._body_order = list(info.body_order)  # type: ignore[attr-defined]
        else:
            try:
                self._body_order = [b.name for b in info.scene.bodies]
            except Exception:
                self._body_order = sorted(self.bodies.keys())

        self.part_index: Dict[str, int] = {n: i for i, n in enumerate(self._body_order)}

        self._ar = _ARInteractionController()
        self._released_drive_actuators: set[str] = set()

        # ✅ metadata의 explicit inertia를 chrono body에 캐시
        try:
            for bm in getattr(info.scene, "bodies", []):
                try:
                    name = getattr(bm, "name", None)
                    if not name or name not in self.bodies:
                        continue

                    mech = getattr(bm, "mechanical", None)
                    inert = getattr(mech, "inertia", None) if mech is not None else None
                    mode = getattr(inert, "mode", None) if inert is not None else None
                    if str(mode) != "explicit":
                        continue

                    Ixx = float(getattr(inert, "Ixx", 0.0))
                    Iyy = float(getattr(inert, "Iyy", 0.0))
                    Izz = float(getattr(inert, "Izz", 0.0))

                    b = self.bodies[name].body
                    try:
                        setattr(b, "_inertia_diag_local", chrono.ChVector3d(Ixx, Iyy, Izz))
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception:
            pass

        # ✅ (3-1.4) gear runtime state cache
        self._gear_states: Dict[str, _GearRuntimeState] = self._build_gear_runtime_states(built)
        self._last_gear_telemetry: Optional[Dict[str, rt.GearTelemetry]] = None
        self._assembly_states: Dict[str, _AssemblyRuntimeState] = self._build_assembly_runtime_states(built)
        self._last_assembly_telemetry: Optional[Dict[str, rt.AssemblyGuideTelemetry]] = None
        # ✅ (3-3.4) diagnostics persistence / dedupe state
        self._diag_seen_counts: Dict[str, int] = {}

        # ✅ Event feedback cooldown / dedupe state
        # key: "{eventType}:{target}"
        # value: last emitted sim_time
        self._event_feedback_last_emit_time: Dict[str, float] = {}

    @classmethod
    def create(cls, info: SimInfo) -> "Simulator":
        return cls(info)

    # -------------------------------
    # (3-1.4) Gear runtime helpers
    # -------------------------------

    def _build_gear_runtime_states(self, built: Any) -> Dict[str, _GearRuntimeState]:
        """
        sim_builder.py에서 전달된 gear 설정 정보를 우선 사용하고,
        없으면 scene metadata를 fallback으로 사용한다.
        """
        out: Dict[str, _GearRuntimeState] = {}

        # 1) sim_builder가 만들어둔 runtime map 우선 탐색
        candidates = []
        for attr in (
            "gear_runtime_infos",
            "gear_runtime_info",
            "gear_infos",
            "gear_info_map",
            "gear_props_by_name",
            "gear_settings",
        ):
            try:
                v = getattr(built, attr, None)
                if isinstance(v, dict) and v:
                    candidates.append(v)
            except Exception:
                pass

        for cand in candidates:
            for k, item in cand.items():
                try:
                    name = _str_attr_any(item, ["name"], str(k))
                    gearA = _str_attr_any(item, ["gearA", "bodyA", "a"], "")
                    gearB = _str_attr_any(item, ["gearB", "bodyB", "b"], "")
                    ratio = _float_attr_any(item, ["ratio", "transmission_ratio", "ratio_signed"], 0.0)

                    props_obj = None
                    if isinstance(item, dict):
                        props_obj = item.get("props", item.get("gearProps", item.get("settings", None)))
                    else:
                        props_obj = getattr(item, "props", None)
                        if props_obj is None:
                            props_obj = getattr(item, "gearProps", None)
                        if props_obj is None:
                            props_obj = getattr(item, "settings", None)

                    enabled = _bool_attr_any(props_obj, ["enabled"], True)
                    efficiency = _float_attr_any(props_obj, ["efficiency"], 1.0)
                    backlash = _float_attr_any(props_obj, ["backlash"], 0.0)
                    max_torque = _float_attr_any(props_obj, ["max_torque", "maxTorque"], self.GEAR_MAX_TORQUE_DEFAULT)

                    efficiency = _clamp(float(efficiency), 0.0, 1.0)
                    backlash = max(0.0, float(backlash))
                    max_torque = _clamp(float(max_torque), 0.0, float(self.GEAR_MAX_TORQUE_CAP))

                    if (not name) or (not gearA) or (not gearB):
                        continue
                    if abs(float(ratio)) < 1e-12:
                        ratio = _compute_signed_gear_ratio_from_scene(self.info.scene, next(
                            (gp for gp in getattr(self.info.scene, "gearPairs", []) if getattr(gp, "name", None) == name),
                            None,
                        ) or {})
                    if ratio is None or abs(float(ratio)) < 1e-12:
                        continue

                    out[name] = _GearRuntimeState(
                        name=str(name),
                        gearA=str(gearA),
                        gearB=str(gearB),
                        ratio=float(ratio),
                        enabled=bool(enabled),
                        efficiency=float(efficiency),
                        backlash=float(backlash),
                        max_torque=float(max_torque),
                    )
                except Exception:
                    continue

        if out:
            return out

        # 2) fallback: scene metadata만으로 구성
        try:
            for gp in getattr(self.info.scene, "gearPairs", []):
                try:
                    name = str(getattr(gp, "name", ""))
                    gearA = str(getattr(gp, "gearA", ""))
                    gearB = str(getattr(gp, "gearB", ""))
                    if not name or not gearA or not gearB:
                        continue

                    ratio = _compute_signed_gear_ratio_from_scene(self.info.scene, gp)
                    if ratio is None or abs(float(ratio)) < 1e-12:
                        continue

                    props = getattr(gp, "props", None)
                    if props is None:
                        props = getattr(gp, "gearProps", None)

                    enabled = _bool_attr_any(props, ["enabled"], True)
                    efficiency = _clamp(_float_attr_any(props, ["efficiency"], 1.0), 0.0, 1.0)
                    backlash = max(0.0, _float_attr_any(props, ["backlash"], 0.0))
                    max_torque = _clamp(
                        _float_attr_any(props, ["max_torque", "maxTorque"], self.GEAR_MAX_TORQUE_DEFAULT),
                        0.0,
                        float(self.GEAR_MAX_TORQUE_CAP),
                    )

                    out[name] = _GearRuntimeState(
                        name=name,
                        gearA=gearA,
                        gearB=gearB,
                        ratio=float(ratio),
                        enabled=bool(enabled),
                        efficiency=float(efficiency),
                        backlash=float(backlash),
                        max_torque=float(max_torque),
                    )
                except Exception:
                    continue
        except Exception:
            pass

        return out

    def _apply_gear_pair_approximations(self, *, dt: float) -> Optional[Dict[str, rt.GearTelemetry]]:
        """
        gear efficiency/backlash 근사를 per-step 토크로 적용.

        근사 모델:
        - phase_a / phase_b 를 축속도 적분으로 누적
        - ideal relation: phase_b = ratio * phase_a
        - backlash deadband 안에서는 correction 0
        - deadband 밖에서는 PD phase correction 생성
        - efficiency < 1 이면 transmitted torque를 줄이고, loss는 양쪽에 분산된 저항토크로 소산
        """
        if dt <= 1e-12:
            return None
        if not self._gear_states:
            return None

        out: Dict[str, rt.GearTelemetry] = {}

        for name, gs in self._gear_states.items():
            try:
                if not bool(gs.enabled):
                    out[name] = rt.GearTelemetry(
                        applied_efficiency=float(gs.efficiency),
                        loss_torque=0.0,
                        backlash_deadband=float(gs.backlash),
                    )
                    continue

                if gs.gearA not in self.bodies or gs.gearB not in self.bodies:
                    continue

                bodyA = self.bodies[gs.gearA].body
                bodyB = self.bodies[gs.gearB].body

                axisA = _normalize(self._infer_revolute_axis_world_for_body(gs.gearA))
                axisB = _normalize(self._infer_revolute_axis_world_for_body(gs.gearB))
                if _norm(axisA) < 1e-9:
                    axisA = chrono.ChVector3d(0.0, 0.0, 1.0)
                if _norm(axisB) < 1e-9:
                    axisB = chrono.ChVector3d(0.0, 0.0, 1.0)

                wA_vec = _get_angvel_world(bodyA)
                wB_vec = _get_angvel_world(bodyB)

                wA = float(_dot(wA_vec, axisA))
                wB = float(_dot(wB_vec, axisB))

                gs.phase_a += float(wA * dt)
                gs.phase_b += float(wB * dt)

                ratio = float(gs.ratio)
                rel_phase = float(gs.phase_b - ratio * gs.phase_a)
                rel_speed = float(wB - ratio * wA)

                deadband = max(0.0, float(gs.backlash))
                if abs(rel_phase) <= deadband:
                    phase_err = 0.0
                else:
                    phase_err = m.copysign(abs(rel_phase) - deadband, rel_phase)

                tau_raw = -(float(self.GEAR_PHASE_K) * float(phase_err) + float(self.GEAR_SPEED_C) * float(rel_speed))
                tau_raw = _clamp(float(tau_raw), -float(gs.max_torque), float(gs.max_torque))

                eff = _clamp(float(gs.efficiency), 0.0, 1.0)
                tau_transmitted = float(tau_raw * eff)
                tau_loss = float(tau_raw - tau_transmitted)

                # B에 전달되는 토크
                if (not _is_fixed_body(bodyB)) and abs(tau_transmitted) > 1e-12:
                    _apply_torque_world(bodyB, _mul(axisB, float(tau_transmitted)))

                # A에는 반작용 토크
                ratio_reaction = _clamp(abs(float(ratio)), 1.0, float(self.GEAR_RATIO_REACTION_CAP))
                tau_a_mag = _clamp(abs(float(tau_transmitted)) * float(ratio_reaction), 0.0, float(gs.max_torque))
                if (not _is_fixed_body(bodyA)) and tau_a_mag > 1e-12:
                    _apply_torque_world(bodyA, _mul(axisA, -m.copysign(tau_a_mag, tau_transmitted)))

                # 효율 손실은 양쪽 회전을 감쇠시키는 저항토크로 분산
                tau_loss_each = 0.5 * abs(float(tau_loss))
                if tau_loss_each > 1e-12:
                    if (not _is_fixed_body(bodyA)) and abs(wA) > 1e-9:
                        _apply_torque_world(bodyA, _mul(axisA, -m.copysign(tau_loss_each, wA)))
                    if (not _is_fixed_body(bodyB)) and abs(wB) > 1e-9:
                        _apply_torque_world(bodyB, _mul(axisB, -m.copysign(tau_loss_each, wB)))

                out[name] = rt.GearTelemetry(
                    applied_efficiency=float(eff),
                    loss_torque=float(abs(tau_loss)),
                    backlash_deadband=float(deadband),
                )
            except Exception:
                continue

        return out or None

    def _build_assembly_runtime_states(self, built: Any) -> Dict[str, _AssemblyRuntimeState]:
        out: Dict[str, _AssemblyRuntimeState] = {}

        raw_map = getattr(built, "assembly_guides", None)
        if isinstance(raw_map, dict) and raw_map:
            for name, item in raw_map.items():
                try:
                    gname = str(getattr(item, "name", name))

                    moving_body = str(
                        getattr(item, "moving_body", None)
                        or getattr(item, "movingBody", None)
                        or getattr(item, "partA", None)
                        or ""
                    )
                    target_body = str(
                        getattr(item, "target_body", None)
                        or getattr(item, "targetBody", None)
                        or getattr(item, "partB", None)
                        or ""
                    )

                    moving_local_pos = _safe_body_local_point_from_any(
                        getattr(item, "moving_local_pos", None)
                        or getattr(item, "movingLocalPos", None)
                        or getattr(item, "movingLocalPose", None)
                    )
                    target_local_pos = _safe_body_local_point_from_any(
                        getattr(item, "target_local_pos", None)
                        or getattr(item, "targetLocalPos", None)
                        or getattr(item, "targetLocalPose", None)
                    )

                    align_axis = str(getattr(item, "align_axis", None) or getattr(item, "alignAxis", "any"))
                    mode = str(getattr(item, "mode", "assist"))
                    enabled = bool(getattr(item, "enabled", True))
                    position_tolerance = max(0.0, float(getattr(item, "positionTolerance", 0.02)))
                    angle_tolerance = max(0.0, float(getattr(item, "angleTolerance", 0.2617993877991494)))
                    snap_strength = max(0.0, float(getattr(item, "snapStrength", 1.0)))

                    if not gname or not moving_body or not target_body:
                        continue

                    out[gname] = _AssemblyRuntimeState(
                        name=gname,
                        moving_body=moving_body,
                        target_body=target_body,
                        moving_local_pos=moving_local_pos,
                        target_local_pos=target_local_pos,
                        align_axis=align_axis,
                        mode=mode,
                        enabled=enabled,
                        position_tolerance=position_tolerance,
                        angle_tolerance=angle_tolerance,
                        snap_strength=snap_strength,
                    )
                except Exception:
                    continue

        if out:
            return out

        try:
            for g in getattr(self.info.scene, "assemblyGuides", []) or []:
                try:
                    gname = str(getattr(g, "name", ""))
                    moving_body = str(getattr(g, "movingBody", ""))
                    target_body = str(getattr(g, "targetBody", ""))

                    moving_pose = getattr(g, "movingLocalPose", None)
                    target_pose = getattr(g, "targetLocalPose", None)

                    moving_local_pos = chrono.ChVector3d(0.0, 0.0, 0.0)
                    target_local_pos = chrono.ChVector3d(0.0, 0.0, 0.0)

                    try:
                        if moving_pose is not None and hasattr(moving_pose, "pos"):
                            moving_local_pos = chrono.ChVector3d(
                                float(moving_pose.pos.x),
                                float(moving_pose.pos.y),
                                float(moving_pose.pos.z),
                            )
                    except Exception:
                        pass

                    try:
                        if target_pose is not None and hasattr(target_pose, "pos"):
                            target_local_pos = chrono.ChVector3d(
                                float(target_pose.pos.x),
                                float(target_pose.pos.y),
                                float(target_pose.pos.z),
                            )
                    except Exception:
                        pass

                    if not gname or not moving_body or not target_body:
                        continue

                    out[gname] = _AssemblyRuntimeState(
                        name=gname,
                        moving_body=moving_body,
                        target_body=target_body,
                        moving_local_pos=moving_local_pos,
                        target_local_pos=target_local_pos,
                        align_axis=str(getattr(g, "alignAxis", "any")),
                        mode=str(getattr(g, "mode", "assist")),
                        enabled=bool(getattr(g, "enabled", True)),
                        position_tolerance=max(0.0, float(getattr(g, "positionTolerance", 0.02))),
                        angle_tolerance=max(0.0, float(getattr(g, "angleTolerance", 0.2617993877991494))),
                        snap_strength=max(0.0, float(getattr(g, "snapStrength", 1.0))),
                    )
                except Exception:
                    continue
        except Exception:
            pass

        return out


    def _assembly_axis_world(self, body: chrono.ChBody, axis_name: str) -> chrono.ChVector3d:
        axis = str(axis_name or "any").lower()
        q = body.GetRot()

        if axis == "x":
            return _normalize(_quat_rotate(q, chrono.ChVector3d(1.0, 0.0, 0.0)))
        if axis == "y":
            return _normalize(_quat_rotate(q, chrono.ChVector3d(0.0, 1.0, 0.0)))
        if axis == "z":
            return _normalize(_quat_rotate(q, chrono.ChVector3d(0.0, 0.0, 1.0)))
        return chrono.ChVector3d(0.0, 0.0, 0.0)


    def _assembly_angle_error(self, moving_body: chrono.ChBody, target_body: chrono.ChBody, axis_name: str) -> float:
        axis = str(axis_name or "any").lower()
        if axis == "any":
            return _quat_angle_error(moving_body.GetRot(), target_body.GetRot())

        am = self._assembly_axis_world(moving_body, axis)
        at = self._assembly_axis_world(target_body, axis)

        if _norm(am) < 1e-9 or _norm(at) < 1e-9:
            return 0.0

        d = _clamp(_dot(am, at), -1.0, 1.0)
        return float(m.acos(d))


    def _apply_assembly_guides(self, *, dt: float) -> Optional[Dict[str, rt.AssemblyGuideTelemetry]]:
        if dt <= 1e-12:
            return None
        if not self._assembly_states:
            return None

        touched_name = None
        try:
            touched_name = self._ar.ctx.target_name
        except Exception:
            touched_name = None

        if not touched_name:
            return None

        out: Dict[str, rt.AssemblyGuideTelemetry] = {}

        best_name: Optional[str] = None
        best_err_pos = 1e18
        best_err_ang = 1e18

        candidates: List[tuple[_AssemblyRuntimeState, chrono.ChBody, chrono.ChBody, float, float]] = []

        for gs in self._assembly_states.values():
            try:
                if not gs.enabled:
                    continue
                if gs.moving_body != touched_name:
                    continue
                if gs.moving_body not in self.bodies or gs.target_body not in self.bodies:
                    continue

                moving_body = self.bodies[gs.moving_body].body
                target_body = self.bodies[gs.target_body].body

                p_move = _world_point_from_local(moving_body, gs.moving_local_pos)
                p_tgt = _world_point_from_local(target_body, gs.target_local_pos)

                err_vec = _sub(p_tgt, p_move)
                err_pos = _norm(err_vec)
                err_ang = self._assembly_angle_error(moving_body, target_body, gs.align_axis)

                gs.last_candidate = gs.target_body
                gs.last_error_pos = float(err_pos)
                gs.last_error_angle = float(err_ang)
                gs.last_active = False

                candidates.append((gs, moving_body, target_body, float(err_pos), float(err_ang)))

                if (err_pos < best_err_pos) or (abs(err_pos - best_err_pos) < 1e-9 and err_ang < best_err_ang):
                    best_name = gs.name
                    best_err_pos = float(err_pos)
                    best_err_ang = float(err_ang)
            except Exception:
                continue

        if not candidates:
            return None

        for gs, moving_body, target_body, err_pos, err_ang in candidates:
            active = (gs.name == best_name)
            gs.last_active = active

            if active:
                p_move = _world_point_from_local(moving_body, gs.moving_local_pos)
                p_tgt = _world_point_from_local(target_body, gs.target_local_pos)
                err_vec = _sub(p_tgt, p_move)

                pos_ok = err_pos <= float(gs.position_tolerance)
                ang_ok = err_ang <= float(gs.angle_tolerance)

                # 1) position assist
                if pos_ok and (not _is_fixed_body(moving_body)):
                    k_pos = 120.0 * float(gs.snap_strength)
                    c_pos = 12.0 * float(gs.snap_strength)

                    v_move = _point_velocity_world(moving_body, p_move)
                    v_tgt = _point_velocity_world(target_body, p_tgt)
                    v_err = _sub(v_tgt, v_move)

                    F = _add(_mul(err_vec, k_pos), _mul(v_err, c_pos))

                    fmax = max(10.0, 250.0 * float(gs.snap_strength))
                    fmag = _norm(F)
                    if fmag > fmax:
                        F = _mul(_normalize(F), fmax)

                    _apply_force_at_point_world(moving_body, F, p_move)

                # 2) rotation assist
                if ang_ok and (not _is_fixed_body(moving_body)):
                    axis_mode = str(gs.align_axis or "any").lower()
                    tau_max = max(0.2, 8.0 * float(gs.snap_strength))
                    c_rot = 1.5 * float(gs.snap_strength)

                    if axis_mode in ("x", "y", "z"):
                        a_move = self._assembly_axis_world(moving_body, axis_mode)
                        a_tgt = self._assembly_axis_world(target_body, axis_mode)

                        if _norm(a_move) > 1e-9 and _norm(a_tgt) > 1e-9:
                            axis_err = _cross(a_move, a_tgt)
                            if _norm(axis_err) > 1e-9:
                                axis_err_n = _normalize(axis_err)
                                w_world = _get_angvel_world(moving_body)
                                w_along = _dot(w_world, axis_err_n)

                                tau_mag = min(float(err_ang) * 6.0 * float(gs.snap_strength), tau_max)
                                tau = _mul(axis_err_n, tau_mag)
                                tau = _add(tau, _mul(axis_err_n, -c_rot * float(w_along)))

                                if _norm(tau) > tau_max:
                                    tau = _mul(_normalize(tau), tau_max)

                                _apply_torque_world(moving_body, tau)
                    else:
                        q_m = moving_body.GetRot()
                        q_t = target_body.GetRot()

                        vmx = _quat_rotate(q_m, chrono.ChVector3d(1.0, 0.0, 0.0))
                        vtx = _quat_rotate(q_t, chrono.ChVector3d(1.0, 0.0, 0.0))
                        axis_err = _cross(vmx, vtx)

                        if _norm(axis_err) < 1e-9:
                            vmy = _quat_rotate(q_m, chrono.ChVector3d(0.0, 1.0, 0.0))
                            vty = _quat_rotate(q_t, chrono.ChVector3d(0.0, 1.0, 0.0))
                            axis_err = _cross(vmy, vty)

                        if _norm(axis_err) > 1e-9:
                            axis_err_n = _normalize(axis_err)
                            w_world = _get_angvel_world(moving_body)
                            w_along = _dot(w_world, axis_err_n)

                            tau_mag = min(float(err_ang) * 6.0 * float(gs.snap_strength), tau_max)
                            tau = _mul(axis_err_n, tau_mag)
                            tau = _add(tau, _mul(axis_err_n, -c_rot * float(w_along)))

                            if _norm(tau) > tau_max:
                                tau = _mul(_normalize(tau), tau_max)

                            _apply_torque_world(moving_body, tau)

            out[gs.name] = rt.AssemblyGuideTelemetry(
                activeSnap=bool(active),
                snapCandidate=str(gs.last_candidate) if gs.last_candidate is not None else None,
                snapErrorPos=float(gs.last_error_pos),
                snapErrorAngle=float(gs.last_error_angle),
                snapMode=str(gs.mode),
            )

        return out or None

    def _vec3_from_any(self, v: Any) -> Optional[rt.Vec3]:
        xyz = self._vec_components_any(v)
        if xyz is None:
            return None
        x, y, z = xyz
        return rt.Vec3(float(x), float(y), float(z))

    def _compute_joint_telemetry(self) -> Optional[Dict[str, rt.JointTelemetry]]:
        out: Dict[str, rt.JointTelemetry] = {}

        for jname, built_joint in self.joints.items():
            try:
                jm = built_joint.meta
                link = built_joint.link
                jtype = str(getattr(jm, "type", "") or "")

                angle: Optional[float] = None
                position: Optional[float] = None
                angular_velocity: Optional[float] = None
                linear_velocity: Optional[float] = None
                reaction_force_vec: Optional[rt.Vec3] = None
                reaction_torque_vec: Optional[rt.Vec3] = None
                estimated_power: Optional[float] = None

                body2_name = getattr(jm, "body2", None)
                body2 = None
                if body2_name in self.bodies:
                    body2 = self.bodies[body2_name].body

                # -------------------------
                # revolute joint telemetry
                # -------------------------
                if jtype == "revolute":
                    for fn in ("GetRelAngle", "GetRelativeAngle", "GetMotorRot"):
                        try:
                            if hasattr(link, fn):
                                angle = float(getattr(link, fn)())
                                break
                        except Exception:
                            pass

                    if body2 is not None:
                        try:
                            axis_world = _normalize(self._infer_revolute_axis_world_for_body(str(body2_name)))
                            w_world = _get_angvel_world(body2)
                            angular_velocity = float(_dot(w_world, axis_world))
                        except Exception:
                            pass

                # -------------------------
                # prismatic joint telemetry
                # -------------------------
                elif jtype == "prismatic":
                    for fn in ("GetRelDistance", "GetRelativeDistance", "GetDistance"):
                        try:
                            if hasattr(link, fn):
                                position = float(getattr(link, fn)())
                                break
                        except Exception:
                            pass

                    if body2 is not None:
                        try:
                            v_world = _get_linvel_world(body2)
                            linear_velocity = float(_norm(v_world))
                        except Exception:
                            pass

                # -------------------------
                # reaction force / torque
                # -------------------------
                react_force_raw = None
                react_torque_raw = None

                for fn in ("Get_react_force", "GetReactionForce", "GetReactForce"):
                    try:
                        if hasattr(link, fn):
                            react_force_raw = getattr(link, fn)()
                            break
                    except Exception:
                        pass

                for fn in ("Get_react_torque", "GetReactionTorque", "GetReactTorque"):
                    try:
                        if hasattr(link, fn):
                            react_torque_raw = getattr(link, fn)()
                            break
                    except Exception:
                        pass

                reaction_force_vec = self._vec3_from_any(react_force_raw)
                reaction_torque_vec = self._vec3_from_any(react_torque_raw)

                # -------------------------
                # estimated power
                # revolute: torque * angular_velocity
                # prismatic: force * linear_velocity
                # -------------------------
                if (jtype == "revolute") and (reaction_torque_vec is not None) and (angular_velocity is not None):
                    torque_mag = m.sqrt(
                        reaction_torque_vec.x * reaction_torque_vec.x
                        + reaction_torque_vec.y * reaction_torque_vec.y
                        + reaction_torque_vec.z * reaction_torque_vec.z
                    )
                    estimated_power = float(torque_mag * angular_velocity)

                elif (jtype == "prismatic") and (reaction_force_vec is not None) and (linear_velocity is not None):
                    force_mag = m.sqrt(
                        reaction_force_vec.x * reaction_force_vec.x
                        + reaction_force_vec.y * reaction_force_vec.y
                        + reaction_force_vec.z * reaction_force_vec.z
                    )
                    estimated_power = float(force_mag * linear_velocity)

                out[str(jname)] = rt.JointTelemetry(
                    jointType=jtype if jtype else None,
                    angle=angle,
                    position=position,
                    angularVelocity=angular_velocity,
                    linearVelocity=linear_velocity,
                    reactionForce=reaction_force_vec,
                    reactionTorque=reaction_torque_vec,
                    estimatedPower=estimated_power,
                )

            except Exception:
                continue

        return out or None

    def _compute_actuator_telemetry(self) -> Optional[Dict[str, rt.ActuatorTelemetry]]:
        out: Dict[str, rt.ActuatorTelemetry] = {}

        for aname, built_act in self.actuators.items():
            try:
                meta = built_act.meta
                link = built_act.link
                atype = str(getattr(meta, "type", "") or "")
                target_joint = getattr(meta, "targetJoint", None)

                commanded_speed: Optional[float] = None
                commanded_torque: Optional[float] = None
                applied_torque: Optional[float] = None
                estimated_power: Optional[float] = None

                # -------------------------
                # commanded values from metadata
                # -------------------------
                try:
                    if atype == "rotation_speed":
                        commanded_speed = float(getattr(meta, "speed", None))
                except Exception:
                    pass

                try:
                    if atype == "rotation_torque":
                        torque_model = getattr(meta, "torqueModel", None)
                        if torque_model is not None:
                            tm_type = getattr(torque_model, "type", None)
                            tm_val = getattr(torque_model, "value", None)
                            if str(tm_type) == "const" and tm_val is not None:
                                commanded_torque = float(tm_val)
                except Exception:
                    pass

                # -------------------------
                # best-effort getter from actuator link
                # -------------------------
                if commanded_speed is None:
                    for fn in ("GetMotorSpeed", "GetSpeed", "GetMotorRot_dt"):
                        try:
                            if hasattr(link, fn):
                                commanded_speed = float(getattr(link, fn)())
                                break
                        except Exception:
                            pass

                if commanded_torque is None:
                    for fn in ("GetMotorTorque", "GetTorque", "GetMotorTorqueReactionOnBody"):
                        try:
                            if hasattr(link, fn):
                                val = getattr(link, fn)()
                                if isinstance(val, (int, float)):
                                    commanded_torque = float(val)
                                    break
                        except Exception:
                            pass

                # appliedTorque는 지금 단계에서는 best-effort 근사
                if commanded_torque is not None:
                    applied_torque = float(commanded_torque)
                else:
                    for fn in ("GetMotorTorque", "GetTorque", "GetMotorTorqueReactionOnBody"):
                        try:
                            if hasattr(link, fn):
                                val = getattr(link, fn)()
                                if isinstance(val, (int, float)):
                                    applied_torque = float(val)
                                    break
                        except Exception:
                            pass

                # -------------------------
                # estimated power
                # -------------------------
                if (applied_torque is not None) and (commanded_speed is not None):
                    estimated_power = float(applied_torque * commanded_speed)

                out[str(aname)] = rt.ActuatorTelemetry(
                    actuatorType=atype if atype else None,
                    targetJoint=str(target_joint) if target_joint is not None else None,
                    commandedSpeed=commanded_speed,
                    commandedTorque=commanded_torque,
                    appliedTorque=applied_torque,
                    estimatedPower=estimated_power,
                )

            except Exception:
                continue

        return out or None

    def _build_diagnostics(
        self,
        *,
        telemetry: Optional[rt.ContactTelemetry],
        gear_telemetry: Optional[Dict[str, rt.GearTelemetry]],
        assembly_telemetry: Optional[Dict[str, rt.AssemblyGuideTelemetry]],
        joint_telemetry: Optional[Dict[str, rt.JointTelemetry]],
        actuator_telemetry: Optional[Dict[str, rt.ActuatorTelemetry]],
    ) -> Optional[List[rt.DiagnosticItem]]:
        out: List[rt.DiagnosticItem] = []

        # -------------------------------------------------
        # 1) actuator stalled
        #  - commanded torque는 있는데 joint angular velocity가 거의 없음
        # -------------------------------------------------
        if actuator_telemetry:
            for aname, at in actuator_telemetry.items():
                try:
                    tgt = at.targetJoint
                    if not tgt or not joint_telemetry or tgt not in joint_telemetry:
                        continue

                    jt = joint_telemetry[tgt]

                    cmd_tau = at.commandedTorque
                    applied_tau = at.appliedTorque
                    ang_vel = jt.angularVelocity
                    lin_vel = jt.linearVelocity

                    torque_like = None
                    if applied_tau is not None:
                        torque_like = abs(float(applied_tau))
                    elif cmd_tau is not None:
                        torque_like = abs(float(cmd_tau))

                    speed_like = None
                    if ang_vel is not None:
                        speed_like = abs(float(ang_vel))
                    elif lin_vel is not None:
                        speed_like = abs(float(lin_vel))

                    if (torque_like is not None) and (torque_like > 1e-3) and (speed_like is not None) and (speed_like < 1e-3):
                        out.append(
                            rt.DiagnosticItem(
                                code="ACTUATOR_STALLED",
                                severity="warn",
                                message=f"Actuator '{aname}' is commanding effort, but joint '{tgt}' is barely moving.",
                                target=str(aname),
                            )
                        )
                except Exception:
                    continue

        # -------------------------------------------------
        # 2) likely blocked by constraint
        #  - reaction force/torque 크고 속도 거의 없음
        # -------------------------------------------------
        if joint_telemetry:
            for jname, jt in joint_telemetry.items():
                try:
                    speed_like = None
                    if jt.angularVelocity is not None:
                        speed_like = abs(float(jt.angularVelocity))
                    elif jt.linearVelocity is not None:
                        speed_like = abs(float(jt.linearVelocity))

                    react_force_mag = 0.0
                    if jt.reactionForce is not None:
                        react_force_mag = m.sqrt(
                            jt.reactionForce.x * jt.reactionForce.x
                            + jt.reactionForce.y * jt.reactionForce.y
                            + jt.reactionForce.z * jt.reactionForce.z
                        )

                    react_torque_mag = 0.0
                    if jt.reactionTorque is not None:
                        react_torque_mag = m.sqrt(
                            jt.reactionTorque.x * jt.reactionTorque.x
                            + jt.reactionTorque.y * jt.reactionTorque.y
                            + jt.reactionTorque.z * jt.reactionTorque.z
                        )

                    blocked_force = react_force_mag > 10.0
                    blocked_torque = react_torque_mag > 0.5
                    slow = (speed_like is not None) and (speed_like < 1e-3)

                    if slow and (blocked_force or blocked_torque):
                        out.append(
                            rt.DiagnosticItem(
                                code="LIKELY_BLOCKED_BY_CONSTRAINT",
                                severity="warn",
                                message=f"Joint '{jname}' has high reaction load but very small motion.",
                                target=str(jname),
                            )
                        )
                except Exception:
                    continue

        # -------------------------------------------------
        # 2.5) at joint limit
        #  - limit 근처에서 거의 정지
        # -------------------------------------------------
        if joint_telemetry:
            for jname, jt in joint_telemetry.items():
                try:
                    if jname not in self.joints:
                        continue

                    jm = self.joints[jname].meta
                    limits = getattr(jm, "limits", None)
                    if limits is None:
                        continue

                    lower = getattr(limits, "lower", None)
                    upper = getattr(limits, "upper", None)

                    value = None
                    speed_like = None

                    if jt.angle is not None:
                        value = float(jt.angle)
                        if jt.angularVelocity is not None:
                            speed_like = abs(float(jt.angularVelocity))
                    elif jt.position is not None:
                        value = float(jt.position)
                        if jt.linearVelocity is not None:
                            speed_like = abs(float(jt.linearVelocity))

                    if value is None or speed_like is None:
                        continue

                    near_limit = False

                    if lower is not None and abs(value - float(lower)) < 1e-3:
                        near_limit = True
                    if upper is not None and abs(value - float(upper)) < 1e-3:
                        near_limit = True

                    if near_limit and speed_like < 1e-3:
                        out.append(
                            rt.DiagnosticItem(
                                code="AT_JOINT_LIMIT",
                                severity="warn",
                                message=f"Joint '{jname}' is near its motion limit.",
                                target=str(jname),
                            )
                        )
                except Exception:
                    continue

        # -------------------------------------------------
        # 3) high gear loss
        # -------------------------------------------------
        if gear_telemetry:
            for gname, gt in gear_telemetry.items():
                try:
                    if (gt.applied_efficiency is not None) and (float(gt.applied_efficiency) < 0.6):
                        out.append(
                            rt.DiagnosticItem(
                                code="HIGH_GEAR_LOSS",
                                severity="info",
                                message=f"Gear pair '{gname}' is operating with low efficiency.",
                                target=str(gname),
                            )
                        )
                except Exception:
                    continue

        # -------------------------------------------------
        # 4) alignment in progress
        # -------------------------------------------------
        if assembly_telemetry:
            for gname, ag in assembly_telemetry.items():
                try:
                    if bool(ag.activeSnap) and (
                        (float(ag.snapErrorPos) > 1e-4) or (float(ag.snapErrorAngle) > 1e-3)
                    ):
                        out.append(
                            rt.DiagnosticItem(
                                code="ALIGNMENT_IN_PROGRESS",
                                severity="info",
                                message=f"Assembly guide '{gname}' is active and still aligning toward target.",
                                target=str(gname),
                            )
                        )
                except Exception:
                    continue

        # -------------------------------------------------
        # 5) resting contact
        #  - contact 많고, 전체적으로 거의 정지 상태
        # -------------------------------------------------
        if telemetry is not None and telemetry.contact_count > 0:
            try:
                all_speeds: List[float] = []
                if joint_telemetry:
                    for _, jt in joint_telemetry.items():
                        if jt.angularVelocity is not None:
                            all_speeds.append(abs(float(jt.angularVelocity)))
                        if jt.linearVelocity is not None:
                            all_speeds.append(abs(float(jt.linearVelocity)))

                if all_speeds and max(all_speeds) < 1e-3:
                    out.append(
                        rt.DiagnosticItem(
                            code="RESTING_CONTACT",
                            severity="info",
                            message="Bodies are in contact and motion is nearly zero.",
                            target=None,
                        )
                    )
            except Exception:
                pass

        # -------------------------------------------------
        # 6) target fixed
        #  - actuator target joint의 body2가 fixed면 표시
        # -------------------------------------------------
        if actuator_telemetry:
            for aname, at in actuator_telemetry.items():
                try:
                    tgt = at.targetJoint
                    if not tgt:
                        continue
                    if tgt not in self.joints:
                        continue

                    jm = self.joints[tgt].meta
                    body2_name = getattr(jm, "body2", None)
                    if body2_name not in self.bodies:
                        continue

                    body2 = self.bodies[body2_name].body
                    if _is_fixed_body(body2):
                        out.append(
                            rt.DiagnosticItem(
                                code="TARGET_FIXED",
                                severity="warn",
                                message=f"Actuator '{aname}' targets joint '{tgt}', but the driven body is fixed.",
                                target=str(aname),
                            )
                        )
                except Exception:
                    continue

        return out or None

    def _normalize_diagnostics(
        self,
        diagnostics: Optional[List[rt.DiagnosticItem]],
    ) -> Optional[List[rt.DiagnosticItem]]:
        if not diagnostics:
            return None

        out: List[rt.DiagnosticItem] = []

        for item in diagnostics:
            try:
                code = str(item.code)
                sev = str(item.severity or "").strip().lower()
                if sev not in ("info", "warn", "error"):
                    sev = self.DIAG_DEFAULT_SEVERITY.get(code, "info")

                out.append(
                    rt.DiagnosticItem(
                        code=code,
                        severity=sev,
                        message=str(item.message or ""),
                        target=str(item.target) if item.target is not None else None,
                    )
                )
            except Exception:
                continue

        return out or None

    def _dedupe_and_suppress_diagnostics(
        self,
        diagnostics: Optional[List[rt.DiagnosticItem]],
    ) -> Optional[List[rt.DiagnosticItem]]:
        if not diagnostics:
            return None

        unique: Dict[tuple[str, Optional[str]], rt.DiagnosticItem] = {}
        for item in diagnostics:
            key = (str(item.code), str(item.target) if item.target is not None else None)
            if key not in unique:
                unique[key] = item

        items = list(unique.values())

        codes_present = {str(x.code) for x in items}

        # TARGET_FIXED가 있으면 다른 "안 움직임" 계열 일부 제거
        if "TARGET_FIXED" in codes_present:
            fixed_targets = {
                str(item.target)
                for item in items
                if item.code == "TARGET_FIXED" and item.target is not None
            }

            filtered: List[rt.DiagnosticItem] = []
            for item in items:
                if item.code == "ACTUATOR_STALLED" and item.target is not None and str(item.target) in fixed_targets:
                    continue
                filtered.append(item)
            items = filtered
            codes_present = {str(x.code) for x in items}

        # AT_JOINT_LIMIT가 있으면 ACTUATOR_STALLED는 원인 중복이라 제거
        if "AT_JOINT_LIMIT" in codes_present:
            filtered = []
            for item in items:
                if item.code == "ACTUATOR_STALLED":
                    continue
                filtered.append(item)
            items = filtered

        return items or None

    def _finalize_diagnostics(
        self,
        diagnostics: Optional[List[rt.DiagnosticItem]],
    ) -> Optional[List[rt.DiagnosticItem]]:
        if not diagnostics:
            self._diag_seen_counts = {}
            return None

        next_seen: Dict[str, int] = {}

        for item in diagnostics:
            key = f"{item.code}::{item.target if item.target is not None else ''}"
            prev = int(self._diag_seen_counts.get(key, 0))
            next_seen[key] = prev + 1

        self._diag_seen_counts = next_seen

        persisted: List[rt.DiagnosticItem] = []
        for item in diagnostics:
            key = f"{item.code}::{item.target if item.target is not None else ''}"
            seen = int(self._diag_seen_counts.get(key, 0))

            if item.severity == "info" and seen < int(self.DIAG_MIN_PERSIST_STEPS):
                continue

            persisted.append(item)

        severity_rank = {"error": 0, "warn": 1, "info": 2}

        persisted.sort(
            key=lambda x: (
                severity_rank.get(str(x.severity), 9),
                -int(self.DIAG_PRIORITY.get(str(x.code), 0)),
                str(x.code),
                str(x.target) if x.target is not None else "",
            )
        )

        return persisted[: int(self.DIAG_MAX_ITEMS)] or None

    # -------------------------------
    # (1-3) Contact telemetry helpers
    # -------------------------------

    @staticmethod
    def _vec_components_any(v: Any) -> Optional[tuple[float, float, float]]:
        """
        ChVector3d 계열을 다양한 바인딩에서 안전하게 (x,y,z)로 추출.
        - .x/.y/.z 속성
        - .x()/.y()/.z() 메서드
        """
        if v is None:
            return None

        # case 1) attribute-style
        try:
            if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z"):
                x = getattr(v, "x")
                y = getattr(v, "y")
                z = getattr(v, "z")
                # x가 숫자일 수도 있고, callable일 수도 있음
                if callable(x):
                    return (float(x()), float(y()), float(z()))
                return (float(x), float(y), float(z))
        except Exception:
            pass

        # case 2) method-style explicit
        try:
            if hasattr(v, "x") and callable(getattr(v, "x")):
                return (float(v.x()), float(v.y()), float(v.z()))
        except Exception:
            pass

        return None

    @classmethod
    def _vec_norm_any(cls, v: Any) -> float:
        xyz = cls._vec_components_any(v)
        if xyz is None:
            return 0.0
        x, y, z = xyz
        return float(m.sqrt(x * x + y * y + z * z))

    @staticmethod
    def _try_get_body_name_from_contactable(obj: Any) -> Optional[str]:
        """
        contact callback에서 넘어오는 'contactable'/'physics item' 객체에서
        가능한 한 body name을 뽑아낸다. 바인딩 차이가 커서 최대한 방어적으로 처리.
        """
        if obj is None:
            return None

        # 1) 바로 GetName
        try:
            if hasattr(obj, "GetName"):
                nm = obj.GetName()
                if nm:
                    return str(nm)
        except Exception:
            pass

        # 2) GetPhysicsItem() -> GetName()
        try:
            if hasattr(obj, "GetPhysicsItem"):
                it = obj.GetPhysicsItem()
                if it is not None and hasattr(it, "GetName"):
                    nm = it.GetName()
                    if nm:
                        return str(nm)
        except Exception:
            pass

        # 3) GetBody() -> GetName()
        try:
            if hasattr(obj, "GetBody"):
                b = obj.GetBody()
                if b is not None and hasattr(b, "GetName"):
                    nm = b.GetName()
                    if nm:
                        return str(nm)
        except Exception:
            pass

        return None

    def _try_report_all_contacts(self, container: Any, *, max_points: int) -> Optional[rt.ContactTelemetry]:
        """
        ReportAllContacts(callback)를 통해 contact telemetry를 얻는다.

        핵심:
        - contact_count는 reporter가 실제 순회한 contact 수
        - max_contact_force는 react_forces 우선, 실패 시 force-like 벡터 후보 fallback
        - max_pair는 contact object/contactable에서 가능한 한 body name 추출
        """
        if container is None or (not hasattr(container, "ReportAllContacts")):
            return None

        try:
            max_points_i = int(max_points)
        except Exception:
            max_points_i = 0

        if max_points_i <= 0:
            return None

        try:
            base_cb = getattr(chrono, "ReportContactCallback", None)
            if base_cb is None:
                return None

            class _Reporter(base_cb):  # type: ignore[misc]
                def __init__(self, outer: "Simulator", cap: int):
                    super().__init__()
                    self.outer = outer
                    self.cap = int(cap)
                    self.count = 0
                    self.max_force = 0.0
                    self.min_distance: Optional[float] = None
                    self.max_penetration = 0.0
                    self.max_a: Optional[str] = None
                    self.max_b: Optional[str] = None

                    # 🔥 디버그 출력 1회만 수행
                    self.debug_printed = False

                def _force_mag_from_args(self, args: tuple[Any, ...]) -> float:
                    """
                    PyChrono 바인딩별 ReportAllContacts 인자 차이를 흡수한다.

                    흔한 Chrono 시그니처:
                    pA, pB, plane_coord, distance, eff_radius,
                    react_forces, react_torques, contactobjA, contactobjB

                    하지만 바인딩에 따라 react_forces 위치/타입이 다를 수 있으므로
                    1) args[5] 우선
                    2) 이름/메서드 기반 force 후보
                    3) 벡터 후보 중 앞쪽 contact point를 제외하고 가장 큰 값
                    순서로 본다.
                    """
                    # 1) 표준 위치 우선: react_forces
                    try:
                        if len(args) >= 6:
                            mag = self.outer._vec_norm_any(args[5])
                            if mag > 0.0:
                                return float(mag)
                    except Exception:
                        pass

                    # 2) 객체 메서드 기반 후보
                    for a in args:
                        for fn_name in (
                            "GetContactForce",
                            "GetForce",
                            "GetReactionForce",
                            "GetNormalForce",
                            "GetContactForceAbs",
                        ):
                            try:
                                fn = getattr(a, fn_name, None)
                                if callable(fn):
                                    val = fn()
                                    mag = self.outer._vec_norm_any(val)
                                    if mag > 0.0:
                                        return float(mag)
                                    try:
                                        f = float(val)
                                        if abs(f) > 0.0:
                                            return abs(f)
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                    # 3) 벡터 후보 fallback
                    # args[0], args[1]은 보통 contact point라서 제외하는 편이 안전하다.
                    best_mag = 0.0
                    for idx, a in enumerate(args):
                        if idx in (0, 1, 2):
                            continue

                        mag = self.outer._vec_norm_any(a)

                        # contact point 좌표나 normal 좌표가 잘못 force로 잡히는 것 방지:
                        # 아주 작은 값은 무시한다.
                        if mag > best_mag and mag > 1e-12:
                            best_mag = float(mag)

                    return float(best_mag)

                def _pair_from_args(self, args: tuple[Any, ...]) -> tuple[Optional[str], Optional[str]]:
                    """
                    contact object/contactable에서 body name 추출.
                    표준적으로 마지막 두 개가 contactobjA/contactobjB인 경우가 많다.
                    """
                    candidates: list[tuple[Any, Any]] = []

                    if len(args) >= 2:
                        candidates.append((args[-2], args[-1]))

                    if len(args) >= 9:
                        candidates.append((args[7], args[8]))

                    for a, b in candidates:
                        name_a = self.outer._try_get_body_name_from_contactable(a)
                        name_b = self.outer._try_get_body_name_from_contactable(b)
                        if name_a or name_b:
                            return name_a, name_b

                    return None, None

                def OnReportContact(self, *args) -> bool:  # noqa: N802
                    if self.count >= self.cap:
                        return False

                    self.count += 1

                    # 🔥 디버그 출력 (딱 1번만)
                    if not self.debug_printed:
                        self.debug_printed = True
                        print("[CONTACT DEBUG] ReportAllContacts args:")
                        for i, a in enumerate(args):
                            try:
                                mag = self.outer._vec_norm_any(a)
                            except Exception:
                                mag = -1.0
                            print(f"  arg[{i}] type={type(a)} mag={mag} repr={repr(a)[:120]}")

                    # arg[3]은 Chrono ReportAllContacts에서 보통 distance 계열 값
                    # 양수: 떨어져 있음 / 0 근처: 접촉 / 음수: 침투 가능성
                    try:
                        if len(args) >= 4:
                            dist = float(args[3])
                            if self.min_distance is None:
                                self.min_distance = dist
                            else:
                                self.min_distance = min(float(self.min_distance), dist)

                            if dist < 0.0:
                                self.max_penetration = max(float(self.max_penetration), abs(dist))
                    except Exception:
                        pass

                    fmag = self._force_mag_from_args(args)

                    if fmag > self.max_force:
                        self.max_force = float(fmag)

                        name_a, name_b = self._pair_from_args(args)
                        self.max_a = name_a
                        self.max_b = name_b

                    return True

            rep = _Reporter(self, max_points_i)

            try:
                container.ReportAllContacts(rep)
            except Exception:
                return None

            if rep.count > 0:
                print(
                    f"[CONTACT DIST] count={rep.count} "
                    f"min_distance={rep.min_distance} "
                    f"max_penetration={rep.max_penetration}"
                )

            max_pair = None

            if rep.max_a and rep.max_b:
                max_pair = rt.ContactPair(bodyA=str(rep.max_a), bodyB=str(rep.max_b))

            return rt.ContactTelemetry(
                contact_count=int(rep.count),
                max_contact_force=float(rep.max_force),
                max_pair=max_pair,
            )

        except Exception:
            return None

    def _compute_contact_telemetry(self, *, max_points: int) -> Optional[rt.ContactTelemetry]:
        """
        step 이후 현재 contact container에서 최소 telemetry 추출.
        - contact_count: reporter 순회 기반(=cap 적용)
        - max_contact_force
        - max_pair(optional)
        """
        container = None
        try:
            if hasattr(self.sys, "GetContactContainer"):
                container = self.sys.GetContactContainer()
        except Exception:
            container = None

        if container is None:
            return None

        # 1) cap 기반 reporter 시도 (요구사항 1순위)
        rep_tel = self._try_report_all_contacts(container, max_points=int(max_points))
        if rep_tel is not None:
            return rep_tel

        # 2) reporter가 불가능하면: count만이라도 (force/pair는 불가)
        try:
            for fn in ("GetNcontacts", "GetNContacts", "GetNcontact", "GetNContactPoints"):
                if hasattr(container, fn):
                    n_total = int(getattr(container, fn)())
                    return rt.ContactTelemetry(
                        contact_count=int(n_total),
                        max_contact_force=0.0,
                        max_pair=None,
                    )
        except Exception:
            pass

        return None

    # -------------------------------
    # main loop
    # -------------------------------

    def step(self, userInput: Optional[Any] = None) -> SimState:
        dt = float(self.info.options.dt)

        if userInput is not None:
            self._apply_user_input(userInput)

        # accumulator clear (바인딩 이슈 대응)
        try:
            for built in self.bodies.values():
                b = built.body
                if _is_fixed_body(b):
                    continue
                _clear_body_accumulators(b)
        except Exception:
            pass

        self._ar.compute_and_apply(sim=self, dt=dt)

        # ✅ (3-2.4) assembly assist
        assembly_telemetry = self._apply_assembly_guides(dt=dt)
        self._last_assembly_telemetry = assembly_telemetry

        # ✅ (3-1.4) gear loss/backlash approximation
        gear_telemetry = self._apply_gear_pair_approximations(dt=dt)
        self._last_gear_telemetry = gear_telemetry

        # ---- NaN guard (before DoStepDynamics) ----
        for name, bwrap in self.bodies.items():
            b = bwrap.body

            try:
                w = _get_angvel_world(b)
                if not (
                    m.isfinite(float(w.x))
                    and m.isfinite(float(w.y))
                    and m.isfinite(float(w.z))
                ):
                    print(f"[SANITY] NaN angvel detected on {name}, resetting")
                    _set_angvel_world_best_effort(b, chrono.ChVector3d(0.0, 0.0, 0.0))
            except Exception:
                pass

            try:
                v = _get_linvel_world(b)
                if not (
                    m.isfinite(float(v.x))
                    and m.isfinite(float(v.y))
                    and m.isfinite(float(v.z))
                ):
                    print(f"[SANITY] NaN linvel detected on {name}, resetting")
                    _set_linvel_world_best_effort(b, chrono.ChVector3d(0.0, 0.0, 0.0))
            except Exception:
                pass

        # ---- integrate ----
        self.sys.DoStepDynamics(dt)

        self.sim_time += dt
        self._seq += 1

        # ✅ (1-3) Contact telemetry
        telemetry: Optional[rt.ContactTelemetry] = None
        try:
            enabled = bool(getattr(self.info.options, "enable_contact_telemetry", False))
        except Exception:
            enabled = False

        if enabled:
            try:
                cap = int(getattr(self.info.options, "max_contact_points_report", 256))
            except Exception:
                cap = 256
            cap = max(1, cap)

            telemetry = self._compute_contact_telemetry(max_points=cap)

        joint_telemetry = self._compute_joint_telemetry()
        actuator_telemetry = self._compute_actuator_telemetry()
        interaction_telemetry = None
        try:
            interaction_telemetry = self._ar.make_interaction_telemetry(self)
        except Exception:
            interaction_telemetry = None

        diagnostics = self._build_diagnostics(
            telemetry=telemetry,
            gear_telemetry=gear_telemetry,
            assembly_telemetry=assembly_telemetry,
            joint_telemetry=joint_telemetry,
            actuator_telemetry=actuator_telemetry,
        )

        # ----------------------------------------------------
        # 1) metadata diagnostics 먼저 붙이기
        # ----------------------------------------------------
        try:
            metadata_diagnostics = list(getattr(self, "_metadata_diagnostics", []) or [])
        except Exception:
            metadata_diagnostics = []

        if metadata_diagnostics:
            diagnostics = metadata_diagnostics + list(diagnostics or [])

        # ----------------------------------------------------
        # 2) runtime diagnostics 추가
        # ----------------------------------------------------
        runtime_diagnostics = self._build_runtime_diagnostics(
            telemetry=telemetry,
            interaction_telemetry=interaction_telemetry,
        )

        if runtime_diagnostics:
            diagnostics = list(diagnostics or []) + runtime_diagnostics

        # ----------------------------------------------------
        # 3) 후처리
        # ----------------------------------------------------
        diagnostics = self._normalize_diagnostics(diagnostics)
        diagnostics = self._dedupe_and_suppress_diagnostics(diagnostics)
        diagnostics = self._finalize_diagnostics(diagnostics)

        # ----------------------------------------------------
        # 4) event feedback 생성
        # ----------------------------------------------------
        event_feedback = self._build_event_feedback(
            telemetry=telemetry,
            interaction_telemetry=interaction_telemetry,
            gear_telemetry=gear_telemetry,
            assembly_telemetry=assembly_telemetry,
            joint_telemetry=joint_telemetry,
            actuator_telemetry=actuator_telemetry,
            diagnostics=diagnostics,
        )

        parts: List[PartState] = []
        for name in self._body_order:
            b = self.bodies[name].body
            parts.append(PartState.from_chrono_body(b, name=name))

        partNames = self._body_order if bool(getattr(self.info.options, "emit_part_names", False)) else None
        server_time_sec = float(time.time())

        return SimState(
            sim_time=self.sim_time,
            parts=parts,
            partNames=list(partNames) if partNames is not None else None,
            seq=int(self._seq),
            server_time_sec=server_time_sec,
            telemetry=telemetry,
            interactionTelemetry=interaction_telemetry,
            gearTelemetry=gear_telemetry,
            assemblyTelemetry=assembly_telemetry,
            jointTelemetry=joint_telemetry,
            actuatorTelemetry=actuator_telemetry,
            diagnostics=diagnostics,
            eventFeedback=event_feedback,
        )

    def _build_event_feedback(
        self,
        *,
        telemetry: Optional[rt.ContactTelemetry],
        interaction_telemetry: Optional[InteractionTelemetry],
        gear_telemetry: Optional[Dict[str, rt.GearTelemetry]],
        assembly_telemetry: Optional[Dict[str, rt.AssemblyGuideTelemetry]],
        joint_telemetry: Optional[Dict[str, rt.JointTelemetry]],
        actuator_telemetry: Optional[Dict[str, rt.ActuatorTelemetry]],
        diagnostics: Optional[List[rt.DiagnosticItem]],
    ) -> Optional[List[rt.EventFeedback]]:
        """
        telemetry / diagnostics를 사용자용 이벤트 피드백으로 변환한다.

        주의:
        - STEP 3에서는 이 함수만 추가한다.
        - 실제 SimState.eventFeedback 연결은 STEP 4에서 수행한다.
        - cooldown / 반복 억제는 STEP 5에서 추가한다.
        """
        try:
            opt = getattr(self.info, "options", None)
            if opt is not None and not bool(getattr(opt, "enable_event_feedback", True)):
                return None
        except Exception:
            pass

        try:
            max_items = int(getattr(self.info.options, "event_feedback_max_items", 16))
        except Exception:
            max_items = 16
        max_items = max(1, max_items)

        try:
            enable_sound = bool(getattr(self.info.options, "event_feedback_enable_sound", True))
        except Exception:
            enable_sound = True

        events: List[rt.EventFeedback] = []
        seen: set[tuple[str, Optional[str]]] = set()

        def _clamp_float(x: float, lo: float, hi: float) -> float:
            return max(float(lo), min(float(hi), float(x)))

        def _volume_from_value(value: Optional[float], threshold: Optional[float], default: float) -> float:
            if value is None or threshold is None:
                return float(default)
            try:
                if float(threshold) <= 1e-12:
                    return float(default)
                ratio = abs(float(value)) / float(threshold)
                return _clamp_float(0.35 + 0.45 * ratio, 0.35, 1.0)
            except Exception:
                return float(default)

        def _sound_meta(
            event_type: str,
            *,
            value: Optional[float] = None,
            threshold: Optional[float] = None,
        ) -> tuple[Optional[str], Optional[str], Optional[float], Optional[float]]:
            """
            eventType별 sound metadata 매핑.

            반환:
            - soundId: 클라이언트가 재생할 효과음 ID
            - soundType: warning / impact / mechanical / notification 등
            - volume: 0.0 ~ 1.0
            - pitch: 0.1 ~ 4.0

            실제 오디오 재생은 Python 엔진이 하지 않고,
            AR/클라이언트가 soundId를 보고 처리한다.
            """
            if not enable_sound:
                return None, None, None, None

            event_type_s = str(event_type)

            # ----------------------------------------------------
            # 사용자 입력/상호작용 관련
            # ----------------------------------------------------
            if event_type_s == "AR_INPUT_NO_MOTION":
                return (
                    "no_motion_warn",
                    "warning",
                    0.60,
                    1.00,
                )

            # ----------------------------------------------------
            # 충돌/접촉 관련
            # ----------------------------------------------------
            if event_type_s == "EXCESSIVE_CONTACT_FORCE":
                return (
                    "impact_warn",
                    "impact",
                    _volume_from_value(value, threshold, 0.75),
                    1.00,
                )

            # ----------------------------------------------------
            # 속도/불안정성 관련
            # ----------------------------------------------------
            if event_type_s == "HIGH_SPEED_WARNING":
                return (
                    "speed_warn",
                    "warning",
                    _volume_from_value(value, threshold, 0.70),
                    1.00,
                )

            # ----------------------------------------------------
            # 조인트/기구학 구속 관련
            # ----------------------------------------------------
            if event_type_s == "JOINT_LIMIT_REACHED":
                return (
                    "joint_limit_click",
                    "mechanical",
                    0.70,
                    1.00,
                )

            # ----------------------------------------------------
            # 조립/스냅 보조 관련
            # ----------------------------------------------------
            if event_type_s == "SNAP_READY":
                return (
                    "snap_ready",
                    "notification",
                    0.50,
                    1.20,
                )

            # ----------------------------------------------------
            # 기어 관련
            # ----------------------------------------------------
            if event_type_s == "GEAR_BACKLASH_ACTIVE":
                return (
                    "gear_tick",
                    "mechanical",
                    0.50,
                    0.90,
                )

            if event_type_s == "GEAR_EFFICIENCY_LOW":
                return (
                    "gear_loss_warn",
                    "warning",
                    0.55,
                    0.95,
                )

            # ----------------------------------------------------
            # fallback
            # ----------------------------------------------------
            return (
                "event_notice",
                "notification",
                0.45,
                1.00,
            )

        def _append_event(
            *,
            event_type: str,
            severity: str,
            message: str,
            target: Optional[str] = None,
            value: Optional[float] = None,
            threshold: Optional[float] = None,
        ) -> None:
            if len(events) >= max_items:
                return

            event_type_s = str(event_type)
            target_s = str(target) if target is not None else None

            # 1) 같은 step 내부 중복 방지
            key = (event_type_s, target_s)
            if key in seen:
                return
            seen.add(key)

            # 2) step 간 cooldown 방지
            try:
                cooldown_sec = float(getattr(self.info.options, "event_feedback_cooldown_sec", 0.5))
            except Exception:
                cooldown_sec = 0.5
            cooldown_sec = max(0.0, float(cooldown_sec))

            cooldown_key = f"{event_type_s}:{target_s or ''}"
            now_t = float(getattr(self, "sim_time", 0.0))

            try:
                last_t = float(self._event_feedback_last_emit_time.get(cooldown_key, -1.0e30))
            except Exception:
                last_t = -1.0e30

            if cooldown_sec > 0.0 and (now_t - last_t) < cooldown_sec:
                return

            try:
                self._event_feedback_last_emit_time[cooldown_key] = now_t
            except Exception:
                pass

            sound_id, sound_type, volume, pitch = _sound_meta(
                event_type_s,
                value=value,
                threshold=threshold,
            )

            events.append(
                rt.EventFeedback(
                    eventType=event_type_s,
                    severity=str(severity or "info"),
                    message=str(message or ""),
                    target=target_s,
                    soundId=sound_id,
                    soundType=sound_type,
                    volume=volume,
                    pitch=pitch,
                    value=float(value) if value is not None else None,
                    threshold=float(threshold) if threshold is not None else None,
                )
            )

        # ----------------------------------------------------
        # 1) diagnostics 기반 이벤트 변환
        # ----------------------------------------------------
        for item in list(diagnostics or []):
            try:
                code = str(getattr(item, "code", "") or "")
                severity = str(getattr(item, "severity", "info") or "info")
                message = str(getattr(item, "message", "") or "")
                target = getattr(item, "target", None)

                if code == "AR_INPUT_NO_MOTION":
                    _append_event(
                        event_type="AR_INPUT_NO_MOTION",
                        severity=severity,
                        message=message,
                        target=target,
                    )

                elif code == "EXCESSIVE_CONTACT_FORCE":
                    max_force = None
                    try:
                        if telemetry is not None:
                            max_force = float(getattr(telemetry, "max_contact_force", 0.0))
                    except Exception:
                        max_force = None

                    _append_event(
                        event_type="EXCESSIVE_CONTACT_FORCE",
                        severity=severity,
                        message=message,
                        target=target,
                        value=max_force,
                        threshold=100.0,
                    )

                elif code in ("ABNORMAL_LINEAR_SPEED", "ABNORMAL_ANGULAR_SPEED"):
                    _append_event(
                        event_type="HIGH_SPEED_WARNING",
                        severity=severity,
                        message=message,
                        target=target,
                    )

                elif code == "AT_JOINT_LIMIT":
                    value = None
                    threshold = None

                    try:
                        if target is not None and joint_telemetry is not None and str(target) in joint_telemetry:
                            jt = joint_telemetry[str(target)]

                            if jt.angle is not None:
                                value = float(jt.angle)
                            elif jt.position is not None:
                                value = float(jt.position)

                        if target is not None and str(target) in self.joints:
                            jm = self.joints[str(target)].meta
                            limits = getattr(jm, "limits", None)
                            lower = getattr(limits, "lower", None) if limits is not None else None
                            upper = getattr(limits, "upper", None) if limits is not None else None

                            if value is not None:
                                candidates = []
                                if lower is not None:
                                    candidates.append(float(lower))
                                if upper is not None:
                                    candidates.append(float(upper))
                                if candidates:
                                    threshold = min(candidates, key=lambda x: abs(float(value) - x))
                    except Exception:
                        value = None
                        threshold = None

                    _append_event(
                        event_type="JOINT_LIMIT_REACHED",
                        severity=severity,
                        message=message or "조인트가 동작 한계에 도달했습니다.",
                        target=target,
                        value=value,
                        threshold=threshold,
                    )

                elif code == "HIGH_GEAR_LOSS":
                    _append_event(
                        event_type="GEAR_EFFICIENCY_LOW",
                        severity=severity,
                        message=message,
                        target=target,
                    )

                elif code == "ALIGNMENT_IN_PROGRESS":
                    _append_event(
                        event_type="SNAP_READY",
                        severity="info",
                        message=message or "조립 기준 위치에 근접했습니다.",
                        target=target,
                    )

            except Exception:
                continue

        # ----------------------------------------------------
        # 2) assembly telemetry 기반 SNAP_READY 보강
        # ----------------------------------------------------
        if assembly_telemetry:
            for gname, ag in assembly_telemetry.items():
                try:
                    if not bool(getattr(ag, "activeSnap", False)):
                        continue

                    err_pos = float(getattr(ag, "snapErrorPos", 0.0))
                    err_ang = float(getattr(ag, "snapErrorAngle", 0.0))

                    # 스냅 후보가 활성화되었고 오차가 충분히 작으면 사용자 피드백으로 변환
                    if err_pos <= 1e-3 and err_ang <= 1e-2:
                        _append_event(
                            event_type="SNAP_READY",
                            severity="info",
                            message=f"Assembly guide '{gname}' is close enough to snap.",
                            target=str(gname),
                            value=max(err_pos, err_ang),
                            threshold=1e-2,
                        )
                except Exception:
                    continue

        # ----------------------------------------------------
        # 3) gear telemetry 기반 backlash 이벤트 보강
        # ----------------------------------------------------
        if gear_telemetry:
            for gname, gt in gear_telemetry.items():
                try:
                    backlash = float(getattr(gt, "backlash_deadband", 0.0) or 0.0)
                    if backlash > 0.0:
                        _append_event(
                            event_type="GEAR_BACKLASH_ACTIVE",
                            severity="info",
                            message=f"Gear pair '{gname}' has backlash deadband.",
                            target=str(gname),
                            value=backlash,
                            threshold=0.0,
                        )
                except Exception:
                    continue

        return events or None

    def _build_runtime_diagnostics(
        self,
        *,
        telemetry: Optional[rt.ContactTelemetry],
        interaction_telemetry: Optional[InteractionTelemetry],
    ) -> List[rt.DiagnosticItem]:
        """
        실행 중 상태를 기반으로 교육용 진단 메시지를 생성한다.

        검사 항목:
        - AR 입력이 있는데 움직임이 거의 없음
        - 접촉 힘이 과도함
        - body 선속도/각속도가 비정상적으로 큼
        """
        diagnostics: List[rt.DiagnosticItem] = []

        # ----------------------------------------------------
        # 1) AR 입력이 있는데 움직임이 거의 없음
        # ----------------------------------------------------
        try:
            ar_active = bool(getattr(self._ar.ctx, "active", False))

            # AR 입력이 끝났으면 no-motion 감지 기준 시간 초기화
            if not ar_active:
                self._ar_no_motion_active_key = None
                self._ar_no_motion_start_time = None

            if interaction_telemetry is not None:
                target_name = interaction_telemetry.driveBody or interaction_telemetry.targetBody

                if target_name and target_name in self.bodies:
                    body = self.bodies[target_name].body

                    v = _get_linvel_world(body)
                    w = _get_angvel_world(body)

                    lin_speed = _norm(v)
                    ang_speed = _norm(w)

                    target_key = str(target_name)

                    # 새 AR 조작 대상이 시작되면 그 시점을 기록
                    if ar_active:
                        prev_key = getattr(self, "_ar_no_motion_active_key", None)

                        if prev_key != target_key:
                            self._ar_no_motion_active_key = target_key
                            self._ar_no_motion_start_time = float(getattr(self, "sim_time", 0.0))

                    # TouchStart 직후에는 아직 물체가 움직이기 전일 수 있으므로
                    # 일정 시간 동안 no-motion 진단을 유예한다.
                    try:
                        no_motion_grace_sec = float(
                            getattr(self.info.options, "event_feedback_no_motion_grace_sec", 2.0)
                        )
                    except Exception:
                        no_motion_grace_sec = 2.0

                    no_motion_grace_sec = max(0.0, float(no_motion_grace_sec))

                    try:
                        start_t = float(getattr(self, "_ar_no_motion_start_time", self.sim_time))
                    except Exception:
                        start_t = float(getattr(self, "sim_time", 0.0))

                    elapsed_from_touch_start = float(getattr(self, "sim_time", 0.0)) - start_t

                    no_motion_ready = elapsed_from_touch_start >= no_motion_grace_sec

                    if (
                        ar_active
                        and no_motion_ready
                        and lin_speed < 1e-4
                        and ang_speed < 1e-4
                    ):
                        diagnostics.append(
                            rt.DiagnosticItem(
                                code="AR_INPUT_NO_MOTION",
                                severity="warn",
                                message=(
                                    f"AR 입력이 적용되었지만 '{target_name}'의 움직임이 거의 없습니다. "
                                    "조인트 구속, 충돌 간섭, 또는 구동 body 선택을 확인하세요."
                                ),
                                target=str(target_name),
                            )
                        )
        except Exception:
            pass

        # ----------------------------------------------------
        # 2) 과도한 접촉력
        # ----------------------------------------------------
        try:
            if telemetry is not None:
                max_force = float(getattr(telemetry, "max_contact_force", 0.0))

                if max_force > 100.0:
                    target = None
                    try:
                        if telemetry.max_pair is not None:
                            target = f"{telemetry.max_pair.bodyA}-{telemetry.max_pair.bodyB}"
                    except Exception:
                        target = None

                    diagnostics.append(
                        rt.DiagnosticItem(
                            code="EXCESSIVE_CONTACT_FORCE",
                            severity="warn",
                            message=(
                                f"접촉력이 과도하게 큽니다. max_contact_force={max_force:.3f} N. "
                                "충돌 형상 크기, body 간 간섭, 초기 배치를 확인하세요."
                            ),
                            target=target,
                        )
                    )
        except Exception:
            pass

        # ----------------------------------------------------
        # 3) 비정상 속도/각속도
        # ----------------------------------------------------
        try:
            for name, bwrap in self.bodies.items():
                body = bwrap.body

                v = _get_linvel_world(body)
                w = _get_angvel_world(body)

                lin_speed = _norm(v)
                ang_speed = _norm(w)

                if lin_speed > 20.0:
                    diagnostics.append(
                        rt.DiagnosticItem(
                            code="ABNORMAL_LINEAR_SPEED",
                            severity="warn",
                            message=(
                                f"Body '{name}'의 선속도가 비정상적으로 큽니다. "
                                f"speed={lin_speed:.3f} m/s. 힘/질량/충돌 설정을 확인하세요."
                            ),
                            target=str(name),
                        )
                    )

                if ang_speed > 50.0:
                    diagnostics.append(
                        rt.DiagnosticItem(
                            code="ABNORMAL_ANGULAR_SPEED",
                            severity="warn",
                            message=(
                                f"Body '{name}'의 각속도가 비정상적으로 큽니다. "
                                f"angular_speed={ang_speed:.3f} rad/s. 관성/토크/조인트 설정을 확인하세요."
                            ),
                            target=str(name),
                        )
                    )
        except Exception:
            pass

        return diagnostics

    def close(self) -> None:
        try:
            self.sys.Clear()
        except Exception:
            pass

    def _apply_user_input(self, userInput: Any) -> None:
        coerced = _coerce_user_input_any(userInput)
        if coerced is not None:
            userInput = coerced

        motor_speeds = getattr(userInput, "motor_speeds", None)
        torque_cmds = getattr(userInput, "torque_cmds", None)

        if isinstance(motor_speeds, dict) or isinstance(torque_cmds, dict):
            if isinstance(motor_speeds, dict) and motor_speeds:
                for act_name, speed in motor_speeds.items():
                    built_act = self.actuators.get(act_name)  # ✅ 중복 라인 제거된 버전
                    if built_act is None:
                        continue
                    if built_act.meta.type != "rotation_speed":
                        continue
                    motor = built_act.link
                    try:
                        motor.SetSpeedFunction(chrono.ChFunctionConst(float(speed)))
                    except Exception:
                        pass

            if isinstance(torque_cmds, dict) and torque_cmds:
                for act_name, torque in torque_cmds.items():
                    built_act = self.actuators.get(act_name)
                    if built_act is None:
                        continue
                    if built_act.meta.type != "rotation_torque":
                        continue
                    motor = built_act.link
                    try:
                        motor.SetTorqueFunction(chrono.ChFunctionConst(float(torque)))
                    except Exception:
                        pass
            return

        try:
            self._ar.ingest(userInput, part_names=self._body_order, sim=self)
        except Exception as e:
            print("[WARN] ingest failed:", e)

    def _infer_revolute_axis_world_for_body(self, body_name: str) -> chrono.ChVector3d:
        try:
            for j in self.joints.values():
                jm = j.meta
                if getattr(jm, "type", None) != "revolute":
                    continue
                if getattr(jm, "body1", None) != body_name and getattr(jm, "body2", None) != body_name:
                    continue

                link = j.link
                for fn in ("GetFrame1Abs", "GetFrame2Abs", "GetFrame1", "GetFrame2"):
                    try:
                        if hasattr(link, fn):
                            fr = getattr(link, fn)()
                            if fr is None:
                                continue

                            q = None
                            if hasattr(fr, "GetRot"):
                                q = fr.GetRot()
                            elif hasattr(fr, "GetA"):
                                q = fr.GetA().GetQ()

                            if isinstance(q, chrono.ChQuaterniond):
                                axis = _quat_rotate(q, chrono.ChVector3d(0.0, 0.0, 1.0))
                                if _norm(axis) > 1e-9:
                                    return axis
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            for j in self.joints.values():
                jm = j.meta
                if getattr(jm, "type", None) != "revolute":
                    continue
                if getattr(jm, "body1", None) != body_name and getattr(jm, "body2", None) != body_name:
                    continue

                q = jm.frame.rot
                qch = chrono.ChQuaterniond(float(q.w), float(q.x), float(q.y), float(q.z))
                axis = _quat_rotate(qch, chrono.ChVector3d(0.0, 0.0, 1.0))
                if _norm(axis) > 1e-9:
                    return axis
        except Exception:
            pass

        try:
            body = self.bodies[body_name].body
            q = body.GetRot()
            return _quat_rotate(q, chrono.ChVector3d(0.0, 0.0, 1.0))
        except Exception:
            return chrono.ChVector3d(0.0, 0.0, 1.0)

    def _maybe_release_drive_actuators_for_target(self, target_body_name: str) -> None:
        joint_names: List[str] = []
        try:
            for j in self.joints.values():
                jm = j.meta
                if getattr(jm, "type", None) != "revolute":
                    continue
                if getattr(jm, "body1", None) == target_body_name or getattr(jm, "body2", None) == target_body_name:
                    joint_names.append(str(jm.name))
        except Exception:
            joint_names = []

        if not joint_names:
            return

        for act_name, act in self.actuators.items():
            try:
                if act_name in self._released_drive_actuators:
                    continue

                act_type = getattr(act.meta, "type", None)
                if act_type not in ("rotation_speed", "rotation_torque"):
                    continue

                target_joint = getattr(act.meta, "targetJoint", None)
                if target_joint not in joint_names:
                    continue

                motor = act.link
                done = False

                try:
                    if hasattr(motor, "SetDisabled"):
                        motor.SetDisabled(True)
                        done = True
                except Exception:
                    pass

                try:
                    if (not done) and hasattr(motor, "SetActive"):
                        motor.SetActive(False)
                        done = True
                except Exception:
                    pass

                try:
                    if (not done) and hasattr(motor, "Enable"):
                        motor.Enable(False)
                        done = True
                except Exception:
                    pass

                if act_type == "rotation_speed":
                    try:
                        if hasattr(motor, "SetSpeedFunction"):
                            try:
                                motor.SetSpeedFunction(None)  # type: ignore[arg-type]
                            except Exception:
                                motor.SetSpeedFunction(chrono.ChFunctionConst(0.0))
                            done = True
                    except Exception:
                        pass

                if act_type == "rotation_torque":
                    try:
                        if hasattr(motor, "SetTorqueFunction"):
                            motor.SetTorqueFunction(chrono.ChFunctionConst(0.0))
                            done = True
                    except Exception:
                        pass

                if done:
                    self._released_drive_actuators.add(act_name)
                    print(f"[AR] neutralized drive actuator: {act_name} type={act_type} (targetJoint={target_joint})")

            except Exception:
                continue

    def _maybe_release_speed_motors_for_target(self, target_body_name: str) -> None:
        self._maybe_release_drive_actuators_for_target(target_body_name)


if __name__ == "__main__":
    # ✅ (2-3.3) headless joint limit test mode
    if "--joint-limit-test" in sys.argv:
        run_joint_limit_tests_headless()
        raise SystemExit(0)

    # demo
    info = SimInfo.from_json_file("resources/test_scene.json", dt=1e-3)
    # 예: telemetry 켜고 싶으면 이렇게:
    # info.options.enable_contact_telemetry = True
    # info.options.max_contact_points_report = 128

    sim = Simulator.create(info)

    for _ in range(1000):
        state = sim.step(None)

    print("[sim] done. sim_time =", state.sim_time)
    if getattr(state, "telemetry", None) is not None:
        print(
            "[telemetry] contact_count =",
            state.telemetry.contact_count,
            "max_contact_force =",
            state.telemetry.max_contact_force,
        )
        if state.telemetry.max_pair is not None:
            print("[telemetry] max_pair =", state.telemetry.max_pair.bodyA, state.telemetry.max_pair.bodyB)

    if getattr(state, "gearTelemetry", None):
        for gname, gt in state.gearTelemetry.items():
            print(
                "[gearTelemetry]",
                gname,
                "applied_efficiency=",
                gt.applied_efficiency,
                "loss_torque=",
                gt.loss_torque,
                "backlash_deadband=",
                gt.backlash_deadband,
            )

    sim.close()
