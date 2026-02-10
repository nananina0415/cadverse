//! sim_server 통합 테스트 - AR 클라이언트 데이터 흐름 검증
//!
//! mock_ar_client 크레이트의 TestServer를 사용하여
//! 실제 Unity AR 클라이언트가 서버와 주고받는 모든 데이터 흐름을 테스트합니다.
//!
//! ## 실행 방법
//! ```sh
//! cd sim_server
//! cargo test --test ar_client_integration
//! ```

use mock_ar_client::*;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{connect_async, tungstenite::Message};

/// InputBuffer에서 데이터를 읽어오는 헬퍼 (비동기 처리 대기 포함)
async fn drain_input_buffer(buf: &InputBuffer<TouchRaycastInput>) -> Vec<TouchRaycastInput> {
    // WebSocket handler의 push가 완료될 시간 확보
    tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    // write → swap → read 순서로 한 번만 flip
    buf.flip_write();
    buf.flip_read();
    buf.read_all()
}

// ================================================================
// 서버 → 클라 (HTTP): QR 패턴 다운로드
// ================================================================

#[tokio::test]
async fn test_http_get_qr_pattern() {
    let server = TestServer::spawn().await;

    let resp = reqwest::get(format!("{}/cadverse/qr", server.base_url()))
        .await
        .expect("QR 요청 실패");

    assert_eq!(resp.status(), 200);

    let body = resp.text().await.unwrap();
    let lines: Vec<&str> = body.lines().collect();

    // 첫 줄: 모듈 수 (정수)
    let module_count: usize = lines[0].parse().expect("첫 줄이 숫자가 아님");
    assert!(module_count > 0, "QR 모듈 수가 0");

    // 나머지 줄: 0과 1로만 구성
    for (i, line) in lines[1..].iter().enumerate() {
        if line.is_empty() { continue; }
        assert_eq!(line.len(), module_count, "{}번째 행 길이 불일치", i);
        assert!(
            line.chars().all(|c| c == '0' || c == '1'),
            "{}번째 행에 0/1 외 문자 포함",
            i
        );
    }
}

// ================================================================
// 서버 → 클라 (HTTP): 오브젝트 리스트 조회
// ================================================================

#[tokio::test]
async fn test_http_get_object_list() {
    let server = TestServer::spawn().await;

    let resp = reqwest::get(format!("{}/cadverse/object", server.base_url()))
        .await
        .expect("오브젝트 리스트 요청 실패");

    assert_eq!(resp.status(), 200);

    let list: ObjectList = resp.json().await.expect("JSON 파싱 실패");
    println!("오브젝트 리스트: {:?}", list.objects);
}

// ================================================================
// 서버 → 클라 (HTTP): OBJ 메쉬 다운로드 - 존재하지 않는 모델
// ================================================================

#[tokio::test]
async fn test_http_get_object_mesh_not_found() {
    let server = TestServer::spawn().await;

    let resp = reqwest::get(format!(
        "{}/cadverse/object/nonexistent_model",
        server.base_url()
    ))
    .await
    .expect("메쉬 요청 실패");

    assert_eq!(resp.status(), 404, "존재하지 않는 모델은 404여야 함");
}

// ================================================================
// 서버 → 클라 (HTTP): OBJ 메쉬 다운로드 - 실제 모델
// ================================================================

#[tokio::test]
async fn test_http_get_object_mesh_shaft() {
    // model/shaft.obj 존재 여부 확인
    if !std::path::Path::new("model/shaft.obj").exists() {
        println!("SKIP: model/shaft.obj 없음 (working dir 확인 필요)");
        return;
    }

    let server = TestServer::spawn().await;

    let resp = reqwest::get(format!(
        "{}/cadverse/object/shaft",
        server.base_url()
    ))
    .await
    .expect("shaft 메쉬 요청 실패");

    assert_eq!(resp.status(), 200);

    let body = resp.text().await.unwrap();
    assert!(body.contains("v "), "OBJ 파일에 vertex 데이터가 없음");
    assert!(body.contains("f "), "OBJ 파일에 face 데이터가 없음");
    println!("shaft.obj: {} bytes", body.len());
}

// ================================================================
// 서버 → 클라 (WebSocket): SimulationState 수신
// ================================================================

#[tokio::test]
async fn test_ws_receive_initial_sim_state() {
    let server = TestServer::spawn().await;

    let (mut ws, _) = connect_async(&server.ws_url())
        .await
        .expect("WebSocket 연결 실패");

    // 서버가 연결 직후 초기 SimulationState를 보냄
    let msg = tokio::time::timeout(
        std::time::Duration::from_secs(3),
        ws.next(),
    )
    .await
    .expect("초기 상태 수신 타임아웃")
    .expect("스트림 종료")
    .expect("메시지 수신 에러");

    if let Message::Text(text) = msg {
        let state: SimulationState =
            serde_json::from_str(&text).expect("SimulationState JSON 파싱 실패");

        assert!(state.timestamp >= 0.0, "timestamp가 음수");
        assert!(!state.objects.is_empty(), "초기 상태에 오브젝트가 없음");

        for obj in &state.objects {
            assert!(!obj.name.is_empty(), "오브젝트 이름이 비어있음");
            assert_eq!(obj.position.len(), 3, "position은 [x,y,z]여야 함");
            assert_eq!(obj.rotation.len(), 4, "rotation은 [x,y,z,w]여야 함");
        }

        println!("초기 SimState: timestamp={}, objects={:?}",
            state.timestamp,
            state.objects.iter().map(|o| &o.name).collect::<Vec<_>>()
        );
    } else {
        panic!("첫 메시지가 Text가 아님: {:?}", msg);
    }

    ws.close(None).await.ok();
}

