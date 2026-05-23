#[macro_export]
macro_rules! printsh {
    ($($arg:tt)*) => {{
        print!($($arg)*);
        std::io::Write::flush(&mut std::io::stdout()).unwrap();
    }};
}

// ── stdin 입력 ────────────────────────────────────────────────────────────────

pub(crate) fn read_line() -> String {
    use std::io::BufRead;
    std::io::stdin().lock().lines().next().unwrap().unwrap()
}

pub fn input<T: std::str::FromStr>() -> T
where
    T::Err: std::fmt::Debug,
{
    loop {
        match read_line().trim().parse() {
            Ok(v) => return v,
            Err(_) => {}
        }
    }
}

// ── 트리플 버퍼 ───────────────────────────────────────────────────────────────

use std::cell::UnsafeCell;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

// state: bits 0-1 = write_idx, bits 2-3 = fresh_idx, spare = 3 - write - fresh
pub struct TripleBuffer<T> {
    bufs: UnsafeCell<[T; 3]>,
    state: AtomicU64,
}

unsafe impl<T: Send> Send for TripleBuffer<T> {}
unsafe impl<T: Send> Sync for TripleBuffer<T> {}

pub struct TripleBufWriter<T>(Arc<TripleBuffer<T>>);
pub struct TripleBufReader<T>(Arc<TripleBuffer<T>>);
pub struct TripleBufSwapper<T>(Arc<TripleBuffer<T>>);

impl<T> TripleBuffer<T> {
    // 초기: write=0, fresh=1, spare=2
    pub fn new(bufs: [T; 3]) -> (TripleBufReader<T>, TripleBufWriter<T>, TripleBufSwapper<T>) {
        let arc = Arc::new(Self {
            bufs: UnsafeCell::new(bufs),
            state: AtomicU64::new(0 | (1 << 2)), // write=0, fresh=1
        });
        (
            TripleBufReader(arc.clone()),
            TripleBufWriter(arc.clone()),
            TripleBufSwapper(arc),
        )
    }
}

impl<T> TripleBufWriter<T> {
    pub fn write(&mut self) -> &mut T {
        let write_idx = (self.0.state.load(Ordering::Acquire) & 0b11) as usize;
        unsafe { &mut (*self.0.bufs.get())[write_idx] }
    }
}

impl<T> TripleBufReader<T> {
    pub fn read(&self) -> &T {
        let fresh_idx = ((self.0.state.load(Ordering::Acquire) >> 2) & 0b11) as usize;
        unsafe { &(*self.0.bufs.get())[fresh_idx] }
    }
}

pub trait Clearable {
    fn clear(&mut self);
}

impl<T> Clearable for Vec<T> {
    fn clear(&mut self) { self.clear(); }
}

impl<T> TripleBufSwapper<T> {
    // write 슬롯을 fresh로 올리고, spare를 새 write 슬롯으로
    pub fn swap(&self) {
        let state = self.0.state.load(Ordering::Acquire);
        let write_idx = (state & 0b11) as usize;
        let fresh_idx = ((state >> 2) & 0b11) as usize;
        let spare_idx = 3 - write_idx - fresh_idx;
        self.0.state.store(
            (spare_idx as u64) | ((write_idx as u64) << 2),
            Ordering::Release,
        );
    }

    pub fn swap_and_clear(&self) where T: Clearable {
        self.swap();
        let write_idx = (self.0.state.load(Ordering::Acquire) & 0b11) as usize;
        unsafe { (*self.0.bufs.get())[write_idx].clear(); }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::sync::atomic::{AtomicBool, Ordering as AtomicOrdering};

    // SimOut의 telemetry: Option<ContactTelemetryOut> 패턴 모사.
    // clear() 시 self.telemetry = None → ContactTelemetryOut/ContactPairOut의 String 모두 drop.
    // reader가 그 String의 buffer를 직렬화 중이면 use-after-free.
    #[derive(Default, serde::Serialize)]
    struct StringPayload {
        items: Vec<String>,
        telemetry: Option<ContactTelemetryOut>,
    }

    #[derive(serde::Serialize)]
    struct ContactTelemetryOut {
        contact_count: i32,
        max_pair: Option<ContactPairOut>,
    }

    #[derive(serde::Serialize)]
    struct ContactPairOut {
        body_a: String,
        body_b: String,
    }

    impl Clearable for StringPayload {
        fn clear(&mut self) {
            self.items.clear();
            // 실제 SimOut::clear의 self.telemetry = None과 동일.
            // ContactTelemetryOut/ContactPairOut의 String들이 drop되어 buffer가 free된다.
            self.telemetry = None;
        }
    }

    /// reader가 read()로 받은 &T 참조의 유효성을 writer/swapper가 침범할 수 있는지 확인.
    ///
    /// 실제 시나리오에 맞춰 reader는 serde_json::to_vec으로 직렬화 (broadcast 루프와 동일).
    /// writer는 String이 들어간 페이로드를 채우고 swap_and_clear를 반복.
    ///
    /// 자체 TripleBuffer의 race로 STATUS_ACCESS_VIOLATION (Windows segfault)를 재현하는 테스트.
    /// 의도된 실패이므로 `#[ignore]` — 명시 실행 시에만 돌림:
    ///   cargo test --bin server -- --ignored read_reference
    /// simout은 이미 triple_buffer crate로 교체됐고, 이 테스트는 자체 TripleBuffer가
    /// userin에 남아 있는 동안 잠재 race가 있음을 문서화한다 (BUGS.md 참고).
    #[test]
    #[ignore]
    fn read_reference_can_be_invalidated_by_concurrent_swap() {
        let (reader, mut writer, swapper) = TripleBuffer::new([
            StringPayload::default(),
            StringPayload::default(),
            StringPayload::default(),
        ]);

        let stop = std::sync::Arc::new(AtomicBool::new(false));
        let stop_for_writer = stop.clone();

        let writer_handle = thread::spawn(move || {
            let mut counter = 0u64;
            while !stop_for_writer.load(AtomicOrdering::Relaxed) {
                {
                    let payload = writer.write();
                    payload.telemetry = Some(ContactTelemetryOut {
                        contact_count: counter as i32,
                        max_pair: Some(ContactPairOut {
                            body_a: format!("EXPORT_shaft_{counter}"),
                            body_b: format!("5972K315_Ball_Bearing_{counter}"),
                        }),
                    });
                    for i in 0..4 {
                        payload.items.push(format!("diagnostic_message_{counter}_{i}_padding_text"));
                    }
                }
                swapper.swap_and_clear();
                counter += 1;
            }
        });

        // 메인 스레드 = reader. broadcast 루프가 매 read마다 serde_json::to_vec 호출하는 흐름.
        // 직렬화 작업이 충분히 길어야 그 사이 writer가 swap을 여러 번 해서 reader slot을 침범할 수 있다.
        for _ in 0..50_000 {
            let payload = reader.read();
            let _ = serde_json::to_vec(payload);
        }

        stop.store(true, AtomicOrdering::Relaxed);
        writer_handle.join().unwrap();
    }
}
