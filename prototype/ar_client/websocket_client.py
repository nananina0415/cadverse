"""
CADverse AR 클라이언트 - WebSocket 통신
서버로부터 주기적 메시지를 수신하고 응답합니다.

사용법:
    python ar_client/websocket_client.py
"""
import asyncio
import sys
from pathlib import Path

# 필요한 라이브러리 import
try:
    import websockets
except ImportError:
    print("websockets 라이브러리를 설치합니다...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets


# 서버 설정
SERVER_HOST = "localhost"
SERVER_PORT = 8000
WS_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/cadverse/interaction"


async def runClient():
    """
    WebSocket 클라이언트 실행
    - 서버로부터 "Hello, AR! @ {서버시간}" 수신
    - "Hi, CAD! {메시지카운트} times" 응답
    """
    messageCount = 0

    print(f"CADverse AR 클라이언트 시작")
    print(f"서버 연결 시도: {WS_URL}\n")

    try:
        async with websockets.connect(WS_URL) as websocket:
            print("✅ 서버에 연결되었습니다!")
            print("서버로부터 메시지 수신 대기 중...\n")
            print("-" * 60)

            # 메시지 수신 루프
            while True:
                try:
                    # 서버로부터 메시지 수신
                    serverMessage = await websocket.recv()
                    messageCount += 1

                    print(f"[{messageCount}] ← 서버: {serverMessage}")

                    # 응답 메시지 생성
                    response = f"Hi, CAD! {messageCount} times"

                    # 서버로 응답 전송
                    await websocket.send(response)
                    print(f"[{messageCount}] → 클라이언트: {response}")
                    print("-" * 60)

                except websockets.exceptions.ConnectionClosed:
                    print("\n서버와의 연결이 종료되었습니다.")
                    break
                except Exception as e:
                    print(f"\n오류 발생: {e}")
                    import traceback
                    traceback.print_exc()
                    break

    except websockets.exceptions.WebSocketException as e:
        print(f"❌ WebSocket 연결 실패: {e}")
        print("\n서버가 실행 중인지 확인하세요:")
        print("  $ python sim_server/main.py")
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n클라이언트 종료. 총 {messageCount}개의 메시지를 수신했습니다.")


def main():
    """메인 함수"""
    try:
        asyncio.run(runClient())
    except KeyboardInterrupt:
        print("\n\nCtrl+C로 종료되었습니다.")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║         CADverse AR 클라이언트 WebSocket 통신            ║
║                                                          ║
║  서버를 먼저 실행하세요:                                 ║
║  $ cd prototype                                         ║
║  $ python sim_server/main.py                            ║
║                                                          ║
║  Ctrl+C로 종료할 수 있습니다.                            ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)

    main()
