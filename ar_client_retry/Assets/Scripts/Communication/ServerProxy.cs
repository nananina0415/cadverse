using UnityEngine;
using System;
using System.Threading.Tasks;
using System.Net.WebSockets;
using System.Text;
using System.Threading;

namespace CADverse.Communication
{
    public class ServerProxy : MonoBehaviour
    {
        private string _serverBaseUrl;  // e.g., "192.168.1.100:3000"
        private ClientWebSocket _webSocket;
        private CancellationTokenSource _cancellationTokenSource;

        // WebSocket으로 시뮬레이션 상태 수신 시 이벤트
        public event Action<SimulationState> OnSimulationStateReceived;

        // 메인 스레드로 디스패치할 상태 큐
        private readonly System.Collections.Concurrent.ConcurrentQueue<SimulationState> _stateQueue
            = new System.Collections.Concurrent.ConcurrentQueue<SimulationState>();

        void Update()
        {
            // 메인 스레드에서 수신된 상태 처리
            while (_stateQueue.TryDequeue(out SimulationState state))
            {
                OnSimulationStateReceived?.Invoke(state);
            }
        }

        /// <summary>
        /// 서버 주소로 초기화합니다.
        /// QR 코드에서 읽은 주소 (예: "192.168.1.100:3000/cadverse")
        /// </summary>
        public void Initialize(string qrContent)
        {
            // QR 내용에서 base URL 추출
            // 예: "192.168.1.100:3000/cadverse" -> "192.168.1.100:3000"
            // 예: "http://192.168.1.100:3000/cadverse" -> "192.168.1.100:3000"

            string address = qrContent;

            // http:// 또는 https:// 제거
            if (address.StartsWith("http://"))
                address = address.Substring(7);
            else if (address.StartsWith("https://"))
                address = address.Substring(8);

            // /cadverse 등 경로 제거 (호스트:포트만 추출)
            int slashIndex = address.IndexOf('/');
            if (slashIndex > 0)
                address = address.Substring(0, slashIndex);

            _serverBaseUrl = address;
            _cancellationTokenSource = new CancellationTokenSource();

            Debug.Log($"[ServerProxy] Initialized with base URL: {_serverBaseUrl}");
        }

        /// <summary>
        /// 오브젝트 목록을 가져옵니다. GET /cadverse/object
        /// </summary>
        public async Task<ObjectList> GetObjectListAsync()
        {
            string url = $"http://{_serverBaseUrl}/cadverse/object";

            using (var httpClient = new System.Net.Http.HttpClient())
            {
                try
                {
                    Debug.Log($"[ServerProxy] GET {url}");
                    string json = await httpClient.GetStringAsync(url);
                    Debug.Log($"[ServerProxy] Response: {json}");

                    ObjectList objectList = JsonUtility.FromJson<ObjectList>(json);
                    return objectList;
                }
                catch (Exception ex)
                {
                    Debug.LogError($"[ServerProxy] Failed to get object list: {ex.Message}");
                    return null;
                }
            }
        }

        /// <summary>
        /// OBJ 파일을 다운로드합니다. GET /cadverse/object/{name}
        /// </summary>
        public async Task<string> DownloadObjectMeshAsync(string objectName)
        {
            string url = $"http://{_serverBaseUrl}/cadverse/object/{objectName}";

            using (var httpClient = new System.Net.Http.HttpClient())
            {
                try
                {
                    Debug.Log($"[ServerProxy] GET {url}");
                    string objContent = await httpClient.GetStringAsync(url);
                    Debug.Log($"[ServerProxy] Downloaded {objectName}: {objContent.Length} bytes");
                    return objContent;
                }
                catch (Exception ex)
                {
                    Debug.LogError($"[ServerProxy] Failed to download {objectName}: {ex.Message}");
                    return null;
                }
            }
        }

        /// <summary>
        /// 서버에서 QR 코드 패턴을 다운로드합니다. GET /cadverse/qr
        /// 응답: 첫 줄=모듈 수, 이후=0/1 행
        /// </summary>
        public async Task<string> DownloadQrPatternAsync()
        {
            string url = $"http://{_serverBaseUrl}/cadverse/qr";

            using (var httpClient = new System.Net.Http.HttpClient())
            {
                try
                {
                    Debug.Log($"[ServerProxy] GET {url}");
                    string pattern = await httpClient.GetStringAsync(url);
                    Debug.Log($"[ServerProxy] QR pattern received: {pattern.Length} chars");
                    return pattern;
                }
                catch (Exception ex)
                {
                    Debug.LogError($"[ServerProxy] Failed to download QR pattern: {ex.Message}");
                    return null;
                }
            }
        }

