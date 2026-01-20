use axum::{
    extract::Path,
    http::{StatusCode, header},
    response::{IntoResponse, Response},
    Json,
};
use crate::models::ObjectList;
use tracing::info;

/// GET /cadverse/object - 오브젝트 리스트 반환
pub async fn get_object_list() -> Json<ObjectList> {
    info!("Request: GET /cadverse/object");
    
    // TODO: 실제 시뮬레이션에서 오브젝트 리스트 가져오기
    let objects = ObjectList {
        objects: vec![
            "base".to_string(),
            "shaft".to_string(),
        ],
    };

    Json(objects)
}

/// GET /cadverse/object/:name - OBJ 메쉬 파일 반환
pub async fn get_object_mesh(Path(name): Path<String>) -> Response {
    info!("Request: GET /cadverse/object/{}", name);

    // .obj 확장자 제거
    let object_name = name.trim_end_matches(".obj");
    
    // TODO: 실제 OBJ 파일 로드
    // 임시로 빈 OBJ 데이터 반환
    let obj_data = format!(
        "# OBJ file for {}\n# Placeholder - to be implemented\n",
        object_name
    );

    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "model/obj")],
        obj_data,
    )
        .into_response()
}
