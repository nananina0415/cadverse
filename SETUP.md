conda-pack 전체 설정 흐름
1단계: environment.yml 작성

name: cadverse_dev
channels:

- projectchrono
- conda-forge
  dependencies:
- python=3.10
- pychrono=8.0.0
- pip
- pip: - -e ./simulator # 로컬 패키지 설치
  2단계: 환경 생성 + 패키지 설치

conda env create -f environment.yml

# 또는 이미 환경이 있으면

conda env update -f environment.yml
3단계: simulator를 패키지로 만들기
simulator/ 폴더에 pyproject.toml 필요:

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "simulator"
version = "0.1.0"
이래야 pip install -e ./simulator가 conda 환경에 등록됩니다.

4단계: conda-pack 실행

conda activate cadverse_dev
conda pack -n cadverse_dev -o python_env.tar.gz --ignore-missing-files
5단계: 런타임에 압축 해제 + 경로 설정
배포된 바이너리 실행 시:

mkdir -p python_env
tar -xzf python_env.tar.gz -C python_env
./python_env/bin/python # 이 경로를 PYO3_PYTHON에
