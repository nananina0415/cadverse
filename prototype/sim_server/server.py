import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict


class Server:
    """
    FastAPI 기반 WebSocket 서버
    유니티 클라이언트와 실시간 통신하며 모델 상태를 전송
    """

    def __init__(self):
        # FastAPI 앱 생성
        self.app = FastAPI()

        # 모델 상태 관리 (향후 PyChrono 시뮬레이션 루프가 이 데이터를 업데이트)
        self.model_states: Dict = {
            "model_1": {
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}  # 쿼터니언
            },
            # 나중에 "model_2": {...} 등을 쉽게 추가 가능
        }

        # 현재 연결된 모든 클라이언트(유니티 앱) 목록
        self.active_connections: List[WebSocket] = []

        # 라우트 설정
        self._setup_routes()

    def _setup_routes(self):
        """API 엔드포인트 설정"""

        # 서버 시작 시 시뮬레이션 루프를 백그라운드 태스크로 자동 시작
        @self.app.on_event("startup")
        async def on_startup():
            asyncio.create_task(self.simulation_loop())

        # HTTP GET 엔드포인트 (현재 상태 확인용)
        @self.app.get("/models")
        async def get_models():
            return self.model_states

        # WebSocket 엔드포인트 (실시간 통신용)
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self._handle_websocket(websocket)

    async def broadcast_model_states(self):
        """모든 클라이언트에게 데이터를 전송(브로드캐스트)"""
        # 딕셔너리를 JSON 문자열로 변환
        message = json.dumps(self.model_states)

        # 연결 목록을 복사해서 사용 (전송 중 연결이 끊겨도 안전하도록)
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(message)
            except WebSocketDisconnect:
                self.active_connections.remove(connection)

    async def simulation_loop(self):
        """시뮬레이션 루프 (데이터 업데이트)"""
        while True:
            # 1초 대기
            await asyncio.sleep(1)

            # --- 여기가 PyChrono 시뮬레이션이 실행될 부분 ---
            # 예: model_1의 위치를 약간 변경
            self.model_states["model_1"]["position"]["x"] += 0.1
            # ----------------------------------------------

            # 데이터가 변경되었으므로 모든 클라이언트에 전송
            await self.broadcast_model_states()

    async def _handle_websocket(self, websocket: WebSocket):
        """WebSocket 연결 처리"""
        # 클라이언트가 접속하면
        await websocket.accept()
        self.active_connections.append(websocket)

        try:
            # 접속 즉시 현재 모델 상태를 한번 보내줌
            await websocket.send_text(json.dumps(self.model_states))

            # 연결이 끊길 때까지 대기 (클라이언트가 메시지를 보낼 수도 있음)
            while True:
                # 여기서는 클라이언트로부터 메시지를 받는 것을 기다림
                # (지금은 딱히 필요 없지만, 향후 유니티에서 입력을 받을 때 사용)
                data = await websocket.receive_text()
                print(f"Message from client: {data}")

        except WebSocketDisconnect:
            # 연결이 끊기면 목록에서 제거
            self.active_connections.remove(websocket)

    def run(self, host: str = "0.0.0.0", port: int = 8000):
        """서버 실행"""
        import uvicorn
        # 0.0.0.0은 로컬 네트워크의 모든 IP에서 접속을 허용한다는 의미
        uvicorn.run(self.app, host=host, port=port)
