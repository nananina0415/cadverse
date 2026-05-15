# 알려진 버그

## [server] watchdog 리로드 후 시뮬레이션 영구 정지

**파일:** `server/src/sim.rs` — `FLAG_PAUSE` 처리 블록 (라인 521~535)  
**증상:** watchdog이 모델 변경을 감지해 reload가 완료된 후 시뮬레이션이 재개되지 않고 멈춤  
**원인:** reload 완료 후 `flag`를 `FLAG_RUN`으로 되돌리는 코드 없음. 다음 루프 반복에서 다시 `FLAG_PAUSE`로 진입 → `cv.wait`에 영구 블록  
**부가 이슈:** `notify_one`이 `cv.wait` 호출 전에 실행될 수 있는 경쟁 조건 (낮은 확률)

**수정:**
```rust
FLAG_PAUSE => {
    if reload_data.lock().expect("reload_data mutex poisoned").is_none() {
        let (lock, cv) = &*cond;
        let guard = lock.lock().expect("cond mutex poisoned");
        let _guard = cv.wait(guard).expect("condvar wait 실패");
    }
    if let Some((m, init)) = reload_data.lock().expect("reload_data mutex poisoned").take() {
        if let Err(e) = simulator.reload(&m) {
            eprintln!("시뮬레이터 재생성 실패: {e}");
            break;
        }
        sim_io_buf.clear_and_init(init);
        flag.store(FLAG_RUN, Ordering::Relaxed);  // ← 추가
    }
}
```
