"""
대화식 서버 테스트 클라이언트
WebSocket과 HTTP 통신을 터미널에서 테스트할 수 있습니다.

사용법:
    python manual_test_client.py
"""
import asyncio
import json
import sys
from pathlib import Path

# 필요한 라이브러리 import
try:
    import requests
    import websockets
except ImportError:
    print("필요한 라이브러리를 설치합니다...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "websockets"])
    import requests
    import websockets


# 서버 설정
SERVER_HOST = "localhost"
SERVER_PORT = 8000
WS_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/cadverse/interaction"
HTTP_BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


def print_menu():
    """메인 메뉴 출력"""
    print("\n" + "="*50)
    print("CADverse 서버 테스트 클라이언트")
    print("="*50)
    print("1. HTTP GET 테스트 (리소스 파일 요청)")
    print("2. WebSocket 연결 테스트 (단발성)")
    print("3. WebSocket 실시간 모니터링 (지속)")
    print("4. WebSocket 대화식 채팅")
    print("5. 서버 상태 확인")
    print("0. 종료")
    print("="*50)


def test_http_resource():
    """HTTP GET 리소스 파일 테스트"""
    print("\n[HTTP 리소스 테스트]")
    file_path = input("요청할 파일 경로 (예: base.obj, shaft.obj): ").strip()

    if not file_path:
        file_path = "base.obj"
        print(f"기본값 사용: {file_path}")

    url = f"{HTTP_BASE_URL}/cadverse/resources/{file_path}"
    print(f"\n요청 URL: {url}")

    try:
        response = requests.get(url, timeout=5)
        print(f"응답 코드: {response.status_code}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'N/A')}")

        content_length = response.headers.get('Content-Length', 'N/A')
        if content_length != 'N/A':
            size_kb = int(content_length) / 1024
            print(f"Content-Length: {content_length} bytes ({size_kb:.2f} KB)")
        else:
            print(f"Content-Length: {content_length}")

        if response.status_code == 200:
            print("\n✅ 성공!")

            # 텍스트 파일인지 확인 (디코딩 시도)
            try:
                text_content = response.content.decode('utf-8')

                # 처음 1KB만 추출
                max_bytes = 1024
                if len(response.content) > max_bytes:
                    text_preview = response.content[:max_bytes].decode('utf-8', errors='ignore')
                    truncated = True
                else:
                    text_preview = text_content
                    truncated = False

                # 줄 단위로 분리
                lines = text_preview.split('\n')

                # 처음 10줄만 출력
                print(f"\n응답 데이터 (처음 10줄, 최대 1KB):")
                print("-" * 50)
                for i, line in enumerate(lines[:10], 1):
                    print(f"{i:2d}: {line}")

                # 더 많은 줄이 있으면 표시
                if len(lines) > 10:
                    print(f"... (총 {len(lines)}줄 중 10줄 표시)")

                if truncated:
                    print(f"\n※ 파일이 1KB보다 큽니다. 일부만 표시됨")

            except UnicodeDecodeError:
                # 바이너리 파일
                print("\n※ 바이너리 파일입니다. 내용을 표시할 수 없습니다.")
                print(f"파일 크기: {len(response.content)} bytes")
        else:
            print(f"\n❌ 실패: {response.text}")
    except requests.exceptions.ConnectionError:
        print("❌ 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.")
    except Exception as e:
        print(f"❌ 오류: {e}")


async def test_websocket_once():
    """WebSocket 단발성 연결 테스트"""
    print("\n[WebSocket 단발성 테스트]")
    print(f"연결 시도: {WS_URL}")

    try:
        async with websockets.connect(WS_URL) as websocket:
            print("✅ 연결 성공!")

            # 메시지 전송
            message = input("\n서버로 보낼 메시지: ").strip()
            if not message:
                message = "Hello from test client!"
                print(f"기본값 사용: {message}")

            await websocket.send(message)
            print(f"-> 전송: {message}")

            # 응답 대기 (타임아웃 5초)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                print(f"<- 수신: {response}")
            except asyncio.TimeoutError:
                print("<- (응답 없음 - 타임아웃)")

            print("\n✅ 테스트 완료")
    except Exception as e:
        print(f"❌ 오류: {e}")


async def test_websocket_monitor():
    """WebSocket 실시간 모니터링"""
    print("\n[WebSocket 실시간 모니터링]")
    print(f"연결 시도: {WS_URL}")
    print("Ctrl+C로 종료하세요.\n")

    try:
        async with websockets.connect(WS_URL) as websocket:
            print("✅ 연결됨. 서버로부터 메시지 수신 대기 중...\n")

            message_count = 0
            while True:
                try:
                    # 서버로부터 메시지 수신
                    message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    message_count += 1

                    # JSON 파싱 시도
                    try:
                        data = json.loads(message)
                        print(f"[{message_count}] <- 수신 (JSON):")
                        print(json.dumps(data, indent=2, ensure_ascii=False))
                    except json.JSONDecodeError:
                        print(f"[{message_count}] <- 수신 (TEXT): {message}")

                    # 서버에 응답 전송
                    response = f"Hi, CAD! {message_count} times"
                    await websocket.send(response)
                    print(f"[{message_count}] -> 응답: {response}")

                    print("-" * 50)

                except asyncio.TimeoutError:
                    print("(10초간 메시지 없음...)")
                    continue

    except KeyboardInterrupt:
        print("\n\n종료합니다.")
    except Exception as e:
        print(f"❌ 오류: {e}")


async def test_websocket_chat():
    """WebSocket 대화식 채팅"""
    print("\n[WebSocket 대화식 채팅]")
    print(f"연결 시도: {WS_URL}")
    print("메시지를 입력하고 Enter를 누르세요.")
    print("'quit' 입력 시 종료.\n")

    try:
        async with websockets.connect(WS_URL) as websocket:
            print("✅ 연결됨!\n")

            while True:
                # 사용자 입력 (비동기)
                message = await asyncio.get_event_loop().run_in_executor(
                    None, input, "-> 보낼 메시지: "
                )

                if message.strip().lower() == 'quit':
                    print("종료합니다.")
                    break

                if message.strip():
                    # 메시지 전송
                    await websocket.send(message)
                    print(f"  전송됨: {message}")

                    # 응답 수신 (타임아웃 3초)
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                        print(f"<- 수신: {response}\n")
                    except asyncio.TimeoutError:
                        print("<- (응답 없음)\n")

    except Exception as e:
        print(f"❌ 오류: {e}")


def test_server_status():
    """서버 상태 확인"""
    print("\n[서버 상태 확인]")

    # HTTP 연결 테스트
    print(f"HTTP 연결 테스트: {HTTP_BASE_URL}")
    try:
        response = requests.get(f"{HTTP_BASE_URL}/docs", timeout=2)
        if response.status_code == 200:
            print("  ✅ HTTP 서버 응답 정상")
        else:
            print(f"  ⚠️  HTTP 응답 코드: {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("  ❌ HTTP 서버 연결 불가")
    except Exception as e:
        print(f"  ❌ HTTP 오류: {e}")

    # WebSocket 연결 테스트
    print(f"\nWebSocket 연결 테스트: {WS_URL}")
    async def check_ws():
        try:
            async with websockets.connect(WS_URL) as ws:
                print("  ✅ WebSocket 연결 성공")
                return True
        except Exception as e:
            print(f"  ❌ WebSocket 연결 실패: {e}")
            return False

    asyncio.run(check_ws())


def main():
    """메인 함수"""
    while True:
        print_menu()
        choice = input("\n선택: ").strip()

        try:
            if choice == '1':
                test_http_resource()
            elif choice == '2':
                asyncio.run(test_websocket_once())
            elif choice == '3':
                asyncio.run(test_websocket_monitor())
            elif choice == '4':
                asyncio.run(test_websocket_chat())
            elif choice == '5':
                test_server_status()
            elif choice == '0':
                print("\n종료합니다.")
                break
            else:
                print("❌ 잘못된 선택입니다.")
        except KeyboardInterrupt:
            print("\n\n중단되었습니다.")
        except Exception as e:
            print(f"\n❌ 예상치 못한 오류: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║       CADverse 서버 대화식 테스트 클라이언트             ║
║                                                          ║
║  서버를 먼저 실행하세요:                                 ║
║  $ python sim_server/main.py                            ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)

    main()
