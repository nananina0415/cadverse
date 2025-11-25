import copy
from typing import TypeVar, Generic, List, Optional, Callable

T = TypeVar('T')

# TODO: 한 시뮬스레드만이 버퍼에 쓸 수 있도록 제한하는 기능 추가

class ReadWriteBuffer(Generic[T]):
    """
    모든 타입 T에 대해 작동하는 스레드 안전한 배치 스트리밍 버퍼
    """
    def __init__(self, initialData: Optional[List[T]] = None):
        self._buff: List[T] = initialData if initialData is not None else []

    def commit(self, new_data: List[T]) -> None:
        """[Write Thread] 데이터 교체 (Atomic)"""
        self._buff = new_data

    def getReadAccess(self, doDeepCopy: bool = True) -> Callable[[],List[T]]:
        """
        버퍼 데이터 읽기

        Args:
            doDeepCopy: True면 deepcopy 수행, False면 참조 반환

        Returns:
            버퍼의 데이터 리스트
        """
        if doDeepCopy:
            return lambda: copy.deepcopy(self._buff)
        else:
            return lambda: self._buff

