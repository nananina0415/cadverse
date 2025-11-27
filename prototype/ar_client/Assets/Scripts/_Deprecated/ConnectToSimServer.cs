using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using TMPro;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.UI;

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

/// <summary>
/// QR 스캔 버튼에서 호출되어 SimServer 인스턴스를 생성하는 컨트롤러.
/// </summary>
public sealed class ConnectToSimServer : MonoBehaviour
{
    [Header("Dependencies")]
    [SerializeField] private QrScanner qrScanner;
    [SerializeField] private Button scanButton;
    [SerializeField] private TMP_Text statusLabel;

    [Header("Events")]
    [SerializeField] private UnityEvent onConnectionStarted;
    [SerializeField] private UnityEvent onConnectionSucceeded;
    [SerializeField] private UnityEvent onConnectionCanceled;
    [SerializeField] private StringEvent onConnectionFailed;
    [SerializeField] private StringEvent onQrPayloadRead;
    [SerializeField] private StringEvent onServerReady;

    [Header("Behaviour")]
    [SerializeField] private float scanCancelAfterSeconds = 20f;

    public SimServer CurrentServer { get; private set; }
    public string LastQrPayload { get; private set; }

    public event Action<SimServer> ServerConnected;
    public event Action<string> ConnectionFailed;

    private bool _isConnecting;
    private CancellationTokenSource _connectionCts;

    private void Awake()
    {
        if (scanButton != null)
        {
            scanButton.onClick.AddListener(ConnectToServerViaQr);
        }
    }

    public async void ConnectToServerViaQr()
    {
        // 이미 스캔 중이면 취소
        if (_isConnecting)
        {
            Debug.Log("QR 스캔 취소 중...");
            CancelCurrentScan();
            return;
        }

        if (qrScanner == null)
        {
            Debug.LogError("QrScanner 참조가 필요합니다.");
            return;
        }

        _isConnecting = true;
        SetInteractable(true); // 취소를 위해 버튼은 활성화 유지
        SetStatus("QR 스캔 중... (다시 클릭하여 취소)");

        onConnectionStarted?.Invoke();

        _connectionCts = new CancellationTokenSource();
        if (scanCancelAfterSeconds > 0f)
        {
            _connectionCts.CancelAfter(TimeSpan.FromSeconds(scanCancelAfterSeconds));
        }

        try
        {
            string payload = await qrScanner.ScanOnceAsync(_connectionCts.Token);
            LastQrPayload = payload;
            onQrPayloadRead?.Invoke(payload);

            var createResult = TryCreateServerFromPayload(payload);
            if (!createResult.IsSuccess)
            {
                HandleFailure(createResult.Error);
                return;
            }

            var server = createResult.Value;
            CurrentServer = server;
            ServerConnected?.Invoke(server);
            onServerReady?.Invoke(server.HttpBaseUrl);

            // WebSocket 연결 시작
            server.ConnectWebSocket();

            SetStatus("SimServer 연결 준비됨 (WebSocket 연결 중...)");
            onConnectionSucceeded?.Invoke();
        }
        catch (OperationCanceledException)
        {
            SetStatus("QR 스캔이 취소되었습니다.");
            onConnectionCanceled?.Invoke();
        }
        catch (Exception ex)
        {
            HandleFailure($"QR 스캔 실패: {ex.Message}");
        }
        finally
        {
            _connectionCts?.Dispose();
            _connectionCts = null;
            SetInteractable(true);
            _isConnecting = false;
        }
    }

    private void CancelCurrentScan()
    {
        if (qrScanner != null && qrScanner.IsScanning)
        {
            qrScanner.CancelScan();
        }

        _connectionCts?.Cancel();
        _connectionCts?.Dispose();
        _connectionCts = null;

        SetStatus("QR 스캔이 취소되었습니다.");
        onConnectionCanceled?.Invoke();
        SetInteractable(true);
        _isConnecting = false;
    }

    private void HandleFailure(string reason)
    {
        Debug.LogError(reason);
        SetStatus(reason);
        onConnectionFailed?.Invoke(reason);
        ConnectionFailed?.Invoke(reason);
    }

    private void SetStatus(string status)
    {
        if (statusLabel != null)
        {
            statusLabel.text = status;
        }
    }

    private void SetInteractable(bool value)
    {
        if (scanButton != null)
        {
            scanButton.interactable = value;
        }
    }

    private Result<SimServer> TryCreateServerFromPayload(string payload)
    {
        if (string.IsNullOrWhiteSpace(payload))
        {
            return Result<SimServer>.Failure("QR 데이터가 비어 있습니다.");
        }

        string trimmed = payload.Trim();

        // IP:포트 형식 파싱 (스키마 없이)
        var parseResult = TryParseAddress(trimmed);
        if (!parseResult.IsSuccess)
        {
            return Result<SimServer>.Failure($"유효하지 않은 주소 형식: {payload}");
        }

        var addressInfo = parseResult.Value;

        if (!IsLocalNetworkAddress(addressInfo.Host))
        {
            return Result<SimServer>.Failure("허용되는 로컬 IP 주소가 아닙니다.");
        }

        if (!IsCadversePath(addressInfo.Path))
        {
            return Result<SimServer>.Failure("QR 경로에 /cadverse 가 필요합니다.");
        }

        // SimServer.TryCreateFromQrPayload에 원본 payload 전달 (스키마 없이)
        return SimServer.TryCreateFromQrPayload(trimmed);
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
}

[Serializable]
public sealed class StringEvent : UnityEvent<string>
{
}

