# 시뮬관련 코드는 모두 여기로 통합
# TODO: simulate.py, simloop.py 파일의 내용을 여기에 통합
# TODO: SimloopThread 재사용 불가
#       pythonsim = SimloopThread(desc, input)
#       h1 = sim(buffer1)  # OK
#       h2 = sim(buffer2)  # 위험! simEndFlag, simulator 공유
# TODO: 예외처리, 에러처리 및 테스트 코드 작성
# TODO: 문서화

import copy
import threading
from dataclasses import dataclass
from typing import Callable
# from simulate import simulate, SimStates, SimDescription
from sim_server.utils.OwnedBuffer import OwnedBuffer
from sim_server.utils.customTypes import Indexable

@dataclass(frozen=True)
class SimLoopThreadHandle:
    thread: threading.Thread
    release: Callable[[], OwnedBuffer]

# 사용단에서 스레딩을 직접 사용하지 않아도 됨
class SimLoopThread:
    def __init__(self,
                 simDescription: SimDescription,
                 readUserInput: Callable[[], Indexable]):
        self.simulator, self.initState = simulate(simDescription)
        self.readUserInput = readUserInput

    def __call__(self, stateShareBuff: OwnedBuffer) -> SimLoopThreadHandle:
        simEndFlag = threading.Event()
        stateShareBuff.commit(self.initState)
        th = threading.Thread(target=self.simLoop, args=(stateShareBuff,simEndFlag))
        th.start()
        del self.initState
        def releaseSimThread():
            simEndFlag.set()
            th.join()
            return stateShareBuff
        return SimLoopThreadHandle(th, releaseSimThread)

    def simLoop(self, stateShareBuff, simEndFlag):
        try:
            with stateShareBuff as (commitToPrevState, readPrevState):
                while not simEndFlag.is_set():
                    nextState = self.simulator.step(readPrevState, self.readUserInput)
                    commitToPrevState(nextState)
        finally:
            self.simulator.clear()

def hotSwapSimLoopThread(oldHandle, newDescription, inputBuffer):
    newSim = SimLoopThread(newDescription, inputBuffer.readonly)
    return newSim(oldHandle.release())


# 시뮬 모델 변경 시 변경 사이의 텀을 줄이기 위한 디자인
# 매개변수는 함수 시작 전에 평가되지만 함수 내부에선
# 새 시뮬 실행 전에 이런저런 설정을 하는데 시간이 듦
# 메인 스레드에서 아래와 같은 코드
stateShareBuff = OwnedBuffer({})
inputShareBuff = OwnedBuffer({})
oldSimStart = SimLoopThread(SimDescription.fromJSON("filename"), inputShareBuff.readonly)
oldSimLoopThreadHandle = oldSimStart(stateShareBuff)
newSimLoopThreadHandle = hotSwapSimLoopThread(oldSimLoopThreadHandle, SimDescription.fromSDF("filename"), inputShareBuff)


