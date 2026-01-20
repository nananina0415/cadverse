use anyhow::Result;

/// CAD 데이터 로드
pub fn load_cad_data(file_path: &str) {
    println!("Loading CAD data from: {}", file_path);
}

/// CAD 데이터 파싱
pub fn parse_obj_file(file_path: &str) -> Result<()> {
    println!("Parsing OBJ file: {}", file_path);
    Ok(())
}
