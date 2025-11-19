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
    def fromJson(cls, jsonPath: str) -> 'ServerConfig':
        """JSON 파일에서 설정 로드"""
        with open(jsonPath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls(**data)

    @classmethod
    def fromDict(cls, data: dict) -> 'ServerConfig':
        """딕셔너리에서 설정 생성"""
        return cls(**data)

    def toDict(self) -> dict:
        """딕셔너리로 변환"""
        return asdict(self)


def runServer(config: ServerConfig,
              onWebsocketMessage: Optional[Callable] = None,
              **callbackKwargs):
    """
    FastAPI 기반 서버 실행 함수
    - WebSocket을 통한 실시간 인터랙션
    - HTTP를 통한 리소스 파일 제공 (메시 데이터 등)

    Args:
        config: 서버 설정 (ServerConfig)
        onWebsocketMessage: WebSocket 메시지 수신 시 호출할 콜백 함수
                           시그니처: callback(websocket, message, **kwargs)
        **callbackKwargs: 콜백 함수에 전달할 추가 매개변수
                         예: outputBuffer=buffer, inputBuffer=buffer 등
    """
    # FastAPI 앱 생성
    app = FastAPI()

    # 리소스 파일 디렉토리
    resourcesPath = Path(config.resources_dir)

    # 현재 연결된 클라이언트 목록
    activeConnections: List[WebSocket] = []

    # HTTP GET: 리소스 파일 제공
    @app.get("/cadverse/resources/{file_path:path}")
    async def getResource(file_path: str):
        """
        리소스 파일 제공
        예: GET /cadverse/resources/meshes/model.obj
        """
        fullPath = resourcesPath / file_path

        # 파일 존재 여부 확인
        if not fullPath.exists() or not fullPath.is_file():
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

        # 보안: 지정된 디렉토리 밖의 파일 접근 방지
        try:
            fullPath.resolve().relative_to(resourcesPath.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="접근이 거부되었습니다")

        return FileResponse(fullPath)

    # WebSocket: 실시간 인터랙션
    @app.websocket("/cadverse/interaction")
    async def websocketEndpoint(websocket: WebSocket):
        """WebSocket 연결 처리"""
        import asyncio
        import random
        from datetime import datetime

        # 클라이언트 접속
        await websocket.accept()
        activeConnections.append(websocket)
        print("클라이언트 연결됨")

        # 주기적 메시지 전송 태스크
        async def sendPeriodicMessages():
            """1~3초마다 서버에서 메시지 전송"""
            try:
                while True:
                    # 랜덤 대기 (1~3초)
                    await asyncio.sleep(random.uniform(3, 5))

                    # 서버 시간과 함께 메시지 전송
                    serverTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    message = f"Hello, AR! @ {serverTime}"
                    await websocket.send_text(message)
                    print(f"-> 서버가 전송: {message}")
            except Exception as e:
                print(f"주기적 메시지 전송 종료: {e}")

        # 백그라운드 태스크 시작
        sendTask = asyncio.create_task(sendPeriodicMessages())

        try:
            # 연결이 끊길 때까지 메시지 수신
            while True:
                data = await websocket.receive_text()
                print(f"<- 클라이언트로부터 수신: {data}")

                # 응답 전송 추가
                response = f"I received \"{data}\""
                await websocket.send_text(response)
                print(f"-> 서버가 응답: {response}")

                # 콜백 함수가 등록되어 있으면 호출
                if onWebsocketMessage:
                    try:
                        # 콜백 함수 호출 (websocket, message, **kwargs)
                        result = onWebsocketMessage(websocket, data, **callbackKwargs)
                        # 비동기 함수인 경우 await
                        if hasattr(result, '__await__'):
                            await result
                    except Exception as e:
                        print(f"콜백 함수 오류: {e}")
                        import traceback
                        traceback.print_exc()

        except WebSocketDisconnect:
            # 연결 종료 시 목록에서 제거
            if websocket in activeConnections:
                activeConnections.remove(websocket)
            print("클라이언트 연결 종료")
        finally:
            # 주기적 전송 태스크 취소
            sendTask.cancel()
            try:
                await sendTask
            except asyncio.CancelledError:
                pass

    # 서버 실행
    print(f"서버 시작: {config.host}:{config.port}")
    print(f"리소스 디렉토리: {config.resources_dir}")
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)


class ServerThread(threading.Thread):
    """
    서버를 별도 스레드에서 실행하는 스레드
    runServer() 함수를 스레드에서 실행하는 래퍼
    """

    def __init__(self,
                 config: ServerConfig,
                 onWebsocketMessage: Optional[Callable] = None,
                 **callbackKwargs):
        """
        Args:
            config: 서버 설정
            onWebsocketMessage: WebSocket 메시지 콜백
            **callbackKwargs: 콜백에 전달할 매개변수 (예: outputBuffer=buffer)
        """
        super().__init__(daemon=True)

        self.config = config
        self.onWebsocketMessage = onWebsocketMessage
        self.callbackKwargs = callbackKwargs

    def run(self):
        """스레드에서 실행될 서버"""
        try:
            runServer(
                config=self.config,
                onWebsocketMessage=self.onWebsocketMessage,
                **self.callbackKwargs
            )
        except Exception as e:
            print(f"서버 오류 발생: {e}")
            import traceback
            traceback.print_exc()
