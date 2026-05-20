# CADverse Palette 설계 문서

## 개요

Fusion 360 Addin으로 동작하는 서버 컨트롤 패널. 별도 서버 GUI 앱 없이 Fusion 360 내부 패널에서 시뮬레이션 서버를 제어한다.

---

## 배포 폴더 구조

```
cadverse/
├── plugin/               ← Fusion 360 Addin (이 폴더를 Add-ins에 등록)
│   ├── CADverse.py
│   ├── CADverse.manifest
│   ├── extract.py
│   └── palette.html
└── sim_server/
    ├── sim_server.exe
    └── py_env/           ← 번들된 Python 환경
```

플러그인은 `../sim_server/sim_server.exe` 경로로 서버를 실행한다.

---

## 아키텍처

```
[Fusion 360]
  └── CADverse Addin (Python)
        ├── palette.html       ← HTML/CSS/JS UI
        ├── extract.py         ← 메시·메타데이터 추출
        └── Named Pipe ────────── sim_server.exe (Rust)
                                        └── sim_server/models/<username>/
                                              ├── metadata.json
                                              └── meshes/*.obj
```

---

## 이벤트 → 동작 매핑

| Fusion 360 이벤트 | 동작 |
|---|---|
| `DocumentSaved` | 한글 검사 → `models/<username>/` 초기화 → 추출 (meshes 먼저, metadata.json 마지막) → watchdog이 감지해 시뮬 자동 시작 |
| `DocumentClosed` | `models/<username>/` 삭제 → watchdog이 감지해 시뮬 종료 |
| 시뮬 실행 중 다른 탭 저장 | "실행 중인 시뮬레이션을 교체하시겠습니까?" 팝업 → 확인 시 교체 |
| Addin `stop()` | 서버 프로세스 종료 |

---

## 파일 구조

```
plugin/
├── CADverse.py          ← Addin 메인 (run/stop, 이벤트 핸들러, 서버 프로세스 관리, Pipe 통신)
├── CADverse.manifest    ← type: "addin"
├── extract.py           ← 추출 로직 (구 CADverse.py, 경로 파라미터로 받음)
└── palette.html         ← Palette UI
```

---

## Palette UI 레이아웃

```
┌──────────────────────────────┐
│  ● CADverse                  │  ← 서버 연결 상태 표시
├──────────────────────────────┤
│  그룹명    [입력 or 표시]    │  ← 미설정 시 입력 가능, 설정 후 표시
│  비밀번호  ●●●●●●           │
│  나        [username]        │
├──────────────────────────────┤
│  [⏸ 일시정지 / ▶ 재개]      │  ← 시뮬 실행 중일 때만 활성화
│  [QR 표시]                   │
├──────────────────────────────┤
│  그룹원                       │
│  kim   ● ● ●                 │  ← 주황(서버) / 파랑(클라) / 초록(시뮬)
│  lee   ● ● ●                 │  ← 꺼짐 = 회색
└──────────────────────────────┘
```

### 상태 인디케이터 색상

| 색상 | 의미 |
|------|------|
| 🟠 주황 | 서버 연결됨 |
| 🔵 파랑 | 클라이언트 연결됨 |
| 🟢 초록 | 시뮬레이션 실행 중 |
| ⚪ 회색 | 꺼짐 |

---

## 초기 설정 (최초 실행)

- Palette 안에 그룹명·비밀번호·사용자명 입력 필드 표시
- 입력 후 "연결" 버튼 → `plugin/config.json`에 저장
- 이후 실행 시 저장된 값 자동 로드

```json
{
  "username": "kim",
  "group_name": "lab01",
  "group_password": "xxxx"
}
```

---

## IPC — Named Pipe

파이프 이름: `\\.\pipe\cadverse`

서버가 Pipe Server, 플러그인이 Pipe Client.

### 메시지 형식

줄바꿈(`\n`)으로 구분된 JSON 메시지.

**Plugin → Server (명령):**
```json
{ "cmd": "pause" }
{ "cmd": "resume" }
{ "cmd": "qr_show" }
{ "cmd": "qr_hide" }
{ "cmd": "init", "username": "kim", "group": "lab01", "password": "xxxx" }
```

**Server → Plugin (상태 푸시):**
```json
{
  "sim_running": true,
  "paused": false,
  "members": [
    { "name": "kim", "server": true,  "client": true,  "sim": true  },
    { "name": "lee", "server": true,  "client": false, "sim": false }
  ]
}
```

서버는 상태 변경 시마다 플러그인에 푸시. 플러그인은 별도 스레드에서 파이프를 읽어 Palette를 갱신.

---

## QR 창

- Rust 서버가 Win32 `SetWindowPos(HWND_TOPMOST)`로 항상 위 고정 창 생성
- 현재 minifb 창에 플래그 추가
- `{ "cmd": "qr_show" }` / `{ "cmd": "qr_hide" }` 명령으로 제어

---

## 추출 경로

```python
plugin_dir    = os.path.dirname(os.path.abspath(__file__))
sim_server_dir = os.path.join(plugin_dir, "..", "sim_server")
model_path    = os.path.join(sim_server_dir, "models", username)
```
