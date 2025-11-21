import threading
import copy
from sim_server.utils.customTypes import Indexable

class OwnedBuffer:
    def __init__(self, initialBuff: Indexable):
        self._buff = initialBuff
        self._ownership = threading.Lock()
        self._commitLock = threading.Lock()

        def commit(newBuff: Indexable):
            with self._commitLock:
                self._buff = newBuff
        self.commit = commit

    def __enter__(self):
        self._ownership.acquire()
        return (self.commit,self._readRef)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._ownership.release()
        return False

    # 전부 필요할 때 사용
    def readonly(self):
        cp = None
        with self._commitLock:
            cp =  copy.deepcopy(self._buff)
        return cp

    # 하나씩 접근할 때 사용
    # 내부 함수임. 밖에서 사용 금지
    # 만약 오너가 쓰기 중이면 데이터가 깨질 위험 있음
    # 내부에서도 오너락을 잡은 상태에서 호출돼야 함
    def _readRef(self, key):
        return self._buff[key]
