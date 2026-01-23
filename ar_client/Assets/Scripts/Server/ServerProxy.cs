using System;
using System.Net.WebSockets;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using CADverse.Server.DataModel;

namespace CADverse.Server
{
    /// <summary>
    /// 시뮬레이션 서버와의 통신을 담당하는 프록시 클래스
    /// WebSocket과 HTTP를 통해 서버와 통신
    /// </summary>
    public class ServerProxy : MonoBehaviour
    {
        // === 서버 정보 ===
        private string _serverIp;
        private int _serverPort;

        // === 연결 상태 ===
        public bool IsConnected { get; private set; }
        public SimulationState LatestState { get; private set; }

        // === 이벤트 ===
        public event Action<SimulationState> OnStateReceived;
        public event Action OnConnected;
        public event Action<string> OnError;
        public event Action OnDisconnected;

        // === WebSocket ===
        private ClientWebSocket _webSocket;
        private CancellationTokenSource _cancellationTokenSource;

        // === HTTP ===
        private HttpClient _httpClient;

        // === 생성 ===
        /// <summary>
        /// ServerProxy 인스턴스를 생성합니다
        /// </summary>
        /// <param name="ip">서버 IP 주소</param>
        /// <param name="port">서버 포트</param>
        /// <returns>생성된 ServerProxy 인스턴스</returns>
        public static ServerProxy Create(string ip, int port)
        {
            var go = new GameObject("ServerProxy");
            var proxy = go.AddComponent<ServerProxy>();
            proxy.Initialize(ip, port);
            return proxy;
        }

        private void Initialize(string ip, int port)
        {
            _serverIp = ip;
            _serverPort = port;
            _httpClient = new HttpClient();
            DontDestroyOnLoad(gameObject);

            Debug.Log($"[ServerProxy] Initialized for {ip}:{port}");
        }

        // === 연결 관리 ===
        /// <summary>
        /// 서버에 연결합니다
        /// </summary>
        public async Task Connect()
        {
            if (IsConnected)
            {
                Debug.LogWarning("[ServerProxy] Already connected");
                return;
            }

            try
            {
                // WebSocket 연결
                _webSocket = new ClientWebSocket();
                _cancellationTokenSource = new CancellationTokenSource();

                var wsUri = new Uri($"ws://{_serverIp}:{_serverPort}/cadverse");
                Debug.Log($"[ServerProxy] Connecting to {wsUri}...");

                await _webSocket.ConnectAsync(wsUri, _cancellationTokenSource.Token);

                IsConnected = true;
                Debug.Log("[ServerProxy] Connected successfully");

                // 수신 루프 시작
                _ = ReceiveLoop();

                // 연결 이벤트 발생 (메인 스레드)
                UnityMainThreadDispatcher.Enqueue(() => OnConnected?.Invoke());
            }
            catch (Exception e)
            {
                IsConnected = false;
                Debug.LogError($"[ServerProxy] Connection failed: {e.Message}");
                UnityMainThreadDispatcher.Enqueue(() => OnError?.Invoke($"연결 실패: {e.Message}"));
                throw;
            }
        }

        /// <summary>
        /// 서버 연결을 종료합니다
        /// </summary>
        public async Task Disconnect()
        {
            if (!IsConnected)
            {
                return;
            }

            try
            {
                IsConnected = false;

                // WebSocket 종료
                _cancellationTokenSource?.Cancel();

                if (_webSocket?.State == WebSocketState.Open)
                {
                    await _webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Client disconnect", CancellationToken.None);
                }

                _webSocket?.Dispose();
                _webSocket = null;

                Debug.Log("[ServerProxy] Disconnected");
                UnityMainThreadDispatcher.Enqueue(() => OnDisconnected?.Invoke());
            }
            catch (Exception e)
            {
                Debug.LogError($"[ServerProxy] Disconnect error: {e.Message}");
            }
        }

