"""
interface.py

Simulation Engine <-> Server / AR Interface Specification

This file defines the data contract used by the Python simulation engine.

This is NOT the simulation engine implementation.
Actual implementation entry points are:

- simulator.SimInfo.SimInfo
- simulator.SimInfo.SimOptions
- simulator.main.Simulator
- simulator.runtime_types.UserInput
- simulator.runtime_types.SimState

External modules should treat this file as a readable contract/reference.
All data must be JSON-serializable.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Union


# =========================================================
# Core Types
# =========================================================

@dataclass
class Vec3:
    x: float
    y: float
    z: float


@dataclass
class Quat:
    w: float
    x: float
    y: float
    z: float


@dataclass
class Pose:
    pos: Vec3
    rot: Quat


# =========================================================
# Scene Metadata Input
# =========================================================

@dataclass
class SceneInput:
    """
    Initial scene metadata.

    This maps to metadata_types.SceneMeta.
    """

    sceneName: str
    gravity: Vec3

    bodies: List[Dict[str, Any]]
    joints: List[Dict[str, Any]]

    gearPairs: Optional[List[Dict[str, Any]]] = None
    actuators: Optional[List[Dict[str, Any]]] = None

    collisionFilter: Optional[Dict[str, Any]] = None
    assemblyGuides: Optional[List[Dict[str, Any]]] = None


# =========================================================
# Simulation Options
# =========================================================

@dataclass
class SimOptionsInput:
    """
    Runtime / build options.

    This maps to SimInfo.SimOptions.
    """

    dt: float = 1.0 / 60.0

    allow_obj_auto_approx: bool = True
    strict_no_inference: bool = False
    emit_part_names: bool = True

    enable_contact_telemetry: bool = False
    max_contact_points_report: int = 256

    physics_preset: Literal["FAST", "DEFAULT", "ROBUST", "SMC_DEFAULT"] = "DEFAULT"
    contact_method: Optional[Literal["NSC", "SMC"]] = None

    solver: Optional[str] = None
    solver_max_iters: Optional[int] = None
    solver_tolerance: Optional[float] = None

    auto_inertia_enabled: bool = True
    debug_auto_inertia: bool = False
    debug_joint_limits: bool = False
    debug_warnings: bool = True
    joint_limits_soft_enable: bool = False


@dataclass
class SimulatorCreateInput:
    """
    Used once at initialization.
    """

    scene: SceneInput
    options: SimOptionsInput
    body_order: Optional[List[str]] = None


# =========================================================
# Runtime Input
# =========================================================

TargetRef = Dict[str, Union[int, str]]
# Preferred:
# { "partName": "shaft" }
# Also supported:
# { "partIndex": 0 }


@dataclass
class TouchStart:
    type: Literal["TouchStart"]
    target: TargetRef

    actionPointLocal: Vec3
    fingerPointWorld: Vec3
    cameraForwardWorld: Vec3

    interactionId: Optional[str] = None
    timestampSec: Optional[float] = None
    seq: Optional[int] = None


@dataclass
class Touching:
    type: Literal["Touching"]

    fingerPointWorld: Vec3
    cameraForwardWorld: Vec3

    target: Optional[TargetRef] = None
    interactionId: Optional[str] = None
    timestampSec: Optional[float] = None
    seq: Optional[int] = None


@dataclass
class TouchEnd:
    type: Literal["TouchEnd"]

    target: Optional[TargetRef] = None
    interactionId: Optional[str] = None
    timestampSec: Optional[float] = None
    seq: Optional[int] = None


UserInput = Union[TouchStart, Touching, TouchEnd]


# =========================================================
# Runtime Output
# =========================================================

@dataclass
class PartState:
    name: str
    pos: Vec3
    rot: Quat


@dataclass
class ContactPair:
    bodyA: str
    bodyB: str


@dataclass
class ContactTelemetry:
    contact_count: int
    max_contact_force: float
    max_pair: Optional[ContactPair] = None


@dataclass
class InteractionTelemetry:
    mode: Optional[str] = None
    targetBody: Optional[str] = None
    driveBody: Optional[str] = None
    driveJoint: Optional[str] = None
    axisWorld: Optional[Vec3] = None
    pivotWorld: Optional[Vec3] = None


@dataclass
class GearTelemetry:
    applied_efficiency: float
    loss_torque: float
    backlash_deadband: float


@dataclass
class AssemblyGuideTelemetry:
    activeSnap: bool
    snapCandidate: Optional[str] = None
    snapErrorPos: float = 0.0
    snapErrorAngle: float = 0.0
    snapMode: Optional[str] = None


@dataclass
class JointTelemetry:
    jointType: Optional[str] = None
    angle: Optional[float] = None
    position: Optional[float] = None
    angularVelocity: Optional[float] = None
    linearVelocity: Optional[float] = None
    reactionForce: Optional[Vec3] = None
    reactionTorque: Optional[Vec3] = None
    estimatedPower: Optional[float] = None


@dataclass
class ActuatorTelemetry:
    actuatorType: Optional[str] = None
    targetJoint: Optional[str] = None
    commandedSpeed: Optional[float] = None
    commandedTorque: Optional[float] = None
    appliedTorque: Optional[float] = None
    estimatedPower: Optional[float] = None


@dataclass
class DiagnosticItem:
    code: str
    severity: Literal["info", "warn", "error"] = "info"
    message: str = ""
    target: Optional[str] = None


@dataclass
class SimState:
    sim_time: float
    parts: List[PartState]

    partNames: Optional[List[str]] = None
    seq: Optional[int] = None
    server_time_sec: Optional[float] = None

    telemetry: Optional[ContactTelemetry] = None
    interactionTelemetry: Optional[InteractionTelemetry] = None

    gearTelemetry: Optional[Dict[str, GearTelemetry]] = None
    assemblyTelemetry: Optional[Dict[str, AssemblyGuideTelemetry]] = None
    jointTelemetry: Optional[Dict[str, JointTelemetry]] = None
    actuatorTelemetry: Optional[Dict[str, ActuatorTelemetry]] = None

    diagnostics: Optional[List[DiagnosticItem]] = None
    warnings: Optional[List[str]] = None


# =========================================================
# Actual External API Shape
# =========================================================

class Simulator:
    """
    External shape of the Python simulation engine.

    Actual implementation:
    - simulator.main.Simulator
    """

    @staticmethod
    def create(info: Any) -> "Simulator":
        """
        info should be simulator.SimInfo.SimInfo.

        Typical flow:
        - Scene JSON
        - SceneMeta.from_dict(...)
        - SimInfo(scene, options, body_order)
        - Simulator.create(info)
        """
        raise NotImplementedError

    def step(self, user_input: Optional[Union[UserInput, Dict[str, Any]]]) -> SimState:
        """
        Advance simulation by one step.

        user_input may be:
        - None
        - TouchStart / Touching / TouchEnd object
        - dict matching runtime_types.user_input_from_dict(...)
        """
        raise NotImplementedError

    def close(self) -> None:
        """
        Release Chrono resources.
        """
        raise NotImplementedError


# =========================================================
# Conventions
# =========================================================

"""
Coordinate System:
- Right-handed

