import threading
import traceback

# TODO: 문서화, 타입힌트, 테스트작성, (메트릭로깅&프로파일링)

class LoopThread(threading.Thread):
    def __init__(self, target, args=(), kwargs=None, cleanup=None, daemon=False):
        super().__init__(daemon=daemon)
        self.target = target
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}
        self.cleanup = cleanup  # 종료 시 실행할 callback
        self._stopFlag = threading.Event()
        self._startFlag = threading.Event()

    def run(self):
        self._startFlag.set()
        try:
            while not self._stopFlag.is_set():
                self.target(*self.args, **self.kwargs)
        except Exception:
            traceback.print_exc()
        finally:
            if self.cleanup:
                try:
                    self.cleanup()
                except Exception:
                    traceback.print_exc()

    def stop(self):
        self._stopFlag.set()

    def waitStartEvent(self):
        self._startFlag.wait()

    def wait_stopped(self):
        self.join()
