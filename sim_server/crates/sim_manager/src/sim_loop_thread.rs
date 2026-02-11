// src/sim_loop_thread.rs
//
// Sim loop runner:
// - 별도 스레드에서 Python Simulator(=PyChrono 래퍼)를 계속 step()
// - 입력은 외부에서 주입받는 "읽기 전용" 인터페이스로 가정
// - 출력은 외부 버퍼(publish)로 내보내는 콜백/클로저로 가정
//
// 팀원 요구 형태:
// fn make_sim_loop_thread(input)->Thread{
//     let simulator = Simulator::new();
//     loop {
//         simulator.step(input.read())
//     }
// }

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use anyhow::Result;

use crate::sim_state::SimState;
use crate::simulator_binding::Simulator;

/// 시뮬레이션 루프에 주입될 "입력 읽기" 인터페이스.
/// - 구현체는 Arc로 공유되고, 루프는 계속 read()를 호출한다.
/// - 여기서 Input은 "Python step(userInput)"에 넘길 데이터.
///   (예: runtime_input_schema(06) 기반 dict/json/구조체 등)
pub trait InputSource: Send + Sync + 'static {
    type Input: Send + Sync + Clone + 'static;

    /// 현재 프레임에서 쓸 입력을 읽어온다.
    /// - 입력이 없으면 None을 반환해도 됨.
    fn read(&self) -> Option<Self::Input>;
}

/// 시뮬레이션 결과를 내보내는 sink.
/// - 예: SimStateBuffer.publish(state)
pub trait StateSink: Send + Sync + 'static {
    fn publish(&self, state: SimState);
}

/// 루프 제어(중지)용 핸들.
/// - stop_flag를 true로 바꾸면 스레드가 빠져나오게 설계.
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
/// orchestrator에서 Simulator를 외부에서 생성한 뒤 이 함수에 전달한다.
/// 1ms 간격으로 step()을 실행하고 결과를 sink로 publish한다.
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
            let _maybe_in = input.read();

            let state: SimState = simulator.step()?;

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
