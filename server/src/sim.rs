use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::{Arc, Condvar, Mutex, atomic::{AtomicBool, Ordering}};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use crate::utils::{TripleBufReader, TripleBufWriter, TripleBufSwapper};

// ── SimIoBuf ──────────────────────────────────────────────────────────────────

pub struct SimIoBuf {
    pub userin_r:    TripleBufReader<Vec<UserIn>>,
    pub userin_swap: TripleBufSwapper<Vec<UserIn>>,
    pub simout_w:    TripleBufWriter<SimFrame>,
    pub simout_swap: TripleBufSwapper<SimFrame>,
}

impl SimIoBuf {
    pub fn clear_and_init(&mut self, init: SimOut) {
        self.userin_swap.swap_and_clear();
        *self.simout_w.write() = SimFrame::State(init);
        self.simout_swap.swap_and_clear();
    }
}

// ── UserIn ────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PartTarget {
    #[serde(rename = "partIndex", skip_serializing_if = "Option::is_none")]
    pub part_index: Option<f32>,

    #[serde(rename = "partName", skip_serializing_if = "Option::is_none")]
    pub part_name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TouchStartPayload {
    // docs/06 권장 구조
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<PartTarget>,

    #[serde(rename = "actionPointLocal", skip_serializing_if = "Option::is_none")]
    pub action_point_local: Option<Vec3>,

    #[serde(rename = "fingerPointWorld", skip_serializing_if = "Option::is_none")]
    pub finger_point_world: Option<Vec3>,

    #[serde(rename = "cameraForwardWorld", skip_serializing_if = "Option::is_none")]
    pub camera_forward_world: Option<Vec3>,

    // legacy 호환 구조
    #[serde(rename = "targetPartIndex", skip_serializing_if = "Option::is_none")]
    pub target_part_index: Option<f32>,

    #[serde(rename = "targetPartName", skip_serializing_if = "Option::is_none")]
    pub target_part_name: Option<String>,

    #[serde(rename = "actionPoint", skip_serializing_if = "Option::is_none")]
    pub action_point: Option<Vec3>,

    #[serde(rename = "fingerPoint", skip_serializing_if = "Option::is_none")]
    pub finger_point: Option<Vec3>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub z_direction: Option<Vec3>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TouchingPayload {
    // docs/06 권장 구조
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<PartTarget>,

    #[serde(rename = "fingerPointWorld", skip_serializing_if = "Option::is_none")]
    pub finger_point_world: Option<Vec3>,

    #[serde(rename = "cameraForwardWorld", skip_serializing_if = "Option::is_none")]
    pub camera_forward_world: Option<Vec3>,

    // legacy 호환 구조
    #[serde(rename = "fingerPoint", skip_serializing_if = "Option::is_none")]
    pub finger_point: Option<Vec3>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub z_direction: Option<Vec3>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TouchEndPayload {
    // docs/06 권장 구조
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<PartTarget>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum UserIn {
    TouchStart(TouchStartPayload),
    Touching(TouchingPayload),
    TouchEnd(TouchEndPayload),
}

// ── SimOut ────────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ObjectTransform {
    pub name: String,
    pub position: [f32; 3],
    pub rotation: [f32; 4],
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SimOut {
    pub timestamp: f64,
    pub objects: Vec<ObjectTransform>,
}

impl crate::utils::Clearable for SimOut {
    fn clear(&mut self) { self.objects.clear(); }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SimFrame {
    State(SimOut),
    Reload,
}

impl Default for SimFrame {
    fn default() -> Self { SimFrame::State(SimOut::default()) }
}

impl crate::utils::Clearable for SimFrame {
    fn clear(&mut self) { *self = SimFrame::default(); }
}

// ── SimModel (metadata_types.py::SceneMeta 미러) ──────────────────────────────

#[derive(Debug, Clone, Serialize)]
pub struct BodyPose {
    pub pos: [f64; 3],
    pub rot: [f64; 4],  // w, x, y, z
}

#[derive(Debug, Clone, Serialize)]
pub struct BodyVisual {
    pub kind: String,
    pub file: String,
    pub scale: [f64; 3],
    pub offset: BodyPose,
}

#[derive(Debug, Clone, Serialize)]
pub struct BodyGeometry {
    pub visual: BodyVisual,
    pub collision: String,  // "auto"
}

#[derive(Debug, Clone, Serialize)]
pub struct BodyInertia {
    pub mode: String,  // "explicit"
    #[serde(rename = "Ixx")] pub ixx: f64,
    #[serde(rename = "Iyy")] pub iyy: f64,
    #[serde(rename = "Izz")] pub izz: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct BodyMechanical {
    pub mass: f64,
    pub inertia: BodyInertia,
}

#[derive(Debug, Clone, Serialize)]
pub struct BodyDef {
    pub name: String,
    pub pose: BodyPose,
    pub geometry: BodyGeometry,
    pub mechanical: BodyMechanical,
}

#[derive(Debug, Clone, Serialize)]
pub struct JointLimits {
    pub lower: f64,
    pub upper: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct JointDef {
    pub name: String,
    #[serde(rename = "type")] pub joint_type: String,
    pub body1: String,
    pub body2: String,
    pub frame: BodyPose,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limits: Option<JointLimits>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SimModel {
    pub bodies: Vec<BodyDef>,
    pub joints: Vec<JointDef>,
}

pub struct Simulator {
    py_obj: Py<PyAny>,
}

fn build_py_sim(py: Python, model: &SimModel, dt: f64) -> PyResult<Py<PyAny>> {
    // stdout을 stderr로 리다이렉트해 stdout 파이프 프로토콜 오염 방지
    eprintln!("[build_py_sim] 1: stdout redirect");
    py.run_bound("import sys; sys.stdout = sys.stderr", None, None)?;

    eprintln!("[build_py_sim] 2: add_dll_directory");
    #[cfg(windows)]
    py.run_bound(
        "import os; [os.add_dll_directory(d) for d in [\
            os.path.join(os.environ.get('CONDA_PREFIX',''), 'Library', 'bin'),\
            os.path.join(os.environ.get('CONDA_PREFIX',''), 'Library', 'mingw-w64', 'bin'),\
        ] if d and os.path.isdir(d)]",
        None, None,
    )?;

    eprintln!("[build_py_sim] 3: json serialize");
    let mut value = serde_json::to_value(model).expect("SimModel 직렬화 실패");

    if let Some(obj) = value.as_object_mut() {
        obj.entry("sceneName".to_string())
            .or_insert(serde_json::json!("rust_loaded_scene"));
        obj.entry("gravity".to_string())
            .or_insert(serde_json::json!([0.0, -9.81, 0.0]));
        obj.entry("gearPairs".to_string())
            .or_insert(serde_json::json!([]));
        obj.entry("actuators".to_string())
            .or_insert(serde_json::json!([]));

        if let Some(bodies) = obj.get_mut("bodies").and_then(|v| v.as_array_mut()) {
            for body in bodies {
                let name = body
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_lowercase();

                if let Some(body_obj) = body.as_object_mut() {
                    body_obj.entry("category".to_string()).or_insert(
                        if name == "ground" || name == "base" {
                            serde_json::json!("base")
                        } else {
                            serde_json::json!("generic")
                        }
                    );

                    if let Some(mech) = body_obj.get_mut("mechanical").and_then(|v| v.as_object_mut()) {
                        mech.entry("fixed".to_string()).or_insert(
                            serde_json::json!(name == "ground" || name == "base")
                        );
                    }
                }
            }
        }
    }

    let json = serde_json::to_string(&value).expect("SimModel 직렬화 실패");

    eprintln!("[build_py_sim] 4: import simulator.SimInfo");
    let siminfo_mod = py.import("simulator.SimInfo")?;

    eprintln!("[build_py_sim] 5: SimOptions");
    let opt_kwargs = PyDict::new(py);
    opt_kwargs.set_item("dt", dt)?;
    opt_kwargs.set_item("allow_obj_auto_approx", true)?;
    opt_kwargs.set_item("strict_no_inference", false)?;
    opt_kwargs.set_item("emit_part_names", true)?;
    opt_kwargs.set_item("enable_contact_telemetry", false)?;
    opt_kwargs.set_item("physics_preset", "DEFAULT")?;

    let options = siminfo_mod
        .getattr("SimOptions")?
        .call((), Some(&opt_kwargs))?;

    eprintln!("[build_py_sim] 6: SimInfo.from_json_string");
    let kwargs = PyDict::new(py);
    kwargs.set_item("dt", dt)?;
    kwargs.set_item("options", options)?;

    let info = siminfo_mod
        .getattr("SimInfo")?
        .call_method("from_json_string", (json,), Some(&kwargs))?;

    eprintln!("[build_py_sim] 7: import simulator.main");
    let sim_mod = py.import("simulator.main")?;

    eprintln!("[build_py_sim] 8: Simulator.create");
    let sim = sim_mod
        .getattr("Simulator")?
        .call_method1("create", (info,))?;

    eprintln!("[build_py_sim] 9: 완료");
    Ok(sim.unbind())
}

impl Simulator {
    pub fn new(model: &SimModel) -> Result<Self, String> {
        let py_obj = Python::with_gil(|py| build_py_sim(py, model, 1.0 / 60.0))
            .map_err(|e| format!("Python 시뮬레이터 생성 실패: {e}"))?;
        Ok(Self { py_obj })
    }

    pub fn reload(&mut self, model: &SimModel) -> Result<(), String> {
        Python::with_gil(|py| {
            let _ = self.py_obj.bind(py).call_method0("close");
        });
        let py_obj = Python::with_gil(|py| build_py_sim(py, model, 1.0 / 60.0))
            .map_err(|e| format!("Python 시뮬레이터 재생성 실패: {e}"))?;
        self.py_obj = py_obj;
        Ok(())
    }

    pub fn step(&mut self, inputs: &[UserIn]) -> Result<Vec<ObjectTransform>, String> {
        let deduped = dedup_inputs(inputs);
        Python::with_gil(|py| -> PyResult<Vec<ObjectTransform>> {
            let sim = self.py_obj.bind(py);

            let mut state = sim.call_method1("step", (py.None(),))?;

            if !deduped.is_empty() {
                let json_mod = py.import("json")?;

                for input in &deduped {
                    let input_json = serde_json::to_string(input).expect("UserIn 직렬화 실패");
                    let event_dict = json_mod.call_method1("loads", (input_json,))?;
                    state = sim.call_method1("step", (event_dict,))?;
                }
            }

            py_state_to_transforms(&state)
        })
        .map_err(|e| format!("Python step 실패: {e}"))
    }
}

impl Drop for Simulator {
    fn drop(&mut self) {
        Python::with_gil(|py| {
            let _ = self.py_obj.bind(py).call_method0("close");
        });
    }
}

// ── 입력 중복 제거 ─────────────────────────────────────────────────────────────

fn dedup_inputs(inputs: &[UserIn]) -> Vec<UserIn> {
    let mut starts: Vec<UserIn> = vec![];
    let mut last_touching: Option<UserIn> = None;
    let mut ends: Vec<UserIn> = vec![];

    for input in inputs {
        match input {
            UserIn::TouchStart(_) => starts.push(input.clone()),
            UserIn::Touching(_)   => last_touching = Some(input.clone()),
            UserIn::TouchEnd(_)   => ends.push(input.clone()),
        }
    }

    let mut result = starts;
    if let Some(t) = last_touching { result.push(t); }
    result.extend(ends);
    result
}

// ── Python SimState → Vec<ObjectTransform> ────────────────────────────────────

fn py_state_to_transforms(state: &Bound<'_, PyAny>) -> PyResult<Vec<ObjectTransform>> {
    let parts = state.getattr("parts")?;
    let mut out = Vec::new();
    for p in parts.try_iter()? {
        let p = p?;
        let name: String = p.getattr("name")?.extract()?;

        let pos = p.getattr("pos")?;
        let position = [
            pos.getattr("x")?.extract::<f32>()?,
            pos.getattr("y")?.extract::<f32>()?,
            pos.getattr("z")?.extract::<f32>()?,
        ];

        let rot = p.getattr("rot")?;
        let rotation = [
            rot.getattr("w")?.extract::<f32>()?,
            rot.getattr("x")?.extract::<f32>()?,
            rot.getattr("y")?.extract::<f32>()?,
            rot.getattr("z")?.extract::<f32>()?,
        ];

        out.push(ObjectTransform { name, position, rotation });
    }
    Ok(out)
}

const POSITION_SCALE: f64 = 0.01; // cm → m

/// row-major 4×4 행렬 → (pos_m, quat_wxyz)
fn decompose_mat4(flat: &[f64; 16]) -> ([f64; 3], [f64; 4]) {
    use nalgebra::{Matrix3, Rotation3, UnitQuaternion};

    let pos = [flat[3] * POSITION_SCALE, flat[7] * POSITION_SCALE, flat[11] * POSITION_SCALE];

    let rot_m = Matrix3::from_row_slice(&[
        flat[0], flat[1], flat[2],
        flat[4], flat[5], flat[6],
        flat[8], flat[9], flat[10],
    ]);
    let rot = Rotation3::from_matrix_eps(&rot_m, 1e-6, 100, Rotation3::identity());
    let q = UnitQuaternion::from_rotation_matrix(&rot);
    let q = q.quaternion();
    ([pos[0], pos[1], pos[2]], [q.w, q.i, q.j, q.k])
}

/// Z축을 axis 방향으로 정렬하는 quaternion (w,x,y,z)
fn axis_to_quat(axis: [f64; 3]) -> [f64; 4] {
    use nalgebra::{UnitQuaternion, Unit, Vector3};

    let z = match Unit::try_new(Vector3::new(axis[0], axis[1], axis[2]), 1e-12) {
        Some(v) => v,
        None => return [1.0, 0.0, 0.0, 0.0],
    };
    let rot = UnitQuaternion::rotation_between_axis(&Vector3::z_axis(), &z)
        .unwrap_or(UnitQuaternion::identity());
    let q = rot.quaternion();
    [q.w, q.i, q.j, q.k]
}

fn load_model_from_folder(folder: &PathBuf) -> Result<(SimModel, SimOut), String> {
    let metadata_path = folder.join("metadata.json");
    let text = std::fs::read_to_string(&metadata_path)
        .map_err(|e| format!("metadata.json 읽기 실패: {e}"))?;
    let meta: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("metadata.json 파싱 실패: {e}"))?;

    // bodies
    let transforms = meta.get("transforms")
        .and_then(|v| v.as_object())
        .ok_or("metadata.json에 transforms 없음")?;

    let mut bodies = Vec::new();
    for (name, val) in transforms {
        let flat16: Vec<f64> = val.as_array()
            .ok_or_else(|| format!("transforms.{name}: 배열이 아님"))?
            .iter()
            .map(|v| v.as_f64().unwrap_or(0.0))
            .collect();
        if flat16.len() != 16 {
            return Err(format!("transforms.{name}: 16개 값 필요, {}개 있음", flat16.len()));
        }
        let arr: [f64; 16] = flat16.try_into().unwrap();
        let (pos, rot) = decompose_mat4(&arr);

        bodies.push(BodyDef {
            name: name.clone(),
            pose: BodyPose { pos, rot },
            geometry: BodyGeometry {
                visual: BodyVisual {
                    kind: "mesh".into(),
                    file: folder.join("meshes").join(format!("{name}.obj")).to_string_lossy().into_owned(),
                    scale: [1.0, 1.0, 1.0],
                    offset: BodyPose { pos: [0.0; 3], rot: [1.0, 0.0, 0.0, 0.0] },
                },
                collision: "auto".into(),
            },
            mechanical: BodyMechanical {
                mass: 1.0,
                inertia: BodyInertia { mode: "explicit".into(), ixx: 0.01, iyy: 0.01, izz: 0.01 },
            },
        });
    }

    // joints
    let joints_raw = meta.get("joints")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    let mut joints = Vec::new();
    for j in &joints_raw {
        let name = j.get("name").and_then(|v| v.as_str()).unwrap_or("joint").to_string();
        let jtype = j.get("type").and_then(|v| v.as_str()).unwrap_or("revolute").to_lowercase();
        let cp = j.get("connected_parts");
        let body1 = cp.and_then(|v| v.get("parent")).and_then(|v| v.as_str()).unwrap_or("").to_string();
        let body2 = cp.and_then(|v| v.get("child")).and_then(|v| v.as_str()).unwrap_or("").to_string();

        let axis: [f64; 3] = j.get("axis").and_then(|v| v.as_array()).map(|a| {
            [a.get(0).and_then(|v| v.as_f64()).unwrap_or(0.0),
             a.get(1).and_then(|v| v.as_f64()).unwrap_or(0.0),
             a.get(2).and_then(|v| v.as_f64()).unwrap_or(1.0)]
        }).unwrap_or([0.0, 0.0, 1.0]);

        let origin_cm: [f64; 3] = j.get("origin").and_then(|v| v.as_array()).map(|a| {
            [a.get(0).and_then(|v| v.as_f64()).unwrap_or(0.0),
             a.get(1).and_then(|v| v.as_f64()).unwrap_or(0.0),
             a.get(2).and_then(|v| v.as_f64()).unwrap_or(0.0)]
        }).unwrap_or([0.0; 3]);

        let pos = [origin_cm[0] * POSITION_SCALE, origin_cm[1] * POSITION_SCALE, origin_cm[2] * POSITION_SCALE];
        let rot = axis_to_quat(axis);

        let limits = j.get("limits").and_then(|v| v.as_object()).map(|lim| {
            let lower = lim.get("min").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let upper = lim.get("max").and_then(|v| v.as_f64()).unwrap_or(0.0);
            JointLimits { lower: lower.to_radians(), upper: upper.to_radians() }
        });

        joints.push(JointDef { name, joint_type: jtype, body1, body2, frame: BodyPose { pos, rot }, limits });
    }

    Ok((SimModel { bodies, joints }, SimOut::default()))
}

// ── SimLoop ───────────────────────────────────────────────────────────────────

pub struct SimLoop {
    next_sim:    Arc<Mutex<Option<(Simulator, SimOut)>>>,
    run_flag:    Arc<AtomicBool>,
    cond:        Arc<(Mutex<()>, Condvar)>,
    sim_running: Arc<AtomicBool>,
    _thread:     std::thread::JoinHandle<()>,
}

impl SimLoop {
    pub fn new(mut sim_io_buf: SimIoBuf) -> Self {
        let next_sim    = Arc::new(Mutex::new(None::<(Simulator, SimOut)>));
        let run_flag    = Arc::new(AtomicBool::new(false));
        let cond        = Arc::new((Mutex::new(()), Condvar::new()));
        let sim_running = Arc::new(AtomicBool::new(false));

        let thread = std::thread::spawn({
            let next_sim    = next_sim.clone();
            let run_flag    = run_flag.clone();
            let cond        = cond.clone();
            let sim_running = sim_running.clone();
            move || {
                eprintln!("[sim_loop] 스레드 시작");
                loop {
                    // IDLE: run_flag=true 가 될 때까지 대기
                    {
                        let (lock, cv) = &*cond;
                        let mut guard = lock.lock().expect("cond mutex poisoned");
                        while !run_flag.load(Ordering::Acquire) {
                            guard = cv.wait(guard).expect("condvar wait 실패");
                        }
                    }

                    // run_flag 가 true 지만 next_sim 이 없으면 루프 다시
                    let pair = next_sim.lock().expect("next_sim mutex poisoned").take();
                    let (mut sim, init) = match pair {
                        Some(v) => v,
                        None    => { run_flag.store(false, Ordering::Relaxed); continue; }
                    };

                    sim_io_buf.clear_and_init(init);
                    sim_running.store(true, Ordering::Relaxed);
                    eprintln!("[sim_loop] 루프 시작");

                    // RUNNING
                    while run_flag.load(Ordering::Relaxed) {
                        // 교체 요청 확인
                        if let Some((new_sim, _)) = next_sim.lock().expect("next_sim mutex poisoned").take() {
                            eprintln!("[sim_loop] 시뮬레이터 교체");
                            sim_io_buf.userin_swap.swap_and_clear();
                            *sim_io_buf.simout_w.write() = SimFrame::Reload;
                            sim_io_buf.simout_swap.swap_and_clear();
                            sim = new_sim;
                        }

                        sim_io_buf.userin_swap.swap_and_clear();
                        let inputs = sim_io_buf.userin_r.read();
                        match sim.step(inputs) {
                            Ok(objects) => {
                                *sim_io_buf.simout_w.write() = SimFrame::State(SimOut { timestamp: 0.0, objects });
                                sim_io_buf.simout_swap.swap_and_clear();
                            }
                            Err(e) => {
                                eprintln!("[sim_loop] step 오류 → 정지: {e}");
                                run_flag.store(false, Ordering::Relaxed);
                                break;
                            }
                        }
                    }

                    sim_running.store(false, Ordering::Relaxed);
                    eprintln!("[sim_loop] 루프 정지");
                    // sim 여기서 drop (Python 객체 해제)
                }
            }
        });

        Self { next_sim, run_flag, cond, sim_running, _thread: thread }
    }

    // 새 시뮬레이터 세팅 후 실행 (idle·running 모두 동작)
    pub fn set_sim(&self, sim: Simulator, init: SimOut) {
        *self.next_sim.lock().expect("next_sim mutex poisoned") = Some((sim, init));
        self.run_flag.store(true, Ordering::Release);
        let _g = self.cond.0.lock().expect("cond mutex poisoned");
        self.cond.1.notify_one();
    }

    pub fn stop(&self) {
        self.run_flag.store(false, Ordering::Relaxed);
        // running 루프는 다음 step 후 run_flag 확인 → 자동 종료
        // idle 상태면 이미 멈춰있으므로 notify 불필요
    }

    pub fn is_running(&self) -> bool {
        self.sim_running.load(Ordering::Relaxed)
    }
}

// ── SimManager ────────────────────────────────────────────────────────────────

pub struct SimManager {
    pub sim_loop:  SimLoop,
    pub reloading: Arc<AtomicBool>,
    pub sim_error: Arc<Mutex<Option<String>>>,
}

impl SimManager {
    pub fn new(sim_io_buf: SimIoBuf) -> Self {
        let sim_loop  = SimLoop::new(sim_io_buf);
        let reloading = Arc::new(AtomicBool::new(false));
        let sim_error = Arc::new(Mutex::new(None::<String>));
        Self { sim_loop, reloading, sim_error }
    }

    // 시뮬 시작 (블로킹: Simulator::new 포함)
    pub fn start(&self, model_path: &std::path::Path) -> Result<(), String> {
        eprintln!("[sim_mgr] 모델 로드: {}", model_path.display());
        let (model, init) = load_model_from_folder(&model_path.to_path_buf())?;
        eprintln!("[sim_mgr] Simulator::new 호출 중...");
        match Simulator::new(&model) {
            Ok(sim) => {
                eprintln!("[sim_mgr] Simulator 생성 완료 → SimLoop 실행");
                self.sim_loop.set_sim(sim, init);
                Ok(())
            }
            Err(e) => {
                eprintln!("[sim_mgr] Simulator 생성 실패: {e}");
                *self.sim_error.lock().expect("sim_error mutex poisoned") = Some(e.clone());
                Err(e)
            }
        }
    }

    // 시뮬 정지 (논블로킹: 플래그만 세움)
    pub fn stop(&self) {
        eprintln!("[sim_mgr] stop");
        self.sim_loop.stop();
    }

    pub fn is_running(&self) -> bool { self.sim_loop.is_running() }
    pub fn is_reloading(&self) -> bool { self.reloading.load(Ordering::Relaxed) }
    pub fn take_error(&self) -> Option<String> {
        self.sim_error.lock().expect("sim_error mutex poisoned").take()
    }
}

