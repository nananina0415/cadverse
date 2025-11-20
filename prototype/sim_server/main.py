import time
import json
import sys
from pathlib import Path

# sim_server 디렉토리 안에서도 실행할 수 있도록 상위 디렉토리를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sim_server.utils.OwnedBuffer import OwnedBuffer
from sim_server.server import ServerThread, ServerConfig
from sim_server.simloop import SimLoopThread


def loadServerConfig(configPath: str = None) -> ServerConfig:
    """
    서버 설정 파일 로드

    Args:
        configPath: 설정 파일 경로 (None이면 자동 탐색)

    Returns:
        ServerConfig 객체
    """
    # 설정 파일 경로 자동 탐색
    if configPath is None:
        # main.py 위치 기준
        scriptDir = Path(__file__).parent
        configFile = scriptDir / "server_config.json"
    else:
        configFile = Path(configPath)

    if not configFile.exists():
        print(f"설정 파일이 없습니다. 기본값을 사용합니다: {configFile}")
        return ServerConfig()

    try:
        config = ServerConfig.fromJson(str(configFile))

        # resources_dir을 절대 경로로 변환 (상대 경로인 경우)
        resourcesPath = Path(config.resources_dir)
        if not resourcesPath.is_absolute():
            # 설정 파일 위치 기준으로 해석
            resourcesPath = (configFile.parent / resourcesPath).resolve()
            config.resources_dir = str(resourcesPath)
            print(f"리소스 디렉토리 절대 경로: {config.resources_dir}")

        return config
    except Exception as e:
        print(f"설정 파일 로드 실패: {e}. 기본값을 사용합니다.")
        import traceback
        traceback.print_exc()
        return ServerConfig()


def onWebsocketMessage(websocket, message, **kwargs):
    """
    WebSocket 메시지 수신 시 호출되는 콜백 함수

    Args:
        websocket: WebSocket 연결 객체
        message: 수신한 메시지
        **kwargs: 추가 매개변수 (outputBuffer 등)
    """
    # 현재는 로그만 출력 (서버에서 이미 출력함)
    # 향후 여기서 메시지 처리 로직 구현
    # 예:
    # outputBuffer = kwargs.get('outputBuffer')
    # if outputBuffer:
    #     data = outputBuffer.readBuff()
    #     await websocket.send_text(json.dumps(data))
    pass


def cleanup(serverThread, simThread):
    """
    프로그램 종료 시 리소스 정리
    - 스레드 안전하게 종료
    - 리소스 해제
    """
    print("\n정리 작업 시작...")

    # 시뮬레이션 스레드 중지
    if simThread and simThread.is_alive():
        print("시뮬레이션 스레드 중지 중...")
        if hasattr(simThread, 'stop'):
            simThread.stop()
        simThread.join(timeout=5)

        if simThread.is_alive():
            print("경고: 시뮬레이션 스레드가 5초 내에 종료되지 않음")

    # 서버 스레드 중지
    if serverThread and serverThread.is_alive():
        print("서버 스레드 중지 중...")
        # 데몬 스레드이므로 메인이 종료되면 자동 종료됨
        # 하지만 명시적으로 정리 시도
        serverThread.join(timeout=2)

        if serverThread.is_alive():
            print("경고: 서버 스레드가 2초 내에 종료되지 않음 (데몬 스레드)")

    print("정리 완료.")


def main():
    """
    메인 스레드: ServerThread와 SimLoopThread를 관리
    - 버퍼를 생성하고 소유
    - 설정 파일에서 서버 설정 로드
    - 각 스레드에 버퍼와 콜백 전달
    - 스레드가 죽으면 재시작
    - 예외 처리 및 우아한 종료
    """

    # 서버 설정 로드
    serverConfig = loadServerConfig()
    print(f"서버 설정 로드: {serverConfig.toDict()}")

    # 입출력 버퍼 생성 (메인이 소유)
    outputBuffer = OwnedBuffer({})

    # TODO: 실제 모델 description 데이터 로드
    modelDescription = {}

    # 스레드 참조
    serverThread = None
    simThread = None

    print("CADverse 시뮬레이션 서버 시작")

    try:
        # 메인 루프 (외부 try: KeyboardInterrupt 처리)
        while True:
            try:
                # 내부 try: 개별 반복의 예외 처리

                # ServerThread 상태 체크 및 재시작
                if serverThread is None or not serverThread.is_alive():
                    if serverThread is not None:
                        print("서버 스레드가 종료됨. 재시작 중...")

                    # 서버 스레드 생성 (config와 콜백 전달)
                    serverThread = ServerThread(
                        config=serverConfig,
                        onWebsocketMessage=onWebsocketMessage,
                        outputBuffer=outputBuffer  # kwargs로 전달
                    )
                    serverThread.start()
                    print(f"서버 스레드 시작됨 (http://{serverConfig.host}:{serverConfig.port})")

                # SimLoopThread 상태 체크 및 재시작
                if simThread is None or not simThread.is_alive():
                    if simThread is not None:
                        print("시뮬레이션 스레드가 종료됨. 재시작 중...")

                    simThread = SimLoopThread(
                        modelDescription=modelDescription,
                        outputBuffer=outputBuffer
                    )
                    simThread.start()
                    print("시뮬레이션 스레드 시작됨")

                # 1초 대기 후 다시 체크
                time.sleep(1)

            except Exception as e:
                # 개별 반복에서 예외 발생 시
                print(f"에러 발생: {e}")
                import traceback
                traceback.print_exc()

                # 에러 발생 시 잠시 대기 후 재시도
                print("5초 후 재시도...")
                time.sleep(5)

    except KeyboardInterrupt:
        # Ctrl+C로 종료
        print("\n종료 신호 수신 (Ctrl+C)")

    except Exception as e:
        # 예상치 못한 전역 에러
        print(f"심각한 에러 발생: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 어떤 경우든 정리 작업 수행
        cleanup(serverThread, simThread)


if __name__ == "__main__":
    main()
