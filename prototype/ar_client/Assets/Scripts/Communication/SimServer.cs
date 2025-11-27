using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using UnityEngine;
using CADverse.Connection;
using CADverse.Utils;

namespace CADverse.Communication
{
    /// <summary>
    /// 시뮬레이션 서버와의 통신을 캡슐화하는 고수준 래퍼 클래스
    /// - QR 코드로부터 서버 연결 (QR 파싱 포함)
    /// - 모델 리소스 다운로드
    /// - 실시간 모델 상태 수신
    /// - 사용자 입력 전송
    /// - 자동 재접속 관리
    /// </summary>
    public class SimServer : MonoBehaviour
    {
        private HttpConnection _httpConnection;
        private WebSocketConnection _wsConnection;
        private List<PartState> _latestModelState = new List<PartState>();
        private readonly object _stateLock = new object();
        private bool _shouldReconnect = true;
        private Coroutine _reconnectCoroutine;

        [Header("QR Scanner")]
        [SerializeField] private QrScanner qrScanner;

        [Header("WebSocket Settings")]
        [SerializeField] private float reconnectDelaySeconds = 3f;
        [SerializeField] private int maxReconnectAttempts = 10;

        // 이벤트
        public event Action<List<PartState>> OnModelStateReceived;
        public event Action OnConnected;
        public event Action OnDisconnected;
        public event Action<string> OnError;
        public event Action OnQrScanStarted;
        public event Action<string> OnQrScanCompleted;

        // 상태 프로퍼티
        public bool IsConnected => _wsConnection != null && _wsConnection.IsConnected;
        public string ServerAddress => _httpConnection?.BaseUrl;

        /// <summary>
        /// QR 스캔을 시작하여 서버에 연결한다. (공개 API)
        /// QrScanner가 설정되어 있어야 한다.
        /// 카메라가 실행되고, QR 코드를 찍으면 자동으로 서버에 연결한다.
        /// 이미 연결되어 있으면 기존 연결을 끊고 새로 연결한다.
        /// </summary>
        public async void ConnectByQrScan()
        {
            if (qrScanner == null)
            {
                Debug.LogError("[SimServer] QrScanner가 설정되지 않았습니다. Inspector에서 QrScanner를 할당하세요.");
                OnError?.Invoke("QrScanner가 설정되지 않음");
                return;
            }

            // 기존 연결 해제
            if (IsConnected)
            {
                Debug.Log("[SimServer] 기존 연결 해제 중...");
                await DisconnectAsync();
            }

            try
            {
                Debug.Log("[SimServer] QR 스캔 시작");
                OnQrScanStarted?.Invoke();

                // QR 스캔 (카메라 실행 → QR 인식 → 문자열 반환)
                var cts = new CancellationTokenSource();
                string qrPayload = await qrScanner.ScanOnceAsync(cts.Token);

                Debug.Log($"[SimServer] QR 스캔 완료: {qrPayload}");
                OnQrScanCompleted?.Invoke(qrPayload);

                // QR 코드 파싱 및 연결 (고수준에서 처리)
                var parseResult = TryParseQrPayload(qrPayload);
                if (!parseResult.IsSuccess)
                {
                    Debug.LogError($"[SimServer] QR 코드 파싱 실패: {parseResult.Error}");
                    OnError?.Invoke(parseResult.Error);
                    return;
                }

                var addressInfo = parseResult.Value;
                CreateConnections(addressInfo.Host, addressInfo.Port);
                Connect();
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] QR 스캔 실패: {ex.Message}");
                OnError?.Invoke(ex.Message);
            }
        }

        /// <summary>
        /// QR 코드 문자열로 직접 서버에 연결한다. (테스트/디버깅용)
        /// </summary>
        public void ConnectByQrCode(string qrPayload)
        {
            var parseResult = TryParseQrPayload(qrPayload);
            if (!parseResult.IsSuccess)
            {
                Debug.LogError($"[SimServer] QR 코드 파싱 실패: {parseResult.Error}");
                OnError?.Invoke(parseResult.Error);
                return;
            }

            var addressInfo = parseResult.Value;
            CreateConnections(addressInfo.Host, addressInfo.Port);
            Connect();
        }

