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
            Err(e) => println!("잘못된 입력: {e:?}"),
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
