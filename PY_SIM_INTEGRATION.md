# py_sim 브랜치 통합 작업

`origin/py_sim`의 이벤트 기반 피드백 기능을 현재 브랜치(`feature/palette-ui`)에 가져오는 작업.

**작업 원칙**
- 현재 코드의 구조적 변경은 하지 않는다.
- py_sim 브랜치 작성자가 만든 레거시 호환/하드코딩/레이어 위반 부분은 가려서 버린다.
- 모든 코드 변경 전 사용자 승인을 받는다.

---

## 분류 결과

### A. 그대로 가져옴 (Python 시뮬레이터)

위치: `server/pychrono/simulator/`

| 파일 | 비고 |
|---|---|
| `SimInfo.py` (신규 36줄) | `SimOptions`에 `enable_event_feedback`, `event_feedback_enable_sound` 등 토글, `SimInfo` 래퍼 |
| `runtime_types.py` (+119줄) | `EventFeedback`, `PartRef`, `SimState` telemetry 확장 |
| `sim_builder.py` (+51줄) | physics preset, contact material 확장 |
| `main.py` (+442줄) | 이벤트 피드백 발생 로직 |

**`SimState.to_dict()`가 새로 내보내는 필드** (모두 optional):
- `partNames: List[str]`
- `telemetry: ContactTelemetry`
- `interactionTelemetry: InteractionTelemetry`
- `gearTelemetry`, `assemblyTelemetry`, `jointTelemetry`, `actuatorTelemetry`
- `diagnostics: List[DiagnosticItem]`
- **`eventFeedback: List[EventFeedback]`** ← 핵심 (soundId/soundType/volume/pitch/message)
- `warnings: List[str]`

---

### B. 로직만 가져와 직접 코딩 (구조 보존)

#### B-1. `server/src/sim.rs`

**가져옴:**
- 새 출력 타입 정의:
  - `ContactPairOut`, `ContactTelemetryOut`
  - `InteractionTelemetryOut`
  - `DiagnosticOut`
  - **`EventFeedbackOut`** ← 핵심
- `SimOut`에 새 필드 추가:
  ```rust
  pub seq: Option<i64>,
  pub telemetry: Option<ContactTelemetryOut>,
  pub interaction_telemetry: Option<InteractionTelemetryOut>,
  pub diagnostics: Vec<DiagnosticOut>,
  pub event_feedback: Vec<EventFeedbackOut>,
  pub warnings: Vec<String>,
  // 스키마 미고정은 raw JSON value로
  pub joint_telemetry: Option<serde_json::Value>,
  pub actuator_telemetry: Option<serde_json::Value>,
  pub gear_telemetry: Option<serde_json::Value>,
  pub assembly_telemetry: Option<serde_json::Value>,
  ```
- `Clearable` 구현에 새 필드 clear 추가
- `build_py_sim`에서 `SimOptions` 인자:
  - `enable_contact_telemetry=true`
  - `enable_event_feedback=true`
  - `event_feedback_enable_sound=true`
  - `max_contact_points_report=256`
- `py_state_to_simout`: `state.to_dict()` 호출 → JSON 변환 → 모든 새 필드 추출하는 함수

**가져오지 않음 (현재 구조 유지):**
- `SimFrame` enum 제거 → 현재의 `SimFrame::State(SimOut)` / `SimFrame::Reload` 유지
- `AtomicBool` → `AtomicU8` 상태머신 변환 → 현재 watchdog 구조 유지
- `meta: &serde_json::Value` → `model: &SimModel` 강타입화 → 영향 너무 큼, 보류
- 디버그 `eprintln!` 일괄 삭제 → 유지

#### B-2. `client/Assets/Script/Server.cs` 확장

- `_RawState`에 새 필드 추가 (서버 JSON 미러):
  - `telemetry`, `interactionTelemetry`, `diagnostics`, `eventFeedback`, `warnings`, `partNames`, `seq`
- `StateFrame`에 typed 필드 추가
- `EventFeedback` C# 타입 신설 (Python 미러):
  ```csharp
  public struct EventFeedback {
      public string EventType, Severity, Message, Target;
      public string SoundId, SoundType;
      public float? Volume, Pitch;
  }
  ```

#### B-3. `client/Assets/Script/AppManager.cs` (또는 새 클래스)

- `StateFrame.EventFeedback` 도착 시 처리 로직 추가
  - 메시지 → `Toast`
  - sound → 재생 (D 영역에서 별도 컴포넌트 작성)