        /// <summary>
        /// 서버에 연결하고 WebSocket 통신을 시작한다. (내부 연결 관리용)
        /// </summary>
        private async void Connect()
        {
            if (_wsConnection == null)
            {
                Debug.LogError("[SimServer] WebSocketConnection이 초기화되지 않았습니다.");
                return;
            }

            _shouldReconnect = true;

            try
            {
                // WebSocket 이벤트 핸들러 등록
                _wsConnection.OnConnected += HandleConnected;
                _wsConnection.OnDisconnected += HandleDisconnected;
                _wsConnection.OnError += HandleError;
                _wsConnection.OnMessageReceived += HandleMessage;

                await _wsConnection.ConnectAsync();
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] 연결 실패: {ex.Message}");
                OnError?.Invoke(ex.Message);
                HandleReconnect();
            }
        }

        /// <summary>
        /// 서버 연결을 해제한다. (동기)
        /// </summary>
        public async void Disconnect()
        {
            await DisconnectAsync();
        }

        /// <summary>
        /// 서버 연결을 해제한다. (비동기)
        /// </summary>
        private async System.Threading.Tasks.Task DisconnectAsync()
        {
            _shouldReconnect = false;

            if (_reconnectCoroutine != null)
            {
                StopCoroutine(_reconnectCoroutine);
                _reconnectCoroutine = null;
            }

            if (_wsConnection != null)
            {
                _wsConnection.OnConnected -= HandleConnected;
                _wsConnection.OnDisconnected -= HandleDisconnected;
                _wsConnection.OnError -= HandleError;
                _wsConnection.OnMessageReceived -= HandleMessage;

                await _wsConnection.DisconnectAsync();
            }

            _httpConnection?.Dispose();
            _wsConnection?.Dispose();
        }

        /// <summary>
        /// 서버로 사용자 입력을 전송한다.
        /// </summary>
        public async void SendUserInput(Vector3 point, Vector3 direction)
        {
            if (!IsConnected)
            {
                Debug.LogWarning("[SimServer] 서버 연결되지 않음");
                return;
            }

            var message = new UserInputMessage(point, direction);
            string json = message.ToJson();

            try
            {
                await _wsConnection.SendTextAsync(json);
                Debug.Log($"[SimServer] 사용자 입력 전송: {json}");
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] 사용자 입력 전송 실패: {ex.Message}");
                OnError?.Invoke(ex.Message);
            }
        }

        /// <summary>
        /// 서버로부터 모델 파일을 다운로드한다.
        /// </summary>
        public async void LoadModel(string modelPath, Action<string> onSuccess, Action<string> onError)
        {
            if (_httpConnection == null)
            {
                onError?.Invoke("HttpConnection이 초기화되지 않았습니다.");
                return;
            }

            try
            {
                string modelData = await _httpConnection.GetTextAsync(modelPath);
                onSuccess?.Invoke(modelData);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] 모델 로드 실패: {ex.Message}");
                onError?.Invoke(ex.Message);
            }
        }

        /// <summary>
        /// 최신 모델 상태 가져오기 (스레드 안전)
        /// </summary>
        public List<PartState> GetLatestModelState()
        {
            lock (_stateLock)
            {
                return new List<PartState>(_latestModelState);
            }
        }

        /// <summary>
        /// 특정 인덱스의 파트 상태 가져오기
        /// </summary>
        public PartState GetPartState(int index)
        {
            lock (_stateLock)
            {
                if (index >= 0 && index < _latestModelState.Count)
                {
                    return _latestModelState[index];
                }
                return null;
            }
        }

        /// <summary>
        /// 파트 개수 가져오기
        /// </summary>
        public int GetPartCount()
        {
            lock (_stateLock)
            {
                return _latestModelState.Count;
            }
        }

        // ===== QR 파싱 로직 (고수준에서 처리) =====

        private Result<AddressInfo> TryParseQrPayload(string qrPayload)
        {
            if (string.IsNullOrWhiteSpace(qrPayload))
            {
                return Result<AddressInfo>.Failure("QR 데이터가 비어 있습니다.");
            }

            string trimmed = qrPayload.Trim();

            // 주소 파싱
            var parseResult = TryParseAddress(trimmed);
            if (!parseResult.IsSuccess)
            {
                return Result<AddressInfo>.Failure($"유효하지 않은 주소 형식: {qrPayload}");
            }

            var addressInfo = parseResult.Value;

            // 보안 검증: 로컬 네트워크만 허용
            if (!IsLocalNetworkAddress(addressInfo.Host))
            {
                return Result<AddressInfo>.Failure("허용되는 로컬 IP 주소가 아닙니다.");
            }

            // 경로 검증: /cadverse 경로 확인
            if (!IsCadversePath(addressInfo.Path))
            {
                return Result<AddressInfo>.Failure("QR 경로에 /cadverse 가 필요합니다.");
            }

            return Result<AddressInfo>.Success(addressInfo);
        }

        private static Result<AddressInfo> TryParseAddress(string address)
        {
            // 경로 분리
            int pathIndex = address.IndexOf('/');
            string addressPart = pathIndex >= 0 ? address.Substring(0, pathIndex) : address;
            string path = pathIndex >= 0 ? address.Substring(pathIndex) : "/";

            // 포트 분리
            int portIndex = addressPart.LastIndexOf(':');
            if (portIndex < 0)
            {
                return Result<AddressInfo>.Failure("포트 정보가 없습니다.");
            }

            string host = addressPart.Substring(0, portIndex);
            if (!int.TryParse(addressPart.Substring(portIndex + 1), out int port))
            {
                return Result<AddressInfo>.Failure("포트 번호가 유효하지 않습니다.");
            }

            if (string.IsNullOrEmpty(host))
            {
                return Result<AddressInfo>.Failure("호스트 주소가 비어 있습니다.");
            }

            if (port <= 0 || port > 65535)
            {
                return Result<AddressInfo>.Failure("포트 번호는 1-65535 범위여야 합니다.");
            }

            return Result<AddressInfo>.Success(new AddressInfo(host, port, path));
        }

        private static bool IsCadversePath(string path)
        {
            var normalizedPath = path?.TrimEnd('/');
            return string.Equals(normalizedPath, "/cadverse", StringComparison.OrdinalIgnoreCase);
        }

        private static bool IsLocalNetworkAddress(string host)
        {
            if (string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (!IPAddress.TryParse(host, out var address))
            {
                return false;
            }

            if (address.AddressFamily != AddressFamily.InterNetwork)
            {
                return false;
            }

            var octets = address.GetAddressBytes();
            return
                octets[0] == 10 ||
                (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) ||
                (octets[0] == 192 && octets[1] == 168) ||
                octets[0] == 127;
        }

        // ===== 연결 생성 =====

        private void CreateConnections(string host, int port)
        {
            string httpUrl = $"http://{host}:{port}";
            string wsUrl = $"ws://{host}:{port}/ws";

            _httpConnection?.Dispose();
            _wsConnection?.Dispose();

            _httpConnection = new HttpConnection(httpUrl);
            _wsConnection = new WebSocketConnection(wsUrl);

            Debug.Log($"[SimServer] 연결 생성: HTTP={httpUrl}, WS={wsUrl}");
        }

        // ===== 이벤트 핸들러 =====

        private void HandleConnected()
        {
            Debug.Log("[SimServer] 서버 연결 성공");
            OnConnected?.Invoke();
        }

        private void HandleDisconnected()
        {
            Debug.Log("[SimServer] 서버 연결 종료");
            OnDisconnected?.Invoke();

            if (_shouldReconnect)
            {
                HandleReconnect();
            }
        }

        private void HandleError(string error)
        {
            Debug.LogError($"[SimServer] 에러: {error}");
            OnError?.Invoke(error);
        }

        private void HandleMessage(byte[] bytes)
        {
            try
            {
                string json = System.Text.Encoding.UTF8.GetString(bytes);
                var message = ModelStateMessage.FromJson(json);

                lock (_stateLock)
                {
                    _latestModelState = message.parts;
                }

                OnModelStateReceived?.Invoke(message.parts);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] 메시지 파싱 에러: {ex.Message}");
                OnError?.Invoke(ex.Message);
            }
        }

        // ===== 재접속 로직 =====

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
                Debug.Log($"[SimServer] WebSocket 재접속 시도 {attempts}/{maxReconnectAttempts}");

                var task = _wsConnection.ConnectAsync();

                while (!task.IsCompleted)
                {
                    yield return null;
                }

                if (task.IsFaulted)
                {
                    Debug.LogWarning($"[SimServer] 재접속 실패: {task.Exception?.GetBaseException().Message}");
                }
                else if (task.IsCompletedSuccessfully && IsConnected)
                {
                    Debug.Log("[SimServer] WebSocket 재접속 성공");
                    _reconnectCoroutine = null;
                    yield break;
                }
            }

            if (attempts >= maxReconnectAttempts)
            {
                Debug.LogError("[SimServer] WebSocket 재접속 시도 횟수 초과");
                OnError?.Invoke("재접속 시도 횟수 초과");
            }

            _reconnectCoroutine = null;
        }

        // ===== Unity 라이프사이클 =====

        private void Update()
        {
            // WebSocket 메시지 큐 처리
            _wsConnection?.DispatchMessageQueue();
        }

        private void OnDestroy()
        {
            Disconnect();
        }
    }

    // ===== 내부 데이터 구조 =====

    internal readonly struct AddressInfo
    {
        public readonly string Host;
        public readonly int Port;
        public readonly string Path;

        public AddressInfo(string host, int port, string path)
        {
            Host = host;
            Port = port;
            Path = path;
        }
    }
}
