use axum::{
    extract::{Path, ConnectInfo},
    http::{StatusCode, header},
    response::{IntoResponse, Response},
    Json,
};
use crate::models::ObjectList;
use tracing::{info, error};
use std::net::SocketAddr;
use std::path::PathBuf;
use qrcode::{QrCode, EcLevel};
use local_ip_address::local_ip;

/// GET /cadverse/object - 오브젝트 리스트 반환
pub async fn get_object_list(
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
) -> Json<ObjectList> {
    info!("Request: GET /cadverse/object from client {}", addr);

    // model 폴더에서 .obj 파일 목록 읽기
    let model_dir = PathBuf::from("model");
    let mut objects = Vec::new();

    if let Ok(entries) = std::fs::read_dir(&model_dir) {
        for entry in entries.flatten() {
            if let Ok(file_type) = entry.file_type() {
                if file_type.is_file() {
                    if let Some(path) = entry.path().file_stem() {
                        if entry.path().extension().and_then(|s| s.to_str()) == Some("obj") {
                            objects.push(path.to_string_lossy().to_string());
                        }
                    }
                }
            }
        }
    } else {
        error!("Failed to read model directory");
    }

    Json(ObjectList { objects })
}

/// GET /cadverse/object/:name - OBJ 메쉬 파일 반환
pub async fn get_object_mesh(
    Path(name): Path<String>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
) -> Response {
    info!("Request: GET /cadverse/object/{} from client {}", name, addr);

    // .obj 확장자 제거
    let object_name = name.trim_end_matches(".obj");

    // model 폴더에서 OBJ 파일 읽기
    let file_path = PathBuf::from("model").join(format!("{}.obj", object_name));

    match std::fs::read_to_string(&file_path) {
        Ok(obj_data) => {
            info!("Loaded OBJ file: {} ({} bytes)", object_name, obj_data.len());
            (
                StatusCode::OK,
                [(header::CONTENT_TYPE, "model/obj")],
                obj_data,
            )
                .into_response()
        }
        Err(e) => {
            error!("Failed to load OBJ file '{}': {}", object_name, e);
            (
                StatusCode::NOT_FOUND,
                [(header::CONTENT_TYPE, "text/plain")],
                format!("Object '{}' not found", object_name),
            )
                .into_response()
        }
    }
}

/// GET /cadverse/qr - QR 코드 패턴을 0/1 텍스트로 반환
///
/// 응답 형식:
/// 첫 줄: 모듈 수 (예: "25")
/// 이후: 0과 1로 이루어진 행 (0=흰색, 1=검정)
///
/// 서버의 qr_display와 동일한 설정 (EcLevel::M, as_bytes)으로 생성
pub async fn get_qr_pattern(
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
) -> Response {
    info!("Request: GET /cadverse/qr from client {}", addr);

    let ip = match local_ip() {
        Ok(ip) => ip.to_string(),
        Err(e) => {
            error!("Failed to get local IP: {}", e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                [(header::CONTENT_TYPE, "text/plain")],
                "Failed to get local IP".to_string(),
            )
                .into_response();
        }
    };

    let server_info = format!("{}:{}", ip, 3000);
    info!("QR content: {}", server_info);

    let code = match QrCode::with_error_correction_level(server_info.as_bytes(), EcLevel::M) {
        Ok(c) => c,
        Err(e) => {
            error!("Failed to generate QR code: {}", e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                [(header::CONTENT_TYPE, "text/plain")],
                "Failed to generate QR code".to_string(),
            )
                .into_response();
        }
    };

    // QR 모듈을 0/1 문자열로 변환
    let modules = code.to_colors();
    let width = code.width();

    let mut output = String::new();
    // 첫 줄: 모듈 수
    output.push_str(&format!("{}\n", width));

    // 각 행을 0/1로 출력
    for row in modules.chunks(width) {
        for &module in row {
            if module == qrcode::Color::Dark {
                output.push('1');
            } else {
                output.push('0');
            }
        }
        output.push('\n');
    }

    info!("QR pattern: {}x{} modules", width, width);

    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/plain")],
        output,
    )
        .into_response()
}