        // === WebSocket 수신 ===
        private async Task ReceiveLoop()
        {
            var buffer = new byte[1024 * 16]; // 16KB buffer

            try
            {
                while (IsConnected && _webSocket?.State == WebSocketState.Open)
                {
                    var result = await _webSocket.ReceiveAsync(
                        new ArraySegment<byte>(buffer),
                        _cancellationTokenSource.Token
                    );

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        Debug.Log("[ServerProxy] Server closed connection");
                        await Disconnect();
                        break;
                    }

                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        var json = Encoding.UTF8.GetString(buffer, 0, result.Count);
                        HandleMessage(json);
                    }
                }
            }
            catch (OperationCanceledException)
            {
                Debug.Log("[ServerProxy] Receive loop cancelled");
            }
            catch (Exception e)
            {
                Debug.LogError($"[ServerProxy] Receive error: {e.Message}");

                if (IsConnected)
                {
                    IsConnected = false;
                    UnityMainThreadDispatcher.Enqueue(() => OnError?.Invoke($"수신 오류: {e.Message}"));
                    UnityMainThreadDispatcher.Enqueue(() => OnDisconnected?.Invoke());
                }
            }
        }

        private void HandleMessage(string json)
        {
            try
            {
                // JSON 역직렬화
                var state = JsonUtility.FromJson<SimulationState>(json);
                LatestState = state;

                // 메인 스레드에서 이벤트 발생
                UnityMainThreadDispatcher.Enqueue(() => OnStateReceived?.Invoke(state));
            }
            catch (Exception e)
            {
                Debug.LogError($"[ServerProxy] JSON parse error: {e.Message}\nJSON: {json}");
                UnityMainThreadDispatcher.Enqueue(() => OnError?.Invoke($"메시지 파싱 실패: {e.Message}"));
            }
        }

        // === WebSocket 송신 ===
        /// <summary>
        /// 사용자 입력을 서버로 전송합니다
        /// </summary>
        public async Task SendInput(UserInput input)
        {
            if (!IsConnected || _webSocket?.State != WebSocketState.Open)
            {
                throw new InvalidOperationException("서버에 연결되지 않음");
            }

            try
            {
                var json = JsonUtility.ToJson(input);
                var bytes = Encoding.UTF8.GetBytes(json);

                await _webSocket.SendAsync(
                    new ArraySegment<byte>(bytes),
                    WebSocketMessageType.Text,
                    true,
                    _cancellationTokenSource.Token
                );

                Debug.Log($"[ServerProxy] Sent input: {input.input_type}");
            }
            catch (Exception e)
            {
                Debug.LogError($"[ServerProxy] Send error: {e.Message}");
                throw;
            }
        }

        /// <summary>
        /// 터치 레이캐스트 입력을 서버로 전송합니다 (제네릭)
        /// </summary>
        public async Task SendTouchInput<T>(T input) where T : class
        {
            if (!IsConnected || _webSocket?.State != WebSocketState.Open)
            {
                throw new InvalidOperationException("서버에 연결되지 않음");
            }

            try
            {
                var json = JsonUtility.ToJson(input);
                var bytes = Encoding.UTF8.GetBytes(json);

                await _webSocket.SendAsync(
                    new ArraySegment<byte>(bytes),
                    WebSocketMessageType.Text,
                    true,
                    _cancellationTokenSource.Token
                );

                Debug.Log($"[ServerProxy] Sent touch input: {typeof(T).Name}");
            }
            catch (Exception e)
            {
                Debug.LogError($"[ServerProxy] Send error: {e.Message}");
                throw;
            }
        }

        // === HTTP 요청 ===
        /// <summary>
        /// 서버에서 오브젝트 목록을 가져옵니다
        /// </summary>
        public async Task<ObjectList> GetObjectList()
        {
            try
            {
                var url = $"http://{_serverIp}:{_serverPort}/cadverse/object";
                Debug.Log($"[ServerProxy] GET {url}");

                var response = await _httpClient.GetStringAsync(url);
                var objectList = JsonUtility.FromJson<ObjectList>(response);

                Debug.Log($"[ServerProxy] Received {objectList.objects.Length} objects");
                return objectList;
            }
            catch (Exception e)
            {
                Debug.LogError($"[ServerProxy] GetObjectList error: {e.Message}");
                throw;
            }
        }

        /// <summary>
        /// 서버에서 특정 오브젝트의 메쉬 데이터를 가져옵니다
        /// </summary>
        /// <param name="objectName">오브젝트 이름</param>
        /// <returns>OBJ 포맷 메쉬 데이터</returns>
        public async Task<string> GetObjectMesh(string objectName)
        {
            try
            {
                var url = $"http://{_serverIp}:{_serverPort}/cadverse/object/{objectName}";
                Debug.Log($"[ServerProxy] GET {url}");

                var objData = await _httpClient.GetStringAsync(url);

                Debug.Log($"[ServerProxy] Received mesh for {objectName} ({objData.Length} bytes)");
                return objData;
            }
            catch (Exception e)
            {
                Debug.LogError($"[ServerProxy] GetObjectMesh error: {e.Message}");
                throw;
            }
        }

        // === Unity 생명주기 ===
        private void OnDestroy()
        {
            // 리소스 정리
            _ = Disconnect();
            _httpClient?.Dispose();
            _cancellationTokenSource?.Dispose();

            Debug.Log("[ServerProxy] Destroyed");
        }
    }
}
