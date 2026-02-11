// src/simulator_binding.rs
//
// 역할:
// - Rust(sim_manager)에서 Python(simulator 패키지)의 Simulator를 PyO3로 감싸서 사용
// - new(): Python Simulator 인스턴스를 생성
// - step(): Python Simulator.step(None) 호출 -> Rust SimState로 변환

use std::sync::Mutex;

use anyhow::{anyhow, Context, Result};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::sim_state::{PartState, SimState};

pub struct Simulator {
    /// Python side simulator.main.Simulator instance
    py_simulator_obj: Py<PyAny>,

    /// 마지막으로 얻은 상태 (외부에서 step 결과 누적/참조 용)
    prev_state: Mutex<SimState>,
}

impl Simulator {
    /// Python Simulator 생성
    pub fn new(scene_path: &str) -> Result<Self> {
        let scene_path = scene_path.to_string();

        let dt: f64 = 1e-3;

        let py_simulator_obj = Python::with_gil(|py| -> Result<Py<PyAny>> {
            // 1) import simulator.SimInfo.SimInfo
            let siminfo_mod = py
                .import("simulator.SimInfo")
                .context("Failed to import Python module: simulator.SimInfo")?;
            let siminfo_cls = siminfo_mod
                .getattr("SimInfo")
                .context("Failed to get SimInfo class from simulator.SimInfo")?;

            // 2) info = SimInfo.from_json_file(scene_path, dt=dt)
            let kwargs = PyDict::new(py);
            kwargs
                .set_item("dt", dt)
                .context("Failed to set dt kwarg")?;

            let info_obj = siminfo_cls
                .call_method("from_json_file", (scene_path.as_str(),), Some(&kwargs))
                .context("Failed to call SimInfo.from_json_file(path, dt=...)")?;

            // 3) import simulator.main.Simulator
            let sim_mod = py
                .import("simulator.main")
                .context("Failed to import Python module: simulator.main")?;
            let sim_cls = sim_mod
                .getattr("Simulator")
                .context("Failed to get Simulator class from simulator.main")?;

            // 4) sim = Simulator.create(info)
            let sim_obj = sim_cls
                .call_method("create", (info_obj,), None)
                .context("Failed to call Simulator.create(info)")?;

            Ok(sim_obj.unbind())
        })?;

        Ok(Self {
            py_simulator_obj,
            prev_state: Mutex::new(SimState::empty()),
        })
    }

    /// 한 step 진행하고, Rust SimState 반환
    pub fn step(&self) -> Result<SimState> {
        let new_state = Python::with_gil(|py| -> Result<SimState> {
            let sim_any = self.py_simulator_obj.bind(py);

            // Python: state = sim.step(None)
            let state_any = sim_any
                .call_method1("step", (py.None(),))
                .context("Failed to call Python Simulator.step(None)")?;

            py_state_to_rust(&state_any).context("Failed to convert Python SimState -> Rust SimState")
        })?;

        // prev_state 갱신
        if let Ok(mut guard) = self.prev_state.lock() {
            *guard = new_state.clone();
        }

        Ok(new_state)
    }

