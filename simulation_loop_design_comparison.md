# 시뮬레이션 루프 설계 시안 비교 분석

## 평가 기준 (중요도 순)

1. **성능**: 심루프가 최대한 멈춤없이 다음 계산에 돌입할 것
2. **가독성**: 로직이 직관적이고 간결하여 읽고 이해하기 쉬울 것
3. **결정성**: 부수효과가 없고 코드 자체로 결정적일 것

---

## 시안 1: Generator Yield + 외부 Write

```python
def simulate(stateBuff, inputBuff):
    while True:
        state = stateBuff.read()  # deepcopy
        input = inputBuff.read()
        # ...계산 로직...
        yield result

state = SingleBuffer(buffSize, initialState)
input = SingleBuffer(buffSize)
output = SingleBuffer(buffSize)

for result in simulate(state, input):
    output.write(result)  # deepcopy
```

**장점:**
- Generator로 제어 흐름이 명확
- 외부에서 output 제어 가능
- 테스트 시 결과만 수집 가능

**단점:**
- `for` 루프에서 `output.write()` 호출 시 메인 스레드 블로킹 가능
- deepcopy 2회 (read + write)
- yield 오버헤드

**평가:**
- 성능: ⭐⭐ (yield 오버헤드, deepcopy 2회)
- 가독성: ⭐⭐⭐⭐ (generator 패턴 직관적)
- 결정성: ⭐⭐⭐⭐ (부수효과 없음, 순수 함수)

---

## 시안 2: 콜백으로 OutputBuff 전달 + 내부 Write

```python
def simulate(stateBuff, inputBuff, outputBuff):
    while True:
        state = stateBuff.read()
        input = inputBuff.read()
        # ...계산 로직...
        outputBuff.write(result)

state = SingleBuffer(buffSize, initialState)
input = SingleBuffer(buffSize)
output = SingleBuffer(buffSize)

simulate(state, input, output)  # 블로킹
```

**장점:**
- 함수 내부에서 모든 처리
- 별도 스레드에서 실행 시 간단

**단점:**
- outputBuff에 직접 의존 (결합도 증가)
- 테스트 시 mock buffer 필요
- 부수효과 있음 (write)

**평가:**
- 성능: ⭐⭐⭐ (직접 write, yield 오버헤드 없음)
- 가독성: ⭐⭐⭐ (명확하지만 부수효과로 인해 추적 어려움)
- 결정성: ⭐⭐ (부수효과 있음)

---

## 시안 3: 순수 함수형 (버퍼 없이 값 반환)

```python
def simulate_step(prev_state: dict, input: dict) -> dict:
    # ...계산 로직...
    return next_state

# 외부 루프
state = initial_state
while True:
    input = inputBuff.read()
    state = simulate_step(state, input)
    outputBuff.write(state)
```

**장점:**
- 완전한 순수 함수 (테스트 용이)
- 부수효과 전혀 없음
- 함수형 프로그래밍 원칙 준수

**단점:**
- 외부에서 루프 관리 필요
- 상태 관리가 외부에 노출됨

**평가:**
- 성능: ⭐⭐⭐⭐ (오버헤드 최소)
- 가독성: ⭐⭐⭐⭐⭐ (순수 함수, 가장 이해하기 쉬움)
- 결정성: ⭐⭐⭐⭐⭐ (완전한 순수 함수)

---

## 시안 4: Double Buffering (현재 ReadWriteBuffer 패턴)

```python
def simulate(stateBuff, inputBuff, outputBuff: ReadWriteBuffer):
    while True:
        state = stateBuff.read()
        input = inputBuff.read()
        # ...계산 로직...

        with outputBuff as mutable:
            mutable.clear()
            mutable.update(result)
        # commit 자동 호출

state = ReadWriteBuffer(initialState)
input = ReadWriteBuffer()
output = ReadWriteBuffer()

# 별도 스레드에서 실행
thread = Thread(target=simulate, args=(state, input, output))
```

**장점:**
- Lock을 최소화 (commit 시점만)
- Context manager로 안전한 동기화
- 읽기는 lock 없이 가능

