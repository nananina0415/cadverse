import json
import threading
import sys
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from typing import List, TYPE_CHECKING

# 상위 디렉토리를 import path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

if TYPE_CHECKING:
    from utils.ReadWriteBuffer import ReadWriteBuffer


def run_server(output_buffer: 'ReadWriteBuffer',
               resources_dir: str = "./resources",
               host: str = "0.0.0.0",
               port: int = 8000):
    """
    FastAPI 기반 서버 실행 함수
    - WebSocket을 통한 실시간 인터랙션
    - HTTP를 통한 리소스 파일 제공 (메시 데이터 등)

    Args:
        output_buffer: 시뮬레이션 출력 버퍼
        resources_dir: 리소스 파일 디렉토리
        host: 서버 호스트
        port: 서버 포트
    """
    # FastAPI 앱 생성
    app = FastAPI()

    # 리소스 파일 디렉토리
    resources_path = Path(resources_dir)

    # 현재 연결된 클라이언트 목록
    active_connections: List[WebSocket] = []

    # HTTP GET: 리소스 파일 제공
    @app.get("/cadverse/resources/{file_path:path}")
    async def get_resource(file_path: str):
        """
        리소스 파일 제공
        예: GET /cadverse/resources/meshes/model.obj
        """
        full_path = resources_path / file_path

        # 파일 존재 여부 확인
        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

        # 보안: 지정된 디렉토리 밖의 파일 접근 방지
        try:
            full_path.resolve().relative_to(resources_path.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="접근이 거부되었습니다")

        return FileResponse(full_path)

    # WebSocket: 실시간 인터랙션
    @app.websocket("/cadverse/interaction")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket 연결 처리"""
        # 클라이언트 접속
        await websocket.accept()
        active_connections.append(websocket)

        try:
            # 연결이 끊길 때까지 메시지 수신
            while True:
                data = await websocket.receive_text()
                print(f"클라이언트로부터 메시지 수신: {data}")

                # TODO: 메시지 처리 로직 구현

        except WebSocketDisconnect:
            # 연결 종료 시 목록에서 제거
            if websocket in active_connections:
                active_connections.remove(websocket)
            print("클라이언트 연결 종료")

    # 서버 실행
    print(f"서버 시작: {host}:{port}")
    import uvicorn
    uvicorn.run(app, host=host, port=port)


class ServerThread(threading.Thread):
    """
    서버를 별도 스레드에서 실행하는 스레드
    run_server() 함수를 스레드에서 실행하는 간단한 래퍼
    """

    def __init__(self, output_buffer: 'ReadWriteBuffer',
                 resources_dir: str = "./resources",
                 host: str = "0.0.0.0",
                 port: int = 8000):
        super().__init__(daemon=True)

        self.output_buffer = output_buffer
        self.resources_dir = resources_dir
        self.host = host
        self.port = port

    def run(self):
        """스레드에서 실행될 서버"""
        try:
            run_server(
                output_buffer=self.output_buffer,
                resources_dir=self.resources_dir,
                host=self.host,
                port=self.port
            )
        except Exception as e:
            print(f"서버 오류 발생: {e}")
            import traceback
            traceback.print_exc()