// ================================================================
// 클라 → 서버 (WebSocket): TouchStart 전송
// ================================================================

#[tokio::test]
async fn test_ws_send_touch_start() {
    let server = TestServer::spawn().await;

    let (mut ws, _) = connect_async(&server.ws_url())
        .await
        .expect("WebSocket 연결 실패");

    // 초기 메시지 소비
    let _ = ws.next().await;

    let touch_start = serde_json::json!({
        "type": "TouchStart",
        "payload": {
            "targetPartIndex": 0,
            "actionPoint": { "x": 0.5, "y": 0.2, "z": -0.1 },
            "fingerPoint": { "x": 0.0, "y": 0.5, "z": -1.0 },
            "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
        }
    });

    ws.send(Message::Text(touch_start.to_string().into()))
        .await
        .expect("TouchStart 전송 실패");

    let inputs = drain_input_buffer(&server.input_buffer).await;

    assert_eq!(inputs.len(), 1, "TouchStart가 input_buffer에 들어가야 함");
    println!("TouchStart 수신 확인: {:?}", inputs[0]);
}

// ================================================================
// 클라 → 서버 (WebSocket): Touching (드래그) 전송
// ================================================================

#[tokio::test]
async fn test_ws_send_touching() {
    let server = TestServer::spawn().await;

    let (mut ws, _) = connect_async(&server.ws_url())
        .await
        .expect("WebSocket 연결 실패");

    let _ = ws.next().await;

    let touching = serde_json::json!({
        "type": "Touching",
        "payload": {
            "fingerPoint": { "x": 0.1, "y": 0.5, "z": -1.0 },
            "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
        }
    });

    ws.send(Message::Text(touching.to_string().into()))
        .await
        .expect("Touching 전송 실패");

    let inputs = drain_input_buffer(&server.input_buffer).await;

    assert_eq!(inputs.len(), 1, "Touching이 input_buffer에 들어가야 함");
    println!("Touching 수신 확인: {:?}", inputs[0]);
}

// ================================================================
// 클라 → 서버 (WebSocket): TouchEnd 전송
// ================================================================

#[tokio::test]
async fn test_ws_send_touch_end() {
    let server = TestServer::spawn().await;

    let (mut ws, _) = connect_async(&server.ws_url())
        .await
        .expect("WebSocket 연결 실패");

    let _ = ws.next().await;

    let touch_end = serde_json::json!({
        "type": "TouchEnd",
        "payload": {}
    });

    ws.send(Message::Text(touch_end.to_string().into()))
        .await
        .expect("TouchEnd 전송 실패");

    let inputs = drain_input_buffer(&server.input_buffer).await;

    assert_eq!(inputs.len(), 1, "TouchEnd가 input_buffer에 들어가야 함");
    println!("TouchEnd 수신 확인: {:?}", inputs[0]);
}

// ================================================================
// 클라 → 서버 (WebSocket): 연속 터치 시퀀스 (Start → Touching × N → End)
// ================================================================

#[tokio::test]
async fn test_ws_full_touch_sequence() {
    let server = TestServer::spawn().await;

    let (mut ws, _) = connect_async(&server.ws_url())
        .await
        .expect("WebSocket 연결 실패");

    let _ = ws.next().await;

    // 1. TouchStart
    let start = serde_json::json!({
        "type": "TouchStart",
        "payload": {
            "targetPartIndex": 1,
            "actionPoint": { "x": 0.5, "y": 0.2, "z": -0.1 },
            "fingerPoint": { "x": 0.0, "y": 0.5, "z": -1.0 },
            "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
        }
    });
    ws.send(Message::Text(start.to_string().into())).await.unwrap();

    // 2. Touching × 3
    for i in 0..3 {
        let drag = serde_json::json!({
            "type": "Touching",
            "payload": {
                "fingerPoint": { "x": 0.0 + (i as f64) * 0.1, "y": 0.5, "z": -1.0 },
                "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
            }
        });
        ws.send(Message::Text(drag.to_string().into())).await.unwrap();
    }

    // 3. TouchEnd
    let end = serde_json::json!({
        "type": "TouchEnd",
        "payload": {}
    });
    ws.send(Message::Text(end.to_string().into())).await.unwrap();

    let inputs = drain_input_buffer(&server.input_buffer).await;

    assert_eq!(inputs.len(), 5, "Start(1) + Touching(3) + End(1) = 5개여야 함");
    println!("전체 터치 시퀀스 {} 이벤트 수신 확인", inputs.len());
}

// ================================================================
// 클라 → 서버 (WebSocket): 잘못된 JSON 전송 시 연결 유지
// ================================================================

#[tokio::test]
async fn test_ws_send_invalid_json_keeps_connection() {
    let server = TestServer::spawn().await;

    let (mut ws, _) = connect_async(&server.ws_url())
        .await
        .expect("WebSocket 연결 실패");

    let _ = ws.next().await;

    // 잘못된 JSON 전송
    ws.send(Message::Text("not a json".into()))
        .await
        .expect("전송 실패");

    // Ping 보내서 연결 확인
    ws.send(Message::Ping(vec![1, 2, 3].into()))
        .await
        .expect("Ping 전송 실패");

    let pong = tokio::time::timeout(
        std::time::Duration::from_secs(2),
        ws.next(),
    )
    .await
    .expect("Pong 타임아웃")
    .expect("스트림 종료")
    .expect("Pong 수신 에러");

    assert!(matches!(pong, Message::Pong(_)), "Pong이 와야 함");
}
