import threading
import socket
import time
from pathlib import Path
from typing import List, Callable
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from server_data_models import ServerConfig, Server
from sim_data_models import PartState, UserInput
from message_dto import ModelStateMessage, UserInputMessage
from utils.read_write_buffer import ReadWriteBuffer
from pychrono import ChVector3d


def getLocalIpAddress() -> str:
    """로컬 네트워크 IP 주소를 가져옵니다."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def showQrCode(serverAddress: str):
    """QR 코드를 생성하고 GUI 창에 표시합니다."""
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_L
        from PIL import Image
        import PIL.ImageTk as ImageTk
        import tkinter as tk
    except ImportError:
        print("QR 코드 표시를 위해 다음 패키지가 필요합니다:")
        print("  pip install qrcode[pil]")
        print(f"\n서버 주소: {serverAddress}")
        return

    # QR 코드 생성
    qr = qrcode.QRCode(
        version=1,
        error_correction=ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(serverAddress)
    qr.make(fit=True)

    # 이미지 생성
    img = qr.make_image(fill_color="black", back_color="white")

    # tkinter 창 생성
    root = tk.Tk()
    root.title("CADverse 서버 QR 코드")

    # 이미지를 PhotoImage로 변환 (PIL Image로 명시적 변환)
    photo = ImageTk.PhotoImage(img.convert('RGB'))  # type: ignore

    # 라벨에 이미지 표시
    label = tk.Label(root, image=photo)
    label.pack(padx=20, pady=20)

    # 주소 텍스트 표시
    address_label = tk.Label(root, text=serverAddress, font=("Arial", 12))
    address_label.pack(pady=10)

    # 창 닫기 버튼
    close_button = tk.Button(root, text="닫기", command=root.destroy)
    close_button.pack(pady=10)

    print(f"QR 코드 창이 열렸습니다. 서버 주소: {serverAddress}")

    # GUI 이벤트 루프 시작
    root.mainloop()


def buildServer(config: ServerConfig) -> Server:
    """
    ServerConfig로부터 Server 객체 생성

    Args:
        config: 서버 설정

    Returns:
        Server: 초기화된 서버 객체
    """
    # UserInput 버퍼 생성
    user_input_buffer = ReadWriteBuffer[UserInput]()

    # Server 객체 생성
    server = Server(
        config=config,
        userInput=user_input_buffer
    )

    return server


class ServerRunner:
    """
    서버 실행 엔진

    - Server 객체를 소유하고 FastAPI 서버 실행
    - getModelState로 시뮬레이션 상태를 읽어서 클라이언트에 전송
    - runOneCycle() 호출 시 주기적 작업 수행
    """

    def __init__(self, server: Server, getModelState: 'Callable[[], List[PartState]]'):
        """
        Args:
            server: Server 객체 (상태 컨테이너)
            getModelState: 모델 상태를 읽는 함수 (getReadAccess()의 반환값)
        """
        self.server = server
        self.getModelState = getModelState
        self.uvicorn_server = None
        self.server_thread = None

        # FastAPI 앱 생성 및 서버 시작
        self._startUvicornServer()

        # QR 코드 표시
        localIp = getLocalIpAddress()
        serverAddress = f"{localIp}:{server.config.port}/cadverse"
        qrThread = threading.Thread(target=showQrCode, args=(serverAddress,), daemon=True)
        qrThread.start()

    def _startUvicornServer(self):
        """uvicorn 서버를 백그라운드 스레드에서 시작"""
        app = FastAPI()
        config = self.server.config
        resourcesPath = Path(config.resources_dir)

        # HTTP GET: 리소스 파일 제공
        @app.get("/cadverse/resources/{file_path:path}")
        async def getResource(file_path: str):
            fullPath = resourcesPath / file_path
            if not fullPath.exists() or not fullPath.is_file():
                raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
            try:
                fullPath.resolve().relative_to(resourcesPath.resolve())
            except ValueError:
                raise HTTPException(status_code=403, detail="접근이 거부되었습니다")
            return FileResponse(fullPath)

        # WebSocket: 실시간 인터랙션 (단방향 푸시)
        @app.websocket("/cadverse/interaction")
        async def websocketEndpoint(websocket: WebSocket):
            import asyncio

            await websocket.accept()
            print("[ws] 클라이언트 연결됨")

            async def receiveTask():
                """클라이언트 → 서버: 사용자 입력 수신 (응답 없음)"""
                try:
                    while True:
                        # 클라이언트로부터 메시지 수신
                        data = await websocket.receive_text()
                        print(f"[ws] <- 클라이언트: {data}")

                        # DTO로 파싱
                        user_input_msg = UserInputMessage.fromJson(data)

                        # ChVector3d로 변환
                        point = ChVector3d(
                            user_input_msg.point["x"],
                            user_input_msg.point["y"],
                            user_input_msg.point["z"]
                        )
                        direction = ChVector3d(
                            user_input_msg.direction["x"],
                            user_input_msg.direction["y"],
                            user_input_msg.direction["z"]
                        )

                        # 사용자 입력을 버퍼에 커밋 (응답 없음)
                        user_input = UserInput(point=point, direction=direction)
                        self.server.userInput.commit([user_input])

                except WebSocketDisconnect:
                    print("[ws] 클라이언트 연결 종료 (수신)")
                except Exception as e:
                    print(f"[ws] 수신 에러: {e}")

            async def sendTask():
                """서버 → 클라이언트: 모델 상태 푸시 (응답 기다리지 않음)"""
                send_count = 0
                try:
                    while True:
                        # 모델 상태 읽기
                        model_states = self.getModelState()

                        # DTO로 변환 후 JSON 직렬화
                        message = ModelStateMessage.fromPartStates(model_states)
                        states_json = message.toJson()

                        # 클라이언트로 전송 (응답 기다리지 않음)
                        await websocket.send_text(states_json)

                        # 100번마다 상태 로그 출력
                        send_count += 1
                        if send_count % 100 == 0:
                            # 첫 번째 파트의 위치만 출력
                            if model_states:
                                pos = model_states[0].pos
                                print(f"[ws] 송신 #{send_count}: parts={len(model_states)}, pos=({pos.x:.3f}, {pos.y:.3f}, {pos.z:.3f})", flush=True)

                        # 송신 주기 (100ms)
                        await asyncio.sleep(0.1)

                except WebSocketDisconnect:
                    print("[ws] 클라이언트 연결 종료 (송신)")
                except Exception as e:
                    print(f"[ws] 송신 에러: {e}")

            try:
                # 수신과 송신을 동시에 실행
                await asyncio.gather(receiveTask(), sendTask())
            except Exception as e:
                print(f"[ws] WebSocket 에러: {e}")
            finally:
                print("[ws] WebSocket 연결 종료")

        # uvicorn 서버를 별도 스레드에서 실행
        def runUvicorn():
            import uvicorn
            print(f"서버 시작: {config.host}:{config.port}")
            print(f"리소스 디렉토리: {config.resources_dir}")
            uvicorn.run(app, host=config.host, port=config.port, log_level="warning")

        self.server_thread = threading.Thread(target=runUvicorn, daemon=True)
        self.server_thread.start()

    def runOneCycle(self):
        """
        한 사이클 실행
        - uvicorn이 백그라운드에서 실행 중이므로 여기서는 짧은 대기만 수행
        """
        time.sleep(0.1)  # 100ms 대기

    def clear(self):
        """서버 정리 (리소스 해제)"""
        print("서버 종료 중...")
        # uvicorn 서버는 daemon 스레드로 실행되므로 자동 종료됨
