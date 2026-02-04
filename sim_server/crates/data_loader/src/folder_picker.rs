use std::path::PathBuf;
use anyhow::{Result, bail};

/// 네이티브 폴더 선택 다이얼로그를 열고 선택된 경로를 반환한다.
///
/// **주의**: main 스레드에서, tokio 런타임 진입 전에 호출해야 한다.
/// 일부 OS(macOS 등)에서 네이티브 다이얼로그는 main 스레드를 요구한다.
pub fn pick_cad_folder() -> Result<PathBuf> {
    let folder = rfd::FileDialog::new()
        .set_title("CAD 내보내기 폴더 선택")
        .pick_folder();

    match folder {
        Some(path) => {
            tracing::info!("폴더 선택됨: {:?}", path);
            Ok(path)
        }
        None => bail!("폴더가 선택되지 않았습니다. 종료합니다."),
    }
}
