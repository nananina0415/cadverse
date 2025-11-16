# 대화식 테스트 클라이언트 사용법

## 실행 방법

### 1. 서버 시작
```bash
# 터미널 1
cd prototype
python sim_server/main.py
```

### 2. 테스트 클라이언트 실행
```bash
# 터미널 2
cd prototype
python sim_server/manual_test_client.py
```

## 기능

### 1. HTTP GET 테스트
리소스 파일 요청 테스트
```
선택: 1
요청할 파일 경로: meshes/model.obj
```

### 2. WebSocket 단발성 테스트
한 번만 메시지를 보내고 응답 확인
```
선택: 2
서버로 보낼 메시지: Hello!
```

### 3. WebSocket 실시간 모니터링
서버에서 오는 메시지를 계속 수신 (시뮬레이션 상태 모니터링)
```
선택: 3
(Ctrl+C로 종료)
```
**예상 출력:**
```json
[1] 수신 (JSON):
{
  "model_1": {
    "position": {"x": 1.23, "y": 0.0, "z": 0.0},
    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
  }
}
```

### 4. WebSocket 대화식 채팅
서버와 메시지를 주고받기
```
선택: 4
→ 보낼 메시지: test message
← 수신: (서버 응답)
→ 보낼 메시지: quit  (종료)
```

### 5. 서버 상태 확인
HTTP와 WebSocket 연결 가능 여부 확인
```
선택: 5
```

## 테스트 시나리오 예시

### 시나리오 1: 시뮬레이션 모니터링
1. 서버 실행
2. 클라이언트에서 **옵션 3** 선택
3. 시뮬레이션 데이터가 실시간으로 출력되는지 확인
4. `model_1`의 `position.x` 값이 변하는지 관찰

### 시나리오 2: 리소스 파일 제공 확인
1. `prototype/resources/meshes/test.obj` 파일 생성
2. 클라이언트에서 **옵션 1** 선택
3. 파일 경로: `meshes/test.obj`
4. 200 OK 응답 확인

### 시나리오 3: WebSocket 통신 확인
1. 클라이언트에서 **옵션 2** 선택
2. 메시지 전송
3. 서버 로그에서 메시지 수신 확인
4. 클라이언트에서 응답 확인

## 트러블슈팅

### "서버에 연결할 수 없습니다"
- 서버가 실행 중인지 확인: `python sim_server/main.py`
- 포트가 맞는지 확인: 기본값 `8000`

### "ModuleNotFoundError: No module named 'websockets'"
- 자동으로 설치됩니다. 수동 설치: `pip install websockets requests`

### WebSocket에서 응답이 없음
- 정상입니다. 현재 서버는 클라이언트 메시지에 응답하지 않고 로그만 출력합니다.
- 실시간 모니터링(옵션 3)으로 시뮬레이션 데이터 수신을 확인하세요.
