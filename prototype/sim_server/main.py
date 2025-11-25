import sys
import time
from pathlib import Path

# prototype 폴더를 sys.path에 추가 (server_client_interface.py 임포트를 위해)
_script_dir = Path(__file__).parent
_prototype_dir = _script_dir.parent
if str(_prototype_dir) not in sys.path:
    sys.path.insert(0, str(_prototype_dir))

from typing import Optional
from server_logic import buildServer, ServerRunner
from sim_logic import buildSimulation, Simulator
from sim_data_models import SimDescription
from server_data_models import ServerConfig
from utils.loop_thread import LoopThread

def loadServerConfig(configPath: Optional[str] = None) -> ServerConfig:
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
        configFile = scriptDir / "resources/server_config.json"
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

def parseCadData()->SimDescription:
    # 프로토타입이라 존재하는 하드코딩 함수
    # 원래는 와처 스레드가 SimDescription.fromCadData 로 변환한 값을 반환해야함
    scriptDir = Path(__file__).parent
    simContentsPath = scriptDir / "resources/sim_contents.json"
    return SimDescription.fromJsonFile(str(simContentsPath), dt=1e-3)

def main():
    """
    메인 스레드: ServerThread와 SimLoopThread를 관리
    - 버퍼를 생성하고 소유
    - 설정 파일에서 서버 설정 로드
    - 각 스레드에 버퍼와 콜백 전달
    - 스레드가 죽으면 재시작
    - 예외 처리 및 우아한 종료
    """

    # 작업 디렉토리 확인 (PyChrono 한글 경로 이슈로 인해 sim_server에서만 실행 가능)
    scriptDir = Path(__file__).parent
    currentDir = Path.cwd()
    if scriptDir.resolve() != currentDir.resolve():
        print(f"[main] 오류: sim_server 디렉토리에서 실행해야 합니다.", flush=True)
        print(f"[main] 현재 작업 디렉토리: {currentDir}", flush=True)
        print(f"[main] 필요한 디렉토리: {scriptDir}", flush=True)
        print(f"[main] 다음 명령어로 실행하세요:", flush=True)
        print(f"[main]   cd {scriptDir}", flush=True)
        print(f"[main]   python main.py", flush=True)
        return

    # 서버 설정 로드
    print("[main] 서버 설정 로드 중...", flush=True)
    serverConfig = loadServerConfig()
    print(f"[main] 서버 설정 로드: {serverConfig.toDict()}", flush=True)

    # 시뮬레이션 설명 정보 로드 (CAD 데이터 파싱 목업)
    print("[main] CAD 데이터 파싱 중...", flush=True)
    simDescription = parseCadData()
    print("[main] CAD 데이터 파싱 완료", flush=True)

    print("[main] 시뮬레이션 빌드 중...", flush=True)
    sim = buildSimulation(simDescription) # 버퍼는 sim.modelState 사용
    print("[main] 시뮬레이션 빌드 완료", flush=True)

    print("[main] 서버 빌드 중...", flush=True)
    server = buildServer(serverConfig)    # 버퍼는 server.userInput 사용
    print("[main] 서버 빌드 완료", flush=True)
    # TODO: Simulation객체 자체가 유효한 시뮬스레드를 판단하는기준.(?) 시뮬레이션 객체는 싱글톤이어야 함.

    # 스레드 참조
    serverThread = None
    simLoopThread = None

    print("[main] CADverse 시뮬레이션 서버 시작", flush=True)
    try:
        # 메인 루프 (외부 try: KeyboardInterrupt 처리)
        while True:
            try: # 내부 try: 개별 반복의 예외 처리

                # ServerThread 상태 체크 및 재시작
                if serverThread is None or not serverThread.is_alive():
                    if serverThread is not None:
                        print("[main] 서버 스레드가 종료됨. 재시작 중...", flush=True)

                    # 서버 스레드 생성 (config와 콜백 전달)
                    print("[main] 서버 스레드 생성 중...", flush=True)
                    serverThread = LoopThread(
                        initFn = lambda: ServerRunner(server, sim.modelState.getReadAccess(doDeepCopy=False)),
                        loopFn = lambda runner: runner.runOneCycle(),
                        clearFn = lambda runner: runner.clear(),
                    )
                    print("[main] 서버 스레드 시작 중...", flush=True)
                    serverThread.start()
                    print(f"[main] 서버 스레드 시작됨 (http://{serverConfig.host}:{serverConfig.port})", flush=True)

                # SimLoopThread 상태 체크 및 재시작
                if simLoopThread is None or not simLoopThread.is_alive():
                    if simLoopThread is not None:
                        print("[main] 시뮬레이션 스레드가 종료됨. 재시작 중...", flush=True)

                    print("[main] 시뮬레이션 스레드 생성 중...", flush=True)
                    simLoopThread = LoopThread(
                        initFn = lambda: Simulator(sim, server.userInput.getReadAccess(doDeepCopy=False)),
                        loopFn = lambda simulator: simulator.step(),
                        clearFn = lambda simulator: simulator.clear(),
                    )
                    print("[main] 시뮬레이션 스레드 시작 중...", flush=True)
                    simLoopThread.start()
                    print("[main] 시뮬레이션 스레드 시작됨", flush=True)

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
        cleanup(serverThread, simLoopThread)


if __name__ == "__main__":
    main()
