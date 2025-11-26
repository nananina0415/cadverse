using System;
using System.Collections;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;
using NativeWebSocket;

/// <summary>
/// CADverse 시뮬레이션 서버와의 HTTP/WebSocket 통신을 담당한다.
/// QR 코드에 인코딩된 서버 주소로부터 안전하게 인스턴스를 생성하고,
/// 모델 메시 데이터를 문자열 형태로 내려받고, 위치/자세 정보를 실시간으로 수신한다.
/// </summary>
public sealed class SimServer : MonoBehaviour
{
    private string _httpBaseUri;
    private WebSocket _websocket;
    private string _wsUrl;
    private bool _isConnecting;
    private bool _shouldReconnect = true;
    private Coroutine _reconnectCoroutine;

    [Header("WebSocket Settings")]
    [SerializeField] private float reconnectDelaySeconds = 3f;
    [SerializeField] private int maxReconnectAttempts = 10;

    public event Action<string> OnPoseDataReceived;
    public event Action OnWebSocketConnected;
    public event Action OnWebSocketDisconnected;
    public event Action<string> OnWebSocketError;

    public bool IsWebSocketConnected => _websocket != null && _websocket.State == WebSocketState.Open;

    public string HttpBaseUrl => _httpBaseUri;

    /// <summary>모델 리소스 엔드포인트 (예: http://.../cadverse/resources)</summary>
    public string ResourcesEndpoint => $"http://{HttpBaseUrl}/cadverse/resources";

    /// <summary>
    /// QR 코드에서 읽은 문자열로 시뮬레이션 서버 인스턴스를 생성한다.
    /// ws/wss 스킴이 들어오면 http/https로 자동 변환한다.
    /// GameObject를 생성하고 SimServer 컴포넌트를 추가한다.
    /// </summary>
    public static Result<SimServer> TryCreateFromQrPayload(string qrPayload)
    {
        if (string.IsNullOrWhiteSpace(qrPayload))
        {
            return Result<SimServer>.Failure("QR 코드에 서버 주소가 없습니다.");
        }

        qrPayload = qrPayload.Trim();

        if (!Uri.TryCreate(qrPayload, UriKind.Absolute, out var uri))
        {
            // 호스트만 인코딩된 경우 http:// 접두사를 붙여 재시도
            if (!Uri.TryCreate($"http://{qrPayload}", UriKind.Absolute, out uri))
            {
                return Result<SimServer>.Failure($"유효하지 않은 주소 형식: {qrPayload}");
            }
        }

        var normalizedUri = NormalizeToHttp(uri);
        if (normalizedUri == null)
        {
            return Result<SimServer>.Failure($"지원하지 않는 프로토콜: {uri.Scheme}");
        }

        var baseUri = StripCadverseSegment(normalizedUri);

        // GameObject 생성 및 SimServer 컴포넌트 추가
        GameObject serverObject = new GameObject("SimServer");
        var server = serverObject.AddComponent<SimServer>();
        server._httpBaseUri = baseUri.ToString().TrimEnd('/');

        return Result<SimServer>.Success(server);
    }

    /// <summary>
    /// 모델 경로(예: base.obj)를 받아 서버로부터 OBJ/SDF 등의 원본 텍스트를 내려받는다.
    /// </summary>
    /// <exception cref="ArgumentException">모델 경로가 비어 있을 때</exception>
    /// <exception cref="OperationCanceledException">다운로드가 취소될 때</exception>
    /// <exception cref="InvalidOperationException">HTTP 에러가 발생했을 때</exception>
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

