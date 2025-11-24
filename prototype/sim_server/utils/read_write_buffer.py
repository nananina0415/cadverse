import struct
import threading
import time
from typing import TypeVar, Generic, List, Iterator, Callable, Tuple

T = TypeVar('T')

class ReadWriteBuffer(Generic[T]):
    """
    모든 타입 T에 대해 작동하는 스레드 안전한 배치 스트리밍 버퍼
    """
    def __init__(self, initialData: List[T] = None):
        self._buff: List[T] = initialData if initialData is not None else []

    def commit(self, new_data: List[T]) -> None:
        """[Write Thread] 데이터 교체 (Atomic)"""
        self._buff = new_data

    def getReadAccess(self,
                      serializerFn: Callable[[T], bytes],
                      batchSize: int = 1) -> Iterator[bytes]:
        def getLatestSerialStream() -> Iterator[bytes]:
            """
            [Read Thread]
            스냅샷을 뜨고, 'serializerFn'으로 T를 직렬화
            batchSize만큼 모이면 yield
            """
            # [Snapshot] 참조 획득 (데이터 생존 보장)
            snapshot = self._buff
            if not snapshot:
                return

            batchBuffer = bytearray()
            count = 0

            # 데이터 순회
            for item in snapshot:
                # [Injection] 외부에서 주입된 직렬화 함수 실행
                # T 타입의 item을 bytes로 변환
                serializedData = serializerFn(item)

                batchBuffer.extend(serializedData)
                count += 1

                # 배치 전송
                if count >= batchSize:
                    yield batchBuffer
                    batchBuffer = bytearray()
                    count = 0

            # 잔여 데이터 전송
            if batchBuffer:
                yield batchBuffer
        return getLatestSerialStream


if __name__ == "__main__":
    # --- [사용 예시] 구체적인 상황 적용 ---

    # 가상의 Chrono 데이터 타입 정의 (Tuple 사용 예시)
    # T = Tuple[MockVector, MockQuaternion]
    class MockVector:
        def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
    class MockQuaternion:
        def __init__(self, e0, e1, e2, e3): self.e0, self.e1, self.e2, self.e3 = e0, e1, e2, e3

    # 1. 직렬화 전략 정의 (Strategy Pattern)
    # 이 함수가 T를 어떻게 bytes로 바꿀지 결정합니다.
    # 미리 컴파일된 struct 객체를 사용하여 성능 최적화
    _chrono_packer = struct.Struct('<7d') # double 7개

    def chrono_serializer(item: Tuple[MockVector, MockQuaternion]) -> bytes:
        pos, rot = item
        return _chrono_packer.pack(pos.x, pos.y, pos.z,
                                rot.e0, rot.e1, rot.e2, rot.e3)

    # 2. 버퍼 인스턴스 생성 (구체적 타입 명시)
    # 타입 힌트: 이 버퍼는 (Vector, Quaternion) 튜플을 담는다.
    buffer = ReadWriteBuffer[Tuple[MockVector, MockQuaternion]]()

    def simulation_thread(prevStateBuffer: ReadWriteBuffer[Tuple[MockVector, MockQuaternion]]):
        while True:
            # 시뮬레이션 데이터 생성 (T 타입의 리스트)
            new_frame = []
            for _ in range(1000):
                new_frame.append((
                    MockVector(1.0, 2.0, 3.0),
                    MockQuaternion(1, 0, 0, 0)
                ))

            # 커밋
            prevStateBuffer.commit(new_frame)
            time.sleep(0.01)

    def server_thread(getLatestSerialStream):
        while True:
            # 스트리밍 요청 시 '어떻게 직렬화할지' 함수를 같이 넘깁니다.
            # 이렇게 하면 버퍼 클래스는 PyChrono를 몰라도 됩니다.
            stream = getLatestSerialStream()
            i=0
            data_available = False
            for chunk in stream:
                data_available = True
                # socket.sendall(chunk)
                print(f"[Server] {len(chunk)} bytes sent {i}")
                i += 1
            if not data_available:
                time.sleep(0.001)

    # 실행
    t1 = threading.Thread(target=simulation_thread, args=(buffer,), daemon=True)
    t2 = threading.Thread(target=server_thread, args=(buffer.getReadAccess(serializerFn=chrono_serializer,batchSize=100),), daemon=True)
    t1.start()
    t2.start()

    while True: time.sleep(1)
