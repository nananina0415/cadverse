"""
interface.py

Simulation Engine <-> Server (Rust) Interface Specification

This file defines:
1) Scene Input (initial metadata)
2) Runtime Input (User interaction events)
3) Simulation Output (SimState)

⚠️ This is NOT the actual engine implementation.
⚠️ This is a CONTRACT FILE for cross-language integration.

All data must be JSON-serializable.
"""

from dataclasses import dataclass
from typing import List, Optional, Union, Literal, Dict, Any


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
# Scene Input (Initial)
# =========================================================

@dataclass
class SceneInput:
    """
    Initial scene metadata (from CAD / JSON)

    This maps to SceneMeta in simulation engine.
    """

    sceneName: str
    gravity: Vec3

    bodies: List[Dict[str, Any]]
    joints: List[Dict[str, Any]]
    gearPairs: Optional[List[Dict[str, Any]]] = None
    actuators: Optional[List[Dict[str, Any]]] = None

    # optional extensions
    collisionFilter: Optional[Dict[str, Any]] = None
    assemblyGuides: Optional[List[Dict[str, Any]]] = None


# =========================================================
# Simulation Options
# =========================================================

@dataclass
class SimOptions:
    """
    Simulation runtime configuration
    """

    dt: float

    # behavior flags
    allow_obj_auto_approx: bool = True
    strict_no_inference: bool = False

    # output options
    emit_part_names: bool = True
    enable_contact_telemetry: bool = False

    # physics presets
    physics_preset: Literal[
        "FAST", "DEFAULT", "ROBUST", "SMC_DEFAULT"
    ] = "DEFAULT"

    contact_method: Literal["NSC", "SMC"] = "NSC"


# =========================================================
# Simulator Init Contract
# =========================================================

@dataclass
class SimulatorCreateInput:
    """
    Used once at initialization
    """

    scene: SceneInput
    options: SimOptions


# =========================================================
# Runtime Input (AR / Server)
# =========================================================

TargetRef = Dict[str, Union[int, str]]
# example:
# { "partIndex": 0 } or { "partName": "shaft" }


# ---------------------------
# Touch Events
# ---------------------------

@dataclass
class TouchStart:
    type: Literal["TouchStart"]

    target: TargetRef

    actionPointLocal: Vec3
    fingerPointWorld: Vec3
    cameraForwardWorld: Vec3

    # optional metadata
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
# Output (Simulation State)
# =========================================================

@dataclass
class PartState:
    """
    Per-body state (WORLD coordinates)
    """

    name: str
    pos: Vec3
    rot: Quat


@dataclass
class SimState:
    """
    Output from Simulator.step()
    """

    sim_time: float
    parts: List[PartState]

    # optional metadata
    seq: Optional[int] = None
    server_time_sec: Optional[float] = None

    # mapping stability
    partNames: Optional[List[str]] = None

    # telemetry (optional)
    telemetry: Optional[Dict[str, Any]] = None
    jointTelemetry: Optional[Dict[str, Any]] = None
    actuatorTelemetry: Optional[Dict[str, Any]] = None

    diagnostics: Optional[Dict[str, Any]] = None
    warnings: Optional[List[str]] = None


# =========================================================
# Simulator External API (IMPORTANT)
# =========================================================

class Simulator:
    """
    Python Simulation Engine External Interface

    Rust server MUST use ONLY this interface.
    """

    @staticmethod
    def create(input: SimulatorCreateInput) -> "Simulator":
        """
        Initialize simulation

        Internally:
        SceneInput -> SceneMeta -> PyChrono system
        """
        raise NotImplementedError

    def step(self, user_input: Optional[UserInput]) -> SimState:
        """
        Advance simulation by one step (dt)

        Flow:
        1. Parse user_input
        2. Apply control (torque / motor / AR interaction)
        3. DoStepDynamics(dt)
        4. Return SimState
        """
        raise NotImplementedError

    def close(self) -> None:
        """
        Release resources
        """
        raise NotImplementedError


# =========================================================
# IMPORTANT CONVENTIONS
# =========================================================

"""
Coordinate System:
- Right-handed
- Units: meter, kg, second, rad

Quaternion:
- (w, x, y, z)

Frames:
- WORLD coordinates for outputs
- BODY-LOCAL coordinates for actionPointLocal

Index Mapping:
- parts[i] corresponds to partIndex i
- Use partNames for stable mapping if needed

Input Philosophy:
- UserInput expresses INTENT (not force/torque)
- Simulation engine converts intent -> physics

Collision:
- Primitive / Compound / Auto / None supported
- Visualization mesh is NOT used for physics

Separation:
- CAD / Server / AR / Simulation are fully decoupled
"""



# =========================================================
# JSON EXAMPLES (FOR RUST SERVER TEAM)
# =========================================================

"""
This section provides real examples for:

1. SceneInput (initialization)
2. UserInput (runtime events)
3. SimState (output)

These are DIRECTLY derived from actual test cases:
- Four-bar linkage test
- AR rotate interaction test
"""


