# cad_data_loader

CAD 폴더 선택, 씬 데이터 로드, 파일 변경 감시를 담당하는 크레이트.

## 모듈 구조

```
src/
├── lib.rs            # 모듈 선언 + 공개 API re-export
├── types.rs          # CadSceneData, ObjFileEntry, LoaderMessage
├── folder_picker.rs  # 네이티브 폴더 선택 다이얼로그 (rfd)
├── loader.rs         # 씬 로드 (scene.json 탐색 + OBJ 파일 읽기)
└── watcher.rs        # 파일 변경 감시 (notify + 500ms 디바운스)
```

## 공개 API

```rust
// 폴더 선택 다이얼로그 (메인 스레드에서 호출)
pub fn pick_cad_folder() -> Result<PathBuf>

// 씬 로드: scene.json 찾기 + OBJ 파일 읽기
pub fn load_scene(folder: &Path) -> Result<CadSceneData>

// 파일 감시 시작 (.obj/.json 변경 시 채널로 전송)
pub fn start_watcher(folder: &Path, tx: Sender<LoaderMessage>) -> Result<JoinHandle<()>>
```

## 타입

```rust
pub struct CadSceneData {
    pub scene_json_path: PathBuf,   // scene.json 경로
    pub scene_folder: PathBuf,      // CAD 폴더 경로
    pub obj_files: Vec<ObjFileEntry>,
}

pub struct ObjFileEntry {
    pub name: String,       // 파일명 (확장자 제외)
    pub path: PathBuf,      // 전체 경로
    pub contents: Vec<u8>,  // 파일 내용
}

pub enum LoaderMessage {
    SceneLoaded(CadSceneData),  // 씬 로드 성공
    Error(String),              // 에러
}
```

## 동작 흐름

```
pick_cad_folder()          사용자가 폴더 선택
    → load_scene()         scene.json 찾기 + OBJ 읽기
    → start_watcher()      notify로 파일 감시 시작

[파일 변경 감지]
    → 500ms 디바운스
    → .obj/.json 변경인지 필터링
    → load_scene() 재호출
    → LoaderMessage::SceneLoaded → tx.send()
    → SimOrchestrator가 수신하여 핫스왑
```

## 의존성

| 크레이트 | 용도 |
|----------|------|
| `rfd` | 네이티브 파일 다이얼로그 (Windows/macOS/Linux) |
| `notify` + `notify-debouncer-mini` | 파일 시스템 감시 + 디바운스 |
| `crossbeam-channel` | data_loader → sim_manager 채널 |
| `tracing` | 로깅 |

## 주의사항

- `pick_cad_folder()`는 tokio 런타임 전에 메인 스레드에서 호출해야 함 (rfd 제약)
- `start_watcher()`는 별도 OS 스레드에서 blocking 루프 실행
- 디바운스 500ms: CAD 소프트웨어가 여러 파일을 연속 기록할 때 중복 리로드 방지
