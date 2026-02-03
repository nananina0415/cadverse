# simulator/main.py
#
# "시뮬레이션 엔진의 외부 인터페이스" 역할
# - 서버/AR 쪽에서 Simulator를 가져다 쓰는 진입점
# - 내부 Chrono 구성은 sim_builder.py로 위임
#
# 요구 형태(의도):
#   class Simulator:
#       def __new__(info: SimInfo):
#       def step(userInput: UserInput) -> SimState
#
# Python에서는 보통 __init__를 쓰지만,
# 팀원 요청을 만족시키기 위해 create(info) + step()를 제공.
#
# [UPDATED]
# - schema-06 TouchStart/Touching/TouchEnd 기반 AR 인터랙션 적용
# - 드래그 토크 + "쿨롱(건마찰) + 점성" 혼합 감쇠(부드러운 sgn=tanh)
# - target 파트 선택을 partName/partIndex로 정확히 처리 (베이스 터치 시 샤프트가 도는 버그 방지)
# - 가능하면 "회전 DOF 축"은 revolute joint frame의 local-Z(World)로 추정
#   (없으면 바디의 local-Z를 world로 보낸 축으로 fallback)

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

import math as m
import pychrono as chrono

from .SimInfo import SimInfo

# runtime_types 내부 구현이 프로젝트마다 조금씩 달라서,
# "dict -> 이벤트 객체" 변환을 최대한 유연하게 처리하기 위해 모듈 자체도 import
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
    """a·b (Chrono vector)"""
    return float(a.x * b.x + a.y * b.y + a.z * b.z)


