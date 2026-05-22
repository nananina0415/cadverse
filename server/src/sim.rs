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
    #[serde(rename = "bodyA")] pub body_a: String,
    #[serde(rename = "bodyB")] pub body_b: String,
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
    #[serde(rename = "targetBody")] pub target_body: Option<String>,
    #[serde(rename = "driveBody")]  pub drive_body:  Option<String>,
    #[serde(rename = "driveJoint")] pub drive_joint: Option<String>,
    #[serde(rename = "axisWorld")]  pub axis_world:  Option<Vec3>,
    #[serde(rename = "pivotWorld")] pub pivot_world: Option<Vec3>,
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
    #[serde(rename = "eventType")] pub event_type: String,
    pub severity: String,
    pub message: String,
    pub target: Option<String>,

    #[serde(rename = "soundId")]   pub sound_id:   Option<String>,
    #[serde(rename = "soundType")] pub sound_type: Option<String>,
    pub volume: Option<f32>,
    pub pitch:  Option<f32>,

    pub value:     Option<f64>,
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

    // 스키마 미고정 부분은 raw JSON value로 그대로 보관
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

pub struct Simulator {
    py_obj: Py<PyAny>,
}

fn build_py_sim(py: Python, meta: &serde_json::Value, dt: f64) -> PyResult<Py<PyAny>> {
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
    let mut value = meta.clone();

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

    let json = serde_json::to_string(&value).expect("메타데이터 직렬화 실패");

    eprintln!("[build_py_sim] 4: import simulator.SimInfo");
    let siminfo_mod = py.import("simulator.SimInfo")?;

    eprintln!("[build_py_sim] 5: SimOptions");
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
    pub fn new(meta: &serde_json::Value) -> Result<Self, String> {
        let py_obj = Python::with_gil(|py| build_py_sim(py, meta, 1.0 / 60.0))
            .map_err(|e| format!("Python 시뮬레이터 생성 실패: {e}"))?;
        Ok(Self { py_obj })
    }

    pub fn reload(&mut self, meta: &serde_json::Value) -> Result<(), String> {
        Python::with_gil(|py| {
            let _ = self.py_obj.bind(py).call_method0("close");
        });
        let py_obj = Python::with_gil(|py| build_py_sim(py, meta, 1.0 / 60.0))
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
                    eprintln!("[user_in] {:?}", input);   // DEBUG: 회전 방향 진단
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

// ── Python SimState → SimOut ──────────────────────────────────────────────────

fn py_state_to_simout(py: Python<'_>, state: &Bound<'_, PyAny>) -> PyResult<SimOut> {
    let json_mod = py.import("json")?;

    // Python SimState → dict → JSON 문자열 → serde_json::Value 로 한 번 변환한 뒤,
    // 정의된 필드는 typed로, 미고정 필드는 raw value로 분리해서 보관한다.
    let state_dict = state.call_method0("to_dict")?;
    let json_str: String = json_mod.call_method1("dumps", (state_dict,))?.extract()?;

    // [임시 fix] Python json.dumps는 NaN/Infinity/-Infinity를 표준 JSON 외 토큰으로 출력해서
    // serde_json::from_str이 파싱 실패한다. spring 모드 등에서 발생 확인.
    // 본질적 해결은 Python 측에서 NaN을 막거나 정리하는 것 — BUGS.md 참고.
    // -Infinity를 먼저 치환해야 Infinity 치환과 충돌 안 함.
    let cleaned = json_str
        .replace("-Infinity", "null")
        .replace("Infinity", "null")
        .replace("NaN", "null");

    let value: serde_json::Value = serde_json::from_str(&cleaned).map_err(|e| {
        PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("SimState JSON parse 실패: {e}"))
    })?;

    let timestamp = value.get("sim_time").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let seq       = value.get("seq").and_then(|v| v.as_i64());

    // parts → objects
    let mut objects = Vec::new();
    if let Some(parts) = value.get("parts").and_then(|v| v.as_array()) {
        for p in parts {
            let name = p.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let pos  = p.get("pos").unwrap_or(&serde_json::Value::Null);
            let rot  = p.get("rot").unwrap_or(&serde_json::Value::Null);

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
            objects.push(ObjectTransform { name, position, rotation });
        }
    }

    let telemetry = value.get("telemetry")
        .and_then(|t| serde_json::from_value::<ContactTelemetryOut>(t.clone()).ok());

    let interaction_telemetry = value.get("interactionTelemetry")
        .and_then(|t| serde_json::from_value::<InteractionTelemetryOut>(t.clone()).ok());

    let diagnostics: Vec<DiagnosticOut> = value.get("diagnostics")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| serde_json::from_value(x.clone()).ok()).collect())
        .unwrap_or_default();

    let event_feedback: Vec<EventFeedbackOut> = value.get("eventFeedback")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| serde_json::from_value(x.clone()).ok()).collect())
        .unwrap_or_default();

    let warnings: Vec<String> = value.get("warnings")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default();

    let joint_telemetry    = value.get("jointTelemetry").cloned();
    let actuator_telemetry = value.get("actuatorTelemetry").cloned();
    let gear_telemetry     = value.get("gearTelemetry").cloned();
    let assembly_telemetry = value.get("assemblyTelemetry").cloned();

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

