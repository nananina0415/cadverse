import re

# SimServer.cs에 OnModelStateUpdated 이벤트와 sim_time 검증 추가
with open(
    "prototype/ar_client/Assets/Scripts/Communication/SimServer.cs",
    "r",
    encoding="utf-8",
) as f:
    content = f.read()

# 1. _lastSimTime 필드 추가
if "_lastSimTime" not in content:
    content = content.replace(
        "        private Coroutine _reconnectCoroutine;",
        """        private Coroutine _reconnectCoroutine;
        private float _lastSimTime = -1f;  // 마지막 수신한 sim_time""",
    )

# 2. OnModelStateUpdated 이벤트 추가
if "OnModelStateUpdated" not in content:
    content = content.replace(
        """        public event Action<string> OnError;
        public event Action OnQrScanStarted;""",
        """        public event Action<string> OnError;
        public event Action OnModelStateUpdated;  // 모델 상태 업데이트됨
        public event Action OnQrScanStarted;""",
    )

# 3. HandleMessage에 sim_time 검증 및 이벤트 발생 추가
old_handle = """        private void HandleMessage(byte[] bytes)
        {
            try
            {
                string json = System.Text.Encoding.UTF8.GetString(bytes);
                var message = ModelStateMessage.FromJson(json);

                lock (_stateLock)
                {
                    _latestModelState = message.parts;
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] 메시지 파싱 에러: {ex.Message}");
                OnError?.Invoke(ex.Message);
            }
        }"""

new_handle = """        private void HandleMessage(byte[] bytes)
        {
            try
            {
                string json = System.Text.Encoding.UTF8.GetString(bytes);
                var message = ModelStateMessage.FromJson(json);

                // sim_time 검증
                if (_lastSimTime >= 0 && message.sim_time <= _lastSimTime)
                {
                    Debug.LogWarning(
                        $"[SimServer] sim_time 역행 감지! " +
                        $"이전: {_lastSimTime:F3}s, 현재: {message.sim_time:F3}s"
                    );
                }
                else if (_lastSimTime >= 0)
                {
                    float delta = message.sim_time - _lastSimTime;
                    Debug.Log($"[SimServer] sim_time 갱신: {message.sim_time:F3}s (Δ{delta:F4}s)");
                }

                _lastSimTime = message.sim_time;

                lock (_stateLock)
                {
                    _latestModelState = message.parts;
                }

                // 모델 상태 업데이트 이벤트 발생
                OnModelStateUpdated?.Invoke();
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] 메시지 파싱 에러: {ex.Message}");
                OnError?.Invoke(ex.Message);
            }
        }"""

content = content.replace(old_handle, new_handle)

with open(
    "prototype/ar_client/Assets/Scripts/Communication/SimServer.cs",
    "w",
    encoding="utf-8",
) as f:
    f.write(content)

print("SimServer.cs 수정 완료 - OnModelStateUpdated 이벤트 및 sim_time 검증 추가")
