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

## [server] spring 모드 진입 시 SimState에 NaN/Infinity 섞여 sim_loop 정지

**파일:** `server/src/sim.rs::py_state_to_simout`, `server/pychrono/simulator/main.py::_apply_spring` (또는 그 telemetry 계산 어딘가)
**증상:** 부품을 spring 모드(주로 fixed 아닌 일반 body)로 터치하자마자 sim_loop가 step 오류로 정지

**관찰된 로그:**
```
[user_in] TouchStart(...) target=5972K315_Ball_Bearing_1 mode=spring
[sim_loop] step 오류 → 정지: Python step 실패:
    ValueError: SimState JSON parse 실패: expected value at line 1 column 639
```

**원인:**
- Python `state.to_dict()` 안에 `NaN` 또는 `Infinity` float가 포함됨 (spring 모드 첫 step에서 0으로 나누기 또는 inf 전파로 추정)
- Python `json.dumps`는 기본 `allow_nan=True`라 `NaN`/`Infinity`/`-Infinity`를 비표준 JSON 토큰으로 그대로 출력
- Rust `serde_json::from_str`은 표준 JSON만 받음 → 파싱 실패 → `Python step 실패` 리턴 → sim_loop 정지

**임시 수정 (적용됨):**
`sim.rs::py_state_to_simout`에서 JSON 문자열의 `-Infinity` / `Infinity` / `NaN` 을 `null`로 사전 치환 후 파싱.
이러면 sim_loop는 죽지 않지만 해당 필드가 클라에 `null`로 도달하므로 정확한 telemetry는 잃음.

**본질 수정 (TODO):**
Python `_apply_spring` 또는 telemetry 계산 어디서 NaN/Infinity가 발생하는지 추적해 사전 방지.
힌트: ball bearing이 fixed 아닌 spring 대상이고, 그 step에서 0 division 가능성 — joint reaction force / power 계산 등.

---

## [server↔plugin] sim_loop 도중 정지가 플러그인에 알려지지 않음

**파일:** `server/src/sim.rs::SimLoop`, `server/src/main.rs::push_status`
**증상:** step 오류/패닉으로 sim_loop가 정지해도 플러그인 UI는 `sim_running=true` 그대로 유지. 사용자는 "시뮬이 돌지 않는다"는 것만 보이고 원인 메시지 없음.

**원인:**
- 기존 `sim_error`는 `Simulator::new` 실패 시에만 set됨
- 런타임 `sim.step` 실패는 `run_flag=false`로 자체 정지만 하고 `sim_error`에 메시지 안 남김
- `main.rs::push_status`는 `sim_error`를 받아 `StatusMsg.sim_error`로 plugin에 전달하지만, 비어있어 표시할 게 없음

**수정 (적용됨):**
- `SimLoop::new`가 `sim_error: Arc<Mutex<Option<String>>>` 인자를 받도록 시그니처 변경
- `SimManager::new`에서 sim_error를 만들어 `SimLoop::new`에 클론 전달
- step 오류/패닉 catch arm에서 `sim_error`에 메시지 set (`"step 오류: ..."` / `"step 패닉: ..."`)
- 기존 `push_status` 흐름이 자동으로 plugin status에 실어 보냄

---

## [server] 자체 TripleBuffer의 reader 슬롯 use-after-free

**파일:** `server/src/utils.rs::TripleBuffer`
**증상:** 시뮬 시작 직후 `vec/mod.rs:1637`의 `slice::from_raw_parts` precondition 위반 패닉 또는 Windows `STATUS_ACCESS_VIOLATION` (0xc0000005). broadcast 루프의 `serde_json::to_vec(SimOut)` 안에서 `ContactPairOut.body_a/body_b` 같은 String의 `as_str()` 호출 시 발생.

**원인 — 동기화 누락:**
- `TripleBufReader::read()`는 `&T` 참조만 반환하고, 그 참조의 lifetime이 `swap()`을 막지 않음
- 표준 SPSC triple buffer는 reader 슬롯 인덱스를 별도 추적해 swapper가 그 슬롯을 침범하지 못하게 해야 하는데, 자체 구현은 single `AtomicU64` state만 사용
- writer가 짧은 시간에 swap을 2번 이상 호출하면 reader가 점유한 슬롯이 새로운 `write_idx`가 되고, `swap_and_clear`가 그 슬롯의 `Clearable::clear()`를 호출 → reader가 보던 `&T` 안의 String이 drop돼 buffer free → use-after-free

**재현 (단위 테스트):**
`utils.rs::tests::read_reference_can_be_invalidated_by_concurrent_swap` — `#[ignore]` 처리됨. 명시 실행:
```
cargo test --bin server -- --ignored read_reference
```
실제 SimOut 구조와 동일한 `Option<ContactTelemetryOut(Option<ContactPairOut(String, String)>)>` 페이로드로 `STATUS_ACCESS_VIOLATION` 재현 확인.

**수정 (적용됨, 부분):**
`simout` 채널만 검증된 `triple_buffer = "8"` crate으로 교체.
- `Cargo.toml`: `triple_buffer = "8"` 추가
- `SimIoBuf.simout_w`: `triple_buffer::Input<SimFrame>` 단일 필드 (Writer + Swapper 통합)
- `simout_w.input_buffer()` / `.publish()`로 사용
- `NetThread::new`의 `simout_r`: `triple_buffer::Output<SimFrame>`

**남은 TODO:**
`userin` (`Vec<UserIn>`)은 여전히 자체 TripleBuffer 사용 중. 같은 race가 잠재해 있지만 String/Vec 직렬화 없이 단순 read만 하므로 현실적으로 trigger되기 어려움. 그래도 모든 채널을 동일 crate으로 통일하는 게 안전 — 별도 작업으로 분리.
