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

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SimOut {
    pub timestamp: f64,
    pub objects: Vec<ObjectTransform>,
}

impl crate::utils::Clearable for SimOut {
    fn clear(&mut self) { self.objects.clear(); }
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
    let json = serde_json::to_string(model).expect("SimModel 직렬화 실패");
    let kwargs = PyDict::new(py);
    kwargs.set_item("dt", dt)?;
    let info = py
        .import("simulator.SimInfo")?
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

    pub fn step(&mut self, inputs: &[UserIn]) -> Result<Vec<ObjectTransform>, String> {
        let deduped = dedup_inputs(inputs);
        Python::with_gil(|py| -> PyResult<Vec<ObjectTransform>> {
            let sim = self.py_obj.bind(py);
            let state = if deduped.is_empty() {
                sim.call_method1("step", (py.None(),))?
            } else {
                let json = serde_json::to_string(&deduped).expect("UserIn 직렬화 실패");
                sim.call_method1("step", (json,))?
            };
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
                                Ok(objects) => {
                                    let out = sim_io_buf.simout_w.write();
                                    out.objects = objects;
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