    /// 필요하면 외부에서 마지막 상태만 가져갈 수 있게(선택)
    #[allow(dead_code)]
    pub fn prev_state(&self) -> SimState {
        self.prev_state
            .lock()
            .map(|g: std::sync::MutexGuard<'_, SimState>| g.clone())
            .unwrap_or_else(|_| SimState::empty())
    }
}

/// ------------------------------
/// Python -> Rust 변환 유틸
/// ------------------------------

fn py_state_to_rust(state: &Bound<'_, PyAny>) -> Result<SimState> {
    let sim_time = get_f64_attr_or_key(state, "sim_time")
        .context("SimState missing sim_time")?;

    let parts_any = get_attr_or_key(state, "parts").context("SimState missing parts")?;
    let parts_list: &Bound<'_, PyList> = parts_any
        .downcast::<PyList>()
        .map_err(|e| anyhow!("SimState.parts is not a list: {}", e))?;

    let mut parts: Vec<PartState> = Vec::with_capacity(parts_list.len());
    for p in parts_list.iter() {
        parts.push(py_part_to_rust(&p).context("Failed converting one PartState")?);
    }

    Ok(SimState { sim_time, parts })
}

fn py_part_to_rust(p: &Bound<'_, PyAny>) -> Result<PartState> {
    let name = get_string_attr_or_key(p, "name").context("PartState missing name")?;
    let pos_any = get_attr_or_key(p, "pos").context("PartState missing pos")?;
    let pos = vec3_from_any(&pos_any).context("PartState.pos parse failed")?;
    let rot_any = get_attr_or_key(p, "rot").context("PartState missing rot")?;
    let rot = quat_from_any(&rot_any).context("PartState.rot parse failed")?;
    Ok(PartState { name, pos, rot })
}

/// attr 우선, 없으면 dict key 접근 시도
fn get_attr_or_key<'py>(obj: &Bound<'py, PyAny>, name: &str) -> Option<Bound<'py, PyAny>> {
    if let Ok(v) = obj.getattr(name) {
        return Some(v);
    }
    if let Ok(d) = obj.downcast::<PyDict>() {
        if let Some(v) = d.get_item(name).ok().flatten() {
            return Some(v);
        }
    }
    None
}

fn get_f64_attr_or_key(obj: &Bound<'_, PyAny>, name: &str) -> Option<f64> {
    let v = get_attr_or_key(obj, name)?;
    v.extract::<f64>().ok()
}

fn get_string_attr_or_key(obj: &Bound<'_, PyAny>, name: &str) -> Option<String> {
    let v = get_attr_or_key(obj, name)?;
    v.extract::<String>().ok()
}

fn vec3_from_any(v: &Bound<'_, PyAny>) -> Result<[f64; 3]> {
    if let Ok(seq) = v.extract::<(f64, f64, f64)>() {
        return Ok([seq.0, seq.1, seq.2]);
    }
    if let Ok(vec) = v.extract::<Vec<f64>>() {
        if vec.len() == 3 {
            return Ok([vec[0], vec[1], vec[2]]);
        }
    }
    let x = get_f64_attr_or_key(v, "x").ok_or_else(|| anyhow!("vec3 missing x"))?;
    let y = get_f64_attr_or_key(v, "y").ok_or_else(|| anyhow!("vec3 missing y"))?;
    let z = get_f64_attr_or_key(v, "z").ok_or_else(|| anyhow!("vec3 missing z"))?;
    Ok([x, y, z])
}

fn quat_from_any(q: &Bound<'_, PyAny>) -> Result<[f64; 4]> {
    if let Ok(seq) = q.extract::<(f64, f64, f64, f64)>() {
        return Ok([seq.0, seq.1, seq.2, seq.3]);
    }
    if let Ok(vec) = q.extract::<Vec<f64>>() {
        if vec.len() == 4 {
            return Ok([vec[0], vec[1], vec[2], vec[3]]);
        }
    }
    if let (Some(w), Some(x), Some(y), Some(z)) = (
        get_f64_attr_or_key(q, "w"),
        get_f64_attr_or_key(q, "x"),
        get_f64_attr_or_key(q, "y"),
        get_f64_attr_or_key(q, "z"),
    ) {
        return Ok([w, x, y, z]);
    }
    if let (Some(e0), Some(e1), Some(e2), Some(e3)) = (
        get_f64_attr_or_key(q, "e0"),
        get_f64_attr_or_key(q, "e1"),
        get_f64_attr_or_key(q, "e2"),
        get_f64_attr_or_key(q, "e3"),
    ) {
        return Ok([e0, e1, e2, e3]);
    }
    Err(anyhow!("quat parse failed: expected (w,x,y,z) or attributes w/x/y/z or e0/e1/e2/e3"))
}
