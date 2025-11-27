using System;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using NativeWebSocket;

namespace CADverse.Connection
{
    /// <summary>
    /// CADverse 서버와의 저수준 HTTP/WebSocket 연결 기능 제공
    /// - QR 코드로부터 서버 주소 파싱
    /// - HTTP를 통한 리소스 다운로드
    /// - WebSocket 연결 및 자동 재접속
    /// </summary>
    public class ServerConnection
    {
        private string _httpBaseUri;
        private WebSocket _websocket;
        private string _wsUrl;
        private bool _isConnecting;

        public string HttpBaseUrl => _httpBaseUri;
        public string ResourcesEndpoint => $"http://{HttpBaseUrl}/cadverse/resources";
        public bool IsWebSocketConnected => _websocket != null && _websocket.State == WebSocketState.Open;

        // WebSocket 이벤트
        public event Action OnWebSocketConnected;
        public event Action OnWebSocketDisconnected;
        public event Action<string> OnWebSocketError;
        public event Action<byte[]> OnWebSocketMessage;

        /// <summary>
        /// QR 코드에서 읽은 문자열로 서버 주소를 파싱하여 인스턴스를 생성한다.
        /// ws/wss 스킴이 들어오면 http/https로 자동 변환한다.
        /// </summary>
        public static Result<ServerConnection> TryCreateFromQrPayload(string qrPayload)
        {
            if (string.IsNullOrWhiteSpace(qrPayload))
            {
                return Result<ServerConnection>.Failure("QR 코드에 서버 주소가 없습니다.");
            }

            qrPayload = qrPayload.Trim();

            if (!Uri.TryCreate(qrPayload, UriKind.Absolute, out var uri))
            {
                // 호스트만 인코딩된 경우 http:// 접두사를 붙여 재시도
                if (!Uri.TryCreate($"http://{qrPayload}", UriKind.Absolute, out uri))
                {
                    return Result<ServerConnection>.Failure($"유효하지 않은 주소 형식: {qrPayload}");
                }
            }

            var normalizedUri = NormalizeToHttp(uri);
            if (normalizedUri == null)
            {
                return Result<ServerConnection>.Failure($"지원하지 않는 프로토콜: {uri.Scheme}");
            }

            var baseUri = StripCadverseSegment(normalizedUri);

            var connection = new ServerConnection
            {
                _httpBaseUri = baseUri.ToString().TrimEnd('/')
            };

            return Result<ServerConnection>.Success(connection);
        }

        /// <summary>
        /// 모델 경로(예: base.obj)를 받아 서버로부터 OBJ/SDF 등의 원본 텍스트를 내려받는다.
        /// </summary>
        public async Task<string> LoadModelAsync(string modelPath, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(modelPath))
            {
                throw new ArgumentException("모델 경로가 비어 있습니다.", nameof(modelPath));
            }

            var requestUrl = BuildResourcesUrl(modelPath);

            using var request = UnityWebRequest.Get(requestUrl);
            request.downloadHandler = new DownloadHandlerBuffer();

            var operation = request.SendWebRequest();
            while (!operation.isDone)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    request.Abort();
                    throw new OperationCanceledException(cancellationToken);
                }
                await Task.Yield();
            }

#if UNITY_2020_1_OR_NEWER
            var succeeded = request.result == UnityWebRequest.Result.Success;
#else
            var succeeded = !request.isHttpError && !request.isNetworkError;
