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
# 테스트 커버리지(현재까지)
# - Spring minimal physics (headless) ✅
# - Rotate shaft-base physics (SimInfo + sim_builder + revolute) ✅
# - Hybrid mode selection & call hooking (logic-level) ✅
# - Chrono angvel get/set compatibility diagnostic ✅


from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

import math as m
import time
import pychrono as chrono

from .SimInfo import SimInfo

from . import runtime_types as rt
from .runtime_types import (
    UserInput,
    SimState,
    PartState,
    TouchStartEvent,
    TouchingEvent,
    TouchEndEvent,
    resolve_target_part_name,
)

from .sim_builder import build_system_from_scene


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


class _ARInteractionController:
    MODE_ROTATE = "rotate"
    MODE_SPRING = "spring"

    # ---- Rotate drag torque ----
    DRAG_TORQUE_MAX = 1.0
    DRAG_ANGLE_REF = m.pi / 6.0

    # ---- Rotate damping (torque-based) ----
    # ✅ 튜닝(덜컹/부호반전 완화): 기본값을 "안전한 1차"로 변경
    ROT_DAMP_CW = 1.0

    # ✅ 작은 속도 영역에서 덜컹/플립플롭을 끊기 위해 SNAP을 약간 올림
    VEL_EPS_SNAP_ROT = 0.10

    # ✅ 큰 속도에서 감쇠 토크가 과하게 들어가 반전하는 걸 줄이기 위해 상한을 낮춤
    ROT_DAMP_TAU_MAX = 1.5

    # ✅ "한 스텝에서 w 부호가 뒤집히지 않도록" 안전계수
    # tau_noflip = Ieff * |w| / dt  (여기에 safety를 곱해 살짝 덜 감쇠)
    ROT_DAMP_NOFLIP_SAFETY = 0.95

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

    def ingest(self, user_input: UserInput, *, part_names: List[str], sim: "Simulator") -> None:
        if isinstance(user_input, TouchStartEvent):
            target_name = user_input.payload.target.partName
            if not target_name:
                target_name = resolve_target_part_name(user_input, part_names)

            self.ctx.active = True
            self.ctx.target_name = target_name

            ap = user_input.payload.actionPointLocal
            fp = user_input.payload.fingerPointWorld
            cf = user_input.payload.cameraForwardWorld

            self.ctx.action_point_local = chrono.ChVector3d(ap.x, ap.y, ap.z)
            self.ctx.start_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self.ctx.last_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self.ctx.camera_forward_world = chrono.ChVector3d(cf.x, cf.y, cf.z)

            self._prev_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self._prev_rotate_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)

            self._mode = self._auto_select_mode(sim, target_name)

            sim._maybe_release_drive_actuators_for_target(target_name)

            print(f"[AR] TouchStart target={target_name} mode={self._mode}")
            return

        if isinstance(user_input, TouchingEvent):
            fp = user_input.payload.fingerPointWorld
            cf = user_input.payload.cameraForwardWorld
            self.ctx.last_finger_world = chrono.ChVector3d(fp.x, fp.y, fp.z)
            self.ctx.camera_forward_world = chrono.ChVector3d(cf.x, cf.y, cf.z)
            return

        if isinstance(user_input, TouchEndEvent):
            self.ctx.active = False
            self.ctx.start_finger_world = None
            self._prev_finger_world = None
            self._prev_rotate_finger_world = None
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

        if (len(revolute_joints) == 1) and (len(other_joints) == 0):
            axis = sim._infer_revolute_axis_world_for_body(target_body_name)
            if _norm(axis) > 1e-6:
                return self.MODE_ROTATE
            return self.MODE_SPRING

        return self.MODE_SPRING

    def compute_and_apply(self, *, sim: "Simulator", dt: float) -> None:
        target_name = self.ctx.target_name
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
        axis_world = _normalize(sim._infer_revolute_axis_world_for_body(body_name))
        if _norm(axis_world) < 1e-9:
            self._mode = self.MODE_SPRING
            return

        center_world = body.GetPos()

        # 1) Drag torque (증분 방식)
        if dragging_now:
            f_curr = self.ctx.last_finger_world
            f_prev = self._prev_rotate_finger_world

            if f_prev is None:
                self._prev_rotate_finger_world = chrono.ChVector3d(f_curr.x, f_curr.y, f_curr.z)
                return

            v0 = _sub(f_prev, center_world)
            v1 = _sub(f_curr, center_world)

            self._prev_rotate_finger_world = chrono.ChVector3d(f_curr.x, f_curr.y, f_curr.z)

            if _norm(v0) > 1e-6 and _norm(v1) > 1e-6:
                v0n = _normalize(v0)
                v1n = _normalize(v1)

                c = _clamp(_dot(v0n, v1n), -1.0, 1.0)
                d_ang = m.acos(c)

                if d_ang > 1e-6:
                    arc_axis = _cross(v0n, v1n)
                    arc_axis_n = _normalize(arc_axis)

                    if _norm(arc_axis_n) > 1e-6:
                        sign = 1.0 if _dot(arc_axis_n, axis_world) >= 0.0 else -1.0
                        s = _clamp(d_ang / self.DRAG_ANGLE_REF, 0.0, 1.0)
                        tau_drag = _mul(axis_world, sign * self.DRAG_TORQUE_MAX * s)
                        _apply_torque_world(body, tau_drag)
            return

        # 드래그 끝
        self._prev_rotate_finger_world = None

        # 2) Torque-based damping (TouchEnd 이후)
        if dt <= 1e-9:
            return

        w_world = _get_angvel_world(body)
        w_along = float(_dot(w_world, axis_world))

        if abs(w_along) < self.VEL_EPS_SNAP_ROT:
            return

        # 기본 감쇠 크기
        tau_mag = abs(self.ROT_DAMP_CW * w_along)
        tau_mag = min(tau_mag, float(self.ROT_DAMP_TAU_MAX))

        # ✅ 핵심: anti-flip clamp
        # 한 스텝에서 w를 0 넘어 반대로 뒤집지 못하게 제한
        Ieff = _effective_inertia_about_axis_world(body, axis_world)
        tau_noflip = (Ieff * abs(w_along) / float(dt)) * float(self.ROT_DAMP_NOFLIP_SAFETY)
        if tau_mag > tau_noflip:
            tau_mag = tau_noflip

        # w_along 부호 반대로 (감쇠)
        tau_damp = _mul(axis_world, -m.copysign(tau_mag, w_along))
        _apply_torque_world(body, tau_damp)

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
    def __init__(self, info: SimInfo):
        self.info: SimInfo = info

        built = build_system_from_scene(info.scene)

        self.sys: chrono.ChSystemNSC = built.sys
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

        # ✅ [중요 보강] metadata의 explicit inertia를 chrono body에 캐시
        # - PyChrono 바인딩에서 inertia getter가 없으면 Ieff를 못 구해서 anti-flip clamp가 무력화됨
        # - 특히 shaft처럼 Izz=0.0002 같은 작은 관성에서 damping 토크가 쉽게 “반전/덜컹”을 만들 수 있음
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

    @classmethod
    def create(cls, info: SimInfo) -> "Simulator":
        return cls(info)

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

        self.sys.DoStepDynamics(dt)
        self.sim_time += dt

        self._seq += 1

        parts: List[PartState] = []
        for name in self._body_order:
            b = self.bodies[name].body
            parts.append(PartState.from_chrono_body(b, name=name))

        # ✅ schema-07 optional fields
        partNames = self._body_order if bool(getattr(self.info.options, "emit_part_names", False)) else None
        server_time_sec = float(time.time())

        return SimState(
            sim_time=self.sim_time,
            parts=parts,
            partNames=list(partNames) if partNames is not None else None,
            seq=int(self._seq),
            server_time_sec=server_time_sec,
        )

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
                    built_act = self.actuators.get(act_name)
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
                    # ✅ None이 크래시나는 바인딩이 있어 fallback을 둔다
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
    info = SimInfo.from_json_file("resources/test_scene.json", dt=1e-3)
    sim = Simulator.create(info)

    for _ in range(1000):
        state = sim.step(None)

    print("[sim] done. sim_time =", state.sim_time)
    sim.close()
