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

/// make_sim_loop_thread
/// - 입력 소스 + 출력 싱크를 받아 별도 스레드에서 시뮬레이션을 계속 돈다.
///
/// 주의:
/// - Simulator::new()가 Python 초기화/SimInfo 로딩 등을 내부에서 처리한다고 가정.
/// - 실제 프로젝트에서는 new()에 config/info를 넘기는 형태가 더 자연스럽다.
///
/// 추가로:
/// - 너무 빠르게 도는 busy loop를 피하려고,
///   입력이 없거나 step이 즉시 끝나는 경우 sleep을 조금 넣을 수 있다.
/// - dt 기반 pacing이 필요하면 target_dt 옵션을 써라.
pub fn make_sim_loop_thread<I, S>(
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
        // 1) simulator 생성 (Python Simulator 래핑)
        let simulator = Simulator::new()?;

        // 2) 루프 pacing
        let mut last_tick = Instant::now();

        // 3) main loop
        while !stop_flag.load(Ordering::SeqCst) {
            // 입력 읽기 (없으면 None)
            let maybe_in = input.read();

            // step 실행
            // - Simulator::step는 (Option<Input>)을 받아 SimState를 반환한다고 가정
            // - Input 타입은 simulator_binding.rs에서 pyo3로 dict 변환/처리하도록 설계
            let state: SimState = simulator.step(maybe_in)?;

            // 결과 publish
            sink.publish(state);

            // (선택) target_dt pacing
            if let Some(dt) = target_dt {
                let elapsed = last_tick.elapsed();
                if elapsed < dt {
                    thread::sleep(dt - elapsed);
                }
                last_tick = Instant::now();
            } else {
                // (선택) 과도한 busy loop 방지: 아주 짧게 양보
                // 필요 없으면 지워도 됨.
                thread::sleep(Duration::from_millis(1));
            }
        }

        Ok(())
    });

    (handle, control)
}

/* -----------------------------
   아래는 "팀원 요구 형태"에 더 가까운 최소 예시(참고용)
   -----------------------------

use std::thread::JoinHandle;

pub fn make_sim_loop_thread_minimal<I: InputSource>(input: Arc<I>) -> JoinHandle<()> {
    thread::spawn(move || {
        let simulator = Simulator::new().expect("failed to create Simulator");
        loop {
            let _state = simulator.step(input.read()).expect("step failed");
        }
    })
}

*/
