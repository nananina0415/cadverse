use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::{Arc, Condvar, Mutex, atomic::{AtomicU8, Ordering}};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use crate::utils::{TripleBufReader, TripleBufWriter, TripleBufSwapper};

// ── SimIoBuf ──────────────────────────────────────────────────────────────────

pub struct SimIoBuf {
    pub userin_r:    TripleBufReader<Vec<UserIn>>,
    pub userin_swap: TripleBufSwapper<Vec<UserIn>>,
    pub simout_w:    TripleBufWriter<SimOut>,
    pub simout_swap: TripleBufSwapper<SimOut>,
}

impl SimIoBuf {
    pub fn clear_and_init(&mut self, init: SimOut) {
        self.userin_swap.swap_and_clear();
        *self.simout_w.write() = init;
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
pub struct TouchStartPayload {
    #[serde(rename = "targetPartIndex")]
    pub target_part_index: f32,
    #[serde(rename = "actionPoint")]
    pub action_point: Vec3,
    #[serde(rename = "fingerPoint")]
    pub finger_point: Vec3,
    pub z_direction: Vec3,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TouchingPayload {
    #[serde(rename = "fingerPoint")]
    pub finger_point: Vec3,
    pub z_direction: Vec3,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TouchEndPayload {}

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

// Python runtime_types.ContactTelemetry 최소 미러
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ContactPairOut {
    #[serde(rename = "bodyA")]
    pub body_a: String,
    #[serde(rename = "bodyB")]
    pub body_b: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ContactTelemetryOut {
    pub contact_count: i32,
    pub max_contact_force: f64,
    pub max_pair: Option<ContactPairOut>,
}

// Python runtime_types.InteractionTelemetry 최소 미러
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct InteractionTelemetryOut {
    pub mode: Option<String>,
    #[serde(rename = "targetBody")]
    pub target_body: Option<String>,
    #[serde(rename = "driveBody")]
    pub drive_body: Option<String>,
    #[serde(rename = "driveJoint")]
    pub drive_joint: Option<String>,
    #[serde(rename = "axisWorld")]
    pub axis_world: Option<Vec3>,
    #[serde(rename = "pivotWorld")]
    pub pivot_world: Option<Vec3>,
}

// Python runtime_types.DiagnosticItem 미러
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DiagnosticOut {
    pub code: String,
    pub severity: String,
    pub message: String,
    pub target: Option<String>,
}

// Python runtime_types.EventFeedback 미러
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct EventFeedbackOut {
    #[serde(rename = "eventType")]
    pub event_type: String,
    pub severity: String,
    pub message: String,
    pub target: Option<String>,

    #[serde(rename = "soundId")]
    pub sound_id: Option<String>,
    #[serde(rename = "soundType")]
    pub sound_type: Option<String>,
    pub volume: Option<f32>,
    pub pitch: Option<f32>,

    pub value: Option<f64>,
    pub threshold: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SimOut {
    pub timestamp: f64,
    pub seq: Option<i64>,
    pub objects: Vec<ObjectTransform>,

    pub telemetry: Option<ContactTelemetryOut>,
    #[serde(rename = "interactionTelemetry")]
    pub interaction_telemetry: Option<InteractionTelemetryOut>,

    pub diagnostics: Vec<DiagnosticOut>,
    #[serde(rename = "eventFeedback")]
    pub event_feedback: Vec<EventFeedbackOut>,
    pub warnings: Vec<String>,

    // 일단 JSON 그대로 보존하고 싶을 때를 위한 확장 필드
    #[serde(rename = "jointTelemetry")]
    pub joint_telemetry: Option<serde_json::Value>,
    #[serde(rename = "actuatorTelemetry")]
    pub actuator_telemetry: Option<serde_json::Value>,
    #[serde(rename = "gearTelemetry")]
    pub gear_telemetry: Option<serde_json::Value>,
    #[serde(rename = "assemblyTelemetry")]
    pub assembly_telemetry: Option<serde_json::Value>,
}

impl crate::utils::Clearable for SimOut {
    fn clear(&mut self) {
        self.timestamp = 0.0;
        self.seq = None;
        self.objects.clear();

        self.telemetry = None;
        self.interaction_telemetry = None;

        self.diagnostics.clear();
        self.event_feedback.clear();
        self.warnings.clear();

        self.joint_telemetry = None;
        self.actuator_telemetry = None;
        self.gear_telemetry = None;
        self.assembly_telemetry = None;
    }
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
    // Python 3.8+: PATH 대신 add_dll_directory로 conda 환경의 DLL 경로를 명시
    #[cfg(windows)]
    py.run_bound(
        "import os; [os.add_dll_directory(d) for d in [\
            os.path.join(os.environ.get('CONDA_PREFIX',''), 'Library', 'bin'),\
            os.path.join(os.environ.get('CONDA_PREFIX',''), 'Library', 'mingw-w64', 'bin'),\
        ] if d and os.path.isdir(d)]",
        None, None,
    )?;

    let mut value = serde_json::to_value(model).expect("SimModel 직렬화 실패");

    // Python SceneMeta가 기대하는 top-level / body 필드 보정
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

    let siminfo_mod = py.import("simulator.SimInfo")?;

    let opt_kwargs = PyDict::new(py);
    opt_kwargs.set_item("dt", dt)?;
    opt_kwargs.set_item("allow_obj_auto_approx", true)?;
    opt_kwargs.set_item("strict_no_inference", false)?;
    opt_kwargs.set_item("emit_part_names", true)?;

    // contact telemetry / diagnostics / eventFeedback 출력 활성화
    opt_kwargs.set_item("enable_contact_telemetry", true)?;
    opt_kwargs.set_item("max_contact_points_report", 256)?;
    opt_kwargs.set_item("enable_event_feedback", true)?;
    opt_kwargs.set_item("event_feedback_enable_sound", true)?;

    opt_kwargs.set_item("physics_preset", "DEFAULT")?;

    let options = siminfo_mod
        .getattr("SimOptions")?
        .call((), Some(&opt_kwargs))?;

    let kwargs = PyDict::new(py);
    kwargs.set_item("dt", dt)?;
    kwargs.set_item("options", options)?;

    let info = siminfo_mod
        .getattr("SimInfo")?
        .call_method("from_json_string", (json,), Some(&kwargs))?;

    let sim = py
        .import("simulator.main")?
        .getattr("Simulator")?
        .call_method1("create", (info,))?;

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

    pub fn step(&mut self, inputs: &[UserIn]) -> Result<SimOut, String> {
        let deduped = dedup_inputs(inputs);
        Python::with_gil(|py| -> PyResult<SimOut> {
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

            py_state_to_simout(py, &state)
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

// ── Python SimState → SimOut ──────────────────────────────────────────────────

fn py_state_to_simout(py: Python<'_>, state: &Bound<'_, PyAny>) -> PyResult<SimOut> {
    let json_mod = py.import("json")?;

    // Python SimState 객체를 dict로 변환한 뒤 JSON 문자열로 직렬화
    let state_dict = state.call_method0("to_dict")?;
    let json_str: String = json_mod.call_method1("dumps", (state_dict,))?.extract()?;

    let value: serde_json::Value = serde_json::from_str(&json_str).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("SimState JSON parse 실패: {e}"))
    })?;

    let timestamp = value
        .get("sim_time")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);

    let seq = value
        .get("seq")
        .and_then(|v| v.as_i64());

    // parts -> objects 변환
    let mut objects = Vec::new();

    if let Some(parts) = value.get("parts").and_then(|v| v.as_array()) {
        for p in parts {
            let name = p
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let pos = p.get("pos").unwrap_or(&serde_json::Value::Null);
            let rot = p.get("rot").unwrap_or(&serde_json::Value::Null);

            let position = [
                pos.get("x").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                pos.get("y").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                pos.get("z").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
            ];

            let rotation = [
                rot.get("w").and_then(|v| v.as_f64()).unwrap_or(1.0) as f32,
                rot.get("x").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                rot.get("y").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                rot.get("z").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
            ];

            objects.push(ObjectTransform {
                name,
                position,
                rotation,
            });
        }
    }

    let telemetry = value
        .get("telemetry")
        .cloned()
        .filter(|v| !v.is_null())
        .and_then(|v| serde_json::from_value::<ContactTelemetryOut>(v).ok());

    let interaction_telemetry = value
        .get("interactionTelemetry")
        .cloned()
        .filter(|v| !v.is_null())
        .and_then(|v| serde_json::from_value::<InteractionTelemetryOut>(v).ok());

    let diagnostics = value
        .get("diagnostics")
        .cloned()
        .filter(|v| !v.is_null())
        .and_then(|v| serde_json::from_value::<Vec<DiagnosticOut>>(v).ok())
        .unwrap_or_default();

    let event_feedback = value
        .get("eventFeedback")
        .cloned()
        .filter(|v| !v.is_null())
        .and_then(|v| serde_json::from_value::<Vec<EventFeedbackOut>>(v).ok())
        .unwrap_or_default();

    let warnings = value
        .get("warnings")
        .cloned()
        .filter(|v| !v.is_null())
        .and_then(|v| serde_json::from_value::<Vec<String>>(v).ok())
        .unwrap_or_default();

    let joint_telemetry = value
        .get("jointTelemetry")
        .cloned()
        .filter(|v| !v.is_null());

    let actuator_telemetry = value
        .get("actuatorTelemetry")
        .cloned()
        .filter(|v| !v.is_null());

    let gear_telemetry = value
        .get("gearTelemetry")
        .cloned()
        .filter(|v| !v.is_null());

    let assembly_telemetry = value
        .get("assemblyTelemetry")
        .cloned()
        .filter(|v| !v.is_null());

    Ok(SimOut {
        timestamp,
        seq,
        objects,
        telemetry,
        interaction_telemetry,
        diagnostics,
        event_feedback,
        warnings,
        joint_telemetry,
        actuator_telemetry,
        gear_telemetry,
        assembly_telemetry,
    })
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

// ── SimThread ─────────────────────────────────────────────────────────────────

const FLAG_RUN:   u8 = 0;
const FLAG_PAUSE: u8 = 1;
const FLAG_HALT:  u8 = 2;

pub struct SimThread {
    thread_handle: std::thread::JoinHandle<SimIoBuf>,
    _watchdog: crate::watchdog::Watchdog<(SimModel, SimOut)>,
    flag: Arc<AtomicU8>,
    cond: Arc<(Mutex<()>, Condvar)>,
}

impl SimThread {
    pub fn new(folder: PathBuf, mut sim_io_buf: SimIoBuf) -> Result<SimThread, (String, SimIoBuf)> {
        let (model, init) = match load_model_from_folder(&folder) {
            Ok(v) => v,
            Err(e) => return Err((e, sim_io_buf)),
        };
        sim_io_buf.clear_and_init(init);

        let flag = Arc::new(AtomicU8::new(FLAG_RUN));
        let cond = Arc::new((Mutex::new(()), Condvar::new()));

        let watchdog = {
            let flag = flag.clone();
            let cond = cond.clone();
            crate::watchdog::Watchdog::new(folder.clone(), move |new_folder, data| {
                if !new_folder.join("metadata.json").exists() { return; }
                match load_model_from_folder(&new_folder) {
                    Ok((m, init)) => {
                        *data.lock().expect("watchdog data mutex poisoned") = Some((m, init));
                        flag.store(FLAG_PAUSE, Ordering::Relaxed);
                        cond.1.notify_one();
                    }
                    Err(e) => eprintln!("watchdog: 모델 로드 실패: {e}"),
                }
            }).expect("watchdog 생성 실패")
        };

        let thread_handle = std::thread::spawn({
            let flag = flag.clone();
            let cond = cond.clone();
            let reload_data = watchdog.data.clone();
            move || {
                let mut simulator = match Simulator::new(&model) {
                    Ok(s) => s,
                    Err(e) => {
                        eprintln!("시뮬레이터 생성 실패: {e}");
                        return sim_io_buf;
                    }
                };
                loop {
                    match flag.load(Ordering::Relaxed) {
                        FLAG_RUN => {
                            sim_io_buf.userin_swap.swap_and_clear();
                            let inputs = sim_io_buf.userin_r.read();
                            match simulator.step(inputs) {
                                Ok(simout) => {
                                    let out = sim_io_buf.simout_w.write();
                                    *out = simout;
                                    sim_io_buf.simout_swap.swap_and_clear();
                                }
                                Err(e) => {
                                    eprintln!("시뮬 step 실패: {e}");
                                    break;
                                }
                            }
                        }
                        FLAG_PAUSE => {
                            let (lock, cv) = &*cond;
                            let guard = lock.lock().expect("cond mutex poisoned");
                            let _guard = cv.wait(guard).expect("condvar wait 실패");
                            if let Some((m, init)) = reload_data.lock().expect("reload_data mutex poisoned").take() {
                                if let Err(e) = simulator.reload(&m) {
                                    eprintln!("시뮬레이터 재생성 실패: {e}");
                                    break;
                                }
                                sim_io_buf.clear_and_init(init);
                            }
                        }
                        _ => break,
                    }
                }
                sim_io_buf
            }
        });

        Ok(SimThread {
            thread_handle,
            _watchdog: watchdog,
            flag,
            cond,
        })
    }

    pub fn stop(self) -> SimIoBuf {
        self.flag.store(FLAG_HALT, Ordering::Relaxed);
        self.cond.1.notify_one();
        self.thread_handle.join().expect("시뮬 스레드 join 실패")
    }
}
