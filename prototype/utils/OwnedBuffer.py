import threading
import copy
from utils.customTypes import Indexable

class OwnedBuffer:
    def __init__(self, initialBuff: Indexable):
        self._buff = initialBuff
        self._ownership = threading.Lock()
        self._commitLock = threading.Lock()
        self.readonly = lambda: copy.deepcopy(self._buff) # 전부 필요할 때
        self.readRef = lambda key: self._buff[key]        # 하나씩 접근할 때
        def commit(newBuff: Indexable):
            with self._commitLock:
                self._buff = newBuff
        self.commit = commit

    def __enter__(self):
        self._ownership.acquire()
        return (self.commit,self.readRef)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._ownership.release()
        return False
