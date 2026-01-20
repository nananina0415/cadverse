# CADverse Development Environment Setup

이 가이드는 PyChrono와 Rust (PyO3)를 사용한 CADverse 개발 환경을 설정하는 방법을 설명합니다.

## 사전 요구사항

1. **Anaconda 또는 Miniconda**
   - 다운로드: https://www.anaconda.com/download
   - Python 패키지 관리를 위해 필요

2. **Rust 툴체인**
   - 다운로드: https://rustup.rs/
   - Cargo 빌드 시스템 포함

3. **Visual Studio Build Tools** (Windows)
   - PyO3 빌드를 위해 필요
   - https://visualstudio.microsoft.com/downloads/

## 자동 설치 (권장)

### Windows (CMD)
```cmd
setup_pychrono_env.bat
```

### Windows (PowerShell)
```powershell
.\setup_pychrono_env.ps1
```

스크립트는 다음을 수행합니다:
1. Conda 설치 확인
2. `cadverse_dev` 환경 생성 (Python 3.12)
3. PyChrono 설치 (conda-forge 채널)
4. 설치 검증

## 수동 설치

### 1. Conda 환경 생성

```bash
# Python 3.10으로 새 환경 생성 (PyChrono 8.0.0 호환)
conda create -n cadverse_dev python=3.10 -y

# 환경 활성화
conda activate cadverse_dev
```

### 2. PyChrono 설치

**PyChrono 8.0.0 (프로젝트 사용 버전):**
```bash
conda install projectchrono::pychrono=8.0.0 -c conda-forge -y
```

**최신 개발 버전 (9.x):**
```bash
conda install projectchrono::pychrono -c conda-forge -y
```

### 3. 설치 검증

```bash
python verify_pychrono.py
```

다음과 같은 출력이 표시되어야 합니다:
```
==================================================
PyChrono Installation Verification
==================================================
[1/4] Testing PyChrono import...
✓ PyChrono imported successfully
  Version: 8.0.0

[2/4] Testing basic functionality...
✓ Created ChSystemNSC
✓ Created and added ChBody
✓ Executed DoStepDynamics

[3/4] Testing vectors and quaternions...
✓ ChVector3d: (1.0, 2.0, 3.0)
✓ ChQuaterniond: (1, 0, 0, 0)

[4/4] System Information:
  Python version: 3.10.x
  ...

==================================================
✓ All tests passed!
==================================================
```

## PyO3 환경 설정

Rust에서 PyChrono를 사용하려면 PyO3가 올바른 Python 인터프리터를 찾아야 합니다.

### Windows (CMD)
```cmd
conda activate cadverse_dev
set PYO3_PYTHON=%CONDA_PREFIX%\python.exe
```

### Windows (PowerShell)
```powershell
conda activate cadverse_dev
$env:PYO3_PYTHON = "$env:CONDA_PREFIX\python.exe"
```

### Linux / macOS
```bash
conda activate cadverse_dev
export PYO3_PYTHON=$CONDA_PREFIX/bin/python
```

### 영구 설정 (선택사항)

매번 환경 변수를 설정하지 않으려면 `.cargo/config.toml` 파일을 생성:

**sim_server/.cargo/config.toml**
```toml
[env]
PYO3_PYTHON = "C:\\Users\\nananina\\miniconda3\\envs\\cadverse_dev\\python.exe"
```

> ⚠️ **주의**: 경로는 사용자 환경에 맞게 수정하세요.

## Rust 프로젝트 빌드

```bash
cd sim_server
cargo build
```

## 테스트

### PyO3-PyChrono 통합 테스트

```bash
cd sim_server
cargo test
```

### Python 단독 테스트

```bash
conda activate cadverse_dev
python verify_pychrono.py
```

## 문제 해결

### PyChrono import 실패

**증상:**
```
ImportError: DLL load failed while importing _pychrono
```

**해결:**
1. Conda 환경이 활성화되어 있는지 확인
   ```
   conda activate cadverse_dev
   ```

2. PyChrono가 올바르게 설치되었는지 확인
   ```
   conda list pychrono
   ```

3. 재설치
   ```
   conda remove pychrono -y
   conda install projectchrono::pychrono -c conda-forge -y
   ```

### PyO3 빌드 실패

**증상:**
```
error: failed to run custom build command for `pyo3-ffi`
```

**해결:**
1. PYO3_PYTHON 환경 변수 확인
   ```cmd
   echo %PYO3_PYTHON%
   ```

2. Python 경로가 올바른지 확인
   ```
   %PYO3_PYTHON% --version
   ```

3. Visual Studio Build Tools 설치 확인 (Windows)

### Conda가 PATH에 없음

**증상:**
```
'conda' is not recognized as an internal or external command
```

**해결:**
1. Anaconda Prompt 사용
2. 또는 conda를 PATH에 추가:
   - 시스템 환경 변수 → PATH에 추가
   - `C:\Users\<username>\miniconda3\Scripts`
   - `C:\Users\<username>\miniconda3\condabin`

## 다음 단계

환경 설정이 완료되면 [개발 계획](../README.md)을 참조하여 다음 단계를 진행하세요:

- ✅ Phase 1: 개발 환경 설정 ← **현재 단계**
- ⏭️ Phase 2: 데이터 모델 구현
- ⏭️ Phase 3: Python 시뮬레이터 모듈 작성
- ⏭️ Phase 4: sim_manager 구현
- ⏭️ Phase 5: server 구현
- ⏭️ Phase 6: cad_data_loader 구현
- ⏭️ Phase 7: 통합 테스트 및 배포

## 참고 자료

- [PyChrono 공식 설치 가이드](https://api.projectchrono.org/pychrono_installation.html)
- [PyO3 사용자 가이드](https://pyo3.rs/)
- [Conda 문서](https://docs.conda.io/)
