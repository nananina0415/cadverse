// notes
//     "units": "모든 위치는 미터(m) 단위",
//     "rotation": "쿼터니언 순서 - e0=w, e1=x, e2=y, e3=z",
//     "frequency": "서버는 100ms(10Hz)마다 ModelStateMessage 전송",
//     "encoding": "모든 메시지는 UTF-8 JSON"
//
namespace MessageType {
  type Vector = {
    x: number;
    y: number;
    z: number;
  };
  type LocalPosition = Vector;
  type GlobalPosition = Vector;
  type GlobalDirection = Vector;

  type Orientation = {
    e0: number;
    e1: number;
    e2: number;
    e3: number;
  };
  type PartIndex = number;

  namespace ServerToClient {
    // 서버에서 보내는 각 파트 상태
    export type PartState = {
      pos: GlobalPosition;
      rot: Orientation;
    };

    // 서버에서 보내는 전체 메시지 구조
    export type ModelStateMessage = {
      sim_time: number;
      parts: PartState[];
    };
  }
  namespace ClientToServer {
    type InteractByScreen =
      {
        type: "TouchStart";
        // sim_time: number;
        payload: {
          targetPartIndex: PartIndex;
          actionPoint: LocalPosition;
          fingerPoint: GlobalPosition;
          z_direction: GlobalDirection;
        };
      }
      | {
        type: "Touching";
        // sim_time: number;
        payload: {
          fingerPoint: GlobalPosition;
          z_direction: GlobalDirection;
        };
      }
      | {
        type: "TouchEnd";
        // sim_time: number;
        payload: {};
      };
  }
}
