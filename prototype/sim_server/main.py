import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict

# FastAPI 앱 생성
app = FastAPI()

# -----------------------------------------------------
# 1. 확장성을 위한 모델 상태 관리
# -----------------------------------------------------
# (향후 PyChrono 시뮬레이션 루프가 이 데이터를 업데이트하게 됩니다)
model_states = {
    "model_1": {
        "position": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0} # 쿼터니언
    },
    # 나중에 "model_2": {...} 등을 쉽게 추가 가능
}

# -----------------------------------------------------
# 2. WebSocket 연결 관리
# -----------------------------------------------------
# 현재 연결된 모든 클라이언트(유니티 앱) 목록
active_connections: List[WebSocket] = []

# 모든 클라이언트에게 데이터를 전송(브로드캐스트)하는 헬퍼 함수
async def broadcast_model_states():
    # 딕셔너리를 JSON 문자열로 변환
    message = json.dumps(model_states)
    
    # 연결 목록을 복사해서 사용 (전송 중 연결이 끊겨도 안전하도록)
    for connection in active_connections[:]:
        try:
            await connection.send_text(message)
        except WebSocketDisconnect:
            active_connections.remove(connection)

# -----------------------------------------------------
# 3. 시뮬레이션 루프 (데이터 업데이트)
# -----------------------------------------------------
# (지금은 PyChrono 대신 데이터를 1초마다 임의로 변경)
async def simulation_loop():
    while True:
        # 1초 대기
        await asyncio.sleep(1)
        
        # --- 여기가 PyChrono 시뮬레이션이 실행될 부분 ---
        # 예: model_1의 위치를 약간 변경
        model_states["model_1"]["position"]["x"] += 0.1
        # ----------------------------------------------
        
        # 데이터가 변경되었으므로 모든 클라이언트에 전송
        await broadcast_model_states()

# -----------------------------------------------------
# 4. API 엔드포인트 정의
# -----------------------------------------------------
# 서버 시작 시 시뮬레이션 루프를 백그라운드 태스크로 자동 시작
@app.on_event("startup")
async def on_startup():
    asyncio.create_task(simulation_loop())

# HTTP GET 엔드포인트 (현재 상태 확인용)
@app.get("/models")
async def get_models():
    return model_states

# WebSocket 엔드포인트 (실시간 통신용)
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # 클라이언트가 접속하면
    await websocket.accept()
    active_connections.append(websocket)
    
    try:
        # 접속 즉시 현재 모델 상태를 한번 보내줌
        await websocket.send_text(json.dumps(model_states))
        
        # 연결이 끊길 때까지 대기 (클라이언트가 메시지를 보낼 수도 있음)
        while True:
            # 여기서는 클라이언트로부터 메시지를 받는 것을 기다림
            # (지금은 딱히 필요 없지만, 향후 유니티에서 입력을 받을 때 사용)
            data = await websocket.receive_text()
            print(f"Message from client: {data}")
            
    except WebSocketDisconnect:
        # 연결이 끊기면 목록에서 제거
        active_connections.remove(websocket)

# -----------------------------------------------------
# 5. 서버 실행 (터미널에서)
# -----------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    # 0.0.0.0은 로컬 네트워크의 모든 IP에서 접속을 허용한다는 의미
    uvicorn.run(app, host="0.0.0.0", port=8000)