**단점:**
- 여전히 shallow copy 발생
- 버퍼 크기 고정 불가능 (dict)

**평가:**
- 성능: ⭐⭐⭐⭐ (lock 최소화, 읽기 성능 우수)
- 가독성: ⭐⭐⭐ (context manager 패턴 이해 필요)
- 결정성: ⭐⭐⭐ (lock으로 동기화됨)

---

## 시안 5: Lock-Free Ring Buffer

```python
class RingBuffer:
    def __init__(self, size=3):
        self.buffer = [None] * size
        self.write_idx = 0
        self.read_idx = 0

    def write(self, data):
        self.buffer[self.write_idx] = data
        self.write_idx = (self.write_idx + 1) % len(self.buffer)

    def read(self):
        data = self.buffer[self.read_idx]
        self.read_idx = (self.read_idx + 1) % len(self.buffer)
        return data

def simulate(inputRing, outputRing):
    while True:
        input = inputRing.read()
        # ...계산 로직...
        outputRing.write(result)
```

**장점:**
- Lock-free 설계로 성능 최상
- 오래된 데이터 자동 덮어쓰기

**단점:**
- Race condition 가능 (Python GIL로 일부 완화)
- 데이터 유실 가능
- 복잡도 증가

**평가:**
- 성능: ⭐⭐⭐⭐⭐ (lock 없음, 최고 성능)
- 가독성: ⭐⭐ (동시성 이슈로 이해 어려움)
- 결정성: ⭐ (race condition 가능)

---

## 시안 6: Producer-Consumer Queue

```python
from queue import Queue

def simulate(input_queue: Queue, output_queue: Queue):
    while True:
        input = input_queue.get()  # blocking
        # ...계산 로직...
        output_queue.put(result)

input_q = Queue(maxsize=1)
output_q = Queue(maxsize=1)

# Producer
input_q.put(user_input)

# Consumer
result = output_q.get()
```

**장점:**
- 표준 라이브러리 사용
- Thread-safe 보장
- Backpressure 자동 처리

**단점:**
- `get()` 호출 시 blocking (성능 저하)
- maxsize=1이면 오래된 데이터 못 버림

**평가:**
- 성능: ⭐⭐ (blocking으로 인한 대기 시간)
- 가독성: ⭐⭐⭐⭐ (Queue 패턴 널리 알려짐)
- 결정성: ⭐⭐⭐⭐ (thread-safe 보장)

---

## 시안 7: Async/Await Pattern

```python
import asyncio

async def simulate(state, input_stream):
    async for input in input_stream:
        # ...계산 로직...
        yield result

async def run():
    state = initial_state
    async for result in simulate(state, input_stream):
        await output_writer.write(result)

asyncio.run(run())
```

**장점:**
- Non-blocking I/O
- 모던 Python 패턴
- 다른 비동기 작업과 통합 용이

**단점:**
- CPU-bound 작업에는 부적합 (시뮬레이션은 CPU-bound)
- 기존 동기 코드와 통합 어려움
- 복잡도 증가

**평가:**
- 성능: ⭐⭐ (CPU-bound 작업에 비효율적)
- 가독성: ⭐⭐⭐ (async/await 이해 필요)
- 결정성: ⭐⭐⭐ (비동기 실행 순서 예측 어려움)

---

## 시안 8: Shared Memory (multiprocessing)

```python
from multiprocessing import shared_memory, Process
import numpy as np

def simulate(shm_name, stop_event):
    shm = shared_memory.SharedMemory(name=shm_name)
    arr = np.ndarray((100,), dtype=np.float64, buffer=shm.buf)

    while not stop_event.is_set():
        # arr 직접 수정
        arr[0] = compute()

shm = shared_memory.SharedMemory(create=True, size=800)
p = Process(target=simulate, args=(shm.name, stop_event))
```

**장점:**
- 진짜 병렬 처리 (GIL 우회)
- Zero-copy (메모리 공유)

**단점:**
- 프로세스 생성 오버헤드
- 동기화 복잡도 매우 높음
- 디버깅 어려움
- 데이터 구조 제약 (numpy array 등)

