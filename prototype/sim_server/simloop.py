import time
import threading
from typing import Dict, Any

from sim_server.utils.OwnedBuffer import OwnedBuffer


def runSimloop(modelDescription: Dict[str, Any],
               outputBuffer: OwnedBuffer,
               stopEvent: threading.Event):
    """
    시뮬레이션 루프 실행 함수
    모델 상태를 업데이트하며, 버퍼를 통해 서버에 상태를 전달

    Args:
        modelDescription: 모델 설명 정보
        outputBuffer: 시뮬레이션 출력 버퍼
        stopEvent: 종료 신호를 위한 이벤트
    """
    print("시뮬레이션 루프 시작")

    while not stopEvent.is_set():
        try:
            # TODO: 입력버퍼 읽어오기
            # input_data = input_buffer.readBuff()

            # TODO: 입력과 이전상태 -> 다음상태 계산
            # 여기서 PyChrono 시뮬레이션 스텝 실행
            # new_state = simulate_step(input_data)

            # 임시: 테스트 데이터 생성
            testState = {
                "model_1": {
                    "position": {"x": time.time() % 10, "y": 0.0, "z": 0.0},
                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
                }
            }

            # 결과를 출력버퍼에 쓰기
            outputBuffer.commit(testState)

            # 시뮬레이션 주기 (예: 60 FPS = 16.67ms)
            time.sleep(0.0167)

        except Exception as e:
            print(f"시뮬레이션 루프 오류: {e}")
            import traceback
            traceback.print_exc()

    print("시뮬레이션 루프 종료")


class SimLoopThread(threading.Thread):
    """
    시뮬레이션 루프를 별도 스레드에서 실행하는 스레드
    runSimloop() 함수를 스레드에서 실행하는 래퍼
    """

    def __init__(self, modelDescription: Dict[str, Any], outputBuffer: OwnedBuffer):
        super().__init__(daemon=True)

        self.modelDescription = modelDescription
        self.outputBuffer = outputBuffer

        # 종료 이벤트
        self._stopEvent = threading.Event()

    def run(self):
        """스레드에서 실행될 시뮬레이션 루프"""
        try:
            runSimloop(
                modelDescription=self.modelDescription,
                outputBuffer=self.outputBuffer,
                stopEvent=self._stopEvent
            )
        except Exception as e:
            print(f"시뮬레이션 스레드 오류: {e}")
            import traceback
            traceback.print_exc()

    def stop(self):
        """스레드 정지"""
        self._stopEvent.set()