#endif

            if (!succeeded)
            {
                throw new InvalidOperationException(
                    $"모델 다운로드 실패 ({request.responseCode}): {request.error}");
            }

            return request.downloadHandler.text;
        }

        /// <summary>
        /// WebSocket 연결을 시작한다.
        /// </summary>
        public async Task ConnectWebSocketAsync()
        {
            if (_isConnecting || IsWebSocketConnected)
            {
                Debug.LogWarning("[ServerConnection] WebSocket이 이미 연결 중이거나 연결되어 있습니다.");
                return;
            }

            _isConnecting = true;

            try
            {
                if (string.IsNullOrEmpty(_wsUrl))
                {
                    _wsUrl = BuildWebSocketUrl();
                }

                Debug.Log($"[ServerConnection] WebSocket 연결 시도: {_wsUrl}");

                _websocket = new WebSocket(_wsUrl);

                _websocket.OnOpen += () =>
                {
                    Debug.Log("[ServerConnection] WebSocket 연결됨");
                    OnWebSocketConnected?.Invoke();
                };

                _websocket.OnMessage += (bytes) =>
                {
                    OnWebSocketMessage?.Invoke(bytes);
                };

                _websocket.OnError += (errorMsg) =>
                {
                    Debug.LogError($"[ServerConnection] WebSocket 오류: {errorMsg}");
                    OnWebSocketError?.Invoke(errorMsg);
                };

                _websocket.OnClose += (closeCode) =>
                {
                    Debug.Log($"[ServerConnection] WebSocket 연결 종료 (코드: {closeCode})");
                    OnWebSocketDisconnected?.Invoke();
                };

                await _websocket.Connect();
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ServerConnection] WebSocket 연결 실패: {ex.Message}");
                OnWebSocketError?.Invoke(ex.Message);
                throw;
            }
            finally
            {
                _isConnecting = false;
            }
        }

        /// <summary>
        /// WebSocket 연결을 종료한다.
        /// </summary>
        public async Task DisconnectWebSocketAsync()
        {
            if (_websocket != null)
            {
                if (_websocket.State == WebSocketState.Open)
                {
                    await _websocket.Close();
                }
                _websocket = null;
            }
        }

        /// <summary>
        /// WebSocket을 통해 텍스트 메시지를 전송한다.
        /// </summary>
        public async Task SendTextAsync(string text)
        {
            if (!IsWebSocketConnected)
            {
                throw new InvalidOperationException("WebSocket이 연결되어 있지 않습니다.");
            }

            await _websocket.SendText(text);
        }

        /// <summary>
        /// WebSocket 메시지 큐를 처리한다. (Unity Update에서 호출 필요)
        /// </summary>
        public void DispatchMessageQueue()
        {
#if !UNITY_WEBGL || UNITY_EDITOR
            _websocket?.DispatchMessageQueue();
#endif
        }

        private string BuildResourcesUrl(string modelPath)
        {
            var sanitizedPath = modelPath.Trim().TrimStart('/');
            var baseUri = new Uri(_httpBaseUri);
            var uri = new Uri(baseUri, $"cadverse/resources/{sanitizedPath}");
            return uri.ToString();
        }

        private string BuildWebSocketUrl()
        {
            var baseUri = new Uri(_httpBaseUri);
            var builder = new UriBuilder(baseUri)
            {
                Scheme = baseUri.Scheme == "https" ? "wss" : "ws",
                Path = "/cadverse/interaction"
            };
            return builder.Uri.ToString();
        }

        private static Uri NormalizeToHttp(Uri source)
        {
            if (source.Scheme == Uri.UriSchemeHttp || source.Scheme == Uri.UriSchemeHttps)
            {
                return source;
            }

            if (source.Scheme.Equals("ws", StringComparison.OrdinalIgnoreCase) ||
                source.Scheme.Equals("wss", StringComparison.OrdinalIgnoreCase))
            {
                var builder = new UriBuilder(source)
                {
                    Scheme = source.Scheme.Equals("ws", StringComparison.OrdinalIgnoreCase)
                        ? Uri.UriSchemeHttp
                        : Uri.UriSchemeHttps,
                    Port = source.Port
                };
                return builder.Uri;
            }

            return null;
        }

        private static Uri StripCadverseSegment(Uri uri)
        {
            var path = uri.AbsolutePath?.TrimEnd('/');
            if (string.Equals(path, "/cadverse", StringComparison.OrdinalIgnoreCase))
            {
                var builder = new UriBuilder(uri)
                {
                    Path = "/",
                    Query = string.Empty
                };
                return builder.Uri;
            }

            return uri;
        }
    }
}
