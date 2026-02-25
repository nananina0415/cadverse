// src/sim_loop_thread.rs
//
// Sim loop runner:
// - 별도 스레드에서 Python Simulator(=PyChrono 래퍼)를 계속 step()
// - 입력은 외부에서 주입받는 "읽기 전용" 인터페이스로 가정
// - 출력은 외부 버퍼(publish)로 내보내는 콜백/클로저로 가정

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use anyhow::Result;
use serde_json::Value;

use crate::sim_state::SimState;
use crate::simulator_binding::Simulator;

/// 시뮬레이션 루프에 주입될 "입력 읽기" 인터페이스.
///
/// - Input은 "Python step(userInput)"에 넘길 데이터.
/// - 추천: serde_json::Value로 통일해서 schema-06 이벤트 dict를 그대로 넘긴다.
///   예) {"type":"TouchStart","payload":{...}}
pub trait InputSource: Send + Sync + 'static {
    fn read(&self) -> Option<Value>;
}

/// 시뮬레이션 결과를 내보내는 sink.
pub trait StateSink: Send + Sync + 'static {
    fn publish(&self, state: SimState);
}

/// 루프 제어(중지)용 핸들.
#[derive(Clone)]
pub struct SimLoopControl {
    stop_flag: Arc<AtomicBool>,
}

impl SimLoopControl {
    pub fn stop(&self) {
        self.stop_flag.store(true, Ordering::SeqCst);
    }
}

/// 이미 생성된 Simulator로 시뮬레이션 루프를 시작한다.
///
/// - 입력이 있으면 simulator.step(Some(json))로 전달되어
///   Python(main.py)의 AR interaction이 실제로 동작한다.
pub fn run_sim_loop<I, S>(
    simulator: Simulator,
    input: Arc<I>,
    sink: Arc<S>,
    target_dt: Option<Duration>,
) -> (JoinHandle<Result<()>>, SimLoopControl)
where
    I: InputSource,
    S: StateSink,
{
    let stop_flag = Arc::new(AtomicBool::new(false));
    let control = SimLoopControl {
        stop_flag: stop_flag.clone(),
    };

    let handle: JoinHandle<Result<()>> = thread::spawn(move || {
        let mut last_tick = Instant::now();

        while !stop_flag.load(Ordering::SeqCst) {
            let maybe_in: Option<Value> = input.read();

            // ✅ 핵심: userInput을 Python Simulator.step에 전달
            let state: SimState = simulator.step(maybe_in)?;

            sink.publish(state);

            if let Some(dt) = target_dt {
                let elapsed = last_tick.elapsed();
                if elapsed < dt {
                    thread::sleep(dt - elapsed);
                }
                last_tick = Instant::now();
            } else {
                thread::sleep(Duration::from_millis(1));
            }
        }

        Ok(())
    });

    (handle, control)
}
