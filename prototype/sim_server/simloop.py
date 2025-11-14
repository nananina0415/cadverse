import time
import asyncio
import threading
from typing import TYPE_CHECKING, Dict, Any
from dataclasses import asdict

# (models.py의 타입을 사용)
from types import Vector3, Quaternion, ModelState 

# 순환 참조를 피하기 위해 타입 힌트만 임포트
if TYPE_CHECKING:
    from main import Server
    import ReadWriteBuffer 

# (클래스/타입: PascalCase, 변수/함수: camelCase)
class SimLoopThread(threading.Thread):
    """
    모델 상태를 소유하고 업데이트하며,
    버퍼를 통해 서버에 상태를 전달하는 스레드.
    """
    
    def __init__(self, modelDescriptipon, OutputBuffer: ReadWriteBuffer) -> None:
        super().__init__()
        # OutputBuffer의 mutableBuff가 이 시뮬의 갱신 중의 상태, readonlyBuff가 갱신 완료된 최근 상태입니다.

        # TODO: 추후에 입출력버퍼 참조를 직접 받아오는게 아니라 입출력 버퍼에 접근할 수 있는 키를 받아오게끔 해야 함.
        #       이 키는 싱글톤으로서 프로세스 내에 유일하고 새 시뮬스레드가 만들어질 때 필수적으로 필요하므로 
        #       버퍼에 접근할 수 있는 시뮬스레드가 하나이도록 보장. 
        #       다만 지금은 프로토타입 제작이므로 새 시뮬생성 로직이 없으므로 패스.

    def run(self) -> None:
        """스레드에서 실행될 메인 시뮬레이션 루프"""
        
        while self._running:
            
            # 입력버퍼 읽어오기(이전 결과를 출력버퍼에쓰는동안 읽어오도록 할 수 있나?)
            
            # 입력과 이전상태 -> 다음상태

            # 결과를 출력버퍼에 쓰기

    def stop(self) -> None:
        self._running = False