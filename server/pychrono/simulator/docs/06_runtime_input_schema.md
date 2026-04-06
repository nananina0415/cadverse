# docs/06_runtime_input_schema.md

Runtime Input Schema (Client → Server)
=====================================

본 문서는 AR/클라이언트가 서버(시뮬레이션)로 전송하는
런타임 상호작용 입력(UserInput) 이벤트의 JSON 스키마를 정의한다.

본 스키마는 CAD → JSON 메타데이터(03_metadata_schema.md)와 별개이며,
"사용자 입력(의도)"를 시뮬레이션 엔진이 해석 가능한 형태로 전달하기 위해 존재한다.

시뮬레이션 엔진은 본 입력을 사용하여
토크/속도/제어 명령을 생성하거나 적용할 수 있다.

--------------------------------------------------
Global Notes
--------------------------------------------------

- Units
  - 위치/길이: meter (m)
  - 각도: radian (rad)

- Coordinate system
  - Right-handed

- Quaternion ordering (프로젝트 표준, Chrono 매핑)
  - (w, x, y, z)
  - 문서/메타데이터/런타임 모두 동일하게 유지한다.

- Encoding
  - UTF-8 JSON

- Update Frequency (권장)
  - Client → Server Interaction: 이벤트 기반 + 필요 시 30~60 Hz 권장

- Interaction Interpretation
  - 입력은 "의도(intent)" 전달용이다.
  - 실제 물리 토크/힘 계산은 서버 시뮬레이션 엔진이 수행한다.

--------------------------------------------------
Core Types (02_core_types.md와 동일)
--------------------------------------------------

Vector3 (WORLD)

{
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

Quaternion (WORLD rotation)

{
  "w": 1.0,
  "x": 0.0,
  "y": 0.0,
  "z": 0.0
}

PartIndex

- parts 배열의 인덱스 (0-based)
- Server → Client Output의 parts[i] 와 동일한 순서라고 가정한다.
- (안정성을 위해) name 기반 식별자도 함께 지원할 수 있다.

--------------------------------------------------
UserInput Envelope
--------------------------------------------------

클라이언트 → 서버 메시지는 아래 공통 구조를 가진다.

{
  "type": "<EventType>",
  "payload": { ... }
}

EventType은 아래 중 하나이다.

- "TouchStart"
- "Touching"
- "TouchEnd"

--------------------------------------------------
InteractByScreen (Touch / Drag)
--------------------------------------------------

터치 기반 상호작용 이벤트 스트림.

클라이언트는 아래 순서로 이벤트를 전송한다.

TouchStart → Touching(0..N회) → TouchEnd

좌표계 규칙:

- fingerPointWorld, cameraForwardWorld : WORLD
- actionPointLocal                     : BODY-LOCAL

상태 유지(Statefulness) 규칙:

- 네트워크 유실/재연결/멀티터치 확장을 고려하여,
  Touching/TouchEnd는 가능한 한 "누구(target)를 조작 중인지"를 payload로 명시하는 것을 권장한다.
- 서버는 TouchStart 상태를 영구 보존한다고 가정하지 않는다.

--------------------------------------------------
Common Optional Fields (Recommended)
--------------------------------------------------

모든 이벤트 payload에 아래 필드를 선택적으로 추가할 수 있다.

- interactionId (string, optional)
  - 하나의 상호작용 스트림(TouchStart~TouchEnd)을 식별하는 ID

- timestampSec (number, optional)
  - 클라이언트 기준 이벤트 생성 시각(초)

- seq (integer, optional)
  - 이벤트 시퀀스 번호

예시:

{
  "type": "Touching",
  "payload": {
    "interactionId": "uuid",
    "timestampSec": 12.345,
    "seq": 42
  }
}

--------------------------------------------------
Target Identification
--------------------------------------------------

target은 사용자가 선택한 파트를 식별한다.

{
  "partIndex": 0,
  "partName": "gear_A"
}

권장 규칙:

- TouchStart는 target 필수
- Touching/TouchEnd도 target 또는 interactionId 포함 권장

서버 해석 우선순위:

1) partName
2) partIndex
3) interactionId 매핑

