use std::path::PathBuf;

/// CAD 내보내기 폴더에서 로드된 전체 씬 데이터.
/// data_loader → sim_manager 채널로 전송되는 페이로드.
#[derive(Debug, Clone)]
pub struct CadSceneData {
    /// 씬 JSON 파일 경로 (scene.json 또는 transforms.json)
    pub scene_json_path: PathBuf,

    /// CAD 내보내기 폴더 경로
    pub scene_folder: PathBuf,

    /// 폴더 내 OBJ 파일 목록
    pub obj_files: Vec<ObjFileEntry>,
}

/// 단일 OBJ 파일 정보
#[derive(Debug, Clone)]
pub struct ObjFileEntry {
    /// 파일 이름 (확장자 제외, e.g. "base")
    pub name: String,

    /// 절대 경로
    pub path: PathBuf,

    /// 파일 내용 (HTTP 서빙용)
    pub contents: Vec<u8>,
}

/// data_loader → sim_manager 채널 메시지
pub enum LoaderMessage {
    /// 씬 로드 완료 (초기 또는 리로드)
    SceneLoaded(CadSceneData),

    /// 로더 에러
    Error(String),
}
