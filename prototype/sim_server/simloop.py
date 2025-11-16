import time
import threading
import sys
from pathlib import Path
from typing import Dict, Any

# 상위 디렉토리를 import path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.ReadWriteBuffer import ReadWriteBuffer


def run_simloop(model_description: Dict[str, Any],
                output_buffer: ReadWriteBuffer,
                stop_event: threading.Event):
    """
    시뮬레이션 루프 실행 함수
    모델 상태를 업데이트하며, 버퍼를 통해 서버에 상태를 전달

    Args:
        model_description: 모델 설명 정보
        output_buffer: 시뮬레이션 출력 버퍼
        stop_event: 종료 신호를 위한 이벤트
    """
    print("시뮬레이션 루프 시작")

    while not stop_event.is_set():
        try:
            # TODO: 입력버퍼 읽어오기
            # input_data = input_buffer.readBuff()

            # TODO: 입력과 이전상태 -> 다음상태 계산
            # 여기서 PyChrono 시뮬레이션 스텝 실행
            # new_state = simulate_step(input_data)

            # 임시: 테스트 데이터 생성
            test_state = {
                "model_1": {
                    "position": {"x": time.time() % 10, "y": 0.0, "z": 0.0},
                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
                }
            }

            # 결과를 출력버퍼에 쓰기 (컨텍스트 매니저 사용)
            with output_buffer as mutable_buff:
                # mutable_buff 업데이트
                mutable_buff.clear()
                mutable_buff.update(test_state)
                # with 블록을 벗어나면 자동으로 commit됨

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
    run_simloop() 함수를 스레드에서 실행하는 래퍼
    """

    def __init__(self, modelDescriptipon: Dict[str, Any], OutputBuffer: ReadWriteBuffer):
        super().__init__(daemon=True)

        self.model_description = modelDescriptipon
        self.output_buffer = OutputBuffer

        # 종료 이벤트
        self._stop_event = threading.Event()

    def run(self):
        """스레드에서 실행될 시뮬레이션 루프"""
        try:
            run_simloop(
                model_description=self.model_description,
                output_buffer=self.output_buffer,
                stop_event=self._stop_event
            )
        except Exception as e:
            print(f"시뮬레이션 스레드 오류: {e}")
            import traceback
            traceback.print_exc()

    def stop(self):
        """스레드 정지"""
        self._stop_event.set()
