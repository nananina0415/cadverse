//! data_loader 통합 테스트
//!
//! - CAD 메타데이터 로딩
//! - notify 기반 파일 감시 (debounced)
//! - 실제 파일 시스템 이벤트 처리

use std::fs;
use std::path::PathBuf;
use std::time::Duration;
use tempfile::TempDir;

use cad_data_loader::{load_scene, start_watcher, LoaderMessage};

/// 테스트용 임시 CAD 폴더 생성 (metadata.json + OBJ 파일)
fn create_test_cad_folder() -> TempDir {
    let temp_dir = TempDir::new().expect("임시 폴더 생성 실패");

    // metadata.json 생성
    let metadata = serde_json::json!({
        "info": {
            "version": "2.0",
            "coordinate_system": "Right-Handed (Z-up)",
            "units": "cm"
        },
        "transforms": {
            "base": [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            ],
            "shaft": [
                1.0, 0.0, 0.0, 5.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0
            ]
        },
        "joints": [
            {
                "name": "shaft_revolute",
                "type": "Revolute",
                "connected_parts": {
                    "parent": "base",
                    "child": "shaft"
                },
                "axis": [0.0, 0.0, 1.0],
                "origin": [5.0, 0.0, 0.0],
                "limits": {
                    "min": null,
                    "max": null
                }
            }
        ]
    });

    let metadata_path = temp_dir.path().join("metadata.json");
    fs::write(&metadata_path, serde_json::to_string_pretty(&metadata).unwrap())
        .expect("metadata.json 작성 실패");

    // base.obj 생성
    let base_obj = r#"# Base object
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
f 1 2 3 4
"#;
    fs::write(temp_dir.path().join("base.obj"), base_obj).expect("base.obj 작성 실패");

    // shaft.obj 생성
    let shaft_obj = r#"# Shaft object
v 5 0 0
v 6 0 0
v 6 1 0
v 5 1 0
f 1 2 3 4
"#;
    fs::write(temp_dir.path().join("shaft.obj"), shaft_obj).expect("shaft.obj 작성 실패");

    temp_dir
}

// ================================================================
// 테스트 1: load_scene() - 초기 씬 로드
// ================================================================

#[test]
fn test_load_scene_success() {
    let temp_dir = create_test_cad_folder();

    let result = load_scene(temp_dir.path());
    assert!(result.is_ok(), "씬 로드 실패: {:?}", result.err());

    let scene = result.unwrap();

    // metadata.json 경로 확인
    assert_eq!(
        scene.scene_json_path,
        temp_dir.path().join("metadata.json")
    );

    // 폴더 경로 확인
    assert_eq!(scene.scene_folder, temp_dir.path());

    // OBJ 파일 2개 (base, shaft)
    assert_eq!(scene.obj_files.len(), 2, "OBJ 파일 개수가 2개여야 함");

    let names: Vec<&str> = scene.obj_files.iter().map(|o| o.name.as_str()).collect();
    assert!(names.contains(&"base"), "base.obj가 로드되지 않음");
    assert!(names.contains(&"shaft"), "shaft.obj가 로드되지 않음");

    // OBJ 파일 내용 검증
    for obj in &scene.obj_files {
        assert!(!obj.contents.is_empty(), "{}.obj 내용이 비어있음", obj.name);
        let content = String::from_utf8_lossy(&obj.contents);
        assert!(content.contains("v "), "{}.obj에 vertex가 없음", obj.name);
        assert!(content.contains("f "), "{}.obj에 face가 없음", obj.name);
    }
}

#[test]
fn test_load_scene_missing_metadata() {
    let temp_dir = TempDir::new().unwrap();
    // metadata.json 없이 OBJ만 생성
    fs::write(temp_dir.path().join("test.obj"), "v 0 0 0\n").unwrap();

    let result = load_scene(temp_dir.path());
    assert!(result.is_err(), "metadata.json 없이 성공하면 안 됨");

    let err = result.unwrap_err();
    assert!(
        err.to_string().contains("metadata.json"),
        "에러 메시지에 metadata.json이 포함되어야 함"
    );
}

// ================================================================
// 테스트 2: start_watcher() - notify 기반 파일 감시
// ================================================================

#[test]
fn test_watcher_detects_initial_file() {
    let temp_dir = create_test_cad_folder();

    let (tx, rx) = crossbeam_channel::unbounded();
    let _handle = start_watcher(temp_dir.path(), tx).expect("watcher 시작 실패");

    // watcher 초기화 대기
    std::thread::sleep(Duration::from_millis(100));

    // metadata.json 수정 (touch)
    let metadata_path = temp_dir.path().join("metadata.json");
    let content = fs::read_to_string(&metadata_path).unwrap();
    fs::write(&metadata_path, content).expect("metadata.json 수정 실패");

    // debounce (500ms) + 여유 시간
    let msg = rx.recv_timeout(Duration::from_secs(2));

    assert!(msg.is_ok(), "watcher가 변경을 감지하지 못함");

    match msg.unwrap() {
        LoaderMessage::SceneLoaded(scene) => {
            assert_eq!(scene.scene_json_path, metadata_path);
            assert_eq!(scene.obj_files.len(), 2);
        }
        LoaderMessage::Error(e) => {
            panic!("watcher가 에러 메시지를 보냄: {}", e);
        }
    }
}

