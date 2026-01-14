using System;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using CADverse.Server;
using CADverse.Server.DataModel;
using CADverse.QRScan;

namespace CADverse.Manager
{
    /// <summary>
    /// 앱의 메인 매니저
    /// 서버 연결, QR 스캔, 시뮬레이션 상태 관리
    /// </summary>
    public class MainManager : MonoBehaviour
    {
        [Header("UI References")]
        [SerializeField] private Button connectButton;
        [SerializeField] private GameObject qrScannerPanel;
        [SerializeField] private TMP_Text statusText;

        [Header("Components")]
        [SerializeField] private QRScanner qrScanner;

        // 서버 프록시
        public ServerProxy Server { get; private set; }

        // 연결 상태
        public bool IsConnected => Server != null && Server.IsConnected;

        private void Awake()
        {
            // 버튼 이벤트 등록
            if (connectButton != null)
            {
                connectButton.onClick.AddListener(OnConnectButtonClicked);
            }

            // QR 스캐너 이벤트 등록
            if (qrScanner != null)
            {
                qrScanner.OnQRCodeDetected += OnQRCodeDetected;
                qrScanner.OnScanError += OnQRScanError;
            }

            // 초기 상태
            if (qrScannerPanel != null)
            {
                qrScannerPanel.SetActive(false);
            }

            UpdateStatusText("서버 연결 버튼을 눌러주세요");
        }

        /// <summary>
        /// 연결 버튼 클릭
        /// </summary>
        private void OnConnectButtonClicked()
        {
            if (IsConnected)
            {
                // 이미 연결되어 있으면 연결 해제
                DisconnectFromServer();
            }
            else
            {
                // QR 스캔 시작
                StartQRScan();
            }
        }

        /// <summary>
        /// QR 스캔 시작
        /// </summary>
        private void StartQRScan()
        {
            Debug.Log("[MainManager] Starting QR scan");

            // QR 스캐너 UI 표시
            if (qrScannerPanel != null)
            {
                qrScannerPanel.SetActive(true);
            }

            // 스캔 시작
            if (qrScanner != null)
            {
                qrScanner.StartScanning();
                UpdateStatusText("QR 코드를 카메라에 비춰주세요");
            }
            else
            {
                Debug.LogError("[MainManager] QR Scanner not found!");
                UpdateStatusText("에러: QR 스캐너를 찾을 수 없습니다");
            }
        }

        /// <summary>
        /// QR 코드 인식 콜백
        /// </summary>
        private async void OnQRCodeDetected(string qrData)
        {
            Debug.Log($"[MainManager] QR detected: {qrData}");

            // QR 스캐너 UI 숨기기
            if (qrScannerPanel != null)
            {
                qrScannerPanel.SetActive(false);
            }

            // QR 데이터 파싱 (ip:port 형식)
            if (!TryParseServerInfo(qrData, out string ip, out int port))
            {
                UpdateStatusText($"에러: 잘못된 QR 코드 형식\n{qrData}");
                return;
            }

            // 서버 연결 시도
            await ConnectToServer(ip, port);
        }

        /// <summary>
        /// QR 스캔 에러 콜백
        /// </summary>
        private void OnQRScanError(string error)
        {
            Debug.LogError($"[MainManager] QR scan error: {error}");
            UpdateStatusText($"QR 스캔 에러: {error}");
        }

        /// <summary>
        /// 서버 연결
        /// </summary>
        private async System.Threading.Tasks.Task ConnectToServer(string ip, int port)
        {
            try
            {
                UpdateStatusText($"서버 연결 중...\n{ip}:{port}");

                // ServerProxy 생성
                Server = ServerProxy.Create(ip, port);

                // 이벤트 등록
                Server.OnConnected += OnServerConnected;
                Server.OnDisconnected += OnServerDisconnected;
                Server.OnError += OnServerError;
                Server.OnStateReceived += OnSimulationStateReceived;

                // 연결 시도
                await Server.Connect();
            }
            catch (Exception e)
            {
                Debug.LogError($"[MainManager] Connection failed: {e.Message}");
                UpdateStatusText($"연결 실패: {e.Message}");

                // 서버 객체 정리
                if (Server != null)
                {
                    Destroy(Server.gameObject);
                    Server = null;
                }
            }
        }

        /// <summary>
        /// 서버 연결 해제
        /// </summary>
        private async void DisconnectFromServer()
        {
            if (Server == null)
            {
                return;
            }

            UpdateStatusText("연결 해제 중...");

            try
            {
                await Server.Disconnect();
            }
            catch (Exception e)
            {
                Debug.LogError($"[MainManager] Disconnect error: {e.Message}");
            }
            finally
            {
                if (Server != null)
                {
                    Destroy(Server.gameObject);
                    Server = null;
                }

                UpdateStatusText("연결 해제됨");
                UpdateConnectButton("서버 연결");
            }
        }

        // === 서버 이벤트 핸들러 ===

        private void OnServerConnected()
        {
            Debug.Log("[MainManager] Server connected!");
            UpdateStatusText("서버 연결 성공!");
            UpdateConnectButton("연결 해제");
        }

        private void OnServerDisconnected()
        {
            Debug.Log("[MainManager] Server disconnected");
            UpdateStatusText("서버 연결이 끊어졌습니다");
            UpdateConnectButton("서버 연결");
        }

        private void OnServerError(string error)
        {
            Debug.LogError($"[MainManager] Server error: {error}");
            UpdateStatusText($"서버 에러: {error}");
        }

        private void OnSimulationStateReceived(SimulationState state)
        {
            // TODO: 시뮬레이션 상태 업데이트
            Debug.Log($"[MainManager] Received state: {state.objects.Length} objects at t={state.timestamp}");
        }

        // === UI 업데이트 ===

        private void UpdateStatusText(string message)
        {
            if (statusText != null)
            {
                statusText.text = message;
            }

            Debug.Log($"[MainManager] Status: {message}");
        }

        private void UpdateConnectButton(string label)
        {
            if (connectButton != null && connectButton.GetComponentInChildren<TMP_Text>() != null)
            {
                connectButton.GetComponentInChildren<TMP_Text>().text = label;
            }
        }

        // === 유틸리티 ===

        /// <summary>
        /// QR 데이터를 IP와 포트로 파싱
        /// </summary>
        private bool TryParseServerInfo(string qrData, out string ip, out int port)
        {
            ip = null;
            port = 0;

            if (string.IsNullOrEmpty(qrData))
            {
                return false;
            }

            // ip:port 형식 파싱
            var parts = qrData.Split(':');
            if (parts.Length != 2)
            {
                return false;
            }

            ip = parts[0].Trim();

            if (!int.TryParse(parts[1].Trim(), out port))
            {
                return false;
            }

            return !string.IsNullOrEmpty(ip) && port > 0 && port <= 65535;
        }

        private void OnDestroy()
        {
            // 서버 연결 정리
            if (Server != null)
            {
                _ = Server.Disconnect();
            }
        }
    }
}