**평가:**
- 성능: ⭐⭐⭐⭐⭐ (GIL 우회, zero-copy)
- 가독성: ⭐ (매우 복잡)
- 결정성: ⭐ (동기화 이슈 많음)

---

## 시안 9: Immutable Data + 함수형

```python
from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class State:
    position: Tuple[float, float, float]
    velocity: Tuple[float, float, float]

def simulate_step(state: State, input: Input) -> State:
    # 새로운 State 객체 반환 (불변)
    return State(
        position=new_position,
        velocity=new_velocity
    )

# 외부 루프
state = initial_state
while True:
    input = get_input()
    state = simulate_step(state, input)  # 새 객체 생성
    send_output(state)
```

**장점:**
- 완전한 불변성 (side-effect 없음)
- Thread-safe (데이터 공유 안전)
- 테스트 매우 용이

**단점:**
- 매 스텝마다 객체 생성 (메모리 할당)
- GC 압력 증가
- 큰 상태에서 비효율적

**평가:**
- 성능: ⭐⭐ (객체 생성 오버헤드)
- 가독성: ⭐⭐⭐⭐⭐ (불변성으로 추론 용이)
- 결정성: ⭐⭐⭐⭐⭐ (완전한 불변성)

---

## 시안 10: Triple Buffering

```python
class TripleBuffer:
    def __init__(self):
        self.buffers = [None, None, None]
        self.write_idx = 0
        self.ready_idx = 1
        self.read_idx = 2
        self.lock = Lock()

    def swap_write(self):
        with self.lock:
            self.write_idx, self.ready_idx = self.ready_idx, self.write_idx

    def swap_read(self):
        with self.lock:
            self.read_idx, self.ready_idx = self.ready_idx, self.read_idx

def simulate(input_buff: TripleBuffer, output_buff: TripleBuffer):
    while True:
        # Write buffer에 작성
        output_buff.buffers[output_buff.write_idx] = compute()
        output_buff.swap_write()
```

**장점:**
- Writer와 Reader가 거의 동시에 작업 가능
- Frame drop 최소화
- 게임/그래픽스에서 검증된 패턴

**단점:**
- 메모리 3배 사용
- Swap 타이밍 관리 복잡
- Python에서는 GIL로 인해 이점 제한적

**평가:**
- 성능: ⭐⭐⭐⭐ (동시 읽기/쓰기 가능)
- 가독성: ⭐⭐ (swap 로직 이해 필요)
- 결정성: ⭐⭐⭐ (lock으로 동기화)

---

## 종합 비교표

| 시안 | 성능 | 가독성 | 결정성 | 총점 | 추천도 |
|------|------|--------|--------|------|--------|
| 1. Generator Yield | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 10 | ⭐⭐⭐ |
| 2. 콜백 + 내부 Write | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | 8 | ⭐⭐ |
| **3. 순수 함수형** | **⭐⭐⭐⭐** | **⭐⭐⭐⭐⭐** | **⭐⭐⭐⭐⭐** | **14** | **⭐⭐⭐⭐⭐** |
| **4. Double Buffering (현재)** | **⭐⭐⭐⭐** | **⭐⭐⭐** | **⭐⭐⭐** | **10** | **⭐⭐⭐⭐** |
| 5. Lock-Free Ring | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | 8 | ⭐⭐ |
| 6. Queue Pattern | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 10 | ⭐⭐⭐ |
| 7. Async/Await | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | 8 | ⭐⭐ |
| 8. Shared Memory | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | 7 | ⭐ |
| 9. Immutable Data | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 12 | ⭐⭐⭐⭐ |
| 10. Triple Buffering | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | 9 | ⭐⭐⭐ |

---

## 추천 순위

### 🥇 1위: 시안 3 - 순수 함수형 패턴

```python
def simulate_step(prev_state: dict, input: dict) -> dict:
    """
    순수 함수: 이전 상태 + 입력 → 다음 상태
    부수효과 없음, 테스트 용이, 예측 가능
    """
    # PyChrono 시뮬레이션 스텝
    new_state = physics_engine.step(prev_state, input)
    return new_state

# 외부 루프 (별도 스레드)
def run_simulation_loop(input_buffer, output_buffer, stop_event):
    state = initial_state
    while not stop_event.is_set():
        input_data = input_buffer.readBuff()
        state = simulate_step(state, input_data)

        with output_buffer as mutable:
            mutable.clear()
            mutable.update(state)
```

