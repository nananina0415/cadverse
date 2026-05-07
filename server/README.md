# CADverse Server

AR 클라이언트와 P2P로 통신하는 시뮬레이션 서버. Rust로 작성되었으며, Python(PyChrono) 시뮬레이터를 내장한다.

## 폴더 구조

```
server/
├── src/
│   ├── main.rs        # 진입점, HTTP 라우팅, QR 생성
│   ├── net.rs         # P2P 네트워크, 피어 관리
│   ├── sim.rs         # Python 시뮬레이터 FFI 인터페이스
│   ├── utils.rs       # 공용 유틸리티
│   └── watchdog.rs    # 프로세스 감시
├── pychrono/
│   ├── simulator/     # PyChrono 시뮬레이터 Python 패키지
│   ├── environment.yml  # conda 환경 정의
│   └── pyproject.toml
├── build.rs           # 빌드 스크립트 (conda env 업데이트, conda-pack 번들링)
├── Cargo.toml
├── setup-dev-env.ps1  # 최초 개발 환경 셋업 (1회만 실행)
└── build-server.ps1   # 서버 빌드
```

## 처음 시작하는 경우

conda와 cadverse 환경을 설치한다.

```powershell
.\setup-dev-env.ps1
```

- conda가 없으면 Miniconda를 자동으로 설치한다.
- `CONDA_BASE` 사용자 환경변수를 등록한다.
- `cadverse` conda 환경을 `pychrono/environment.yml`로 생성한다.
- **최초 1회만 실행하면 된다.**

## 빌드

```powershell
# 디버그 빌드
.\build-server.ps1

# 릴리즈 빌드
.\build-server.ps1 -r
```

빌드 시 `build.rs`가 자동으로 conda 환경 업데이트 및 conda-pack 번들링을 처리한다.  
빌드 결과물은 `target/debug/` 또는 `target/release/`에 생성된다.

## 실행

빌드 후 루트의 `run-server.ps1`을 사용하거나 직접 실행한다.

```powershell
.\target\release\cadverse_server.exe
```
