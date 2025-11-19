# 시뮬관련 코드는 모두 여기로 통합
# TODO: simulate.py, simloop.py 파일의 내용을 여기에 통합


# 사용단에서 스레딩을 직접 사용하지 않아도 됨
def simloopThread( simDescription ):
    simulator, initState = simulate(simDescription)
    prevState = initState
    nowState = initState
    simEndFlag = threading.Event()

    def simloop(ioBuffLock): # ioBuffLock는 락과 두 버퍼를 가지는 커스텀 클래스
        with ioBuffLock as nowState, userInput: # 둘 다 버퍼
            while not simEndFlag.is_set():
                prevState, nowState = [ nowState, simulator.step(prevState,userInput) ]
        simulator.clear()

    def startSimloop(ioBuffLock):
        # ioBuffLock이 들어오면 빠르게 새 시뮬을 실행해서 텀을 줄임
        th = threading.Thread( target=simloop,args=(ioBuffLock,) )
        th.start()

        def releaseSimThread():
            simEndFlag.set()
            th.join()
            return ioBuffLock
        th.release = releaseSimThread

        return th

    return startSimloop

# 시뮬 모델 변경 시 변경 사이의 텀을 줄이기 위한 디자인
# 매개변수는 함수 시작 전에 평가되지만 함수 내부에선
# 새 시뮬 실행 전에 이런저런 설정을 하는데 시간이 듦
simloopThread(simDescription)(oldSimloopThread.release())
# or
runSimloopThread = simloopThread(simDescription)
runSimloopThread(oldSimloopThread.release())