        /// <summary>
        /// WebSocket 연결을 시작합니다. WS /cadverse
        /// </summary>
        public async Task ConnectWebSocketAsync()
        {
            if (string.IsNullOrEmpty(_serverBaseUrl))
            {
                Debug.LogError("[ServerProxy] Server address is not set.");
                return;
            }

            if (_webSocket != null && _webSocket.State == WebSocketState.Open)
            {
                Debug.LogWarning("[ServerProxy] WebSocket is already connected.");
                return;
            }

            _webSocket = new ClientWebSocket();
            Uri serverUri = new Uri($"ws://{_serverBaseUrl}/cadverse");

            try
            {
                Debug.Log($"[ServerProxy] Connecting to WebSocket: {serverUri}");
                await _webSocket.ConnectAsync(serverUri, _cancellationTokenSource.Token);
                Debug.Log($"[ServerProxy] WebSocket connected!");

                // 메시지 수신 루프 시작
                _ = ReceiveMessagesAsync(_cancellationTokenSource.Token);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ServerProxy] WebSocket connection failed: {ex.Message}");
                _webSocket?.Dispose();
                _webSocket = null;
            }
        }

        /// <summary>
        /// WebSocket 연결을 종료합니다.
        /// </summary>
        public async Task DisconnectWebSocketAsync()
        {
            if (_webSocket != null && _webSocket.State == WebSocketState.Open)
            {
                try
                {
                    await _webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Client disconnected", CancellationToken.None);
                    Debug.Log("[ServerProxy] WebSocket disconnected.");
                }
                catch (Exception ex)
                {
                    Debug.LogError($"[ServerProxy] Error disconnecting WebSocket: {ex.Message}");
                }
            }
            _cancellationTokenSource?.Cancel();
            _webSocket?.Dispose();
            _webSocket = null;
        }

        private async Task ReceiveMessagesAsync(CancellationToken cancellationToken)
        {
            byte[] buffer = new byte[8192];
            StringBuilder messageBuilder = new StringBuilder();

            try
            {
                while (_webSocket.State == WebSocketState.Open && !cancellationToken.IsCancellationRequested)
                {
                    var result = await _webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), cancellationToken);

                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        messageBuilder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));

                        if (result.EndOfMessage)
                        {
                            string message = messageBuilder.ToString();
                            messageBuilder.Clear();

                            Debug.Log($"[ServerProxy] WebSocket 수신: {message}");

                            // SimulationState 파싱
                            try
                            {
                                SimulationState state = JsonUtility.FromJson<SimulationState>(message);
                                Debug.Log($"[ServerProxy] SimulationState 파싱됨: {state.objects?.Count ?? 0}개 오브젝트");
                                // 메인 스레드로 디스패치하기 위해 큐에 추가
                                _stateQueue.Enqueue(state);
                            }
                            catch (Exception ex)
                            {
                                Debug.LogWarning($"[ServerProxy] Failed to parse message: {ex.Message}");
                            }
                        }
                    }
                    else if (result.MessageType == WebSocketMessageType.Close)
                    {
                        Debug.Log("[ServerProxy] WebSocket received close message from server.");
                        break;
                    }
                }
            }
            catch (OperationCanceledException)
            {
                Debug.Log("[ServerProxy] WebSocket receive operation cancelled.");
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ServerProxy] Error receiving WebSocket message: {ex.Message}");
            }
        }

        /// <summary>
        /// WebSocket으로 메시지를 전송합니다.
        /// </summary>
        public async Task SendMessageAsync(string message)
        {
            if (_webSocket == null || _webSocket.State != WebSocketState.Open)
            {
                Debug.LogWarning("[ServerProxy] WebSocket is not connected.");
                return;
            }

            byte[] buffer = Encoding.UTF8.GetBytes(message);
            await _webSocket.SendAsync(new ArraySegment<byte>(buffer), WebSocketMessageType.Text, true, _cancellationTokenSource.Token);
        }

        private void OnDestroy()
        {
            _cancellationTokenSource?.Cancel();
            _cancellationTokenSource?.Dispose();
            _webSocket?.Dispose();
        }
    }
}
