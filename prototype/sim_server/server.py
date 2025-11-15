import json
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from typing import List


class Server:
    """
    FastAPI 기반 서버
    - WebSocket을 통한 실시간 인터랙션
    - HTTP를 통한 리소스 파일 제공 (메시 데이터 등)
    """

    def __init__(self, resources_dir: str = "./resources"):
        # FastAPI 앱 생성
        self.app = FastAPI()

        # 리소스 파일이 저장된 디렉토리
        self.resources_dir = Path(resources_dir)

        # 현재 연결된 모든 클라이언트 목록
        self.active_connections: List[WebSocket] = []

        # 라우트 설정
        self._setup_routes()

    def _setup_routes(self):
        """API 엔드포인트 설정"""

        # HTTP GET: 리소스 파일 제공 (메시 데이터 등)
        @self.app.get("/cadverse/resources/{file_path:path}")
        async def get_resource(file_path: str):
            """
            리소스 파일 제공
            예: GET /cadverse/resources/meshes/model.obj
            """
            full_path = self.resources_dir / file_path

            # 파일 존재 여부 확인
            if not full_path.exists() or not full_path.is_file():
                raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

            # 보안: 지정된 디렉토리 밖의 파일 접근 방지
            try:
                full_path.resolve().relative_to(self.resources_dir.resolve())
            except ValueError:
                raise HTTPException(status_code=403, detail="접근이 거부되었습니다")

            return FileResponse(full_path)

        # WebSocket: 실시간 인터랙션
        @self.app.websocket("/cadverse/interaction")
        async def websocket_endpoint(websocket: WebSocket):
            await self._handle_websocket(websocket)

    async def _handle_websocket(self, websocket: WebSocket):
        """WebSocket 연결 처리"""
        # 클라이언트 접속
        await websocket.accept()
        self.active_connections.append(websocket)

        try:
            # 연결이 끊길 때까지 메시지 수신
            while True:
                data = await websocket.receive_text()
                print(f"클라이언트로부터 메시지 수신: {data}")

                # TODO: 메시지 처리 로직 구현

        except WebSocketDisconnect:
            # 연결 종료 시 목록에서 제거
            self.active_connections.remove(websocket)
            print("클라이언트 연결 종료")

    async def broadcast(self, message: str):
        """모든 연결된 클라이언트에게 메시지 브로드캐스트"""
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(message)
            except WebSocketDisconnect:
                self.active_connections.remove(connection)

    def run(self, host: str = "0.0.0.0", port: int = 8000):
        """서버 실행"""
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)
