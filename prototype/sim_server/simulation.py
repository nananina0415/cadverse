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
from prototype.sim_server.utils.owned_buffer import OwnedBuffer
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