# =========================================================
# Example 1: SceneInput (Four-bar linkage)
# =========================================================

SCENE_INPUT_FOUR_BAR = {
    "sceneName": "four_bar_linkage_test",
    "gravity": {"x": 0.0, "y": 0.0, "z": 0.0},

    "bodies": [
        {
            "name": "ground",
            "pose": {
                "pos": {"x": 0.0, "y": 0.8, "z": 0.0},
                "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
            },
            "mechanical": {
                "mass": 1000.0,
                "fixed": True,
                "inertia": {"mode": "explicit", "Ixx": 1.0, "Iyy": 1.0, "Izz": 1.0}
            },
            "geometry": {
                "collision": None
            }
        },
        {
            "name": "input_link",
            "pose": {
                "pos": {"x": 0.0, "y": 0.94, "z": 0.0},
                "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
            },
            "mechanical": {
                "mass": 1.0,
                "fixed": False,
                "inertia": {"mode": "explicit", "Ixx": 0.02, "Iyy": 0.02, "Izz": 0.02}
            },
            "geometry": {
                "collision": None
            }
        }
    ],

    "joints": [
        {
            "name": "rev_ground_input",
            "type": "revolute",
            "body1": "ground",
            "body2": "input_link",
            "frame": {
                "pos": {"x": 0.0, "y": 0.8, "z": 0.0},
                "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
            }
        }
    ],

    "gearPairs": [],

    "actuators": [
        {
            "name": "motor_input",
            "type": "rotation_speed",
            "targetJoint": "rev_ground_input",
            "speed": 0.35
        }
    ]
}


# =========================================================
# Example 2: SceneInput (AR rotate test)
# =========================================================

SCENE_INPUT_AR_ROTATE = {
    "sceneName": "rotate_external_like_no_wall",
    "gravity": {"x": 0.0, "y": -9.81, "z": 0.0},

    "bodies": [
        {
            "name": "base",
            "pose": {
                "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
            },
            "mechanical": {
                "fixed": True,
                "mass": 1.0
            },
            "geometry": {
                "collision": None
            }
        },
        {
            "name": "shaft",
            "pose": {
                "pos": {"x": 0.0, "y": 0.0, "z": 0.03},
                "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
            },
            "mechanical": {
                "fixed": False,
                "mass": 1.0
            },
            "geometry": {
                "collision": "auto"
            }
        }
    ],

    "joints": [
        {
            "name": "base_shaft_rev",
            "type": "revolute",
            "body1": "base",
            "body2": "shaft",
            "frame": {
                "pos": {"x": 0.0, "y": 0.0, "z": 0.03},
                "rot": {"w": 0.7071, "x": 0.0, "y": 0.7071, "z": 0.0}
            }
        }
    ],

    "gearPairs": [],
    "actuators": []
}


# =========================================================
# Example 3: UserInput (AR Interaction)
# =========================================================

USER_INPUT_TOUCH_START = {
    "type": "TouchStart",
    "payload": {
        "target": {"partName": "shaft"},
        "actionPointLocal": {"x": 0.0, "y": 0.0, "z": 0.0},
        "fingerPointWorld": {"x": 0.05, "y": 0.04, "z": -0.02},
        "cameraForwardWorld": {"x": 0.0, "y": 0.0, "z": -1.0}
    }
}


USER_INPUT_TOUCHING = {
    "type": "Touching",
    "payload": {
        "target": {"partName": "shaft"},
        "fingerPointWorld": {"x": 0.05, "y": 0.05, "z": -0.01},
        "cameraForwardWorld": {"x": 0.0, "y": 0.0, "z": -1.0}
    }
}


USER_INPUT_TOUCH_END = {
    "type": "TouchEnd",
    "payload": {
        "target": {"partName": "shaft"}
    }
}


# =========================================================
# Example 4: SimState (Output)
# =========================================================

SIM_STATE_EXAMPLE = {
    "sim_time": 0.125,
    "parts": [
        {
            "name": "base",
            "pos": {"x": 0.0, "y": 0.0, "z": 0.0},
            "rot": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}
        },
        {
            "name": "shaft",
            "pos": {"x": 0.0, "y": 0.0, "z": 0.03},
            "rot": {"w": 0.998, "x": 0.0, "y": 0.0, "z": 0.062}
        }
    ],

    "partNames": ["base", "shaft"],

    "telemetry": {
        "contact_count": 0,
        "max_contact_force": 0.0
    }
}


# =========================================================
# Usage Example (Rust-side logic)
# =========================================================

"""
Pseudo-flow for Rust server:

1. Send SceneInput JSON
2. Initialize Simulator

3. Loop:
    send UserInput JSON
    receive SimState JSON

Example:

send(SCENE_INPUT_AR_ROTATE)

loop:
    send(USER_INPUT_TOUCHING)
    state = recv()
"""