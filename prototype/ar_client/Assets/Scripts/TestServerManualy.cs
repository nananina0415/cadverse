using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Networking;
using NativeWebSocket;
using TMPro;

public class TestServerManualy : MonoBehaviour
{
    [Header("Server Settings")]
    [SerializeField] private string serverHost = "localhost";
    [SerializeField] private int serverPort = 8000;

    [Header("UI References")]
    [SerializeField] private TMP_Text statusText;
    [SerializeField] private TMP_Text messagesText;
    [SerializeField] private ScrollRect scrollView;
    [SerializeField] private Button connectButton;
    [SerializeField] private Button disconnectButton;
    [SerializeField] private TMP_InputField messageInput;
    [SerializeField] private Button sendButton;
    [SerializeField] private Button httpTestButton;

    private WebSocket websocket;
    private string wsUrl;
    private string httpBaseUrl;

    void Start()
    {
        wsUrl = $"ws://{serverHost}:{serverPort}/cadverse/interaction";
        httpBaseUrl = $"http://{serverHost}:{serverPort}";

        connectButton.onClick.AddListener(OnConnectClicked);
        disconnectButton.onClick.AddListener(OnDisconnectClicked);
        sendButton.onClick.AddListener(OnSendClicked);
        if (httpTestButton != null)
            httpTestButton.onClick.AddListener(OnHttpTestClicked);

        UpdateUI("대기 중...", false);
        AppendMessage("서버 연결을 시작하세요.");
    }

    async void OnConnectClicked()
    {
        if (websocket != null && websocket.State == WebSocketState.Open)
        {
            AppendMessage("⚠️ 이미 연결되어 있습니다.");
            return;
        }

        try
        {
            UpdateUI("연결 중...", false);
            AppendMessage($"→ 연결 시도: {wsUrl}");

            websocket = new WebSocket(wsUrl);

            websocket.OnOpen += () =>
            {
                Debug.Log("WebSocket 연결됨");
                UpdateUI("✅ 연결됨!", true);
                AppendMessage("✅ WebSocket 연결 성공!");
            };

            websocket.OnMessage += (bytes) =>
            {
                string message = System.Text.Encoding.UTF8.GetString(bytes);
                Debug.Log($"수신: {message}");
                AppendMessage($"← 수신: {message}");
            };

            websocket.OnError += (errorMsg) =>
            {
                Debug.LogError($"WebSocket 오류: {errorMsg}");
                AppendMessage($"❌ 오류: {errorMsg}");
            };

            websocket.OnClose += (closeCode) =>
            {
                Debug.Log("WebSocket 연결 종료");
                UpdateUI("연결 해제됨", false);
                AppendMessage("← 연결 종료됨");
            };

            await websocket.Connect();
        }
        catch (Exception e)
        {
            Debug.LogError($"연결 실패: {e.Message}");
            UpdateUI("❌ 연결 실패", false);
            AppendMessage($"❌ 연결 실패: {e.Message}");
        }
    }

    async void OnDisconnectClicked()
    {
        if (websocket == null || websocket.State != WebSocketState.Open)
        {
            AppendMessage("⚠️ 연결되어 있지 않습니다.");
            return;
        }

        try
        {
            UpdateUI("연결 해제 중...", false);
            AppendMessage("→ 연결 해제 중...");
            await websocket.Close();
        }
        catch (Exception e)
        {
            Debug.LogError($"연결 해제 오류: {e.Message}");
            AppendMessage($"❌ 해제 오류: {e.Message}");
        }
    }

    async void OnSendClicked()
    {
        if (websocket == null || websocket.State != WebSocketState.Open)
        {
            AppendMessage("⚠️ 먼저 서버에 연결하세요.");
            return;
        }

        string message = messageInput.text.Trim();

        if (string.IsNullOrEmpty(message))
        {
            AppendMessage("⚠️ 메시지를 입력하세요.");
            return;
        }

        try
        {
            await websocket.SendText(message);
            AppendMessage($"→ 전송: {message}");
            Debug.Log($"전송: {message}");
            messageInput.text = "";
        }
        catch (Exception e)
        {
            Debug.LogError($"전송 실패: {e.Message}");
            AppendMessage($"❌ 전송 실패: {e.Message}");
        }
    }

    void OnHttpTestClicked()
    {
        StartCoroutine(TestHttpGet("base.obj"));
    }

    IEnumerator TestHttpGet(string fileName)
    {
        string url = $"{httpBaseUrl}/cadverse/resources/{fileName}";
        AppendMessage($"→ HTTP GET: {url}");

        using (UnityWebRequest request = UnityWebRequest.Get(url))
        {
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                string content = request.downloadHandler.text;
                string[] lines = content.Split('\n');
                int lineCount = Mathf.Min(10, lines.Length);

                AppendMessage($"✅ HTTP 성공 ({fileName}):");
                for (int i = 0; i < lineCount; i++)
                {
                    AppendMessage($"  {i + 1}: {lines[i]}");
                }

                if (lines.Length > 10)
                {
                    AppendMessage($"  ... (총 {lines.Length}줄 중 10줄 표시)");
                }
            }
            else
            {
                AppendMessage($"❌ HTTP 실패: {request.error}");
            }
        }
    }

    void UpdateUI(string status, bool isConnected)
    {
        statusText.text = status;
        connectButton.interactable = !isConnected;
        disconnectButton.interactable = isConnected;
        sendButton.interactable = isConnected;
    }

    void AppendMessage(string message)
    {
        string timestamp = DateTime.Now.ToString("HH:mm:ss");
        messagesText.text += $"[{timestamp}] {message}\n";

        if (scrollView != null)
        {
            Canvas.ForceUpdateCanvases();
            scrollView.verticalNormalizedPosition = 0f;
        }
    }

    void Update()
    {
#if !UNITY_WEBGL || UNITY_EDITOR
        websocket?.DispatchMessageQueue();
#endif
    }

    async void OnDestroy()
    {
        if (websocket != null && websocket.State == WebSocketState.Open)
        {
            await websocket.Close();
        }
    }
}
