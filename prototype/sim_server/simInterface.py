import simulate

class Simulator:
    def step(self): ...
    def clear(self): ...
        # 시뮬레이션 종료 시 호출해야 하는 함수가 있으면 여기서 호출

class SimState:
    ...

class SimDescription:
    simMetaJson = "..."

def make_sim(simDescription: SimDescription)->(Simulator,SimState):
    simulate.make_sim()




