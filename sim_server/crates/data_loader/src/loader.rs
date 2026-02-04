use std::path::{Path, PathBuf};
use anyhow::{Result, Context, bail};
use tracing::info;

use crate::types::{CadSceneData, ObjFileEntry};

/// 지정된 폴더에서 CAD 씬 데이터를 로드한다.
///
/// 폴더에 scene.json 또는 transforms.json이 있어야 하며,
/// *.obj 파일들을 함께 읽어온다.
pub fn load_scene(folder: &Path) -> Result<CadSceneData> {
    let scene_json_path = find_scene_json(folder)?;
    info!("씬 JSON 발견: {:?}", scene_json_path);

    let obj_files = load_obj_files(folder)?;
    info!("OBJ 파일 {}개 로드됨", obj_files.len());

    Ok(CadSceneData {
        scene_json_path,
        scene_folder: folder.to_path_buf(),
        obj_files,
    })
}

/// metadata.json 파일을 찾는다.
fn find_scene_json(folder: &Path) -> Result<PathBuf> {
    let p = folder.join("metadata.json");
    if p.exists() {
        return Ok(p);
    }
    bail!(
        "metadata.json을 찾을 수 없습니다: {:?}",
        folder
    )
}

/// 폴더 내 모든 .obj 파일을 읽어온다.
fn load_obj_files(folder: &Path) -> Result<Vec<ObjFileEntry>> {
    let mut entries = Vec::new();

    for entry in std::fs::read_dir(folder)
        .with_context(|| format!("폴더 읽기 실패: {:?}", folder))?
    {
        let entry = entry?;
        let path = entry.path();

        if path.extension().and_then(|s| s.to_str()) == Some("obj") {
            let name = path
                .file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .to_string();

            let contents = std::fs::read(&path)
                .with_context(|| format!("OBJ 파일 읽기 실패: {:?}", path))?;

            info!("OBJ 로드: {} ({} bytes)", name, contents.len());

            entries.push(ObjFileEntry {
                name,
                path,
                contents,
            });
        }
    }

    Ok(entries)
}
