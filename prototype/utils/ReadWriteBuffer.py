import threading 
import copy 
from typing import Dict, Any, Optional, TypeVar, Hashable

BuffKey = TypeVar('BuffKey', bound=Hashable)
FrozenAndNotNested = TypeVar('FrozenAndNotNested', bound=Hashable)
BuffType = TypeVar('BuffType', bound=Dict[BuffKey, FrozenAndNotNested])

class ReadWriteBuffer:
    
    _readonlyBuff: BuffType
    _mutableBuff: BuffType
    _commitLock: threading.RLock
    
    def __init__(self, initialState: Optional[BuffType] = None) -> None:
        if initialState is None:
            initialState = {}
        self._readonlyBuff = copy.deepcopy(initialState) 
        self._mutableBuff = copy.deepcopy(initialState)
        self._commitLock = threading.Lock()
    
    def commit(self) -> None:
        with self._commitLock:
            self._readonlyBuff = self._mutableBuff 
            self._mutableBuff = self._readonlyBuff.copy()
    
    def readBuff(self) -> Dict[str, Any]:
        return self._readonlyBuff
    
    def __enter__(self) -> 'ReadWriteBuffer':
        self._commitLock.acquire()
        return self._mutableBuff
    
    def __exit__(self, excType, excVal, excTb) -> None:
        try:
            if excType is None:
                self.commit()
        finally:
            self._commitLock.release()
    

    