--------------------------------------------------
1) TouchStart
--------------------------------------------------

{
  "type": "TouchStart",
  "payload": {
    "interactionId": "optional",
    "timestampSec": 0.0,
    "seq": 0,

    "target": {
      "partIndex": 0,
      "partName": "gear_A"
    },

    "actionPointLocal": {
      "x": 0.0,
      "y": 0.0,
      "z": 0.0
    },

    "fingerPointWorld": {
      "x": 0.12,
      "y": 0.05,
      "z": 0.30
    },

    "cameraForwardWorld": {
      "x": 0.0,
      "y": 0.0,
      "z": 1.0
    }
  }
}

Field Meaning
-------------

- actionPointLocal
  - 바디 로컬 좌표계 기준 접촉점

- fingerPointWorld
  - 현재 손가락 월드 위치

- cameraForwardWorld
  - 카메라 전방 벡터
  - 회전/병진 해석 기준

--------------------------------------------------
2) Touching
--------------------------------------------------

드래그 중 반복 전송 이벤트.

{
  "type": "Touching",
  "payload": {
    "interactionId": "optional",

    "target": {
      "partIndex": 0,
      "partName": "gear_A"
    },

    "fingerPointWorld": {
      "x": 0.10,
      "y": 0.05,
      "z": 0.29
    },

    "cameraForwardWorld": {
      "x": 0.0,
      "y": 0.0,
      "z": 1.0
    }
  }
}

Notes
-----

- actionPointLocal은 기본적으로 유지된다고 가정
- 필요 시 재전송 가능

--------------------------------------------------
3) TouchEnd
--------------------------------------------------

{
  "type": "TouchEnd",
  "payload": {
    "interactionId": "optional",

    "target": {
      "partIndex": 0,
      "partName": "gear_A"
    }
  }
}

--------------------------------------------------
Behavior Rules (Engine Interpretation)
--------------------------------------------------

입력은 Interaction Controller가 해석한다.

권장 해석 구조:

TouchStart
- target 선택
- 조인트 구성 분석
- rotate / spring 모드 자동 판정
- 기준 벡터 캐싱

Touching
- finger 이동량 계산
- cameraForward 기반 회전 방향 판정
- 결과 → torque / force 적용

TouchEnd
- 입력 종료
- damping만 유지
- accumulator clear 가능

--------------------------------------------------
Interaction Mode Interpretation (UPDATED)
--------------------------------------------------

엔진은 조인트 구조에 따라 입력을 자동 해석할 수 있다.

예:

- revolute 1개 & others 0개
  → rotate mode

- translational constraint
  → spring / drag mode

- fixed target
  → no-op 처리

이 규칙은 metadata 구조 기반으로 판정된다.

--------------------------------------------------
Input Stability & Filtering (UPDATED)
--------------------------------------------------

AR 입력은 다음 노이즈를 포함할 수 있다.

- jitter (미세 진동)
- dropout (프레임 유실)
- repeat frames

엔진은 다음 처리를 수행할 수 있다.

- velocity smoothing
- torque clamp
- snap epsilon deadzone
- damping stabilization

(실제 구현은 main.py Interaction Controller 담당)

--------------------------------------------------
Design Rules
--------------------------------------------------

- 입력은 force/torque가 아닌 intent 전달용
- WORLD / LOCAL 좌표 혼동 금지
- target 없는 입력은 no-op 권장
- fixed body 조작은 무시 권장
- interactionId 기반 복구 지원 권장

--------------------------------------------------
Future Extensions
--------------------------------------------------

- pinch / twist gesture
- 2-finger constraint control
- ray-based pointer input
- affordance hint schema 연동