    private string BuildResourcesUrl(string modelPath)
    {
        var sanitizedPath = modelPath.Trim().TrimStart('/');
        var baseUri = new Uri(_httpBaseUri);
        var uri = new Uri(baseUri, $"cadverse/resources/{sanitizedPath}");
        return uri.ToString();
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

    /// <summary>
    /// WebSocket 연결을 시작한다. 자동 재접속이 활성화되어 있다면 연결이 끊어지면 자동으로 재연결을 시도한다.
    /// </summary>
    public async void ConnectWebSocket()
    {
        if (_isConnecting || IsWebSocketConnected)
        {
            Debug.LogWarning("WebSocket이 이미 연결 중이거나 연결되어 있습니다.");
            return;
        }

        _isConnecting = true;
        _shouldReconnect = true;

        try
        {
            await ConnectWebSocketInternal();
        }
        catch (Exception ex)
        {
            Debug.LogError($"WebSocket 연결 실패: {ex.Message}");
            OnWebSocketError?.Invoke(ex.Message);
            HandleReconnect();
        }
        finally
        {
            _isConnecting = false;
        }
    }

    /// <summary>
    /// WebSocket 연결을 종료하고 재접속을 중지한다.
    /// </summary>
    public async void DisconnectWebSocket()
    {
        _shouldReconnect = false;

        if (_reconnectCoroutine != null)
        {
            StopCoroutine(_reconnectCoroutine);
            _reconnectCoroutine = null;
        }

        if (_websocket != null)
        {
            if (_websocket.State == WebSocketState.Open)
            {
                await _websocket.Close();
            }
            _websocket = null;
        }
    }

    private async Task ConnectWebSocketInternal()
    {
        if (string.IsNullOrEmpty(_wsUrl))
        {
            _wsUrl = BuildWebSocketUrl();
        }

        Debug.Log($"WebSocket 연결 시도: {_wsUrl}");

        _websocket = new WebSocket(_wsUrl);

        _websocket.OnOpen += () =>
        {
            Debug.Log("WebSocket 연결됨");
            OnWebSocketConnected?.Invoke();
        };

        _websocket.OnMessage += (bytes) =>
        {
            string message = System.Text.Encoding.UTF8.GetString(bytes);
            HandleWebSocketMessage(message);
        };

        _websocket.OnError += (errorMsg) =>
        {
            Debug.LogError($"WebSocket 오류: {errorMsg}");
            OnWebSocketError?.Invoke(errorMsg);
        };

        _websocket.OnClose += (closeCode) =>
        {
            Debug.Log($"WebSocket 연결 종료 (코드: {closeCode})");
            OnWebSocketDisconnected?.Invoke();

            if (_shouldReconnect)
            {
                HandleReconnect();
            }
        };

        await _websocket.Connect();
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

    private void HandleWebSocketMessage(string message)
    {
        // 서버에서 보낸 위치/자세 데이터를 파싱하여 이벤트로 브로드캐스트
        // 현재는 서버가 텍스트 메시지를 보내고 있지만, 나중에 JSON 형식으로 변경 예정
        OnPoseDataReceived?.Invoke(message);
    }

    private void HandleReconnect()
    {
        if (!_shouldReconnect || _reconnectCoroutine != null)
        {
            return;
        }

        _reconnectCoroutine = StartCoroutine(ReconnectCoroutine());
    }

    private IEnumerator ReconnectCoroutine()
    {
        int attempts = 0;

        while (_shouldReconnect && attempts < maxReconnectAttempts)
        {
            yield return new WaitForSeconds(reconnectDelaySeconds);

            if (!_shouldReconnect)
            {
                break;
            }

            attempts++;
            Debug.Log($"WebSocket 재접속 시도 {attempts}/{maxReconnectAttempts}");

            _isConnecting = true;
            var task = ConnectWebSocketInternal();

            while (!task.IsCompleted)
            {
                yield return null;
            }

            _isConnecting = false;

            if (task.IsFaulted)
            {
                Debug.LogWarning($"재접속 실패: {task.Exception?.GetBaseException().Message}");
            }
            else if (task.IsCompletedSuccessfully && IsWebSocketConnected)
            {
                Debug.Log("WebSocket 재접속 성공");
                _reconnectCoroutine = null;
                yield break;
            }
        }

        if (attempts >= maxReconnectAttempts)
        {
            Debug.LogError("WebSocket 재접속 시도 횟수 초과");
            OnWebSocketError?.Invoke("재접속 시도 횟수 초과");
        }

        _reconnectCoroutine = null;
    }

    private void Update()
    {
#if !UNITY_WEBGL || UNITY_EDITOR
        _websocket?.DispatchMessageQueue();
#endif
    }

    private void OnDestroy()
    {
        DisconnectWebSocket();
    }
}
