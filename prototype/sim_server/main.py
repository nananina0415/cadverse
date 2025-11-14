import time
import sys
from pathlib import Path

# 상위 디렉토리를 import path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.ReadWriteBuffer import ReadWriteBuffer
from sim_server.server import ServerThread
from sim_server.simloop import SimLoopThread


def cleanup(server_thread, sim_thread):
    """
    프로그램 종료 시 리소스 정리
    - 스레드 안전하게 종료
    - 리소스 해제
    """
    print("\n정리 작업 시작...")

    # 시뮬레이션 스레드 중지
    if sim_thread and sim_thread.is_alive():
        print("시뮬레이션 스레드 중지 중...")
        if hasattr(sim_thread, 'stop'):
            sim_thread.stop()
        sim_thread.join(timeout=5)

        if sim_thread.is_alive():
            print("경고: 시뮬레이션 스레드가 5초 내에 종료되지 않음")

    # 서버 스레드 중지
    if server_thread and server_thread.is_alive():
        print("서버 스레드 중지 중...")
        # 데몬 스레드이므로 메인이 종료되면 자동 종료됨
        # 하지만 명시적으로 정리 시도
        server_thread.join(timeout=2)

        if server_thread.is_alive():
            print("경고: 서버 스레드가 2초 내에 종료되지 않음 (데몬 스레드)")

    print("정리 완료.")


def main():
    """
    메인 스레드: ServerThread와 SimLoopThread를 관리
    - 버퍼를 생성하고 소유
    - 각 스레드에 버퍼 참조를 전달
    - 스레드가 죽으면 재시작
    - 예외 처리 및 우아한 종료
    """

    # 입출력 버퍼 생성 (메인이 소유)
    output_buffer = ReadWriteBuffer()

    # TODO: 실제 모델 description 데이터 로드
    model_description = {}

    # 스레드 참조
    server_thread = None
    sim_thread = None

    print("CADverse 시뮬레이션 서버 시작")

    try:
        # 메인 루프 (외부 try: KeyboardInterrupt 처리)
        while True:
            try:
                # 내부 try: 개별 반복의 예외 처리

                # ServerThread 상태 체크 및 재시작
                if server_thread is None or not server_thread.is_alive():
                    if server_thread is not None:
                        print("서버 스레드가 종료됨. 재시작 중...")

                    server_thread = ServerThread(
                        output_buffer=output_buffer,
                        resources_dir="./resources",
                        host="0.0.0.0",
                        port=8000
                    )
                    server_thread.start()
                    print(f"서버 스레드 시작됨 (http://0.0.0.0:8000)")

                # SimLoopThread 상태 체크 및 재시작
                if sim_thread is None or not sim_thread.is_alive():
                    if sim_thread is not None:
                        print("시뮬레이션 스레드가 종료됨. 재시작 중...")

                    sim_thread = SimLoopThread(
                        modelDescriptipon=model_description,
                        OutputBuffer=output_buffer
                    )
                    sim_thread.start()
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
        cleanup(server_thread, sim_thread)


if __name__ == "__main__":
    main()
