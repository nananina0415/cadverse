import time
import threading
from typing import TYPE_CHECKING, Dict, Any

from ..utils.ReadWriteBuffer import ReadWriteBuffer

# 순환 참조를 피하기 위해 타입 힌트만 임포트
if TYPE_CHECKING:
    from server import Server


class SimLoopThread(threading.Thread):
    """
    모델 상태를 소유하고 업데이트하며,
    버퍼를 통해 서버에 상태를 전달하는 스레드.
    """

    def __init__(self, modelDescriptipon: Dict[str, Any], OutputBuffer: ReadWriteBuffer) -> None:
        super().__init__(daemon=True)

        self.model_description = modelDescriptipon
        self.output_buffer = OutputBuffer

        # 스레드 실행 플래그
        self._running = True

        # TODO: 추후에 입출력버퍼 참조를 직접 받아오는게 아니라 입출력 버퍼에 접근할 수 있는 키를 받아오게끔 해야 함.
        #       이 키는 싱글톤으로서 프로세스 내에 유일하고 새 시뮬스레드가 만들어질 때 필수적으로 필요하므로
        #       버퍼에 접근할 수 있는 시뮬스레드가 하나이도록 보장.
        #       다만 지금은 프로토타입 제작이므로 새 시뮬생성 로직이 없으므로 패스.

    def run(self) -> None:
        """스레드에서 실행될 메인 시뮬레이션 루프"""

        print("시뮬레이션 루프 시작")

        while self._running:
            try:
                # TODO: 입력버퍼 읽어오기
                # input_data = self.input_buffer.readBuff()

                # TODO: 입력과 이전상태 -> 다음상태 계산
                # 여기서 PyChrono 시뮬레이션 스텝 실행
                # new_state = self.simulate_step(input_data)

                # 임시: 테스트 데이터 생성
                test_state = {
                    "model_1": {
                        "position": {"x": time.time() % 10, "y": 0.0, "z": 0.0},
                        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
                    }
                }

                # 결과를 출력버퍼에 쓰기 (컨텍스트 매니저 사용)
                with self.output_buffer as mutable_buff:
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

    def stop(self) -> None:
        """스레드 정지"""
        self._running = False
