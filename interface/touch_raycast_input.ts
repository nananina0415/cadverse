/**
 * Touch Raycast Input Interface
 * Client → Server: 터치 레이캐스트 기반 입력 메시지
 */

/** 3D 벡터 */
interface Vector3 {
  x: number;
  y: number;
  z: number;
}

/** TouchStart 페이로드 */
interface TouchStartPayload {
  /** 터치한 부품의 인덱스 */
  targetPartIndex: number;

  /** 터치 지점 (부품 로컬 좌표) */
  actionPoint: Vector3;

  /** 카메라 위치 (월드 좌표) */
  fingerPoint: Vector3;

  /** 카메라 방향 (정규화된 벡터) */
  z_direction: Vector3;
}

/** Touching 페이로드 */
interface TouchingPayload {
  /** 변경된 카메라 위치 (월드 좌표) */
  fingerPoint: Vector3;

  /** 변경된 카메라 방향 (정규화된 벡터) */
  z_direction: Vector3;
}

/** TouchEnd 페이로드 (빈 객체) */
interface TouchEndPayload {
  // empty
}

/** TouchStart 메시지 */
interface TouchStartMessage {
  type: "TouchStart";
  payload: TouchStartPayload;
}

/** Touching 메시지 */
interface TouchingMessage {
  type: "Touching";
  payload: TouchingPayload;
}

/** TouchEnd 메시지 */
interface TouchEndMessage {
  type: "TouchEnd";
  payload: TouchEndPayload;
}

/** 모든 터치 레이캐스트 입력 메시지 */
type TouchRaycastInput =
  | TouchStartMessage
  | TouchingMessage
  | TouchEndMessage;

/**
 * 사용 예시:
 *
 * // TouchStart
 * {
 *   "type": "TouchStart",
 *   "payload": {
 *     "targetPartIndex": 0,
 *     "actionPoint": { "x": 0.5, "y": 0.2, "z": -0.1 },
 *     "fingerPoint": { "x": 0.0, "y": 0.5, "z": -1.0 },
 *     "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
 *   }
 * }
 *
 * // Touching
 * {
 *   "type": "Touching",
 *   "payload": {
 *     "fingerPoint": { "x": 0.1, "y": 0.5, "z": -1.0 },
 *     "z_direction": { "x": 0.0, "y": 0.0, "z": 1.0 }
 *   }
 * }
 *
 * // TouchEnd
 * {
 *   "type": "TouchEnd",
 *   "payload": {}
 * }
 */
