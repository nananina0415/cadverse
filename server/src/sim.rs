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
                            Ok(Ok(objects)) => {
                                *sim_io_buf.simout_w.write() = SimFrame::State(SimOut { timestamp: 0.0, objects });
                                sim_io_buf.simout_swap.swap_and_clear();
                            }
                            Ok(Err(e)) => {
                                eprintln!("[sim_loop] step 오류 → 정지: {e}");
                                run_flag.store(false, Ordering::Relaxed);
                                break;
                            }
                            Err(e) => {
                                let msg = e.downcast_ref::<String>().cloned()
                                    .or_else(|| e.downcast_ref::<&str>().map(|s| s.to_string()))
                                    .unwrap_or_else(|| "알 수 없는 패닉".to_string());
                                eprintln!("[sim_loop] step 패닉 → 정지: {msg}");
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
        let sim_loop  = SimLoop::new(sim_io_buf);
        let reloading = Arc::new(AtomicBool::new(false));
        let sim_error = Arc::new(Mutex::new(None::<String>));
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

