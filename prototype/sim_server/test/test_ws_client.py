"""
WebSocket 클라이언트 테스트
서버에서 보내는 모델 상태를 확인
"""
import asyncio
import websockets
import json

async def test_client():
    uri = "ws://localhost:8000/cadverse/interaction"

    print(f"[test] 서버 연결 시도: {uri}")

    try:
        async with websockets.connect(uri) as websocket:
            print("[test] 서버 연결 성공!")

            # 5개의 메시지만 받아보기
            for i in range(5):
                message = await websocket.recv()
                data = json.loads(message)

                print(f"\n[test] 수신 메시지 #{i+1}:")
                print(f"  파트 개수: {len(data)}")
                if data:
                    print(f"  첫 번째 파트 위치: {data[0]['pos']}")
                    print(f"  첫 번째 파트 회전: {data[0]['rot']}")

            print("\n[test] 테스트 완료!")

    except Exception as e:
        print(f"[test] 에러: {e}")

if __name__ == "__main__":
    asyncio.run(test_client())
