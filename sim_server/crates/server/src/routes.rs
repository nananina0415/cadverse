use axum::{
    extract::Path,
    http::{StatusCode, header},
    response::{IntoResponse, Response},
    Json,
};
use crate::models::ObjectList;
use tracing::{info, error};
use std::path::PathBuf;

/// GET /cadverse/object - 오브젝트 리스트 반환
pub async fn get_object_list() -> Json<ObjectList> {
    info!("Request: GET /cadverse/object");

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
pub async fn get_object_mesh(Path(name): Path<String>) -> Response {
    info!("Request: GET /cadverse/object/{}", name);

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
