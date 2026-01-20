use axum::{
    extract::{ws::{Message, WebSocket, WebSocketUpgrade}, State},
    response::Response,
};
use tracing::{info, warn, error};
use crate::models::{SimulationState, UserInput, ObjectTransform};
use crate::StateBuffer;

/// WebSocket 연결 핸들러
pub async fn websocket_handler(
    State(buffer): State<StateBuffer>,
    ws: WebSocketUpgrade,
) -> Response {
    ws.on_upgrade(move |socket| handle_socket(socket, buffer))
}

/// WebSocket 연결 처리
async fn handle_socket(mut socket: WebSocket, _buffer: StateBuffer) {
    info!("New WebSocket connection established");

    // TODO: buffer에서 실제 프레임 읽어서 전송
    // 현재는 Any 타입이라 downcast 필요
    // 임시로 더미 데이터 유지
    let initial_state = SimulationState {
        timestamp: 0.0,
        objects: vec![
            ObjectTransform {
                name: "base".to_string(),
                position: [0.0, 0.0, 0.0],
                rotation: [0.0, 0.0, 0.0, 1.0],
            },
            ObjectTransform {
                name: "shaft".to_string(),
                position: [0.0, 1.0, 0.0],
                rotation: [0.0, 0.0, 0.0, 1.0],
            },
        ],
    };

    if let Ok(json) = serde_json::to_string(&initial_state) {
        if let Err(e) = socket.send(Message::Text(json.into())).await {
            error!("Failed to send initial state: {}", e);
            return;
        }
    }

    // 메시지 수신 루프
    while let Some(msg) = socket.recv().await {
        match msg {
            Ok(Message::Text(text)) => {
                info!("Received text: {}", text);
                
                // 유저 입력 파싱
                match serde_json::from_str::<UserInput>(&text) {
                    Ok(input) => {
                        info!("User input: {:?}", input);
                        // TODO: 시뮬레이션에 입력 전달
                    }
                    Err(e) => {
                        warn!("Failed to parse user input: {}", e);
                    }
                }
            }
            Ok(Message::Close(_)) => {
                info!("WebSocket connection closed");
                break;
            }
            Ok(Message::Ping(data)) => {
                if let Err(e) = socket.send(Message::Pong(data)).await {
                    error!("Failed to send pong: {}", e);
                    break;
                }
            }
            Err(e) => {
                error!("WebSocket error: {}", e);
                break;
            }
            _ => {}
        }
    }

    info!("WebSocket connection closed");
}
