using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using UnityEngine;
using CADverse.Connection;
using CADverse.Utils;

namespace CADverse.Communication
{
    /// <summary>
    /// 시뮬레이션 서버와의 통신을 캡슐화하는 고수준 래퍼 클래스
    /// - QR 코드로부터 서버 연결
    /// - 모델 리소스 다운로드 및 파싱
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
        private float _lastSimTime = -1f;  // 마지막 수신한 sim_time

        [Header("QR Scanner")]
        [SerializeField] private QrScanner qrScanner;

        [Header("WebSocket Settings")]
        [SerializeField] private float reconnectDelaySeconds = 3f;
        [SerializeField] private int maxReconnectAttempts = 10;

        // 이벤트
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
        /// </summary>
        public async void ConnectByQrScan()
        {
            if (qrScanner == null)
            {
                Debug.LogError("[SimServer] QrScanner가 설정되지 않았습니다.");
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

                // QR 스캔
                var cts = new CancellationTokenSource();
                string qrPayload = await qrScanner.ScanOnceAsync(cts.Token);

                Debug.Log($"[SimServer] QR 스캔 완료: {qrPayload}");
                OnQrScanCompleted?.Invoke(qrPayload);

                // QR 코드 파싱 (QrCommunication로 위임)
                var parseResult = QrCommunication.ParseQrPayload(qrPayload);
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
            var parseResult = QrCommunication.ParseQrPayload(qrPayload);
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
        /// 서버에 연결하고 WebSocket 통신을 시작한다.
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
        /// 서버 연결을 해제한다.
        /// </summary>
        public async void Disconnect()
        {
            await DisconnectAsync();
        }

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
        /// 원시 JSON 문자열을 서버로 전송한다.
        /// </summary>
        public async void SendRawMessage(string json)
        {
            if (!IsConnected)
            {
                Debug.LogWarning("[SimServer] 서버 연결되지 않음");
                return;
            }

            try
            {
                await _wsConnection.SendTextAsync(json);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[SimServer] 메시지 전송 실패: {ex.Message}");
                OnError?.Invoke(ex.Message);
            }
        }

        /// <summary>
        /// 서버로부터 sim_contents.json을 다운로드하고 모든 파트를 로드하여 CompositeModel을 반환한다.
        /// </summary>
        public async System.Threading.Tasks.Task<CompositeModel> LoadModel()
        {
            if (_httpConnection == null)
            {
                throw new InvalidOperationException("HttpConnection이 초기화되지 않았습니다.");
            }

            // 1. sim_contents.json 다운로드
            string jsonPath = "/cadverse/resources/sim_contents.json";
            Debug.Log($"[SimServer] JSON 다운로드 시작: {jsonPath}");

            string jsonText = await _httpConnection.GetTextAsync(jsonPath);
            Debug.Log($"[SimServer] JSON 다운로드 완료: {jsonText.Length} bytes");

            // 2. JSON 파싱
            var simContents = SimContents.FromJson(jsonText);
            Debug.Log($"[SimServer] Assemblies 수: {simContents.assemblies.Count}");

            // 3. CompositeModel 생성
            CompositeModel compositeModel = new GameObject("CompositeModel").AddComponent<CompositeModel>();

            // 4. 각 assembly의 모든 파트 로드
            foreach (var assembly in simContents.assemblies)
            {
                Debug.Log($"[SimServer] Assembly '{assembly.type}' 파트 수: {assembly.parts.Count}");

                foreach (var partInfo in assembly.parts)
                {
                    if (partInfo != null && !string.IsNullOrEmpty(partInfo.mesh))
                    {
                        // OBJ 파일 로드
                        GameObject partObj = await LoadObjPart(partInfo.mesh, partInfo.name);

                        // Wrapper 생성 (오프셋용, scale 영향 안받음)
                        GameObject partWrapper = new GameObject($"{partInfo.name}_wrapper");

                        // Wrapper를 CompositeModel에 추가
                        compositeModel.AddPart(partWrapper);

                        // 실제 메쉬를 Wrapper의 자식으로 (scale 적용)
                        partObj.transform.SetParent(partWrapper.transform, false);
                        partObj.transform.localPosition = Vector3.zero;
                        partObj.transform.localRotation = Quaternion.identity;
                        partObj.transform.localScale = Vector3.one; // CompositeModel의 0.001 scale 상속받음

                        // MeshCollider 추가 (레이캐스트용)
                        MeshCollider collider = partObj.AddComponent<MeshCollider>();
                        collider.convex = false;  // 정밀한 충돌 감지
                        Debug.Log($"[SimServer] '{partInfo.name}' MeshCollider 추가 완료");

                        // Wrapper에 오프셋 적용 (이미 보정된 값)
                        if (partInfo.offset != null && partInfo.offset.Length == 3)
                        {
                            partWrapper.transform.localPosition = new Vector3(
                                partInfo.offset[0],
                                partInfo.offset[1],
                                partInfo.offset[2]
                            );
                            Debug.Log($"[SimServer] '{partInfo.name}' offset 적용: localPos = {partWrapper.transform.localPosition}");
                        }

                        Debug.Log($"[SimServer] '{partInfo.name}' 로드 완료, wrapper localPos: {partWrapper.transform.localPosition}");
                    }
                }
            }

            Debug.Log($"[SimServer] CompositeModel 생성 완료 - 총 {compositeModel.GetPartCount()} 파트");
            return compositeModel;
        }

        /// <summary>
        /// 단일 OBJ 파일을 다운로드하고 GameObject로 파싱
        /// </summary>
        private async System.Threading.Tasks.Task<GameObject> LoadObjPart(string meshFilename, string partName)
        {
            string objPath = $"/cadverse/resources/{meshFilename}";
            Debug.Log($"[SimServer] OBJ 다운로드 시작: {objPath}");

            string objText = await _httpConnection.GetTextAsync(objPath);
            Debug.Log($"[SimServer] OBJ 다운로드 완료: {meshFilename} ({objText.Length} bytes)");

            GameObject partObject = ObjCommunication.ParseToGameObject(objText, partName);
            return partObject;
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

        // ===== 연결 생성 =====

        private void CreateConnections(string host, int port)
        {
            string httpUrl = $"http://{host}:{port}";
            string wsUrl = $"ws://{host}:{port}/cadverse/interaction";

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
            _wsConnection?.DispatchMessageQueue();
        }

        private void OnDestroy()
        {
            Disconnect();
        }
    }

    /// <summary>
    /// sim_contents.json 파싱용 데이터 구조
    /// </summary>
    [Serializable]
    public class SimContents
    {
        public List<Assembly> assemblies = new List<Assembly>();

        public static SimContents FromJson(string json)
        {
            return JsonUtility.FromJson<SimContents>(json);
        }
    }

    [Serializable]
    public class Assembly
    {
        public string type;
        public List<PartInfo> parts = new List<PartInfo>();
        public float motor_speed;
    }

    [Serializable]
    public class PartInfo
    {
        public string name;
        public string mesh;
        public float mass;
        public bool fixed_;
        public string motor_name;
        public float[] offset;
    }
}
