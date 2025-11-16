import json
import threading
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, TYPE_CHECKING, Callable, Optional, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse

# 상위 디렉토리를 import path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class ServerConfig:
    """서버 설정"""
    host: str = "0.0.0.0"
    port: int = 8000
    resources_dir: str = "./resources"

    @classmethod
    def from_json(cls, json_path: str) -> 'ServerConfig':
        """JSON 파일에서 설정 로드"""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict) -> 'ServerConfig':
        """딕셔너리에서 설정 생성"""
        return cls(**data)

    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return asdict(self)


def run_server(config: ServerConfig,
               on_websocket_message: Optional[Callable] = None,
               **callback_kwargs):
    """
    FastAPI 기반 서버 실행 함수
    - WebSocket을 통한 실시간 인터랙션
    - HTTP를 통한 리소스 파일 제공 (메시 데이터 등)

    Args:
        config: 서버 설정 (ServerConfig)
        on_websocket_message: WebSocket 메시지 수신 시 호출할 콜백 함수
                             시그니처: callback(websocket, message, **kwargs)
        **callback_kwargs: 콜백 함수에 전달할 추가 매개변수
                          예: output_buffer=buffer, input_buffer=buffer 등
    """
    # FastAPI 앱 생성
    app = FastAPI()

    # 리소스 파일 디렉토리
    resources_path = Path(config.resources_dir)

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

                # 콜백 함수가 등록되어 있으면 호출
                if on_websocket_message:
                    try:
                        # 콜백 함수 호출 (websocket, message, **kwargs)
                        result = on_websocket_message(websocket, data, **callback_kwargs)
                        # 비동기 함수인 경우 await
                        if hasattr(result, '__await__'):
                            await result
                    except Exception as e:
                        print(f"콜백 함수 오류: {e}")
                        import traceback
                        traceback.print_exc()

        except WebSocketDisconnect:
            # 연결 종료 시 목록에서 제거
            if websocket in active_connections:
                active_connections.remove(websocket)
            print("클라이언트 연결 종료")

    # 서버 실행
    print(f"서버 시작: {config.host}:{config.port}")
    print(f"리소스 디렉토리: {config.resources_dir}")
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)


class ServerThread(threading.Thread):
    """
    서버를 별도 스레드에서 실행하는 스레드
    run_server() 함수를 스레드에서 실행하는 래퍼
    """

    def __init__(self,
                 config: ServerConfig,
                 on_websocket_message: Optional[Callable] = None,
                 **callback_kwargs):
        """
        Args:
            config: 서버 설정
            on_websocket_message: WebSocket 메시지 콜백
            **callback_kwargs: 콜백에 전달할 매개변수 (예: output_buffer=buffer)
        """
        super().__init__(daemon=True)

        self.config = config
        self.on_websocket_message = on_websocket_message
        self.callback_kwargs = callback_kwargs

    def run(self):
        """스레드에서 실행될 서버"""
        try:
            run_server(
                config=self.config,
                on_websocket_message=self.on_websocket_message,
                **self.callback_kwargs
            )
        except Exception as e:
            print(f"서버 오류 발생: {e}")
            import traceback
            traceback.print_exc()