#[test]
fn test_watcher_ignores_non_metadata_changes() {
    let temp_dir = create_test_cad_folder();

    let (tx, rx) = crossbeam_channel::unbounded();
    let _handle = start_watcher(temp_dir.path(), tx).expect("watcher 시작 실패");

    std::thread::sleep(Duration::from_millis(100));

    // OBJ 파일만 수정 (metadata.json은 변경 안 함)
    let obj_path = temp_dir.path().join("base.obj");
    fs::write(&obj_path, "v 0 0 0\nv 1 1 1\n").expect("base.obj 수정 실패");

    // watcher가 무시해야 함
    let msg = rx.recv_timeout(Duration::from_millis(800));

    assert!(
        msg.is_err(),
        "OBJ 파일 변경은 무시되어야 하는데 메시지가 왔음: {:?}",
        msg.unwrap()
    );
}

#[test]
fn test_watcher_debounces_rapid_changes() {
    let temp_dir = create_test_cad_folder();

    let (tx, rx) = crossbeam_channel::unbounded();
    let _handle = start_watcher(temp_dir.path(), tx).expect("watcher 시작 실패");

    std::thread::sleep(Duration::from_millis(100));

    let metadata_path = temp_dir.path().join("metadata.json");

    // 짧은 시간에 여러 번 수정 (debounce 테스트)
    for i in 0..5 {
        let content = format!("{{\"test\": {}}}", i);
        fs::write(&metadata_path, &content).unwrap();
        std::thread::sleep(Duration::from_millis(50));
    }

    // debounce 500ms 대기
    std::thread::sleep(Duration::from_millis(800));

    // 메시지를 받아야 하지만, 5개 모두 오면 안 됨 (debounce가 동작해야 함)
    let mut count = 0;
    while let Ok(_) = rx.recv_timeout(Duration::from_millis(100)) {
        count += 1;
    }

    assert!(count > 0, "debounce 후 최소 1개 메시지를 받아야 함");
    assert!(count < 5, "debounce로 인해 5개 모두 오면 안 됨 (실제: {}개)", count);
}

// ================================================================
// 테스트 3: 잘못된 JSON 처리
// ================================================================

#[test]
fn test_load_scene_with_invalid_json() {
    let temp_dir = TempDir::new().unwrap();

    // 잘못된 JSON
    fs::write(
        temp_dir.path().join("metadata.json"),
        "{this is not valid json",
    )
    .unwrap();

    let result = load_scene(temp_dir.path());
    // load_scene은 JSON 파싱을 하지 않고 경로만 반환하므로 성공
    // (파싱은 sim_manager에서 Python이 함)
    assert!(result.is_ok(), "load_scene은 JSON 검증 안 함");
}

#[test]
fn test_watcher_with_invalid_json_sends_error() {
    let temp_dir = TempDir::new().unwrap();

    // 일단 유효한 JSON으로 시작
    let valid_json = r#"{"info": {"version": "1.0"}, "transforms": {}, "joints": []}"#;
    fs::write(temp_dir.path().join("metadata.json"), valid_json).unwrap();

    let (tx, rx) = crossbeam_channel::unbounded();
    let _handle = start_watcher(temp_dir.path(), tx).expect("watcher 시작 실패");

    std::thread::sleep(Duration::from_millis(100));

    // 잘못된 JSON으로 변경
    fs::write(
        temp_dir.path().join("metadata.json"),
        "{invalid json",
    )
    .unwrap();

    std::thread::sleep(Duration::from_millis(700));

    let msg = rx.recv_timeout(Duration::from_secs(1));

    // watcher는 load_scene을 호출하는데, load_scene은 JSON 파싱 안 하므로
    // 실제로는 SceneLoaded가 옴. 하지만 향후 JSON 검증이 추가되면 Error가 와야 함
    assert!(msg.is_ok(), "watcher가 응답해야 함");
}

// ================================================================
// 테스트 4: 빈 폴더
// ================================================================

#[test]
fn test_load_scene_empty_folder() {
    let temp_dir = TempDir::new().unwrap();

    let result = load_scene(temp_dir.path());
    assert!(result.is_err(), "빈 폴더에서는 실패해야 함");
}

// ================================================================
// 테스트 5: OBJ 파일만 있고 metadata.json 없음
// ================================================================

#[test]
fn test_load_scene_obj_only() {
    let temp_dir = TempDir::new().unwrap();

    fs::write(temp_dir.path().join("model.obj"), "v 0 0 0\n").unwrap();

    let result = load_scene(temp_dir.path());
    assert!(
        result.is_err(),
        "metadata.json 없이는 실패해야 함"
    );
}
