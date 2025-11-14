import time
import sys
from pathlib import Path

# 상위 디렉토리를 import path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.ReadWriteBuffer import ReadWriteBuffer
from sim_server.server import ServerThread
from sim_server.simloop import SimLoopThread


def main():
    """
    메인 스레드: ServerThread와 SimLoopThread를 관리
    - 버퍼를 생성하고 소유
    - 각 스레드에 버퍼 참조를 전달
    - 스레드가 죽으면 재시작
    """

    # 입출력 버퍼 생성 (메인이 소유)
    output_buffer = ReadWriteBuffer()

    # TODO: 실제 모델 description 데이터 로드
    model_description = {}

    # 스레드 생성
    server_thread = None
    sim_thread = None

    print("CADverse 시뮬레이션 서버 시작")

    try:
        while True:
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
                print("서버 스레드 시작됨")

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

    except KeyboardInterrupt:
        print("\n서버 종료 중...")
        # 스레드 정리
        if sim_thread and hasattr(sim_thread, 'stop'):
            sim_thread.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
