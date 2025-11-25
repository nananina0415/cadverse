import threading
import traceback
from typing import Callable, TypeVar, Optional

T = TypeVar('T')


class LoopThread(threading.Thread):
    """
    초기화 함수로 객체를 생성하고, 루프 함수를 반복 실행하는 스레드

    사용 예:
        thread = LoopThread(
            initFn=lambda: MyObject(),
            loopFn=lambda obj: obj.step(),
            clearFn=lambda obj: obj.clear()
        )
        thread.start()
    """

    def __init__(
        self,
        initFn: Callable[[], T],
        loopFn: Callable[[T], None],
        clearFn: Optional[Callable[[T], None]] = None,
        daemon: bool = False
    ):
        """
        Args:
            initFn: 스레드 시작 시 호출되어 객체를 생성하는 함수
            loopFn: 반복 실행할 함수 (initFn이 반환한 객체를 인자로 받음)
            clearFn: 스레드 종료 시 정리 함수 (선택적)
            daemon: 데몬 스레드 여부
        """
        super().__init__(daemon=daemon)
        self.initFn = initFn
        self.loopFn = loopFn
        self.clearFn = clearFn
        self._stopFlag = threading.Event()
        self._startFlag = threading.Event()

    def run(self):
        """스레드 실행"""
        obj = None
        try:
            # 초기화
            obj = self.initFn()
            self._startFlag.set()

            # 루프 실행
            while not self._stopFlag.is_set():
                self.loopFn(obj)

        except Exception as e:
            print(f"[LoopThread] 에러 발생: {e}")
            traceback.print_exc()
        finally:
            # 정리
            if obj is not None and self.clearFn is not None:
                try:
                    self.clearFn(obj)
                except Exception as e:
                    print(f"[LoopThread] 정리 중 에러: {e}")
                    traceback.print_exc()

    def stop(self):
        """스레드 중지"""
        self._stopFlag.set()

    def waitStartEvent(self):
        """스레드가 시작될 때까지 대기"""
        self._startFlag.wait()

    def wait_stopped(self):
        """스레드가 완전히 종료될 때까지 대기"""
        self.join()
