# simulator/runtime_types.py
# Runtime I/O protocol types (docs/06_runtime_input_schema.md, 07_runtime_output_schema.md)
#
# 목적
# - 서버/AR 팀과 합의한 "런타임 입력(UserInput)" / "런타임 출력(SimState)" 스키마를
#   Python에서 타입으로 고정해두는 파일.
# - 메타데이터(SceneMeta 등)와 성격이 다르므로 metadata_types.py와 분리.
#
# 핵심 원칙
# - 좌표계: Right-handed
# - 단위: meter, radian
# - 입력/출력은 JSON 직렬화 가능해야 함
# - 회전(Quaternion) 표기:
#   - 내부 표준: w,x,y,z
#   - 런타임 출력(rot): {w,x,y,z}  (docs/07 기준)
#
# 호환성(레거시) 지원:
# - 과거 프로토타입에서 rot를 e0/e1/e2/e3로 주고받던 흔적이 있어,
#   from_dict에서는 e0/e1/e2/e3도 fallback으로 받아준다.
# - 입력 스키마도 actionPoint/fingerPoint/z_direction 같은 레거시 키를 fallback으로 받아준다.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Union


# ============================================================
# Small utilities
# ============================================================

def _get_first(d: Dict[str, Any], keys: List[str], default: Any = None) -> Any:
    """dict에서 여러 후보 키 중 첫 번째로 존재하는 값을 반환."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _float_or_default(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _int_or_default(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return int(default)


def _chrono_vec_xyz(v: Any) -> Optional[tuple[float, float, float]]:
    """
    Chrono 벡터류(ChVector3d)가 바인딩에 따라
    - v.x / v.y / v.z 가 '속성'이거나
    - v.x() / v.y() / v.z() 가 '메서드'
    일 수 있어서 안전하게 (x,y,z)를 추출한다.

    runtime_types는 chrono를 import하지 않으므로 duck-typing만 사용.
    """
    if v is None:
        return None
    try:
        if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z"):
            x = getattr(v, "x")
            y = getattr(v, "y")
            z = getattr(v, "z")
            if callable(x):
                return (float(x()), float(y()), float(z()))
            return (float(x), float(y), float(z))
    except Exception:
        return None
    return None


# ============================================================
# Core runtime value objects
# ============================================================

@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Vec3":
        if not isinstance(d, dict):
            raise ValueError(f"Vec3 must be object, got: {type(d)}")
        return Vec3(float(d["x"]), float(d["y"]), float(d["z"]))

    def to_dict(self) -> Dict[str, float]:
        return {"x": float(self.x), "y": float(self.y), "z": float(self.z)}


@dataclass(frozen=True)
class QuatWXYZ:
    """내부 표준 쿼터니언: (w,x,y,z)"""
    w: float
    x: float
    y: float
    z: float

    @staticmethod
    def from_wxyz_list(v: List[float]) -> "QuatWXYZ":
        if not (isinstance(v, list) and len(v) == 4):
            raise ValueError(f"QuatWXYZ must be [w,x,y,z], got: {v}")
        return QuatWXYZ(float(v[0]), float(v[1]), float(v[2]), float(v[3]))

    @staticmethod
    def from_wxyz_dict(d: Dict[str, Any]) -> "QuatWXYZ":
        # docs/07: {"w":..,"x":..,"y":..,"z":..}
        return QuatWXYZ(float(d["w"]), float(d["x"]), float(d["y"]), float(d["z"]))

    @staticmethod
    def from_e0e1e2e3_dict(d: Dict[str, Any]) -> "QuatWXYZ":
        # legacy: {"e0":w,"e1":x,"e2":y,"e3":z}
        return QuatWXYZ(float(d["e0"]), float(d["e1"]), float(d["e2"]), float(d["e3"]))

    @staticmethod
    def from_any_dict(d: Dict[str, Any]) -> "QuatWXYZ":
        if not isinstance(d, dict):
            raise ValueError(f"Quaternion must be object, got: {type(d)}")

        # 우선 docs/07 (wxyz), 그 다음 legacy (e0..e3)
        if all(k in d for k in ("w", "x", "y", "z")):
            return QuatWXYZ.from_wxyz_dict(d)
        if all(k in d for k in ("e0", "e1", "e2", "e3")):
            return QuatWXYZ.from_e0e1e2e3_dict(d)
        raise ValueError(f"Quaternion must be wxyz or e0e1e2e3 dict, got keys={list(d.keys())}")

    def to_wxyz_dict(self) -> Dict[str, float]:
        # docs/07: {"w","x","y","z"}
        return {"w": float(self.w), "x": float(self.x), "y": float(self.y), "z": float(self.z)}

    def to_e0e1e2e3_dict(self) -> Dict[str, float]:
        # legacy export (필요 시)
        return {"e0": float(self.w), "e1": float(self.x), "e2": float(self.y), "e3": float(self.z)}


# ============================================================
# (1-3) Contact telemetry (optional, minimal)
# ============================================================

@dataclass(frozen=True)
class ContactPair:
    """
    가장 강한 접촉(또는 대표 접촉)의 pair 정보.
    - bodyA/bodyB: 파트 이름 (가능하면 SimState의 PartState.name과 동일)
    """
    bodyA: str
    bodyB: str

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ContactPair":
        if not isinstance(d, dict):
            raise ValueError(f"ContactPair must be object, got: {type(d)}")

        # 다양한 레거시 키 허용
        a = _get_first(d, ["bodyA", "a", "body1", "A", "nameA"], "")
        b = _get_first(d, ["bodyB", "b", "body2", "B", "nameB"], "")
        return ContactPair(bodyA=str(a), bodyB=str(b))

    def to_dict(self) -> Dict[str, Any]:
        return {"bodyA": str(self.bodyA), "bodyB": str(self.bodyB)}


@dataclass(frozen=True)
class ContactTelemetry:
    """
    docs/07 optional telemetry (최소 기능).

    - contact_count: 이 step에서 관측된 contact 개수(또는 접촉점 개수)
    - max_contact_force: 관측된 접촉 힘의 최대값 (N) (가능하면 normal force 기반)
    - max_pair: 최대 접촉을 만든 body pair (가능하면)
    """
    contact_count: int
    max_contact_force: float
    max_pair: Optional[ContactPair] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ContactTelemetry":
        if not isinstance(d, dict):
            raise ValueError(f"ContactTelemetry must be object, got: {type(d)}")

        # snake_case / camelCase 둘 다 수용
        cc = _int_or_default(_get_first(d, ["contact_count", "contactCount", "n_contacts", "nContacts"], 0), 0)
        mf = _float_or_default(_get_first(d, ["max_contact_force", "maxContactForce", "max_force", "maxForce"], 0.0), 0.0)

        mp_raw = _get_first(d, ["max_pair", "maxPair", "pair", "max_contact_pair"], None)
        mp = ContactPair.from_dict(mp_raw) if isinstance(mp_raw, dict) else None

        return ContactTelemetry(contact_count=int(cc), max_contact_force=float(mf), max_pair=mp)

    def to_dict(self) -> Dict[str, Any]:
        # docs/07 기본은 snake_case 유지
        out: Dict[str, Any] = {
            "contact_count": int(self.contact_count),
            "max_contact_force": float(self.max_contact_force),
        }
        if self.max_pair is not None:
            out["max_pair"] = self.max_pair.to_dict()
        return out


# ============================================================
# (3-1.3) Gear telemetry (optional, minimal)
# ============================================================

@dataclass(frozen=True)
class GearTelemetry:
    """
    3-1.3 gear 관련 최소 telemetry (런타임 디버그/진단용).

    - applied_efficiency: (0~1] 이번 step에서 적용(또는 사용할 예정인) 효율
    - loss_torque: 효율로 인해 손실로 간주한 토크 (N·m)
    - backlash_deadband: 백래시 데드밴드(근사에 사용) (rad 또는 main.py에서 합의한 단위)
    """
    applied_efficiency: float
    loss_torque: float
    backlash_deadband: float

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "GearTelemetry":
        if not isinstance(d, dict):
            raise ValueError(f"GearTelemetry must be object, got: {type(d)}")

        ae = _float_or_default(_get_first(d, ["applied_efficiency", "appliedEfficiency", "efficiency"], 1.0), 1.0)
        lt = _float_or_default(_get_first(d, ["loss_torque", "lossTorque", "loss"], 0.0), 0.0)
        bd = _float_or_default(_get_first(d, ["backlash_deadband", "backlashDeadband", "deadband", "backlash"], 0.0), 0.0)

        # guardrails (schema-level; main.py에서 추가 clamp 가능)
        ae = max(0.0, min(1.0, float(ae)))
        lt = float(lt)  # loss_torque는 부호를 허용(방향 진단용)할 수 있어 clamp 안 함
        bd = max(0.0, float(bd))

        return GearTelemetry(
            applied_efficiency=float(ae),
            loss_torque=float(lt),
            backlash_deadband=float(bd),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied_efficiency": float(self.applied_efficiency),
            "loss_torque": float(self.loss_torque),
            "backlash_deadband": float(self.backlash_deadband),
        }

@dataclass(frozen=True)
class AssemblyGuideTelemetry:
    """
    3-2.3 조립/스냅 보조 상태 telemetry.

    - activeSnap: 현재 이 guide가 활성 스냅 후보인지
    - snapCandidate: 현재 후보로 판단된 상대/가이드 이름
    - snapErrorPos: 목표 위치까지의 거리 오차 (m)
    - snapErrorAngle: 목표 각도까지의 오차 (rad)
    - snapMode: assist | snap
    """
    activeSnap: bool
    snapCandidate: Optional[str] = None
    snapErrorPos: float = 0.0
    snapErrorAngle: float = 0.0
    snapMode: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AssemblyGuideTelemetry":
        if not isinstance(d, dict):
            raise ValueError(f"AssemblyGuideTelemetry must be object, got: {type(d)}")

        active = bool(_get_first(d, ["activeSnap", "active_snap", "active"], False))
        cand = _get_first(d, ["snapCandidate", "snap_candidate", "candidate"], None)
        err_pos = _float_or_default(_get_first(d, ["snapErrorPos", "snap_error_pos", "errorPos"], 0.0), 0.0)
        err_ang = _float_or_default(_get_first(d, ["snapErrorAngle", "snap_error_angle", "errorAngle"], 0.0), 0.0)
        mode = _get_first(d, ["snapMode", "snap_mode", "mode"], None)

        return AssemblyGuideTelemetry(
            activeSnap=bool(active),
            snapCandidate=str(cand) if cand is not None else None,
            snapErrorPos=max(0.0, float(err_pos)),
            snapErrorAngle=max(0.0, float(err_ang)),
            snapMode=str(mode) if mode is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "activeSnap": bool(self.activeSnap),
            "snapErrorPos": float(self.snapErrorPos),
            "snapErrorAngle": float(self.snapErrorAngle),
        }
        if self.snapCandidate is not None:
            out["snapCandidate"] = str(self.snapCandidate)
        if self.snapMode is not None:
            out["snapMode"] = str(self.snapMode)
        return out

# ============================================================
# (3-3.1) Educational measurement / diagnostics telemetry
# ============================================================

@dataclass(frozen=True)
class JointTelemetry:
    """
    3-3.1 교육용 joint 측정 telemetry.

    - jointType: revolute | prismatic | fixed | ...
    - angle: revolute 계열 joint의 상대 각도 (rad)
    - position: prismatic 계열 joint의 상대 변위 (m)
    - angularVelocity: revolute 계열 상대 각속도 (rad/s)
    - linearVelocity: prismatic 계열 상대 속도 (m/s)
    - reactionForce: joint reaction force (WORLD 또는 main.py 합의 기준) (N)
    - reactionTorque: joint reaction torque (WORLD 또는 main.py 합의 기준) (N·m)
    - estimatedPower: 교육용 근사 파워
        * revolute: torque * angularVelocity
        * prismatic: force * linearVelocity
    """
    jointType: Optional[str] = None

    angle: Optional[float] = None
    position: Optional[float] = None

    angularVelocity: Optional[float] = None
    linearVelocity: Optional[float] = None

    reactionForce: Optional[Vec3] = None
    reactionTorque: Optional[Vec3] = None

    estimatedPower: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "JointTelemetry":
        if not isinstance(d, dict):
            raise ValueError(f"JointTelemetry must be object, got: {type(d)}")

        joint_type = _get_first(d, ["jointType", "joint_type", "type"], None)

        angle = _get_first(d, ["angle"], None)
        position = _get_first(d, ["position", "pos"], None)

        angular_velocity = _get_first(d, ["angularVelocity", "angular_velocity", "omega"], None)
        linear_velocity = _get_first(d, ["linearVelocity", "linear_velocity", "velocity", "vel"], None)

        rf_raw = _get_first(d, ["reactionForce", "reaction_force"], None)
        rt_raw = _get_first(d, ["reactionTorque", "reaction_torque"], None)

        ep = _get_first(d, ["estimatedPower", "estimated_power", "power"], None)

        return JointTelemetry(
            jointType=str(joint_type) if joint_type is not None else None,
            angle=float(angle) if angle is not None else None,
            position=float(position) if position is not None else None,
            angularVelocity=float(angular_velocity) if angular_velocity is not None else None,
            linearVelocity=float(linear_velocity) if linear_velocity is not None else None,
            reactionForce=Vec3.from_dict(rf_raw) if isinstance(rf_raw, dict) else None,
            reactionTorque=Vec3.from_dict(rt_raw) if isinstance(rt_raw, dict) else None,
            estimatedPower=float(ep) if ep is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.jointType is not None:
            out["jointType"] = str(self.jointType)
        if self.angle is not None:
            out["angle"] = float(self.angle)
        if self.position is not None:
            out["position"] = float(self.position)
        if self.angularVelocity is not None:
            out["angularVelocity"] = float(self.angularVelocity)
        if self.linearVelocity is not None:
            out["linearVelocity"] = float(self.linearVelocity)
        if self.reactionForce is not None:
            out["reactionForce"] = self.reactionForce.to_dict()
        if self.reactionTorque is not None:
            out["reactionTorque"] = self.reactionTorque.to_dict()
        if self.estimatedPower is not None:
            out["estimatedPower"] = float(self.estimatedPower)
        return out


@dataclass(frozen=True)
class ActuatorTelemetry:
    """
    3-3.1 교육용 actuator 측정 telemetry.

    - actuatorType: rotation_speed | rotation_torque | ...
    - targetJoint: 연결된 joint 이름
    - commandedSpeed: 명령 속도 (rad/s 또는 m/s)
    - commandedTorque: 명령 토크 (N·m)
    - appliedTorque: 실제/근사 적용 토크 (N·m)
    - estimatedPower: 교육용 근사 파워
    """
    actuatorType: Optional[str] = None
    targetJoint: Optional[str] = None

    commandedSpeed: Optional[float] = None
    commandedTorque: Optional[float] = None

    appliedTorque: Optional[float] = None
    estimatedPower: Optional[float] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ActuatorTelemetry":
        if not isinstance(d, dict):
            raise ValueError(f"ActuatorTelemetry must be object, got: {type(d)}")

        actuator_type = _get_first(d, ["actuatorType", "actuator_type", "type"], None)
        target_joint = _get_first(d, ["targetJoint", "target_joint", "joint"], None)

        commanded_speed = _get_first(d, ["commandedSpeed", "commanded_speed", "speed"], None)
        commanded_torque = _get_first(d, ["commandedTorque", "commanded_torque", "torque"], None)

        applied_torque = _get_first(d, ["appliedTorque", "applied_torque"], None)
        estimated_power = _get_first(d, ["estimatedPower", "estimated_power", "power"], None)

        return ActuatorTelemetry(
            actuatorType=str(actuator_type) if actuator_type is not None else None,
            targetJoint=str(target_joint) if target_joint is not None else None,
            commandedSpeed=float(commanded_speed) if commanded_speed is not None else None,
            commandedTorque=float(commanded_torque) if commanded_torque is not None else None,
            appliedTorque=float(applied_torque) if applied_torque is not None else None,
            estimatedPower=float(estimated_power) if estimated_power is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.actuatorType is not None:
            out["actuatorType"] = str(self.actuatorType)
        if self.targetJoint is not None:
            out["targetJoint"] = str(self.targetJoint)
        if self.commandedSpeed is not None:
            out["commandedSpeed"] = float(self.commandedSpeed)
        if self.commandedTorque is not None:
            out["commandedTorque"] = float(self.commandedTorque)
        if self.appliedTorque is not None:
            out["appliedTorque"] = float(self.appliedTorque)
        if self.estimatedPower is not None:
            out["estimatedPower"] = float(self.estimatedPower)
        return out


@dataclass(frozen=True)
class DiagnosticItem:
    """
    3-3.1 교육용 진단 항목.

    - code: 기계 판독용 진단 코드
    - severity: info | warn | error
    - message: 사람이 읽는 설명
    - target: 관련 joint/body/actuator 이름 등
    """
    code: str
    severity: str = "info"
    message: str = ""
    target: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DiagnosticItem":
        if not isinstance(d, dict):
            raise ValueError(f"DiagnosticItem must be object, got: {type(d)}")

        code = str(_get_first(d, ["code"], ""))
        severity = str(_get_first(d, ["severity", "level"], "info"))
        message = str(_get_first(d, ["message", "msg", "description"], ""))
        target = _get_first(d, ["target", "name", "joint", "body", "actuator"], None)

        return DiagnosticItem(
            code=code,
            severity=severity,
            message=message,
            target=str(target) if target is not None else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "code": str(self.code),
            "severity": str(self.severity),
            "message": str(self.message),
        }
        if self.target is not None:
            out["target"] = str(self.target)
        return out

@dataclass(frozen=True)
class InteractionTelemetry:
    """
    AR 인터랙션 상태 telemetry.

    - mode: rotate | spring 등 현재 인터랙션 모드
    - targetBody: 사용자가 선택한 body
    - driveBody: 실제 구동에 사용된 body
    - driveJoint: 선택된 구동 joint
    - axisWorld: 회전 축 (WORLD)
    - pivotWorld: 회전 중심 (WORLD)
    """
    mode: Optional[str] = None
    targetBody: Optional[str] = None
    driveBody: Optional[str] = None
    driveJoint: Optional[str] = None
    axisWorld: Optional[Vec3] = None
    pivotWorld: Optional[Vec3] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "InteractionTelemetry":
        if not isinstance(d, dict):
            raise ValueError(f"InteractionTelemetry must be object, got: {type(d)}")

        return InteractionTelemetry(
            mode=str(d["mode"]) if d.get("mode") is not None else None,
            targetBody=str(d["targetBody"]) if d.get("targetBody") is not None else None,
            driveBody=str(d["driveBody"]) if d.get("driveBody") is not None else None,
            driveJoint=str(d["driveJoint"]) if d.get("driveJoint") is not None else None,
            axisWorld=Vec3.from_dict(d["axisWorld"]) if isinstance(d.get("axisWorld"), dict) else None,
            pivotWorld=Vec3.from_dict(d["pivotWorld"]) if isinstance(d.get("pivotWorld"), dict) else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.mode is not None:
            out["mode"] = str(self.mode)
        if self.targetBody is not None:
            out["targetBody"] = str(self.targetBody)
        if self.driveBody is not None:
            out["driveBody"] = str(self.driveBody)
        if self.driveJoint is not None:
            out["driveJoint"] = str(self.driveJoint)
        if self.axisWorld is not None:
            out["axisWorld"] = self.axisWorld.to_dict()
        if self.pivotWorld is not None:
            out["pivotWorld"] = self.pivotWorld.to_dict()
        return out

# ============================================================
# Runtime Output (Server -> Client)
# ============================================================

@dataclass(frozen=True)
class PartState:
    """
    07_runtime_output_schema.md에서 정의할 "parts" 원자 단위.
    - name/pos/rot 는 WORLD 기준
    - rot는 {w,x,y,z}로 직렬화 (docs/07)
    """
    name: str
    pos: Vec3
    rot: QuatWXYZ

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PartState":
        # docs/07: {"name":..., "pos":{x,y,z}, "rot":{w,x,y,z}}
        if not isinstance(d, dict):
            raise ValueError(f"PartState must be object, got: {type(d)}")
        return PartState(
            name=str(d.get("name", "")),
            pos=Vec3.from_dict(d["pos"]),
            rot=QuatWXYZ.from_any_dict(d["rot"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        # docs/07 준수
        return {
            "name": str(self.name),
            "pos": self.pos.to_dict(),
            "rot": self.rot.to_wxyz_dict(),
        }

    @staticmethod
    def from_chrono_body(body: Any, *, name: str) -> "PartState":
        """
        Chrono body -> PartState 변환 헬퍼.
        - name: docs/07에서 요구하는 bodies[*].name 과 동일한 문자열
        - pos: WORLD (x,y,z)
        - rot: WORLD quaternion (w,x,y,z) == Chrono (e0,e1,e2,e3)

        ✅ FIX:
        - 바인딩에 따라 p.x가 값이 아니라 p.x()일 수 있어 안전 추출
        """
        p = body.GetPos()
        q = body.GetRot()  # Chrono: e0=w, e1=x, e2=y, e3=z

        xyz = _chrono_vec_xyz(p)
        if xyz is None:
            # 최후 fallback
            px = float(getattr(p, "x", 0.0)) if not callable(getattr(p, "x", None)) else float(p.x())
            py = float(getattr(p, "y", 0.0)) if not callable(getattr(p, "y", None)) else float(p.y())
            pz = float(getattr(p, "z", 0.0)) if not callable(getattr(p, "z", None)) else float(p.z())
        else:
            px, py, pz = xyz

        return PartState(
            name=str(name),
            pos=Vec3(float(px), float(py), float(pz)),
            rot=QuatWXYZ(float(q.e0), float(q.e1), float(q.e2), float(q.e3)),
        )

@dataclass(frozen=True)
class SimState:
    """
    서버가 클라이언트로 내보내는 상태 메시지.

    docs/07 기본:
    - sim_time: float
    - parts: List[PartState]

    docs/07 Optional:
    - partNames: List[str]  (index 안정성)
    - seq: int              (증가하는 시퀀스)
    - server_time_sec: float (서버 wall-clock timestamp, seconds)

    (1-3) Optional telemetry:
    - telemetry: ContactTelemetry

    (AR) Optional interaction telemetry:
    - interactionTelemetry: InteractionTelemetry

    (3-1.3) Optional gear telemetry:
    - gearTelemetry: Dict[str, GearTelemetry]   # key = gearPair name

    (3-2.3) Optional assembly guide telemetry:
    - assemblyTelemetry: Dict[str, AssemblyGuideTelemetry]  # key = assembly guide name

    (3-3.1) Optional educational telemetry:
    - jointTelemetry: Dict[str, JointTelemetry]      # key = joint name
    - actuatorTelemetry: Dict[str, ActuatorTelemetry] # key = actuator name
    - diagnostics: List[DiagnosticItem]

    (2-3.4) Optional build warnings:
    - warnings: List[str]
    """
    sim_time: float
    parts: List[PartState]

    # (Optional) index 안정성 / 디버깅용
    partNames: Optional[List[str]] = None
    seq: Optional[int] = None
    server_time_sec: Optional[float] = None

    # (Optional) contact telemetry
    telemetry: Optional[ContactTelemetry] = None

    # (Optional) AR interaction telemetry
    interactionTelemetry: Optional[InteractionTelemetry] = None

    # (Optional) gear telemetry (3-1.3)
    gearTelemetry: Optional[Dict[str, GearTelemetry]] = None

    # (Optional) assembly telemetry (3-2.3)
    assemblyTelemetry: Optional[Dict[str, AssemblyGuideTelemetry]] = None

    # (Optional) joint/actuator telemetry (3-3.1)
    jointTelemetry: Optional[Dict[str, JointTelemetry]] = None
    actuatorTelemetry: Optional[Dict[str, ActuatorTelemetry]] = None

    # (Optional) diagnostics (3-3.1)
    diagnostics: Optional[List[DiagnosticItem]] = None

    # (Optional) build warnings (e.g., joint limit best-effort unsupported)
    warnings: Optional[List[str]] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SimState":
        if not isinstance(d, dict):
            raise ValueError(f"SimState must be object, got: {type(d)}")

        sim_time = float(d["sim_time"])
        seq = int(d["seq"]) if "seq" in d and d["seq"] is not None else None
        server_time_sec = (
            float(d["server_time_sec"]) if "server_time_sec" in d and d["server_time_sec"] is not None else None
        )

        partNames = [str(x) for x in d.get("partNames", [])] if "partNames" in d else None
        raw_parts = d.get("parts", [])

        telemetry = None
        if "telemetry" in d and d["telemetry"] is not None:
            telemetry = ContactTelemetry.from_dict(d["telemetry"])

        interactionTelemetry = None
        if "interactionTelemetry" in d and d["interactionTelemetry"] is not None:
            interactionTelemetry = InteractionTelemetry.from_dict(d["interactionTelemetry"])

        gear_raw = _get_first(d, ["gearTelemetry", "gear_telemetry", "gear"], None)
        gearTelemetry: Optional[Dict[str, GearTelemetry]] = None
        if isinstance(gear_raw, dict):
            gt: Dict[str, GearTelemetry] = {}
            for k, v in gear_raw.items():
                if isinstance(v, dict):
                    gt[str(k)] = GearTelemetry.from_dict(v)
            gearTelemetry = gt

        assembly_raw = _get_first(d, ["assemblyTelemetry", "assembly_telemetry", "assembly"], None)
        assemblyTelemetry: Optional[Dict[str, AssemblyGuideTelemetry]] = None
        if isinstance(assembly_raw, dict):
            at: Dict[str, AssemblyGuideTelemetry] = {}
            for k, v in assembly_raw.items():
                if isinstance(v, dict):
                    at[str(k)] = AssemblyGuideTelemetry.from_dict(v)
            assemblyTelemetry = at

        joint_raw = _get_first(d, ["jointTelemetry", "joint_telemetry", "joints"], None)
        jointTelemetry: Optional[Dict[str, JointTelemetry]] = None
        if isinstance(joint_raw, dict):
            jt: Dict[str, JointTelemetry] = {}
            for k, v in joint_raw.items():
                if isinstance(v, dict):
                    jt[str(k)] = JointTelemetry.from_dict(v)
            jointTelemetry = jt

        actuator_raw = _get_first(d, ["actuatorTelemetry", "actuator_telemetry", "actuators"], None)
        actuatorTelemetry: Optional[Dict[str, ActuatorTelemetry]] = None
        if isinstance(actuator_raw, dict):
            at2: Dict[str, ActuatorTelemetry] = {}
            for k, v in actuator_raw.items():
                if isinstance(v, dict):
                    at2[str(k)] = ActuatorTelemetry.from_dict(v)
            actuatorTelemetry = at2

        diagnostics_raw = _get_first(d, ["diagnostics", "diagnosticItems", "diagnostic_items"], None)
        diagnostics: Optional[List[DiagnosticItem]] = None
        if isinstance(diagnostics_raw, list):
            diagnostics = [
                DiagnosticItem.from_dict(x)
                for x in diagnostics_raw
                if isinstance(x, dict)
            ]

        warnings_raw = _get_first(d, ["warnings", "buildWarnings"], None)
        warnings: Optional[List[str]] = None
        if isinstance(warnings_raw, list):
            warnings = [str(x) for x in warnings_raw if x is not None]

        parts: List[PartState] = []

        if isinstance(raw_parts, list) and raw_parts:
            if isinstance(raw_parts[0], dict) and "name" in raw_parts[0]:
                parts = [PartState.from_dict(p) for p in raw_parts]
            else:
                if partNames is None:
                    raise ValueError("SimState.parts has no 'name' field; requires 'partNames' to map indices.")
                if len(raw_parts) != len(partNames):
                    raise ValueError(
                        f"SimState.parts length ({len(raw_parts)}) must match partNames length ({len(partNames)}) in index-mapped mode."
                    )
                for nm, p in zip(partNames, raw_parts):
                    if not isinstance(p, dict):
                        raise ValueError(f"SimState.parts item must be object, got: {type(p)}")
                    parts.append(
                        PartState(
                            name=str(nm),
                            pos=Vec3.from_dict(p["pos"]),
                            rot=QuatWXYZ.from_any_dict(p["rot"]),
                        )
                    )
        else:
            parts = []

        return SimState(
            sim_time=sim_time,
            parts=parts,
            partNames=partNames,
            seq=seq,
            server_time_sec=server_time_sec,
            telemetry=telemetry,
            interactionTelemetry=interactionTelemetry,
            gearTelemetry=gearTelemetry,
            assemblyTelemetry=assemblyTelemetry,
            jointTelemetry=jointTelemetry,
            actuatorTelemetry=actuatorTelemetry,
            diagnostics=diagnostics,
            warnings=warnings,
        )

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "sim_time": float(self.sim_time),
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.partNames is not None:
            out["partNames"] = [str(x) for x in self.partNames]
        if self.seq is not None:
            out["seq"] = int(self.seq)
        if self.server_time_sec is not None:
            out["server_time_sec"] = float(self.server_time_sec)
        if self.telemetry is not None:
            out["telemetry"] = self.telemetry.to_dict()
        if self.interactionTelemetry is not None:
            out["interactionTelemetry"] = self.interactionTelemetry.to_dict()
        if self.gearTelemetry is not None:
            out["gearTelemetry"] = {str(k): v.to_dict() for k, v in self.gearTelemetry.items()}
        if self.assemblyTelemetry is not None:
            out["assemblyTelemetry"] = {str(k): v.to_dict() for k, v in self.assemblyTelemetry.items()}
        if self.jointTelemetry is not None:
            out["jointTelemetry"] = {str(k): v.to_dict() for k, v in self.jointTelemetry.items()}
        if self.actuatorTelemetry is not None:
            out["actuatorTelemetry"] = {str(k): v.to_dict() for k, v in self.actuatorTelemetry.items()}
        if self.diagnostics is not None:
            out["diagnostics"] = [x.to_dict() for x in self.diagnostics]
        if self.warnings is not None:
            out["warnings"] = [str(x) for x in self.warnings]
        return out


# ============================================================
# Runtime Input (Client -> Server)
# ============================================================

PartIndex = int


@dataclass(frozen=True)
class PartRef:
    """
    타겟 파트 지정.
    - docs/06: payload.target.partIndex / payload.target.partName (둘 다 optional)
    - 레거시: targetPartIndex / targetPartName 같은 키가 payload 최상단에 있던 버전도 fallback 지원
    """
    partIndex: Optional[PartIndex] = None
    partName: Optional[str] = None

    @staticmethod
    def from_any(d: Dict[str, Any]) -> "PartRef":
        if not isinstance(d, dict):
            raise ValueError(f"PartRef payload must be object, got: {type(d)}")

        # 1) docs/06: {"target": {"partIndex":..,"partName":..}}
        if "target" in d and isinstance(d["target"], dict):
            t = d["target"]
            return PartRef(
                partIndex=int(t["partIndex"]) if "partIndex" in t and t["partIndex"] is not None else None,
                partName=str(t["partName"]) if "partName" in t and t["partName"] is not None else None,
            )

        # 2) 레거시 형태: {"targetPartIndex": 3} / {"targetPartName": "gear_A"}
        if "targetPartIndex" in d or "targetPartName" in d:
            return PartRef(
                partIndex=int(d["targetPartIndex"]) if "targetPartIndex" in d and d["targetPartIndex"] is not None else None,
                partName=str(d["targetPartName"]) if "targetPartName" in d and d["targetPartName"] is not None else None,
            )

        # 3) 확장 형태(예전 코드): {"partIndex": 3} / {"partName": "gear_A"}
        return PartRef(
            partIndex=int(d["partIndex"]) if "partIndex" in d and d["partIndex"] is not None else None,
            partName=str(d["partName"]) if "partName" in d and d["partName"] is not None else None,
        )

    def to_target_dict(self) -> Dict[str, Any]:
        # docs/06 준수: payload.target = {partIndex?, partName?}
        t: Dict[str, Any] = {}
        if self.partIndex is not None:
            t["partIndex"] = int(self.partIndex)
        if self.partName is not None:
            t["partName"] = str(self.partName)
        return {"target": t}


# ---- Common optional meta fields (docs/06 Recommended) ----

@dataclass(frozen=True)
class InputMeta:
    interactionId: Optional[str] = None
    timestampSec: Optional[float] = None
    seq: Optional[int] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "InputMeta":
        if not isinstance(d, dict):
            raise ValueError(f"InputMeta must be object, got: {type(d)}")
        interactionId = str(d["interactionId"]) if "interactionId" in d and d["interactionId"] is not None else None
        timestampSec = float(d["timestampSec"]) if "timestampSec" in d and d["timestampSec"] is not None else None
        seq = int(d["seq"]) if "seq" in d and d["seq"] is not None else None
        return InputMeta(interactionId=interactionId, timestampSec=timestampSec, seq=seq)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.interactionId is not None:
            out["interactionId"] = str(self.interactionId)
        if self.timestampSec is not None:
            out["timestampSec"] = float(self.timestampSec)
        if self.seq is not None:
            out["seq"] = int(self.seq)
        return out


@dataclass(frozen=True)
class TouchStartPayload:
    # docs/06
    target: PartRef
    actionPointLocal: Vec3        # BODY-LOCAL
    fingerPointWorld: Vec3        # WORLD
    cameraForwardWorld: Vec3      # WORLD (camera forward)

    # docs/06 recommended optional fields
    meta: InputMeta = InputMeta()

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchStartPayload":
        if not isinstance(d, dict):
            raise ValueError(f"TouchStartPayload must be object, got: {type(d)}")

        target = PartRef.from_any(d)

        # docs/06 keys (preferred)
        if "actionPointLocal" in d:
            ap = Vec3.from_dict(d["actionPointLocal"])
        else:
            # legacy fallback
            ap = Vec3.from_dict(d.get("actionPoint", {"x": 0, "y": 0, "z": 0}))

        if "fingerPointWorld" in d:
            fp = Vec3.from_dict(d["fingerPointWorld"])
        else:
            fp = Vec3.from_dict(d.get("fingerPoint", {"x": 0, "y": 0, "z": 0}))

        if "cameraForwardWorld" in d:
            cf = Vec3.from_dict(d["cameraForwardWorld"])
        else:
            cf = Vec3.from_dict(d.get("z_direction", {"x": 0, "y": 0, "z": 1}))

        meta = InputMeta.from_dict(d)

        return TouchStartPayload(
            target=target,
            actionPointLocal=ap,
            fingerPointWorld=fp,
            cameraForwardWorld=cf,
            meta=meta,
        )

    def to_dict(self) -> Dict[str, Any]:
        # docs/06 준수
        out: Dict[str, Any] = {
            **self.target.to_target_dict(),
            "actionPointLocal": self.actionPointLocal.to_dict(),
            "fingerPointWorld": self.fingerPointWorld.to_dict(),
            "cameraForwardWorld": self.cameraForwardWorld.to_dict(),
            **self.meta.to_dict(),
        }
        return out

    # 레거시 코드 호환용 프로퍼티
    @property
    def interactionId(self) -> Optional[str]:
        return self.meta.interactionId

    @property
    def timestampSec(self) -> Optional[float]:
        return self.meta.timestampSec

    @property
    def seq(self) -> Optional[int]:
        return self.meta.seq

    @property
    def actionPoint(self) -> Vec3:
        return self.actionPointLocal

    @property
    def fingerPoint(self) -> Vec3:
        return self.fingerPointWorld

    @property
    def z_direction(self) -> Vec3:
        return self.cameraForwardWorld


@dataclass(frozen=True)
class TouchingPayload:
    # docs/06
    fingerPointWorld: Vec3      # WORLD
    cameraForwardWorld: Vec3    # WORLD

    # docs/06 recommended: target or interactionId
    target: Optional[PartRef] = None
    meta: InputMeta = InputMeta()

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchingPayload":
        if not isinstance(d, dict):
            raise ValueError(f"TouchingPayload must be object, got: {type(d)}")

        if "fingerPointWorld" in d:
            fp = Vec3.from_dict(d["fingerPointWorld"])
        else:
            fp = Vec3.from_dict(d.get("fingerPoint", {"x": 0, "y": 0, "z": 0}))

        if "cameraForwardWorld" in d:
            cf = Vec3.from_dict(d["cameraForwardWorld"])
        else:
            cf = Vec3.from_dict(d.get("z_direction", {"x": 0, "y": 0, "z": 1}))

        # target is optional (recommended in docs/06)
        target = (
            PartRef.from_any(d)
            if ("target" in d or "targetPartIndex" in d or "targetPartName" in d or "partIndex" in d or "partName" in d)
            else None
        )
        meta = InputMeta.from_dict(d)

        return TouchingPayload(
            fingerPointWorld=fp,
            cameraForwardWorld=cf,
            target=target,
            meta=meta,
        )

    def to_dict(self) -> Dict[str, Any]:
        # docs/06 준수
        out: Dict[str, Any] = {
            "fingerPointWorld": self.fingerPointWorld.to_dict(),
            "cameraForwardWorld": self.cameraForwardWorld.to_dict(),
            **self.meta.to_dict(),
        }
        if self.target is not None:
            out.update(self.target.to_target_dict())
        return out

    # 레거시 코드 호환용 프로퍼티
    @property
    def interactionId(self) -> Optional[str]:
        return self.meta.interactionId

    @property
    def timestampSec(self) -> Optional[float]:
        return self.meta.timestampSec

    @property
    def seq(self) -> Optional[int]:
        return self.meta.seq

    @property
    def fingerPoint(self) -> Vec3:
        return self.fingerPointWorld

    @property
    def z_direction(self) -> Vec3:
        return self.cameraForwardWorld


@dataclass(frozen=True)
class TouchEndPayload:
    # docs/06 recommended: target or interactionId
    target: Optional[PartRef] = None
    meta: InputMeta = InputMeta()

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchEndPayload":
        if not isinstance(d, dict):
            # TouchEnd는 payload {}가 일반적이지만, None이면 {}로 취급
            d = {}

        target = (
            PartRef.from_any(d)
            if ("target" in d or "targetPartIndex" in d or "targetPartName" in d or "partIndex" in d or "partName" in d)
            else None
        )
        meta = InputMeta.from_dict(d)

        return TouchEndPayload(target=target, meta=meta)

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            **self.meta.to_dict(),
        }
        if self.target is not None:
            out.update(self.target.to_target_dict())
        return out

    @property
    def interactionId(self) -> Optional[str]:
        return self.meta.interactionId

    @property
    def timestampSec(self) -> Optional[float]:
        return self.meta.timestampSec

    @property
    def seq(self) -> Optional[int]:
        return self.meta.seq


# ---- Event wrappers (discriminated union) ----

TouchEventType = Literal["TouchStart", "Touching", "TouchEnd"]


@dataclass(frozen=True)
class TouchStartEvent:
    type: Literal["TouchStart"]
    payload: TouchStartPayload

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchStartEvent":
        return TouchStartEvent(type="TouchStart", payload=TouchStartPayload.from_dict(d.get("payload", {})))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "TouchStart", "payload": self.payload.to_dict()}


@dataclass(frozen=True)
class TouchingEvent:
    type: Literal["Touching"]
    payload: TouchingPayload

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchingEvent":
        return TouchingEvent(type="Touching", payload=TouchingPayload.from_dict(d.get("payload", {})))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "Touching", "payload": self.payload.to_dict()}


@dataclass(frozen=True)
class TouchEndEvent:
    type: Literal["TouchEnd"]
    payload: TouchEndPayload

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TouchEndEvent":
        return TouchEndEvent(type="TouchEnd", payload=TouchEndPayload.from_dict(d.get("payload", {})))

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "TouchEnd", "payload": self.payload.to_dict()}


UserInput = Union[TouchStartEvent, TouchingEvent, TouchEndEvent]


def user_input_from_dict(d: Dict[str, Any]) -> UserInput:
    """
    런타임 입력 dict(JSON)을 UserInput 타입으로 파싱하는 단일 엔트리.
    서버/엔진 코드에서는 이 함수만 호출하면 됨.
    """
    if not isinstance(d, dict):
        raise ValueError(f"UserInput must be object, got: {type(d)}")

    t = d.get("type")
    if t == "TouchStart":
        return TouchStartEvent.from_dict(d)
    if t == "Touching":
        return TouchingEvent.from_dict(d)
    if t == "TouchEnd":
        return TouchEndEvent.from_dict(d)
    raise ValueError(f"Unknown UserInput.type: {t}")


def user_input_to_dict(ev: UserInput) -> Dict[str, Any]:
    """UserInput -> JSON dict"""
    return ev.to_dict()


# ============================================================
# (Optional) helper for index-based protocols
# ============================================================

def resolve_target_part_name(
    event: UserInput,
    part_names: List[str],
) -> Optional[str]:
    """
    PartIndex 기반 입력을 name으로 해석하고 싶을 때 사용.
    - part_names는 SimState.parts와 동일한 순서의 이름 배열(엔진이 제공/합의)
    """
    # TouchStart: payload.target
    if isinstance(event, TouchStartEvent):
        if event.payload.target.partName:
            return event.payload.target.partName

        idx = event.payload.target.partIndex
        if idx is None:
            return None
        if 0 <= idx < len(part_names):
            return part_names[idx]
        return None

    # Touching: optional payload.target
    if isinstance(event, TouchingEvent):
        if event.payload.target is None:
            return None
        if event.payload.target.partName:
            return event.payload.target.partName
        idx = event.payload.target.partIndex
        if idx is None:
            return None
        if 0 <= idx < len(part_names):
            return part_names[idx]
        return None

    # TouchEnd: optional payload.target
    if isinstance(event, TouchEndEvent):
        if event.payload.target is None:
            return None
        if event.payload.target.partName:
            return event.payload.target.partName
        idx = event.payload.target.partIndex
        if idx is None:
            return None
        if 0 <= idx < len(part_names):
            return part_names[idx]
        return None

    return None