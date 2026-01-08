# CADverse 빌드 가이드

이 문서는 CADverse Sim Server의 빌드 및 배포 프로세스를 설명합니다.

## 📋 목차

1. [빌드 시스템 개요](#빌드-시스템-개요)
2. [개발 빌드](#개발-빌드)
3. [릴리즈 빌드](#릴리즈-빌드)
4. [Python 환경 번들링](#python-환경-번들링)
5. [문제 해결](#문제-해결)
6. [배포](#배포)

---

## 빌드 시스템 개요

CADverse는 **스마트 캐싱 빌드 시스템**을 사용합니다:

- **개발 빌드** (`cargo build`): 빠른 빌드, Python 번들링 없음
- **릴리즈 빌드** (`cargo build --release`): 자동 Python 환경 번들링 (첫 빌드만)
- **캐싱**: 한 번 번들링되면 재사용 (빌드 속도 대폭 향상)

### 빌드 스크립트 동작

`sim_server/build.rs` 파일이 다음을 자동으로 처리합니다:

1. **빌드 모드 감지**: Debug vs Release
2. **캐시 확인**: 이미 번들링된 Python 환경이 있는지 확인
3. **자동 번들링**: 릴리즈 빌드 시 conda-pack으로 Python 환경 패키징
4. **조건부 재빌드**: 필요할 때만 재번들링

---

## 개발 빌드

개발 중에는 빠른 빌드를 위해 Debug 모드를 사용합니다.

### 명령어

```bash
cd sim_server
cargo build
```

### 동작

- ✅ **빠른 컴파일** (~10-30초)
- ✅ Python 번들링 **하지 않음**
- ✅ 디버그 심볼 포함
- ⚠️ 최적화 없음 (느린 실행 속도)

### 실행

```bash
# PYO3_PYTHON 환경 변수 필요 (개발 환경)
$env:PYO3_PYTHON = "C:\Users\nananina\anaconda3\envs\cadverse_dev\python.exe"

# 실행
cargo run
```

### 언제 사용?

- ✅ 코드 수정 후 빠른 테스트
- ✅ 디버깅
- ✅ 로컬 개발

---

## 릴리즈 빌드

프로덕션 배포를 위한 최적화된 빌드입니다.

### 첫 릴리즈 빌드

```bash
cd sim_server
cargo build --release
```

**예상 시간**: 3-5분 (Python 환경 번들링 포함)

#### 진행 과정:

```
cargo:warning=Release mode detected
cargo:warning===========================================
cargo:warning=Bundling Python environment with conda-pack
cargo:warning=This may take 3-5 minutes (first time only)
cargo:warning===========================================
cargo:warning=Found conda: conda 24.x.x
cargo:warning=conda-pack is installed
cargo:warning=Running: conda pack -n cadverse_dev -o "target/release/python_env.tar.gz"
...
cargo:warning===========================================
cargo:warning=Python environment bundled successfully!
cargo:warning=Location: "target/release/python_env.tar.gz"
cargo:warning===========================================
```

### 두 번째 이후 릴리즈 빌드

```bash
cargo build --release
```

**예상 시간**: 10-30초 (캐시 사용)

#### 진행 과정:

```
cargo:warning=Release mode detected
cargo:warning=Python environment already bundled at "target/release/python_env.tar.gz"
cargo:warning=Using cached bundle (set FORCE_REBUNDLE=1 to rebuild)
```

### 동작

- ✅ **최적화된 바이너리** (크기 작고 빠름)
- ✅ **Python 환경 자동 번들링** (첫 빌드만)
- ✅ **캐싱**: 이미 번들링된 경우 재사용
- ✅ 디버그 심볼 제거

### 언제 사용?

- ✅ 배포 전 최종 빌드
- ✅ 성능 테스트
- ✅ 릴리즈 패키징

---

## Python 환경 번들링

### 자동 번들링

릴리즈 빌드 시 자동으로 수행됩니다:

```bash
cargo build --release
```

### 수동 번들링 (고급)

필요한 경우 conda-pack을 직접 실행할 수 있습니다:

```bash
conda activate cadverse_dev
conda pack -n cadverse_dev -o target/release/python_env.tar.gz
```

### 강제 재번들링

Python 환경이 변경되었을 때 강제로 재번들링:

```bash
# Windows PowerShell
$env:FORCE_REBUNDLE = "1"
cargo build --release

# Windows CMD
set FORCE_REBUNDLE=1
cargo build --release

# Linux/macOS
FORCE_REBUNDLE=1 cargo build --release
```

### 번들 삭제 및 재생성

```bash
# 번들 삭제
rm target/release/python_env.tar.gz

# 또는 전체 클린
cargo clean

# 재빌드 (새로 번들링됨)
cargo build --release
```

---

## 빌드 캐싱 시스템

### 재번들링 조건

다음 경우에만 Python 환경을 재번들링합니다:

1. ✅ `environment.yml` 파일이 변경됨
2. ✅ `FORCE_REBUNDLE=1` 환경 변수 설정됨
3. ✅ `target/release/python_env.tar.gz`가 삭제됨
4. ✅ `cargo clean` 실행 후

### 재번들링하지 않는 경우

- ❌ Python 코드 변경 (`.py` 파일)
- ❌ Rust 코드 변경 (`.rs` 파일)
- ❌ 리소스 파일 변경 (`.obj`, `.json`)
- ❌ 두 번째 이후 릴리즈 빌드

### 캐싱 동작 예시

```bash
# 첫 릴리즈 빌드
cargo build --release  # 3-5분 (번들링 수행)

# Rust 코드 수정 후
cargo build --release  # 10-30초 (캐시 사용)

# Python 코드 수정 후
cargo build --release  # 10-30초 (캐시 사용, Python 코드는 별도 복사)

# environment.yml 수정 후
cargo build --release  # 3-5분 (재번들링 수행)
```

---

## 문제 해결

### conda를 찾을 수 없음

**증상:**
```
ERROR: conda is not available in PATH
```

**해결:**
1. Anaconda Prompt 사용
2. 또는 conda를 PATH에 추가:
   ```powershell
   $env:PATH += ";C:\Users\nananina\anaconda3\Scripts"
   $env:PATH += ";C:\Users\nananina\anaconda3\condabin"
   ```

### conda-pack 설치 실패

**증상:**
```
ERROR: Failed to install conda-pack
```

**해결:**
```bash
conda activate base
conda install conda-pack -y
```

### Python 환경이 없음

**증상:**
```
PackagesNotFoundError: The following packages are not available from current channels:
  - cadverse_dev
```

**해결:**
먼저 Python 환경을 설정하세요:
```bash
.\setup_pychrono_env.ps1
```

### 빌드 스크립트 오류

**증상:**
빌드 중 `build.rs`에서 패닉 발생

**해결:**
1. conda 환경 확인:
   ```bash
   conda env list
   conda activate cadverse_dev
   ```

2. 빌드 캐시 클린:
   ```bash
   cargo clean
   ```

3. 재빌드:
   ```bash
   cargo build --release
   ```

### 강제 재번들링

모든 것을 처음부터 다시 시작하려면:

```bash
# 1. 빌드 결과물 삭제
cargo clean

# 2. Python 환경 재생성 (선택사항)
conda env remove -n cadverse_dev -y
.\setup_pychrono_env.ps1

# 3. 재빌드
cargo build --release
```

---

## 배포

### 배포 파일 구조

릴리즈 빌드 후 다음 파일들을 배포합니다:

```
cadverse_release/
├── sim_server.exe                      # Rust 바이너리
├── python_env.tar.gz                   # Python 환경 번들
├── simulator/                          # Python 시뮬레이터 코드
│   ├── __init__.py
│   ├── rust_interface.py
│   └── sim_logic.py
└── resources/                          # 리소스 파일
    ├── server_config.json
    ├── sim_contents.json
    ├── base.obj
    └── shaft.obj
```

### 배포 스크립트 (추후 작성 예정)

```powershell
# build_release.ps1
# 1. 릴리즈 빌드
cargo build --release

# 2. 배포 디렉토리 생성
New-Item -ItemType Directory -Force -Path release

# 3. 바이너리 복사
Copy-Item target/release/sim_server.exe release/

# 4. Python 환경 복사
Copy-Item target/release/python_env.tar.gz release/

# 5. Python 코드 복사
Copy-Item -Recurse simulator release/

# 6. 리소스 복사
Copy-Item -Recurse ../prototype/sim_server/resources release/

# 7. 압축
Compress-Archive -Path release/* -DestinationPath cadverse_release.zip -Force
```

---

## 빌드 시간 비교

| 빌드 타입 | Python 번들링 | 예상 시간 | 용도 |
|----------|--------------|----------|------|
| **Debug (첫 빌드)** | ❌ | 30초-1분 | 초기 설정 |
| **Debug (재빌드)** | ❌ | 5-10초 | 개발 중 |
| **Release (첫 빌드)** | ✅ | 3-5분 | 첫 릴리즈 |
| **Release (캐시)** | ❌ | 10-30초 | 이후 릴리즈 |
| **Release (강제)** | ✅ | 3-5분 | 환경 변경 시 |

---

## 환경 변수 요약

### 필수 환경 변수

| 변수 | 값 | 용도 | 설정 시점 |
|------|-----|------|----------|
| `PYO3_PYTHON` | `C:\Users\...\python.exe` | PyO3가 사용할 Python | 개발 전 |

### 선택적 환경 변수

| 변수 | 값 | 용도 | 설정 시점 |
|------|-----|------|----------|
| `FORCE_REBUNDLE` | `1` | 강제 재번들링 | 필요 시만 |
| `PROFILE` | `release`/`debug` | 빌드 모드 | Cargo 자동 설정 |

---

## 권장 워크플로우

### 일반 개발

```bash
# 1. 환경 활성화
conda activate cadverse_dev

# 2. 개발 빌드 및 실행
cargo run

# 3. 코드 수정 후 빠른 재빌드
cargo build
```

### 릴리즈 전

```bash
# 1. 릴리즈 빌드 (첫 실행)
cargo build --release

# 2. 테스트
./target/release/sim_server

# 3. 문제 발견 시 수정 후 재빌드 (빠름)
cargo build --release

# 4. 배포 파일 생성
# (배포 스크립트 실행)
```

### Python 환경 변경 후

```bash
# 1. environment.yml 수정
# 2. conda 환경 재생성
conda env remove -n cadverse_dev -y
.\setup_pychrono_env.ps1

# 3. 강제 재번들링
$env:FORCE_REBUNDLE = "1"
cargo build --release
```

---

## 추가 정보

- **개발 환경 설정**: [README_SETUP.md](README_SETUP.md)
- **프로젝트 구조**: [README.md](README.md)
- **PyO3 문서**: https://pyo3.rs/
- **conda-pack 문서**: https://conda.github.io/conda-pack/

---

## 요약

✅ **개발 중**: `cargo build` (빠름)
✅ **릴리즈**: `cargo build --release` (첫 빌드만 느림, 이후 빠름)
✅ **재번들링**: `FORCE_REBUNDLE=1 cargo build --release`
✅ **클린 빌드**: `cargo clean && cargo build --release`

**스마트 캐싱 덕분에 개발 경험과 배포 자동화를 모두 확보했습니다!** 🎉
