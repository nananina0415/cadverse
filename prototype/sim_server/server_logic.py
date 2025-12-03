import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pychrono import ChVector3d
from server_data_models import ModelStateMessage, Server, ServerConfig
from sim_data_models import PartState, UserInput
from utils.read_write_buffer import ReadWriteBuffer


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
        import tkinter as tk

        import PIL.ImageTk as ImageTk
        import qrcode
        from PIL import Image
        from qrcode.constants import ERROR_CORRECT_L
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
    photo = ImageTk.PhotoImage(img.convert("RGB"))  # type: ignore

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
    """
    # AR 이벤트(dict) 버퍼 생성
    user_input_buffer = ReadWriteBuffer[Dict[str, Any]]()

    # Server 객체 생성
    server = Server(config=config, userInput=user_input_buffer)

    return server

class ServerRunner:
    """
    서버 실행 엔진

    - Server 객체를 소유하고 FastAPI 서버 실행
    - getModelState로 시뮬레이션 상태를 읽어서 클라이언트에 전송
    - runOneCycle() 호출 시 주기적 작업 수행
    """

    def __init__(
        self, server: Server, getModelState: "Callable[[], List[PartState]]", simulation
    ):
        """
        Args:
            server: Server 객체 (상태 컨테이너)
            getModelState: 모델 상태를 읽는 함수 (getReadAccess()의 반환값)
            simulation: Simulation 객체 (힘 계산용)
        """
        self.server = server
        self.getModelState = getModelState
        self.simulation = simulation
        self.uvicorn_server = None
        self.server_thread = None

        # 터치 상태 추적
        self.touch_state = {
            "active": False,
            "part_index": -1,
            "action_point_local": None,  # ChVector3d
        }

        # FastAPI 앱 생성 및 서버 시작
        self._startUvicornServer()

        # QR 코드 표시
        localIp = getLocalIpAddress()
        serverAddress = f"{localIp}:{server.config.port}/cadverse"
        qrThread = threading.Thread(
            target=showQrCode, args=(serverAddress,), daemon=True
        )
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
                print(f"[HTTP] 리소스 요청 실패 (404): {file_path}", flush=True)
                raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
            try:
                fullPath.resolve().relative_to(resourcesPath.resolve())
            except ValueError:
                print(f"[HTTP] 리소스 접근 거부 (403): {file_path}", flush=True)
                raise HTTPException(status_code=403, detail="접근이 거부되었습니다")

            print(
                f"[HTTP] 리소스 전송 성공: {file_path} ({fullPath.stat().st_size} bytes)",
                flush=True,
            )
            return FileResponse(fullPath)

        # WebSocket: 실시간 인터랙션 (단방향 푸시)
        @app.websocket("/cadverse/interaction")
        async def websocketEndpoint(websocket: WebSocket):
            import asyncio
            import json

            await websocket.accept()

            # 클라이언트 연결 시 플래그 설정 (시뮬레이션 시작 트리거)
            self.server.hasClientConnected = True
            print("[ws] 클라이언트 연결됨 - 시뮬레이션 시작 준비", flush=True)

            async def receiveTask():
                """클라이언트 → 서버: 사용자 입력 수신 (응답 없음)"""
                try:
                    while True:
                        # 클라이언트로부터 메시지 수신
                        data = await websocket.receive_text()

                        # JSON 파싱하여 타입 확인
                        msg = json.loads(data)
                        msg_type = msg.get("type")
                        # ===  받은 AR 이벤트를 그대로 userInput 버퍼에 기록 ===
                        #    - ReadWriteBuffer는 타입 제약이 없으니 dict 그대로 넣어도 됨.
                        #    - 시뮬 쪽에서는 "최근 이벤트 1개만 쓴다"는 가정으로 마지막 것만 사용.
                        try:
                            self.server.userInput.commit([msg])
                        except Exception as e:
                            print(f"[ws] userInput 버퍼 commit 에러: {e}")

                        # TouchStart 메시지 처리
                        if msg_type == "TouchStart":
                            payload = msg.get("payload", {})
                            part_idx = payload.get("targetPartIndex", -1)
                            action_pt = payload.get("actionPoint", {})

                            # 터치 상태 저장
                            self.touch_state = {
                                "active": True,
                                "part_index": part_idx,
                                "action_point_local": ChVector3d(
                                    action_pt.get("x", 0),
                                    action_pt.get("y", 0),
                                    action_pt.get("z", 0),
                                ),
                            }

                            print(
                                f"[TouchStart] Part #{part_idx} | "
                                f"ActionPoint: ({action_pt.get('x', 0):.3f}, "
                                f"{action_pt.get('y', 0):.3f}, "
                                f"{action_pt.get('z', 0):.3f})"
                            )
                            continue

                        # Touching 메시지 처리 - 힘 벡터 계산
                        if msg_type == "Touching":
                            if not self.touch_state["active"]:
                                continue

                            payload = msg.get("payload", {})
                            finger_pt_dict = payload.get("fingerPoint", {})
                            finger_pt_global = ChVector3d(
                                finger_pt_dict.get("x", 0),
                                finger_pt_dict.get("y", 0),
                                finger_pt_dict.get("z", 0),
                            )

                            # 부품 ChBody 가져오기
                            part_idx = self.touch_state["part_index"]
                            bodies = self.simulation.simHandle.bodies
                            if part_idx < 0 or part_idx >= len(bodies):
                                continue

                            body = bodies[part_idx]

                            # 글로벌 → 로컬 변환
                            finger_pt_local = body.TransformPointParentToLocal(
                                finger_pt_global
                            )

                            # 힘 벡터 = fingerPoint(로컬) - actionPoint(로컬)
                            action_pt = self.touch_state["action_point_local"]
                            force_vector = finger_pt_local - action_pt

                            print(
                                f"[Force] ({force_vector.x:.3f}, "
                                f"{force_vector.y:.3f}, {force_vector.z:.3f})"
                            )
                            continue

                        # TouchEnd 메시지 처리
                        if msg_type == "TouchEnd":
                            self.touch_state["active"] = False
                            print("[TouchEnd] 터치 종료")
                            continue

                except WebSocketDisconnect:
                    print("[ws] 클라이언트 연결 종료 (수신)")
                except Exception as e:
                    print(f"[ws] 수신 에러: {e}")

            async def sendTask():
                """서버 → 클라이언트: 모델 상태 푸시 (sim_time 변경 시에만)"""
                last_sent_time = -1.0  # 마지막 전송한 sim_time

                try:
                    while True:
                        # 현재 sim_time 확인
                        current_time = self.simulation.sim_time

                        # sim_time이 변경되었을 때만 전송
                        if current_time != last_sent_time:
                            # 모델 상태 읽기
                            model_states = self.getModelState()

                            # DTO로 변환 후 JSON 직렬화 (sim_time 포함)
                            message = ModelStateMessage.fromPartStates(
                                model_states, current_time
                            )
                            states_json = message.toJson()

                            # 클라이언트로 전송
                            await websocket.send_text(states_json)

                            last_sent_time = current_time

                        # 10ms마다 체크 (너무 자주 체크하지 않도록)
                        await asyncio.sleep(0.01)

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