def _cross(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    """a×b (Chrono vector)"""
    return chrono.ChVector3d(
        float(a.y * b.z - a.z * b.y),
        float(a.z * b.x - a.x * b.z),
        float(a.x * b.y - a.y * b.x),
    )


def _norm(a: chrono.ChVector3d) -> float:
    """||a||"""
    return float(m.sqrt(_dot(a, a)))


def _normalize(a: chrono.ChVector3d, eps: float = 1e-12) -> chrono.ChVector3d:
    """a / ||a|| (eps 이하이면 0벡터)"""
    n = _norm(a)
    if n < eps:
        return chrono.ChVector3d(0.0, 0.0, 0.0)
    inv = 1.0 / n
    return chrono.ChVector3d(float(a.x * inv), float(a.y * inv), float(a.z * inv))


def _sub(a: chrono.ChVector3d, b: chrono.ChVector3d) -> chrono.ChVector3d:
    """a - b"""
    return chrono.ChVector3d(float(a.x - b.x), float(a.y - b.y), float(a.z - b.z))


def _mul(a: chrono.ChVector3d, s: float) -> chrono.ChVector3d:
    """a * s"""
    return chrono.ChVector3d(float(a.x * s), float(a.y * s), float(a.z * s))


def _clamp(x: float, lo: float, hi: float) -> float:
    """clamp x into [lo, hi]"""
    return max(lo, min(hi, x))


def _quat_rotate(q: chrono.ChQuaterniond, v0: chrono.ChVector3d) -> chrono.ChVector3d:
    """
    Rotate vector by quaternion (Chrono quaternion: e0=w, e1=x, e2=y, e3=z).
    Uses q * (0,v) * q_conj.
    """
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


def _get_angvel_world(body: chrono.ChBody) -> chrono.ChVector3d:
    """
    최대한 world 각속도를 얻는다. (Chrono 버전 차이 흡수)
    - 가능한 world getter들을 먼저 시도
    - local만 있으면 quaternion으로 world로 회전해서 반환
    """
    # 1) world getter 후보들
    for name in ("GetAngVel", "GetAngVelWorld", "GetWvel", "GetWvel_par"):
        try:
            if hasattr(body, name):
                w = getattr(body, name)()
                if isinstance(w, chrono.ChVector3d):
                    return w
        except Exception:
            pass

    # 2) local만 있으면 -> world로 회전
    for name in ("GetAngVelLocal", "GetWvel_loc"):
        try:
            if hasattr(body, name):
                wloc = getattr(body, name)()
                q = body.GetRot()
                if hasattr(chrono, "QRotate"):
                    return chrono.QRotate(q, wloc)
                # QRotate 없으면 local을 그냥 반환(최후 fallback)
                return wloc
        except Exception:
            pass

    return chrono.ChVector3d(0.0, 0.0, 0.0)


def _set_angvel_world(body: chrono.ChBody, w_world: chrono.ChVector3d) -> None:
    """
    world 각속도 설정 (Chrono 버전/바인딩 차이 흡수)
    - 있으면 SetAngVel
    - 없으면 SetWvel_par 같은 후보 사용
    """
    try:
        if hasattr(body, "SetAngVel"):
            body.SetAngVel(w_world)
            return
    except Exception:
        pass
    try:
        if hasattr(body, "SetWvel_par"):
            body.SetWvel_par(w_world)
            return
    except Exception:
        pass


def _apply_torque_world(body: chrono.ChBody, tau_world: chrono.ChVector3d) -> None:
    """
    가능한 한 "토크"로 물리적으로 적용.
    - AccumulateTorque가 있으면 그것을 사용
    - 바인딩에 따라 (torque, local) 인자가 다를 수 있어 try/except로 흡수
    """
    try:
        if hasattr(body, "AccumulateTorque"):
            try:
                body.AccumulateTorque(tau_world, False)  # world
            except TypeError:
                body.AccumulateTorque(tau_world)
            return
    except Exception:
        pass
    return


def _is_fixed_body(body: chrono.ChBody) -> bool:
    """
    fixed 바디인지 확인 (GetFixed 지원 여부/예외 흡수)
    """
    try:
        if hasattr(body, "GetFixed"):
            return bool(body.GetFixed())
    except Exception:
        pass
    return False


# ============================================================
# dict -> UserInput(Event) coercion
# ============================================================

def _coerce_user_input_any(user_input_any: Any) -> Optional[UserInput]:
    """
    외부에서 들어오는 userInput이:
    - 이미 Event 객체면 그대로
    - dict(JSON)면 runtime_types에 있는 from_dict/parse 계열로 최대한 변환
    - 실패하면 None 반환 (엔진이 죽지 않게)
    """
    if user_input_any is None:
        return None

    # 이미 올바른 이벤트 타입이면 통과
    if isinstance(user_input_any, (TouchStartEvent, TouchingEvent, TouchEndEvent)):
        return user_input_any

    # dict(JSON) -> Event 변환 시도
    if isinstance(user_input_any, dict):
        # 1) UserInput.from_dict
        try:
            if hasattr(UserInput, "from_dict"):
                return UserInput.from_dict(user_input_any)  # type: ignore[attr-defined]
        except Exception:
            pass

        # 2) module parser (프로젝트별 이름 차이 흡수)
        for fn_name in ("parse_user_input", "user_input_from_dict", "parse", "from_dict"):
            try:
                fn = getattr(rt, fn_name, None)
                if callable(fn):
                    out = fn(user_input_any)
                    if isinstance(out, (TouchStartEvent, TouchingEvent, TouchEndEvent)):
                        return out
            except Exception:
                pass

        # 3) event class from_dict (각 이벤트 클래스에서 제공하는 경우)
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

    # 그 외 타입은 지원하지 않음
    print("[WARN] Unsupported userInput type:", type(user_input_any))
    return None


# ============================================================
# AR Interaction Controller (schema-06)
# ============================================================

@dataclass
class _TouchContext:
    """
    TouchStart/Touching/TouchEnd 상태를 step 간 유지하기 위한 컨텍스트
    """
    active: bool = False
    target_name: Optional[str] = None
    action_point_local: Optional[chrono.ChVector3d] = None  # BODY-LOCAL
    start_finger_world: Optional[chrono.ChVector3d] = None
    last_finger_world: Optional[chrono.ChVector3d] = None
    camera_forward_world: Optional[chrono.ChVector3d] = None


class _ARInteractionController:
    """
    TouchStart/Touching/TouchEnd -> Drag torque + Damping

    ✅ 고친 포인트:
    - fixed body를 터치했더라도 "전체 return" 하지 않음.
      (드래그 토크만 스킵)
    - 감쇠는 "마지막으로 유효했던 회전 대상(last_dynamic_target)"에 계속 적용 가능.
      => 드래그 몇 초 주고 손 떼고 가만히 놔두는 테스트에 안정적.
    """

    # ---- Drag torque tuning ----
    # 손가락 드래그가 만들어내는 "토크"의 상한
    DRAG_TORQUE_MAX = 1.0

    # 드래그 각도(arc angle)가 이 값에 도달하면 토크가 최대치에 근접하도록 스케일링
    DRAG_ANGLE_REF = m.pi / 6.0

    # ---- Damping tuning ----
    # TouchEnd 이후 더 빨리 감쇠시키고 싶으면 LAMBDA_FREE를 키우면 됨.
    LAMBDA_FREE = 3.0
    # 드래그 중에는 약하게 감쇠
    LAMBDA_DRAG = 1.0

    # Snap deadzone: 일정 각속도 이하에서는 떨림 제거를 위해 "완전 정지"
    VEL_EPS_SNAP = 0.03

    def __init__(self) -> None:
        self.ctx = _TouchContext()
        # 마지막으로 "동적 바디"로 유효했던 타겟을 저장 (TouchEnd 이후 감쇠 유지용)
        self._last_dynamic_target: Optional[str] = None

    # ---------- input ingest ----------
    def ingest(self, user_input: UserInput, *, part_names: List[str]) -> None:
        """
        step()에서 들어오는 이벤트를 내부 컨텍스트로 저장한다.
        - TouchStart: 타겟/시작 손가락 위치 등을 저장
        - Touching  : 현재 손가락 위치 갱신
        - TouchEnd  : active off (하지만 감쇠는 계속 될 수 있음)
        """
        if isinstance(user_input, TouchStartEvent):
            target_name = user_input.payload.target.partName
            if not target_name:
                # partIndex fallback
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
            return

    # ---------- per-step compute ----------
    def compute_and_apply(self, *, sim: "Simulator", dt: float) -> None:
        """
        매 step마다 호출:
        1) (가능하면) 드래그 토크를 적용
        2) 항상 감쇠를 적용 (TouchEnd 후에도 last_dynamic_target에 적용 가능)
        """
        # ---- 어떤 바디에 감쇠를 적용할지 결정 ----
        # 1) 기본은 현재 target
        target_name = self.ctx.target_name

        # 2) target이 없으면: last_dynamic_target이 있으면 그걸로 감쇠만 유지
        if not target_name:
            target_name = self._last_dynamic_target

        if not target_name:
            return
        if target_name not in sim.bodies:
            return

        target_body = sim.bodies[target_name].body
        target_is_fixed = _is_fixed_body(target_body)

        # revolute 축(world) 추정 (없으면 body localZ -> world fallback)
        axis_world = sim._infer_revolute_axis_world_for_body(target_name)
        axis_world = _normalize(axis_world)
        if _norm(axis_world) < 1e-9:
            return

        # ---- dragging? ----
        dragging_now = (
            self.ctx.active
            and (self.ctx.start_finger_world is not None)
            and (self.ctx.last_finger_world is not None)
        )

        # ✅ fixed target이면 "드래그 토크"는 스킵하지만,
        # 감쇠는 last_dynamic_target에 계속 적용되도록 한다.
        if target_is_fixed:
            # fixed를 만졌다면, last_dynamic_target이 있으면 감쇠 대상만 그쪽으로 바꿔준다.
            if self._last_dynamic_target and (self._last_dynamic_target in sim.bodies):
                target_name_for_damp = self._last_dynamic_target
                target_body_for_damp = sim.bodies[target_name_for_damp].body

                # last_dynamic_target도 fixed면 어차피 의미 없으니 종료
                if _is_fixed_body(target_body_for_damp):
                    return

                # 감쇠는 last_dynamic_target에만 적용
                self._apply_exponential_damping(
                    body=target_body_for_damp,
                    axis_world=sim._infer_revolute_axis_world_for_body(target_name_for_damp),
                    dt=dt,
                    dragging_now=False,  # fixed 터치 중이라도 감쇠는 free로 처리
                )
            return

        # 여기까지 왔으면 target은 동적 바디 -> last_dynamic_target 갱신
        self._last_dynamic_target = target_name

        # 드래그 중이면 모터 해제 (있다면)
        # (speed=0 강제 등이 AR 드래그를 막는 상황 완화 목적)
        if dragging_now:
            sim._maybe_release_speed_motors_for_target(target_name)

        # 회전 중심: 기본 COM (필요 시 actionPointLocal을 world로 바꾸도록 확장 가능)
        center_world = target_body.GetPos()

        # ============================================================
        # 1) Drag torque (동적 바디에서만)
        # ============================================================
        if dragging_now:
            f0 = self.ctx.start_finger_world
            f1 = self.ctx.last_finger_world

            v0 = _sub(f0, center_world)
            v1 = _sub(f1, center_world)

            # 중심에서 충분히 떨어진 경우에만 의미있는 각도 계산 가능
            if _norm(v0) > 1e-6 and _norm(v1) > 1e-6:
                v0n = _normalize(v0)
                v1n = _normalize(v1)

                # 두 벡터 사이 각도
                c = _clamp(_dot(v0n, v1n), -1.0, 1.0)
                ang = m.acos(c)

                # 드래그가 만든 회전축(arc axis)
                arc_axis = _cross(v0n, v1n)
                arc_axis_n = _normalize(arc_axis)

                # arc_axis가 축과 유사한 방향이면 sign=+1 아니면 -1
                if _norm(arc_axis_n) > 1e-6 and ang > 1e-5:
                    sign = 1.0 if _dot(arc_axis_n, axis_world) >= 0.0 else -1.0

                    # ang -> [0,1] scale (REF에서 1에 근접)
                    s = _clamp(ang / self.DRAG_ANGLE_REF, 0.0, 1.0)

                    # 최종 드래그 토크(축 성분만)
                    tau_drag = _mul(axis_world, sign * self.DRAG_TORQUE_MAX * s)

                    # 디버깅 로그
                    print(
                        f"[AR][drag] target={target_name} ang={ang:.4f} s={s:.3f} "
                        f"tau=({tau_drag.x:.3f},{tau_drag.y:.3f},{tau_drag.z:.3f})"
                    )

                    _apply_torque_world(target_body, tau_drag)

        # ============================================================
        # 2) Exponential damping (항상 동적 타겟에 적용)
        # ============================================================
        self._apply_exponential_damping(
            body=target_body,
            axis_world=axis_world,
            dt=dt,
            dragging_now=dragging_now,
        )

    def _apply_exponential_damping(
        self,
        *,
        body: chrono.ChBody,
        axis_world: chrono.ChVector3d,
        dt: float,
        dragging_now: bool,
    ) -> None:
        """
        지수 감쇠(안정적):
            ω <- ω * exp(-λ dt)

        - revolute UX를 위해 축 성분만 남김
        - TouchEnd 이후 저속에서는 스냅 정지로 떨림 제거
        """
        axis_world = _normalize(axis_world)
        if _norm(axis_world) < 1e-9:
            return

        # 현재 world 각속도에서 축 성분만 추출
        w_world = _get_angvel_world(body)
        w_along = _dot(w_world, axis_world)

        # 드래그 중/후에 따라 감쇠계수 선택
        lam = self.LAMBDA_DRAG if dragging_now else self.LAMBDA_FREE

        # deadzone snap (손 뗀 뒤 떨림 제거)
        if (not dragging_now) and abs(w_along) < self.VEL_EPS_SNAP:
            _set_angvel_world(body, chrono.ChVector3d(0.0, 0.0, 0.0))
            return

        # exp(-λ dt)
        decay = m.exp(-lam * max(0.0, float(dt)))
        w_new_along = w_along * decay

        # 축 성분만 남겨서 set (다른 축 흔들림 제거)
        w_new_world = _mul(axis_world, w_new_along)
        _set_angvel_world(body, w_new_world)


# ============================================================
# Simulator
# ============================================================

class Simulator:
    """
    Simulator = 메타데이터 기반 PyChrono 시뮬 엔진 래퍼

    - create(info)로 생성
    - step(userInput) -> SimState 로 한 tick 진행
    - close()로 리소스 정리
    """

    # -----------------------------
    # Construction
    # -----------------------------
    def __init__(self, info: SimInfo):
        self.info: SimInfo = info

        # 내부 Chrono 구성은 sim_builder.py에서 수행
        built = build_system_from_scene(info.scene)

        self.sys: chrono.ChSystemNSC = built.sys
        self.bodies = built.bodies        # Dict[str, BuiltBody]
        self.joints = built.joints        # Dict[str, BuiltJoint]
        self.actuators = built.actuators  # Dict[str, BuiltActuator]

        self.sim_time: float = 0.0

        # 출력 순서 고정 (PartIndex 기반 통신을 위함)
        if getattr(info, "body_order", None):
            self._body_order = list(info.body_order)  # type: ignore[attr-defined]
        else:
            try:
                self._body_order = [b.name for b in info.scene.bodies]
            except Exception:
                self._body_order = sorted(self.bodies.keys())

        self.part_index: Dict[str, int] = {n: i for i, n in enumerate(self._body_order)}

        # AR interaction controller (schema-06)
        self._ar = _ARInteractionController()

        # speed motor 잠금 해제: 한번만 시도하도록 캐시
        self._released_speed_motors: set[str] = set()

    @classmethod
    def create(cls, info: SimInfo) -> "Simulator":
        return cls(info)

    # -----------------------------
    # Public API
    # -----------------------------
    def step(self, userInput: Optional[Any] = None) -> SimState:
        """
        한 스텝 진행:
        1) userInput(AR/서버 이벤트)을 actuator 명령 등으로 변환
        2) AR interaction (drag + damping)
        3) DoStepDynamics(dt)
        4) 현재 바디 포즈를 SimState로 반환
        """
        dt = float(self.info.options.dt)

        # 1) 입력 반영
        if userInput is not None:
            self._apply_user_input(userInput)

        # 1.5) AR interaction forces/torques
        #      - 입력이 없더라도 TouchEnd 이후 감쇠는 계속 적용될 수 있음
        self._ar.compute_and_apply(sim=self, dt=dt)

        # 2) 물리 스텝
        self.sys.DoStepDynamics(dt)
        self.sim_time += dt

        # 3) 상태 스냅샷
        parts: List[PartState] = []
        for name in self._body_order:
            b = self.bodies[name].body
            parts.append(PartState.from_chrono_body(b, name=name))

        return SimState(sim_time=self.sim_time, parts=parts)

    def close(self) -> None:
        """Chrono 리소스 정리"""
        try:
            self.sys.Clear()
        except Exception:
            pass

    # -----------------------------
    # Input handling (extensible)
    # -----------------------------
    def _apply_user_input(self, userInput: Any) -> None:
        """
        입력을 엔진에 반영하는 내부 함수.

        0) dict(JSON)/Any -> 이벤트 객체 변환 시도
        1) (legacy) userInput.motor_speeds / userInput.torque_cmds 형태
        2) (schema-06) TouchStart/Touching/TouchEnd 이벤트
           -> ARInteractionController에 전달
        """

        # ---- 0) dict(JSON)/Any -> 이벤트 객체로 먼저 변환 시도 ----
        coerced = _coerce_user_input_any(userInput)
        if coerced is not None:
            userInput = coerced

        # ------------------------------------------------------------
        # (A) legacy path: motor_speeds / torque_cmds
        # ------------------------------------------------------------
        motor_speeds = getattr(userInput, "motor_speeds", None)
        torque_cmds = getattr(userInput, "torque_cmds", None)

        if isinstance(motor_speeds, dict) or isinstance(torque_cmds, dict):
            # 1) rotation_speed actuator 업데이트
            if isinstance(motor_speeds, dict) and motor_speeds:
                for act_name, speed in motor_speeds.items():
                    built_act = self.actuators.get(act_name)
                    if built_act is None:
                        continue
                    if built_act.meta.type != "rotation_speed":
                        continue

                    motor = built_act.link  # chrono.ChLinkMotorRotationSpeed
                    try:
                        motor.SetSpeedFunction(chrono.ChFunctionConst(float(speed)))
                    except Exception:
                        pass

            # 2) rotation_torque actuator 업데이트(가능한 경우)
            if isinstance(torque_cmds, dict) and torque_cmds:
                for act_name, torque in torque_cmds.items():
                    built_act = self.actuators.get(act_name)
                    if built_act is None:
                        continue
                    if built_act.meta.type != "rotation_torque":
                        continue

                    motor = built_act.link  # chrono.ChLinkMotorRotationTorque (존재할 때만)
                    try:
                        motor.SetTorqueFunction(chrono.ChFunctionConst(float(torque)))
                    except Exception:
                        pass

            return

        # ------------------------------------------------------------
        # (B) schema-06 path: TouchStart/Touching/TouchEnd
        # ------------------------------------------------------------
        # 여기서 "target을 정확히 캐싱"하므로,
        # 베이스를 터치했는데 샤프트가 도는 류의 버그가 사라짐(이전엔 shaft를 하드코딩했기 때문).
        try:
            self._ar.ingest(userInput, part_names=self._body_order)
        except Exception as e:
            print("[WARN] ingest failed:", e)

    # -----------------------------
    # Axis inference helper
    # -----------------------------
    def _infer_revolute_axis_world_for_body(self, body_name: str) -> chrono.ChVector3d:
        """
        AR 인터랙션이 어떤 축으로 돌아야 하는지 결정.
        우선순위:
        1) revolute joint 중 body_name이 연결된 joint의 frame.localZ (WORLD)
        2) 없으면 body local-Z를 world로 회전시킨 축
        """
        # 1) joint frame 기반 (WORLD)
        try:
            for j in self.joints.values():
                jm = j.meta
                if getattr(jm, "type", None) != "revolute":
                    continue
                if getattr(jm, "body1", None) != body_name and getattr(jm, "body2", None) != body_name:
                    continue

                q = jm.frame.rot  # metadata_types.Quat (w,x,y,z)
                qch = chrono.ChQuaterniond(float(q.w), float(q.x), float(q.y), float(q.z))
                axis = _quat_rotate(qch, chrono.ChVector3d(0.0, 0.0, 1.0))
                if _norm(axis) > 1e-9:
                    return axis
        except Exception:
            pass

        # 2) fallback: body local-Z rotated to world
        try:
            body = self.bodies[body_name].body
            q = body.GetRot()
            return _quat_rotate(q, chrono.ChVector3d(0.0, 0.0, 1.0))
        except Exception:
            return chrono.ChVector3d(0.0, 0.0, 1.0)

    # ============================================================
    # rotation_speed 모터(속도강제)가 AR 드래그를 막는 문제 완화
    # ============================================================
    def _maybe_release_speed_motors_for_target(self, target_body_name: str) -> None:
        """
        target 바디에 연결된 revolute joint를 찾고,
        그 joint를 타겟으로 하는 rotation_speed actuator가 있으면
        '속도 강제'를 최대한 풀어본다.

        ※ Chrono 버전/바인딩마다 "disable" API가 달라서
          가능한 후보를 여러 개 시도하고 실패해도 조용히 넘어간다.
        """
        # 1) target이 포함된 revolute joint 이름들 수집
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

        # 2) 해당 joint를 타겟으로 하는 rotation_speed actuator 찾기
        for act_name, act in self.actuators.items():
            try:
                if act_name in self._released_speed_motors:
                    continue
                if getattr(act.meta, "type", None) != "rotation_speed":
                    continue

                target_joint = getattr(act.meta, "targetJoint", None)
                if target_joint not in joint_names:
                    continue

                motor = act.link  # chrono motor link

                done = False

                # a) SetDisabled(True)
                try:
                    if hasattr(motor, "SetDisabled"):
                        motor.SetDisabled(True)
                        done = True
                except Exception:
                    pass

                # b) SetActive(False)
                try:
                    if (not done) and hasattr(motor, "SetActive"):
                        motor.SetActive(False)
                        done = True
                except Exception:
                    pass

                # c) Enable(False)
                try:
                    if (not done) and hasattr(motor, "Enable"):
                        motor.Enable(False)
                        done = True
                except Exception:
                    pass

                # d) SetSpeedFunction(None)
                try:
                    if (not done) and hasattr(motor, "SetSpeedFunction"):
                        motor.SetSpeedFunction(None)  # type: ignore[arg-type]
                        done = True
                except Exception:
                    pass

                if done:
                    self._released_speed_motors.add(act_name)
                    print(f"[AR] released rotation_speed motor: {act_name} (targetJoint={target_joint})")

            except Exception:
                continue


# -----------------------------
# (선택) 간단한 수동 테스트용 런너
# -----------------------------
if __name__ == "__main__":
    info = SimInfo.from_json_file("resources/test_scene.json", dt=1e-3)  # 예시
    sim = Simulator.create(info)

    for _ in range(1000):
        state = sim.step(None)

    print("[sim] done. sim_time =", state.sim_time)
    sim.close()