fn load_model_from_folder(folder: &PathBuf) -> Result<(serde_json::Value, SimOut), String> {
    let metadata_path = folder.join("metadata.json");
    let text = std::fs::read_to_string(&metadata_path)
        .map_err(|e| format!("metadata.json 읽기 실패: {e}"))?;
    let mut meta: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("metadata.json 파싱 실패: {e}"))?;

    // visual mesh 경로를 절대 경로로 변환
    if let Some(bodies) = meta.get_mut("bodies").and_then(|v| v.as_array_mut()) {
        for body in bodies.iter_mut() {
            let file_rel = body
                .get("geometry")
                .and_then(|g| g.get("visual"))
                .and_then(|v| v.get("file"))
                .and_then(|f| f.as_str())
                .map(|s| s.to_string());

            if let Some(rel) = file_rel {
                if !std::path::Path::new(&rel).is_absolute() {
                    let abs = folder.join(&rel).to_string_lossy().into_owned();
                    if let Some(vis) = body
                        .get_mut("geometry")
                        .and_then(|g| g.get_mut("visual"))
                        .and_then(|v| v.as_object_mut())
                    {
                        vis.insert("file".to_string(), serde_json::Value::String(abs));
                    }
                }
            }
        }
    }

    Ok((meta, SimOut::default()))
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
    pub fn new(mut sim_io_buf: SimIoBuf, sim_error: Arc<Mutex<Option<String>>>) -> Self {
        let next_sim    = Arc::new(Mutex::new(None::<(Simulator, SimOut)>));
        let run_flag    = Arc::new(AtomicBool::new(false));
        let cond        = Arc::new((Mutex::new(()), Condvar::new()));
        let sim_running = Arc::new(AtomicBool::new(false));

        let thread = std::thread::spawn({
            let next_sim    = next_sim.clone();
            let run_flag    = run_flag.clone();
            let cond        = cond.clone();
            let sim_running = sim_running.clone();
            let sim_error   = sim_error.clone();
            move || {
                eprintln!("[sim_loop] 스레드 시작");
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
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
                        let step_result = std::panic::catch_unwind(
                            std::panic::AssertUnwindSafe(|| sim.step(inputs))
                        );
                        match step_result {
                            Ok(Ok(out)) => {
                                *sim_io_buf.simout_w.write() = SimFrame::State(out);
                                sim_io_buf.simout_swap.swap_and_clear();
                            }
                            Ok(Err(e)) => {
                                eprintln!("[sim_loop] step 오류 → 정지: {e}");
                                *sim_error.lock().expect("sim_error mutex poisoned") =
                                    Some(format!("step 오류: {e}"));
                                run_flag.store(false, Ordering::Relaxed);
                                break;
                            }
                            Err(e) => {
                                let msg = e.downcast_ref::<String>().cloned()
                                    .or_else(|| e.downcast_ref::<&str>().map(|s| s.to_string()))
                                    .unwrap_or_else(|| "알 수 없는 패닉".to_string());
                                eprintln!("[sim_loop] step 패닉 → 정지: {msg}");
                                *sim_error.lock().expect("sim_error mutex poisoned") =
                                    Some(format!("step 패닉: {msg}"));
                                run_flag.store(false, Ordering::Relaxed);
                                break;
                            }
                        }
                    }

                    sim_running.store(false, Ordering::Relaxed);
                    eprintln!("[sim_loop] 루프 정지");
                    // sim 여기서 drop (Python 객체 해제)
                }
                }));
                match result {
                    Ok(_) => eprintln!("[sim_loop] 스레드 정상 종료"),
                    Err(e) => {
                        let msg = e.downcast_ref::<String>().cloned()
                            .or_else(|| e.downcast_ref::<&str>().map(|s| s.to_string()))
                            .unwrap_or_else(|| "알 수 없는 패닉".to_string());
                        eprintln!("[sim_loop] 스레드 패닉: {msg}");
                    }
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
        let sim_error = Arc::new(Mutex::new(None::<String>));
        let sim_loop  = SimLoop::new(sim_io_buf, sim_error.clone());
        let reloading = Arc::new(AtomicBool::new(false));
        Self { sim_loop, reloading, sim_error }
    }

    // 시뮬 시작 (블로킹: Simulator::new 포함)
    pub fn start(&self, model_path: &std::path::Path) -> Result<(), String> {
        eprintln!("[sim_mgr] 모델 로드: {}", model_path.display());
        let (meta, init) = load_model_from_folder(&model_path.to_path_buf())?;
        eprintln!("[sim_mgr] Simulator::new 호출 중...");
        match Simulator::new(&meta) {
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

