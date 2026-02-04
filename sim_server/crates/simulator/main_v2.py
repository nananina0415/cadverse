# simulator/main_v2.py
# Simulator class for metadata.json-based scenes (Fusion 360 plugin export).
# Conforms to the same create() / step() contract that simulator_binding.rs expects.

from __future__ import annotations

from typing import Any, Dict, List, Optional

from simulator.runtime_types import PartState, Vec3, QuatWXYZ
from simulator.sim_info_v2 import SimInfoV2
from simulator.scene_loader import build_chrono_system


class SimStateV2:
    """
    Step output with debug info.
    Has same attributes as runtime_types.SimState (sim_time, parts)
    plus optional debug_joints for dev-mode visualization.
    """
    __slots__ = ("sim_time", "parts", "debug_joints")

    def __init__(
        self,
        sim_time: float,
        parts: List[PartState],
        debug_joints: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.sim_time = sim_time
        self.parts = parts
        self.debug_joints = debug_joints


class Simulator:
    """
    PyChrono-based simulator for metadata.json scenes.

    Rust binding contract:
        sim = Simulator.create(info)   # info: SimInfoV2
        state = sim.step(userInput)    # returns object with sim_time, parts, debug_joints
    """

    def __init__(self, info: SimInfoV2) -> None:
        self._info = info
        self._sim_time: float = 0.0

        # Build Chrono world
        result = build_chrono_system(info.metadata, info.obj_dir)
        self._system = result.system
        self._bodies: Dict[str, Any] = result.bodies
        self._joints: Dict[str, Any] = result.joints
        self._body_order: List[str] = result.body_order

        # Debug: joint visualization data (static, computed once)
        self._debug_joints = self._build_debug_joints(info.metadata)

        print(f"[Simulator V2] Created: {len(self._bodies)} bodies, "
              f"{len(self._joints)} joints, dt={info.dt}")

    @staticmethod
    def _build_debug_joints(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract joint debug visualization data from metadata (cm -> m)."""
        result = []
        for jdef in metadata.get("joints", []):
            origin_cm = jdef.get("origin", [0, 0, 0])
            axis = jdef.get("axis", [0, 0, 1])
            result.append({
                "name": jdef.get("name", ""),
                "origin": [float(v) * 0.01 for v in origin_cm],  # cm -> m
                "axis": [float(v) for v in axis],
                "parent": jdef.get("connected_parts", {}).get("parent", ""),
                "child": jdef.get("connected_parts", {}).get("child", ""),
            })
        return result

    @classmethod
    def create(cls, info: SimInfoV2) -> "Simulator":
        return cls(info)

    def step(self, userInput: Optional[Any] = None) -> SimStateV2:
        dt = self._info.dt

        # Advance physics
        self._system.DoStepDynamics(dt)
        self._sim_time += dt

        # Extract state for each body in order
        parts: List[PartState] = []
        for name in self._body_order:
            body = self._bodies[name]
            parts.append(PartState.from_chrono_body(body, name=name))

        return SimStateV2(
            sim_time=self._sim_time,
            parts=parts,
            debug_joints=self._debug_joints,
        )
