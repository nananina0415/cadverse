use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=pychrono/environment.yml");
    println!("cargo:rerun-if-changed=pychrono/simulator/");

    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let env_yml = Path::new(&manifest_dir).join("pychrono/environment.yml");
    let profile = env::var("PROFILE").unwrap_or_default();

    update_conda_env(&env_yml);

    if profile == "release" {
        let bundle_out = Path::new(&manifest_dir).join("target/release/python_env.tar.gz");
        pack_conda_env(&bundle_out);
    }
}

/// conda 환경 업데이트
/// shell이 환경을 생성한 뒤 cargo가 실행되므로, 이 시점엔 환경이 반드시 존재함
/// environment.yml 변경 시 cargo:rerun-if-changed에 의해 자동 재실행됨
fn update_conda_env(env_yml: &Path) {
    println!("cargo:warning=Updating conda environment...");
    let conda = env::var("CONDA_PATH").unwrap_or_else(|_| "conda".to_string());
    let env_path = env::var("CONDA_ENV_PATH").expect("CONDA_ENV_PATH not set in .cargo/config.toml");
    let status = Command::new(&conda)
        .args(["env", "update", "-p", &env_path, "--file", env_yml.to_str().unwrap(), "--prune", "--solver=libmamba"])
        .status()
        .expect("conda not found. Set CONDA_PATH in .cargo/config.toml");
    assert!(status.success(), "conda env update failed");
}

/// conda-pack으로 Python 환경 번들링
fn pack_conda_env(bundle_out: &PathBuf) {
    println!("cargo:warning=Bundling Python environment with conda-pack...");
    std::fs::create_dir_all(bundle_out.parent().unwrap()).unwrap();
    if bundle_out.exists() {
        std::fs::remove_file(bundle_out).expect("python_env.tar.gz 삭제 실패");
    }
    let conda = env::var("CONDA_PATH").unwrap_or_else(|_| "conda".to_string());
    let env_path = env::var("CONDA_ENV_PATH").expect("CONDA_ENV_PATH not set in .cargo/config.toml");
    let status = Command::new(&conda)
        .args([
            "run", "-p", &env_path,
            "conda-pack", "-p", &env_path,
            "-o", bundle_out.to_str().unwrap(),
            "--ignore-missing-files",
        ])
        .status()
        .expect("conda-pack failed");
    assert!(status.success(), "conda-pack failed");
    println!("cargo:warning=Python bundle created at {:?}", bundle_out);
}
