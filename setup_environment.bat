@echo off
REM CADverse 개발 환경 셋업 스크립트 (Windows)
REM PyChrono 공식 가이드 기반: https://api.projectchrono.org/pychrono_installation.html

echo ==================================================
echo CADverse 개발 환경 셋업 (Windows)
echo ==================================================
echo.

REM 1. Conda 설치 확인
where conda >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Conda가 설치되어 있지 않습니다.
    echo.
    echo Anaconda 또는 Miniconda를 먼저 설치하세요:
    echo   https://docs.conda.io/en/latest/miniconda.html
    echo.
    pause
    exit /b 1
)

echo ✅ Conda 발견
conda --version
echo.

REM 2. conda-forge 채널 추가
echo 📦 conda-forge 채널 추가...
conda config --add channels conda-forge
conda config --set channel_priority strict
echo.

REM 3. 기존 환경 확인
conda env list | findstr /C:"cadverse" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo ⚠️  'cadverse' 환경이 이미 존재합니다.
    set /p REPLY="기존 환경을 삭제하고 새로 만드시겠습니까? (y/N): "

    if /i "%REPLY%"=="y" (
        echo 🗑️  기존 환경 삭제 중...
        conda env remove -n cadverse -y
        echo.
    ) else (
        echo ℹ️  기존 환경을 유지합니다. 패키지 업데이트를 시도합니다.
        conda env update -n cadverse -f environment.yml
        echo.
        echo ==================================================
        echo ✅ 환경 업데이트 완료!
        echo ==================================================
        echo.
        echo 다음 명령어로 환경을 활성화하세요:
        echo   conda activate cadverse
        echo.
        pause
        exit /b 0
    )
)

REM 4. 환경 생성
echo 🔨 'cadverse' conda 환경 생성 중...
echo    (PyChrono 9.0.1 + Python 3.11 + FastAPI + 기타 의존성)
echo.

conda env create -f environment.yml

echo.
echo ==================================================
echo ✅ 환경 셋업 완료!
echo ==================================================
echo.
echo 다음 명령어로 환경을 활성화하세요:
echo   conda activate cadverse
echo.
echo 환경 활성화 후 서버를 실행할 수 있습니다:
echo   cd prototype
echo   python sim_server\main.py
echo.
echo 설치된 PyChrono 버전 확인:
echo   python -c "import pychrono; print(pychrono.GetChronoVersion())"
echo.
pause