Units:
- Length: meter
- Mass: kilogram
- Time: second
- Angle: radian
- Force: N
- Torque: N·m

Quaternion:
- (w, x, y, z)

Frames:
- body pose: WORLD
- joint frame: WORLD
- actionPointLocal: BODY-LOCAL
- fingerPointWorld: WORLD
- cameraForwardWorld: WORLD

Target Identification:
- Prefer partName
- partIndex is supported when partNames ordering is shared

Input Philosophy:
- UserInput expresses intent
- The simulation engine converts intent into torque / force internally

Collision:
- primitive
- compound
- auto
- none / null

Separation:
- CAD / Server / AR / Simulation are decoupled by JSON contracts
"""


# =========================================================
# JSON Examples
# =========================================================

SCENE_INPUT_AR_ROTATE = {
    "sceneName": "rotate_external_like_no_wall",
    "gravity": {"x": 0.0, "y": -9.81, "z": 0.0},

    "bodies": [
        {
            "name": "base",
            "category": "base",
            "pose": {
                "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
            },
            "geometry": {
                "visual": {
                    "kind": "mesh",
                    "file": "meshes/base.obj",
                    "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                    "offset": {
                        "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
                        "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                    },
                },
                "collision": None,
            },
            "mechanical": {
                "fixed": True,
                "mass": 1.0,
                "inertia": {
                    "mode": "explicit",
                    "Ixx": 0.01,
                    "Iyy": 0.01,
                    "Izz": 0.01,
                },
            },
        },
        {
            "name": "shaft",
            "category": "shaft",
            "pose": {
                "pos": {"x": 0.0, "y": 0.0, "z": 0.03},
                "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
            },
            "geometry": {
                "visual": {
                    "kind": "mesh",
                    "file": "meshes/shaft.obj",
                    "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                    "offset": {
                        "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
                        "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
                    },
                },
                "collision": "auto",
            },
            "mechanical": {
                "fixed": False,
                "mass": 1.0,
                "inertia": {
                    "mode": "explicit",
                    "Ixx": 0.01,
                    "Iyy": 0.01,
                    "Izz": 0.01,
                },
            },
        },
    ],

    "joints": [
        {
            "name": "base_shaft_rev",
            "type": "revolute",
            "body1": "base",
            "body2": "shaft",
            "frame": {
                "pos": {"x": 0.0, "y": 0.0, "z": 0.03},
                "rot": {"w": 0.7071, "x": 0.0, "y": 0.7071, "z": 0.0},
            },
        }
    ],

    "gearPairs": [],
    "actuators": [],
}


USER_INPUT_TOUCH_START = {
    "type": "TouchStart",
    "payload": {
        "target": {"partName": "shaft"},
        "actionPointLocal": {"x": 0.0, "y": 0.0, "z": 0.0},
        "fingerPointWorld": {"x": 0.05, "y": 0.04, "z": -0.02},
        "cameraForwardWorld": {"x": 0.0, "y": 0.0, "z": -1.0},
    },
}

USER_INPUT_TOUCHING = {
    "type": "Touching",
    "payload": {
        "target": {"partName": "shaft"},
        "fingerPointWorld": {"x": 0.05, "y": 0.05, "z": -0.01},
        "cameraForwardWorld": {"x": 0.0, "y": 0.0, "z": -1.0},
    },
}

USER_INPUT_TOUCH_END = {
    "type": "TouchEnd",
    "payload": {
        "target": {"partName": "shaft"},
    },
}


SIM_STATE_EXAMPLE = {
    "sim_time": 0.125,
    "parts": [
        {
            "name": "base",
            "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
            "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
        },
        {
            "name": "shaft",
            "pos": {"x": 0.0, "y": 0.0, "z": 0.03},
            "rot": {"w": 0.998, "x": 0.0, "y": 0.0, "z": 0.062},
        },
    ],
    "partNames": ["base", "shaft"],
    "interactionTelemetry": {
        "mode": "rotate",
        "targetBody": "shaft",
        "driveBody": "shaft",
        "driveJoint": "base_shaft_rev",
        "axisWorld": {"x": 0.0, "y": 0.0, "z": 1.0},
        "pivotWorld": {"x": 0.0, "y": 0.0, "z": 0.03},
    },
    "diagnostics": [
        {
            "code": "INVALID_INERTIA",
            "severity": "warn",
            "message": "Body inertia value may cause abnormal rotation response.",
            "target": "shaft",
        }
    ],
}


# =========================================================
# Usage Notes
# =========================================================

"""
Typical Python-side flow:

from simulator.SimInfo import SimInfo, SimOptions
from simulator.main import Simulator

info = SimInfo.from_dict(
    SCENE_INPUT_AR_ROTATE,
    options=SimOptions(
        dt=1.0 / 60.0,
        emit_part_names=True,
        allow_obj_auto_approx=True,
    ),
)

sim = Simulator.create(info)
state = sim.step(USER_INPUT_TOUCH_START)
state = sim.step(USER_INPUT_TOUCHING)
state = sim.step(USER_INPUT_TOUCH_END)
sim.close()

Rust-side flow:
- Serialize Scene metadata
- Build SimInfo through Python
- Call Simulator.create(info)
- Pass UserInput dict to Simulator.step(...)
- Convert SimState.parts to ObjectTransform
"""