---

### C. 가져오지 않음 (py_sim 코드 무시)

| 영역 | py_sim 변경 | 무시 사유 |
|---|---|---|
| `server/src/net.rs` `main.rs` `pipe.rs` | 로그 일괄 제거, Windows topmost 코드 제거 | 노이즈, 가져갈 가치 없음 |
| `cad_plugin/CADverse.py` | chrono_310 PATH 주입 + 옛 `stop()` (deadlock 버전) | 비공식 env, 이전 작업 역행 |
| `cad_plugin/extract_meta.py` | `FUSION_CM_TO_M` → `FUSION_MM_TO_M` + `_build_legacy_ar_transforms` | 단위 버그 역행, 레거시 APK 호환 |
| `cad_plugin/extract.py` | `transforms` 키 추가 | 위와 같은 레거시 |
| `cad_plugin/palette.html` | 옛 버전 (인라인 onclick, `_myUsername` 없음) | 현재 브랜치 픽스보다 옛것 |
| `client/Assets/Script/*.cs` | 옛 버전 (Server.cs 없음, fffd133 미적용) | 현재 브랜치가 신규 |

---

### D. 새로 설계할 것 (py_sim에 없거나 부족)

#### D-1. 러스트 ↔ 플러그인 소통 추가
- 시뮬 옵션 전환을 플러그인에서 토글하는 채널
- py_sim의 `pipe.rs`엔 없음 — 처음부터 설계

#### D-2. 플러그인 UI
- 이벤트 피드백 옵션, 시뮬 telemetry 표시 등
- py_sim의 `palette.html`엔 없음

#### D-3. 클라이언트 EventFeedback 처리
- Toast 메시지 출력
- 사운드 재생 컴포넌트 (`AudioSource` 또는 풀링)
- 사운드 리소스 매핑(`soundId` → AudioClip)

---

## 진행 순서 및 체크리스트

- [x] **1. Python 시뮬레이터 복사 (A)** — `server/pychrono/simulator/` 4개 파일을 origin/py_sim에서 그대로 가져오기 (`ece2b5e`)
- [x] **2. sim.rs 확장 (B-1)** — 새 타입 + SimOut 새 필드 + build_py_sim 옵션 + py_state_to_simout 재작성. SimFrame/AtomicBool 구조는 그대로
- [ ] **3. 서버 빌드 + 동작 확인** — 시뮬이 SimOut을 새 형식으로 잘 내보내는지 확인 (cargo check ✅ / 실제 런타임 확인 대기)
- [x] **4. Server.cs 확장 (B-2)** — 새 필드 받기 + EventFeedback 타입 (핵심 3종: EventFeedback/Diagnostics/Warnings)
- [x] **5. AppManager EventFeedback 처리 (B-3)** — Message → Toast, Warnings/Diagnostics → Debug 로그, SoundId는 D-3에서 처리
- ~~6. D-3 사운드 재생~~ — **범위 밖**. `SoundId` 도착 시 `Debug.Log`만 남기고 실제 재생은 별도 작업으로 분리
- [x] **7. 통신 레이어 확장 — telemetry typed 수신**
    - Newtonsoft.Json 패키지 추가 (manifest.json)
    - `Server.SimFrameAndInfo()` 신규 — Newtonsoft로 dict telemetry까지 typed 파싱
    - `StateFrame`에 `InteractionTelemetry / Telemetry / Joint/Actuator/Gear/AssemblyTelemetry` 필드 추가
    - `AppManager.NeedsFullInfo` 토글 — UI 측이 정보 표시 모드 진입 시 켜면 `SimFrameAndInfo()` 호출
    - UI 구현은 `HandleStateFrame`의 TODO 주석으로 안내

---

## 결정 사항 기록

| 시점 | 결정 | 이유 |
|---|---|---|
| 분석 시점 | `SimFrame` 구조 유지 | 현재 코드 구조 변경 금지 |
| 분석 시점 | `meta → SimModel` 강타입화 보류 | 영향 범위 너무 큼 |
| 분석 시점 | `_build_legacy_ar_transforms` 무시 | 현재 ARScene이 새 스키마 사용 중 |
| 분석 시점 | `FUSION_MM_TO_M` 변경 무시 | 이전 작업에서 cm가 맞다고 확정 |
| 5단계 직후 | 사운드 재생(D-3) 범위 밖 | 사용자 지시 — `SoundId`는 일단 로그만 |
