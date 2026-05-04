# docs/06_runtime_input_schema.md

# Runtime Input Schema (Client → Server)

본 문서는 AR / 클라이언트가 서버(시뮬레이션 엔진)로 전송하는
런타임 상호작용 입력(UserInput)의 JSON 구조를 정의한다.

본 스키마는 Scene Metadata와 별개이며,
사용자의 조작 의도(intent)를 시뮬레이션 엔진이 해석 가능한 형태로 전달하기 위해 사용된다.

시뮬레이션 엔진은 입력을 직접적인 force/torque 값으로 받지 않고,
main.py의 Interaction Controller에서 물리적 구동으로 변환한다.

---

## Global Rules

- Encoding: UTF-8 JSON
- Coordinate system: Right-handed
- Length unit: meter (m)
- Angle unit: radian (rad)
- Rotation: Quaternion (w, x, y, z)

좌표계 규칙:

- fingerPointWorld: WORLD
- cameraForwardWorld: WORLD
- actionPointLocal: BODY-LOCAL

---

## UserInput Envelope

모든 입력 이벤트는 아래 구조를 가진다.

{
  "type": "TouchStart | Touching | TouchEnd",
  "payload": { ... }
}

이벤트 흐름:

TouchStart → Touching(0..N) → TouchEnd

---

## Target Identification

{
  "target": {
    "partIndex": 0,
    "partName": "shaft"
  }
}

권장 우선순위:

1) partName
2) partIndex
3) interactionId

---

## Common Optional Fields

{
  "interactionId": "uuid",
  "timestampSec": 0.0,
  "seq": 0
}

---

## 1. TouchStart

{
  "type": "TouchStart",
  "payload": {
    "interactionId": "optional",
    "timestampSec": 0.0,
    "seq": 0,

    "target": {
      "partIndex": 0,
      "partName": "shaft"
    },

    "actionPointLocal": {
      "x": 0.0,
      "y": 0.0,
      "z": 0.0
    },

    "fingerPointWorld": {
      "x": 0.05,
      "y": 0.04,
      "z": -0.02
    },

    "cameraForwardWorld": {
      "x": 0.0,
      "y": 0.0,
      "z": -1.0
    }
  }
}

Engine Behavior:

- target 선택
- interaction context 생성
- rotate / spring mode 판정
- actuator drive neutralize (필요 시)

---

## 2. Touching

{
  "type": "Touching",
  "payload": {
    "interactionId": "optional",
    "timestampSec": 0.016,
    "seq": 1,

    "target": {
      "partName": "shaft"
    },

    "fingerPointWorld": {
      "x": 0.05,
      "y": 0.05,
      "z": -0.01
    },

    "cameraForwardWorld": {
      "x": 0.0,
      "y": 0.0,
      "z": -1.0
    }
  }
}

Engine Behavior:

- finger 이동량 계산
- rotate mode → torque 적용
- spring mode → force 적용
- smoothing / clamp 적용

---

## 3. TouchEnd

{
  "type": "TouchEnd",
  "payload": {
    "interactionId": "optional",
    "timestampSec": 0.25,
    "seq": 15,

    "target": {
      "partName": "shaft"
    }
  }
}

Engine Behavior:

- interaction 종료
- damping 유지
- free motion 상태 진입

---

## Legacy Input Compatibility (중요)

현재 runtime_types.py 및 Rust 서버 구조를 위해
아래 레거시 필드도 허용한다.

### Target

{
  "targetPartIndex": 0
}

또는

{
  "partIndex": 0
}

---

### Touch Fields

권장:

- actionPointLocal
- fingerPointWorld
- cameraForwardWorld

호환:

- actionPoint
- fingerPoint
- z_direction

즉 현재 Rust 입력도 정상 동작:

{
  "type": "TouchStart",
  "payload": {
    "targetPartIndex": 0,
    "actionPoint": { "x": 0, "y": 0, "z": 0 },
    "fingerPoint": { "x": 0, "y": 0, "z": 0 },
    "z_direction": { "x": 0, "y": 0, "z": 1 }
  }
}

---

## Interaction Mode Interpretation

엔진은 metadata 기반으로 자동 판단한다.

### Rotate Mode

조건:

- revolute joint 기반 구동 가능

동작:

- 회전축 기준 torque 적용
- inertia 기반 damping
- torque clamp
- no-flip guard

---

### Spring Mode

조건:

- rotate 해석 불가

동작:

- spring-damper force 적용
- 자유도 구조가 불명확해도 안정 동작

---

## Input Stability

엔진은 다음 처리를 수행한다.

- jitter 제거
- smoothing
- deadzone
- torque clamp
- damping stabilization

---

## Invalid Input Handling

- None input → step만 진행
- target 없음 → no-op
- fixed body → 무시
- unknown type → parse error

---

## Design Rules

- 입력은 intent 기반이다 (force/torque 아님)
- WORLD / LOCAL 좌표 구분 필수
- partName 사용 권장
- TouchStart → Touching → TouchEnd 유지