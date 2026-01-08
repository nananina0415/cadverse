# CADverse Sim Server

PyChrono 기반의 CAD 시뮬레이션 서버 (Rust + PyO3)

## 프로젝트 구조

```
sim_server/
├── build.rs                    # 빌드 스크립트 (Python 환경 자동 번들링)
├── Cargo.toml                  # Rust 워크스페이스 설정
├── src/
│   └── main.rs                 # 메인 실행 파일
└── crates/                     # 라이브러리 크레이트들
    ├── server/                 # HTTP/WebSocket 서버 (axum)
    │   ├── Cargo.toml
    │   └── src/
    │       └── lib.rs
    ├── sim_manager/            # 시뮬레이션 관리자
    │   ├── Cargo.toml
    │   └── src/
    │       └── lib.rs
    ├── cad_data_loader/        # CAD 데이터 로더
    │   ├── Cargo.toml
    │   └── src/
    │       └── lib.rs
    └── simulator/              # Python 시뮬레이터 (PyChrono)
        ├── main.py
        └── SimInfo.py
```

## 빠른 시작

### 1. 환경 설정

```bash
# Python 환경 설치
.\setup_pychrono_env.ps1

# PyO3 환경 변수 설정
.\set_pyo3_env.ps1
```

### 2. 개발 빌드

```bash
cargo build
```

### 3. 릴리즈 빌드

```bash
cargo build --release
```

첫 릴리즈 빌드는 3-5분 소요 (Python 환경 번들링)
이후 빌드는 10-30초 소요 (캐시 사용)

## 빌드 시스템

### 자동 Python 번들링

이 프로젝트는 스마트 빌드 시스템을 사용합니다:

- **Debug 모드**: Python 번들링 하지 않음 (빠른 개발)
- **Release 모드**: 자동으로 conda-pack을 사용하여 Python 환경 번들링
- **캐싱**: 한 번 번들링되면 재사용 (속도 향상)

자세한 내용은 [BUILD_GUIDE.md](BUILD_GUIDE.md) 참조

### 번들링 위치

```
target/release/python_env.tar.gz
```

### 강제 재번들링

```bash
# Windows PowerShell
$env:FORCE_REBUNDLE = "1"
cargo build --release

# Linux/macOS
FORCE_REBUNDLE=1 cargo build --release
```

## 개발

### 빠른 빌드 (개발 중)

```bash
cargo build
cargo run
```

### 테스트

```bash
cargo test
```

### 클린 빌드

```bash
cargo clean
cargo build --release
```

## 배포

릴리즈 빌드 후 다음 파일들을 배포합니다:

```
release/
├── sim_server.exe              # Rust 바이너리
├── python_env.tar.gz           # Python 환경
├── crates/
│   └── simulator/              # Python 코드
└── resources/                  # 리소스 파일
```

## 아키텍처

### Rust ↔ Python 통신

- **PyO3**: Rust에서 Python 임베딩
- **PyChrono**: Python에서 물리 시뮬레이션
- **데이터 전달**: JSON 직렬화/역직렬화

### 워크스페이스 구조

| 크레이트 | 역할 |
|---------|------|
| `server` | WebSocket/HTTP 서버 (axum) |
| `sim_manager` | 시뮬레이션 라이프사이클 관리 |
| `cad_data_loader` | OBJ 파싱 및 SimDescription 생성 |

## 의존성

### Rust

- `tokio`: 비동기 런타임
- `axum`: 웹 서버 프레임워크
- `pyo3`: Python 인터프리터 연동
- `serde`: JSON 직렬화/역직렬화

### Python

- `pychrono==8.0.0`: 물리 시뮬레이션 엔진
- `numpy`: 수치 계산

## 문제 해결

### conda를 찾을 수 없음

Anaconda Prompt에서 실행하거나 PATH에 conda를 추가하세요.

### Python 환경이 없음

```bash
.\setup_pychrono_env.ps1
```

### PyO3 빌드 실패

PYO3_PYTHON 환경 변수를 확인하세요:

```powershell
echo $env:PYO3_PYTHON
```

자세한 내용은 [BUILD_GUIDE.md](BUILD_GUIDE.md) 참조

## 문서

- [빌드 가이드](../BUILD_GUIDE.md): 빌드 시스템 상세 설명
- [환경 설정 가이드](README_SETUP.md): 개발 환경 설정

## 라이선스

[프로젝트 라이선스 정보]
