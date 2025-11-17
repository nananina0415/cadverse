# CADverse 개발 환경 셋업 가이드

이 가이드는 CADverse 프로젝트 개발을 위한 환경 설정 방법을 안내합니다.

## 사전 요구사항

### 1. Conda 설치

Anaconda 또는 Miniconda를 먼저 설치해야 합니다.

**Miniconda 다운로드 (권장):**
- 공식 사이트: https://docs.conda.io/en/latest/miniconda.html

**설치 확인:**
```bash
conda --version
```

## 자동 설치 (권장)

### Linux/macOS

```bash
# 리포지토리 루트에서 실행
chmod +x setup_environment.sh
./setup_environment.sh
```

### Windows

```cmd
REM Anaconda Prompt에서 실행
setup_environment.bat
```

## 수동 설치

자동 설치 스크립트가 동작하지 않는 경우, 다음 단계를 수동으로 실행하세요.

### 1. conda-forge 채널 추가

```bash
conda config --add channels conda-forge
conda config --set channel_priority strict
```

### 2. 환경 생성

```bash
conda env create -f environment.yml
```

### 3. 환경 활성화

```bash
conda activate cadverse
```

### 4. 설치 확인

```bash
# PyChrono 버전 확인
python -c "import pychrono; print(pychrono.GetChronoVersion())"

# 기타 패키지 확인
python -c "import fastapi, uvicorn, websockets; print('✅ 모든 패키지 설치됨')"
```

## 설치된 주요 패키지

- **Python**: 3.11
- **PyChrono**: 9.0.1 (물리 시뮬레이션 엔진)
- **FastAPI**: 웹 서버 프레임워크
- **Uvicorn**: ASGI 서버
- **WebSockets**: 실시간 통신
- **NumPy, SciPy**: 수치 계산

## 개발 서버 실행

환경 활성화 후 다음 명령어로 서버를 실행합니다:

```bash
# 환경 활성화
conda activate cadverse

# 프로토타입 디렉토리로 이동
cd prototype

# 서버 실행
python sim_server/main.py
```

서버가 시작되면 다음 주소로 접속할 수 있습니다:
- HTTP API: http://localhost:8000
- API 문서: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/cadverse/interaction

## 환경 업데이트

`environment.yml` 파일이 업데이트된 경우:

```bash
conda env update -n cadverse -f environment.yml
```

## 환경 삭제

환경을 완전히 제거하려면:

```bash
conda deactivate  # 환경이 활성화된 경우
conda env remove -n cadverse
```

## 문제 해결

### 1. "Solving environment" 단계에서 오래 걸림

conda-forge 채널의 우선순위를 올리세요:
```bash
conda config --set channel_priority strict
```

### 2. PyChrono 설치 실패

특정 버전 없이 최신 버전 설치 시도:
```bash
conda install -c conda-forge pychrono
```

### 3. Python 버전 충돌

environment.yml에서 Python 버전을 조정하세요 (3.9, 3.10, 3.11 모두 지원).

### 4. 기존 환경 문제

기존 환경을 삭제하고 새로 생성:
```bash
conda env remove -n cadverse
conda env create -f environment.yml
```

## 참고 자료

- **PyChrono 공식 문서**: https://api.projectchrono.org/
- **PyChrono 설치 가이드**: https://api.projectchrono.org/pychrono_installation.html
- **conda-forge PyChrono**: https://anaconda.org/conda-forge/pychrono
- **FastAPI 문서**: https://fastapi.tiangolo.com/

## 팀원 정보

- 구자웅
- 임영훈
- 김민준
