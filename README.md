# CADverse

Fusion 360에서 설계한 CAD 모델을 실시간 물리 시뮬레이션과 연동하여 AR 기기로 인터랙션할 수 있는 시스템입니다.

---

## 아키텍처

### 시스템 구성도

```
[Fusion 360]
     │
  플러그인
     │ metadata.json + meshes/
     ▼
[시뮬레이션 서버] ◄──── QUIC (P2P) ────► [AR 클라이언트]
  Rust + PyChrono                           Unity XR (Android)
     │                                           │
  물리 계산                              HTTP/3 메타 다운로드
  시뮬레이션 상태 브로드캐스트            터치 입력 전송
```

### 구성 요소

| 구성 요소 | 역할 |
|-----------|------|
| **CAD 플러그인** | Fusion 360 애드인. 설계 모델에서 메시(OBJ)와 관절 메타데이터를 추출해 서버가 읽을 수 있는 형식으로 저장 |
| **시뮬레이션 서버** | Rust 기반 서버. PyChrono(Project Chrono) 물리 엔진을 내장하여 실시간 시뮬레이션을 수행하고 AR 클라이언트에 결과를 브로드캐스트 |
| **AR 클라이언트** | Unity XR 기반 Android 앱. 서버에서 모델을 받아 AR 씬을 구성하고 터치 입력을 서버로 전송 |
| **P2P 네트워킹** | iroh(QUIC) 기반 P2P 레이어. 서버 발견, 메타데이터 전송, 실시간 입출력 통신을 담당 |

---

## 다운로드

최신 버전은 [GitHub Releases](../../releases) 페이지에서 받을 수 있습니다.

| 파일 | 설명 |
|------|------|
| `cadverse-server-vX.X.X.zip` | 시뮬레이션 서버 (Windows) |
| `cadverse-plugin-vX.X.X.zip` | Fusion 360 플러그인 |
| `cadverse-client-vX.X.X.apk` | AR 클라이언트 (Android) |

---

## 요구사항

| 구성 요소 | 요구사항 |
|-----------|---------|
| **시뮬레이션 서버** | Windows 10 이상 (Python 환경 내장, 별도 설치 불필요) |
| **AR 클라이언트** | AR Foundation을 지원하는 Android 기기 |
| **CAD 플러그인** | Autodesk Fusion 360 |

---

## 설치 및 사용

### 1. Fusion 360 플러그인

**설치**

1. `cadverse-plugin-vX.X.X.zip` 압축 해제
2. Fusion 360 실행 → 상단 메뉴 `유틸리티` > `애드인` > `스크립트 및 애드인`
3. `애드인` 탭에서 `+` 버튼으로 압축 해제한 폴더 추가
4. `CADverse` 선택 후 `실행` 또는 `시작 시 실행` 체크

**사용 방법**

1. 익스포트할 Fusion 360 디자인을 열고 애드인 실행
2. 저장 폴더 선택
3. 익스포트 완료 후 선택한 폴더에 `metadata.json`과 `meshes/` 폴더 생성됨

---

### 2. 시뮬레이션 서버

**설치**

1. `cadverse-server-vX.X.X.zip` 압축 해제
2. 압축 해제한 폴더 내 `server.exe` 실행

**사용 방법**

1. 그룹 이름과 비밀번호 입력
2. 메뉴에서 `1. 시뮬레이션 시작` 선택
3. 플러그인으로 익스포트한 폴더 경로 입력
4. QR 코드 창이 표시되면 AR 클라이언트로 스캔

---

### 3. AR 클라이언트

**설치**

1. `cadverse-client-vX.X.X.apk`를 Android 기기에 설치
   - 설치 전 설정에서 `알 수 없는 앱 설치` 허용 필요

**사용 방법**

1. 앱 실행 후 서버와 동일한 그룹 이름, 비밀번호 입력
2. 카메라로 서버의 QR 코드 스캔
3. AR 씬에서 모델을 터치하여 시뮬레이션과 인터랙션

---

## 내부 구현

### 메타데이터 스키마

플러그인이 생성하는 `metadata.json`의 구조입니다.

```json
{
  "info": {
    "version": "2.0",
    "coordinate_system": "Right-Handed (Z-up)",
    "units": "Translation: cm, Rotation: Degree"
  },
  "transforms": {
    "part_name": [/* Row-major 4x4 행렬, 16개 float */]
  },
  "joints": [
    {
      "name": "joint_name",
      "type": "Revolute | Slider | Rigid",
      "connected_parts": { "parent": "...", "child": "..." },
      "axis": [x, y, z],
      "origin": [x, y, z],
      "limits": { "min": 0.0, "max": 90.0 }
    }
  ]
}
```

### 빌드 레이어

서버 빌드는 세 레이어로 구성됩니다.

```
Shell (build-server.ps1)
  └── Cargo (build.rs)
        └── conda-pack
```

- **Shell**: Conda 경로 설정, 환경 활성화
- **Cargo (build.rs)**: `environment.yml` 변경 감지 시 `conda env update`, 릴리즈 빌드 시 `conda-pack`으로 Python 환경 번들링
- **conda-pack**: 배포용 Python 환경을 `python_env.tar.gz`로 패키징

### Triple Buffer

서버는 AR 클라이언트 입력과 시뮬레이션 출력 사이의 지연을 최소화하기 위해 Lock-free Triple Buffer를 사용합니다. Reader, Writer, Swapper 역할을 분리하여 시뮬레이션 스레드와 네트워크 스레드가 서로 블로킹 없이 동작합니다.

### P2P 통신 구조

iroh(QUIC) 기반 P2P 네트워킹을 사용합니다.

- **Coordinator**: 첫 번째 참가자가 자동으로 담당. 피어 등록 및 브로드캐스트 관리
- **시뮬레이션 서버**: MidServer 역할로 Coordinator에 연결, 시뮬레이션 상태 브로드캐스트
- **AR 클라이언트**: HTTP/3으로 메타데이터와 메시 파일 수신, QUIC 스트림으로 터치 입력 전송 및 시뮬레이션 결과 수신
