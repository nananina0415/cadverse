# sim_manager

시뮬레이션 라이프사이클 관리, PyO3 Python 바인딩, 핫스왑을 담당하는 크레이트.

## 모듈 구조

```
src/
├── lib.rs                # 모듈 선언 + 공개 API
├── simulator_binding.rs  # PyO3 Python 바인딩 (Simulator struct)
├── sim_loop_thread.rs    # 시뮬레이션 루프 (별도 스레드)
├── sim_state.rs          # Rust측 SimState/PartState 구조체
├── input_buffer.rs       # 트리플 버퍼 입력 시스템
└── orchestrator.rs       # 시뮬레이션 핫스왑 오케스트레이터
```

## 핵심 컴포넌트

### Simulator (simulator_binding.rs)

PyO3로 Python의 `simulator.main.Simulator`를 감싸는 구조체.

```rust
pub struct Simulator {
    py_simulator_obj: Py<PyAny>,    // Python Simulator 인스턴스
    prev_state: Mutex<SimState>,
}

impl Simulator {
    pub fn new(scene_path: &str) -> Result<Self>  // Python Simulator 생성
    pub fn step(&self) -> Result<SimState>         // 한 스텝 실행
}
```

Python 호출 순서:
1. `simulator.SimInfo.SimInfo.from_json_file(scene_path, dt=dt)`
2. `simulator.main.Simulator.create(info)`
3. `sim.step(None)` → `SimState` 반환

### SimLoopThread (sim_loop_thread.rs)

별도 OS 스레드에서 시뮬레이션 루프를 실행.

```rust
pub fn run_sim_loop<I, S>(
    simulator: Simulator,       // 이미 생성된 Simulator
    input: Arc<I>,              // InputSource 구현체
    sink: Arc<S>,               // StateSink 구현체
    target_dt: Option<Duration>,
) -> (JoinHandle<Result<()>>, SimLoopControl)
```

트레이트:
```rust
pub trait InputSource: Send + Sync + 'static {
    type Input: Send + Sync + Clone + 'static;
    fn read(&self) -> Option<Self::Input>;
}

pub trait StateSink: Send + Sync + 'static {
    fn publish(&self, state: SimState);
}
```

### SimOrchestrator (orchestrator.rs)

시뮬레이션 핫스왑을 관리. 다운타임 최소화를 위한 교환 순서:

```
swap_simulation(scene_path):
    1. 새 Simulator 생성        ← 기존은 아직 실행 중 (느린 Python 초기화 동안 서비스 유지)
    2. 기존 sim loop 정지 + join
    3. 같은 버퍼(Arc)로 새 sim loop 시작
    4. 기존 Simulator 자동 drop
```

```rust
pub struct SimOrchestrator<I, S> {
    input: Arc<I>,      // 서버 스레드와 공유
    sink: Arc<S>,       // 서버 스레드와 공유
    // ...
}

impl SimOrchestrator {
    pub fn swap_simulation(&mut self, scene_path: &str)
    pub fn run(self, rx: Receiver<LoaderMessage>)  // 리로드 대기 루프
}
```

### InputBuffer (input_buffer.rs)

트리플 버퍼 패턴으로 WebSocket 입력을 시뮬레이션에 전달.

```
WebSocket 스레드:  push() → flip_write()
                          ↓
                     [swap 버퍼]
                          ↓
Sim 스레드:         flip_read() → read_all()
```

`InputSource` 트레이트 구현됨: `read()` 호출 시 `flip_read()` + `read_all()` 자동 수행.

### SimState (sim_state.rs)

Python `runtime_types.SimState`의 Rust 미러 구조체.

```rust
pub struct SimState {
    pub sim_time: f64,
    pub parts: Vec<PartState>,
}

pub struct PartState {
    pub name: String,
    pub pos: [f64; 3],      // [x, y, z]
    pub rot: [f64; 4],      // [w, x, y, z] (Chrono 쿼터니언 순서)
}
```

## 타입 변환

SimState(내부) → SimulationState(서버) 변환은 루트 크레이트의 `sim_state_buffer.rs`에서 수행:

| SimState (Python/내부) | SimulationState (서버/클라이언트) |
|---|---|
| `f64` | `f32` |
| rot: `[w, x, y, z]` | rotation: `[x, y, z, w]` |

## 의존성

| 크레이트 | 용도 |
|----------|------|
| `pyo3` | Python FFI (auto-initialize, Bound API) |
| `crossbeam-channel` | LoaderMessage 수신 |
| `parking_lot` | InputBuffer 내부 RwLock |
| `cad_data_loader` | LoaderMessage 타입 |
