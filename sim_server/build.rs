// ========================================
// CADverse Sim Server Build Script
// ========================================
//
// 이 스크립트는 릴리즈 빌드 시 자동으로 Python 환경을 번들링합니다.
//
// 동작:
// - Debug 모드: 번들링 하지 않음 (빠른 개발)
// - Release 모드: 첫 빌드 시에만 conda-pack으로 Python 환경 번들링
// - 캐싱: 이미 번들링된 경우 재사용 (빌드 속도 향상)
//
// 환경 변수:
// - FORCE_REBUNDLE=1: 강제로 Python 환경 재번들링

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    // 디버그 모드면 번들링 스킵
    let profile = env::var("PROFILE").unwrap_or_else(|_| String::from("debug"));
    if profile != "release" {
        println!("cargo:warning=Debug mode - skipping Python bundling");
        return;
    }

    println!("cargo:warning=Release mode detected");

    let bundle_path = get_bundle_path();

    // 이미 번들이 있고, 강제 재생성 플래그가 없으면 스킵
    let force_rebundle = env::var("FORCE_REBUNDLE").is_ok();

    if bundle_path.exists() && !force_rebundle {
        println!("cargo:warning=Python environment already bundled at {:?}", bundle_path);
        println!("cargo:warning=Using cached bundle (set FORCE_REBUNDLE=1 to rebuild)");
        return;
    }

    if force_rebundle {
        println!("cargo:warning=FORCE_REBUNDLE detected - rebuilding Python bundle");
        // 기존 번들 삭제
        if bundle_path.exists() {
            fs::remove_file(&bundle_path).ok();
        }
    }

    // Python 환경 번들링 수행
    bundle_python_environment(&bundle_path);

    // 재실행 조건 설정
    println!("cargo:rerun-if-changed=../environment.yml");
    println!("cargo:rerun-if-env-changed=FORCE_REBUNDLE");
}

/// Python 환경 번들 파일 경로 반환
fn get_bundle_path() -> PathBuf {
    let manifest_dir = env::var("CARGO_MANIFEST_DIR")
        .expect("CARGO_MANIFEST_DIR not set");

    Path::new(&manifest_dir)
        .join("../target/release/python_env.tar.gz")
        .to_path_buf()
}

/// conda-pack을 사용하여 Python 환경 번들링
fn bundle_python_environment(output_path: &Path) {
    println!("cargo:warning===========================================");
    println!("cargo:warning=Bundling Python environment with conda-pack");
    println!("cargo:warning=This may take 3-5 minutes (first time only)");
    println!("cargo:warning===========================================");

    // 출력 디렉토리 생성
    if let Some(parent) = output_path.parent() {
        fs::create_dir_all(parent)
            .unwrap_or_else(|e| panic!("Failed to create output directory: {}", e));
    }

    // conda 명령어 확인
    check_conda_available();

    // conda-pack 설치 확인
    check_conda_pack_installed();

    // conda-pack 실행
    println!("cargo:warning=Running: conda pack -n cadverse_dev -o {:?}", output_path);

    let status = Command::new("conda")
        .args(&[
            "pack",
            "-n", "cadverse_dev",
            "-o", output_path.to_str().unwrap(),
            "--ignore-missing-files",
        ])
        .status()
        .unwrap_or_else(|e| panic!("Failed to execute conda pack: {}", e));

    if !status.success() {
        panic!("conda pack failed with exit code: {:?}", status.code());
    }

    println!("cargo:warning===========================================");
    println!("cargo:warning=Python environment bundled successfully!");
    println!("cargo:warning=Location: {:?}", output_path);
    println!("cargo:warning===========================================");
}

/// conda 명령어가 사용 가능한지 확인
fn check_conda_available() {
    let result = Command::new("conda")
        .arg("--version")
        .output();

    match result {
        Ok(output) if output.status.success() => {
            let version = String::from_utf8_lossy(&output.stdout);
            println!("cargo:warning=Found conda: {}", version.trim());
        }
        _ => {
            panic!(
                "\n\n\
                ==========================================\n\
                ERROR: conda is not available in PATH\n\
                ==========================================\n\
                \n\
                Please ensure:\n\
                1. Anaconda or Miniconda is installed\n\
                2. conda is in your PATH\n\
                3. You have activated the conda base environment\n\
                \n\
                On Windows, try running from 'Anaconda Prompt'\n\
                ==========================================\n\
                "
            );
        }
    }
}

/// conda-pack이 설치되어 있는지 확인
fn check_conda_pack_installed() {
    let result = Command::new("conda")
        .args(&["list", "conda-pack"])
        .output();

    match result {
        Ok(output) if output.status.success() => {
            let output_str = String::from_utf8_lossy(&output.stdout);
            if !output_str.contains("conda-pack") {
                println!("cargo:warning=conda-pack not found, attempting to install...");
                install_conda_pack();
            } else {
                println!("cargo:warning=conda-pack is installed");
            }
        }
        _ => {
            println!("cargo:warning=Could not check conda-pack, attempting to install...");
            install_conda_pack();
        }
    }
}

/// conda-pack 자동 설치
fn install_conda_pack() {
    println!("cargo:warning=Installing conda-pack...");

    let status = Command::new("conda")
        .args(&["install", "-y", "conda-pack"])
        .status()
        .expect("Failed to install conda-pack");

    if !status.success() {
        panic!(
            "\n\n\
            ==========================================\n\
            ERROR: Failed to install conda-pack\n\
            ==========================================\n\
            \n\
            Please manually install conda-pack:\n\
            \n\
            conda install conda-pack -y\n\
            \n\
            Then run the build again.\n\
            ==========================================\n\
            "
        );
    }

    println!("cargo:warning=conda-pack installed successfully");
}