**선정 이유:**
- ✅ 성능: 오버헤드 최소, 계산 로직에만 집중
- ✅ 가독성: 순수 함수로 가장 이해하기 쉬움
- ✅ 결정성: 부수효과 전혀 없음, 테스트 매우 용이
- ✅ 유지보수: 시뮬레이션 로직과 I/O 로직 완전 분리

---

### 🥈 2위: 시안 4 - Double Buffering (현재 패턴 유지)

```python
def simulate(input_buff: ReadWriteBuffer, output_buff: ReadWriteBuffer):
    state = initial_state
    while True:
        input_data = input_buff.readBuff()  # lock 없음

        # 계산
        state = compute_next_state(state, input_data)

        # 출력 (commit 시에만 lock)
        with output_buff as mutable:
            mutable.clear()
            mutable.update(state)
```

**선정 이유:**
- ✅ 성능: Lock 최소화, 읽기 성능 우수
- ✅ 실전: 이미 구현되어 있고 검증됨
- ⚠️ 가독성: Context manager 이해 필요하지만 Python스럽다

---

### 🥉 3위: 시안 9 - Immutable Data

```python
@dataclass(frozen=True)
class SimState:
    positions: Tuple[Tuple[float, float, float], ...]
    velocities: Tuple[Tuple[float, float, float], ...]
    timestamp: float

def simulate_step(state: SimState, input: Input) -> SimState:
    # 새로운 불변 상태 반환
    return SimState(
        positions=new_positions,
        velocities=new_velocities,
        timestamp=time.time()
    )
```

**선정 이유:**
- ✅ 결정성: 완전한 불변성
- ✅ 가독성: 함수형 프로그래밍 패러다임
- ⚠️ 성능: 작은 상태에서는 괜찮으나, 큰 상태에서는 비효율적

---

## 최종 권장사항

### 현재 프로젝트에 가장 적합한 방안: **시안 3 + 시안 4 하이브리드**

```python
# simloop.py

def simulate_step(prev_state: dict, input_data: dict) -> dict:
    """
    순수 함수: 시뮬레이션 한 스텝 계산

    Args:
        prev_state: 이전 시뮬레이션 상태
        input_data: 사용자 입력

    Returns:
        next_state: 다음 시뮬레이션 상태
    """
    # PyChrono 물리 계산
    # ...
    return next_state


def run_simloop(model_description: dict,
                input_buffer: ReadWriteBuffer,
                output_buffer: ReadWriteBuffer,
                stop_event: threading.Event):
    """
    시뮬레이션 루프 (별도 스레드에서 실행)
    순수 함수를 반복 호출하며, 버퍼 I/O는 외부에서 처리
    """
    state = model_description.get("initial_state", {})

    while not stop_event.is_set():
        # 입력 읽기 (lock 없음)
        input_data = input_buffer.readBuff()

        # 순수 함수 호출 (부수효과 없음)
        state = simulate_step(state, input_data)

        # 출력 쓰기 (commit 시에만 lock)
        with output_buffer as mutable:
            mutable.clear()
            mutable.update(state)

        # 시뮬레이션 주기
        time.sleep(0.0167)  # 60 FPS
```

**장점:**
1. ⚡ **최고 성능**: 순수 계산 + lock 최소화
2. 📖 **최고 가독성**: `simulate_step`은 순수 함수로 매우 명확
3. 🎯 **최고 결정성**: 테스트 시 `simulate_step`만 독립 테스트 가능
4. 🔧 **유지보수성**: 물리 로직과 스레딩/버퍼링 로직 완전 분리

**테스트 예시:**
```python
def test_simulate_step():
    # 순수 함수 테스트 - 버퍼, 스레드 불필요
    prev = {"x": 0, "v": 1}
    input = {"force": 10}

    result = simulate_step(prev, input)

    assert result["x"] == 1  # 위치 업데이트 확인
    assert result["v"] == 11  # 속도 업데이트 확인
```
