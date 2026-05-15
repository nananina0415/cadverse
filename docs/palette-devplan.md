# CADverse Palette 개발 계획

## Phase 1 — 플러그인 구조 전환 (Addin화)

**목표:** Script → Addin 전환, 추출 로직 분리

| 작업 | 파일 | 내용 |
|------|------|------|
| 1-1 | `extract.py` | 기존 `CADverse.py` 내용 이동. `run(context, output_path: str)` 시그니처로 변경. 폴더 선택 대화상자 제거. |
| 1-2 | `CADverse.py` | Addin 메인. `run(context)` / `stop(context)` 구현. Palette 생성 (`ui.palettes.add`). |
| 1-3 | `CADverse.manifest` | `"type": "addin"` 으로 변경. |

검증: Fusion 360에서 Addin으로 로드 → Palette 창 열림 확인

---

## Phase 2 — Palette HTML UI

**목표:** 목업 데이터로 전체 UI 레이아웃 완성

| 작업 | 내용 |
|------|------|
| 2-1 | 초기 설정 섹션 (그룹명·비밀번호·사용자명 입력 필드 + 연결 버튼) |
| 2-2 | 그룹 정보 표시 섹션 (연결 후 표시) |
| 2-3 | 컨트롤 버튼 (일시정지/재개 토글, QR 표시) |
| 2-4 | 그룹원 리스트 + 주황/파랑/초록/회색 인디케이터 |
| 2-5 | 전체 스타일링 |

검증: 목업 데이터로 UI가 의도대로 렌더링되는지 확인

---

## Phase 3 — 서버 프로세스 관리

**목표:** 플러그인이 sim_server.exe 실행/종료 관리

| 작업 | 내용 |
|------|------|
| 3-1 | Addin `run()` 시 `../sim_server/sim_server.exe` 서브프로세스 실행 |
| 3-2 | Addin `stop()` 시 프로세스 종료 |
| 3-3 | 프로세스 비정상 종료 감지 → Palette 상태 반영 |

검증: Addin 활성화/비활성화 시 sim_server.exe 정상 시작/종료 확인

---

## Phase 4 — Named Pipe IPC

**목표:** Python ↔ Rust 양방향 통신 구현

| 작업 | 위치 | 내용 |
|------|------|------|
| 4-1 | `sim_server` (Rust) | Named Pipe 서버 (`\\.\pipe\cadverse`) 생성. 상태 변경 시 JSON 푸시. |
| 4-2 | `sim_server` (Rust) | 명령 수신 처리: `pause`, `resume`, `qr_show`, `qr_hide`, `init` |
| 4-3 | `CADverse.py` | Pipe Client 연결. 백그라운드 스레드에서 읽기. 상태 수신 시 `palette.sendInfoToHTML()` 호출. |
| 4-4 | `palette.html` | `window.adsk.fusionSendData` → Python으로 명령 전송. Python 상태 수신 → UI 갱신. |

검증: 일시정지 버튼 → Rust 서버 일시정지 → Palette 상태 반영 확인

---

## Phase 5 — Fusion 360 이벤트 연동

**목표:** 저장/탭 닫기로 추출 자동화

| 작업 | 내용 |
|------|------|
| 5-1 | `DocumentSaved` 구독 → 한글 검사 → `models/<username>/` 초기화 → 추출 (meshes 먼저, metadata.json 마지막) |
| 5-2 | 시뮬 실행 중 다른 탭 저장 → "교체하시겠습니까?" 팝업 처리 |
| 5-3 | `DocumentClosed` 구독 → `models/<username>/` 삭제 |

검증: 저장 시 모델 폴더 갱신, 탭 닫기 시 폴더 삭제, watchdog 반응 확인

---

## Phase 6 — QR 창 (always-on-top)

**목표:** QR을 별도 항상 위 고정 창으로 표시

| 작업 | 위치 | 내용 |
|------|------|------|
| 6-1 | `sim_server` (Rust) | minifb 창에 Win32 `SetWindowPos(HWND_TOPMOST)` 적용 |
| 6-2 | `sim_server` (Rust) | `qr_show` / `qr_hide` 명령 처리 |

검증: QR 창이 Fusion 360 위에 유지되는지 확인

---

## 개발 순서

```
Phase 1 (구조전환)
  → Phase 2 (UI 목업)
  → Phase 3 (프로세스 관리)
  → Phase 4 (Pipe IPC)        ← Rust 작업 병행
  → Phase 5 (이벤트 연동)
  → Phase 6 (QR 창)           ← Rust 작업
```

Phase 1~3은 Rust 수정 없이 진행 가능.
