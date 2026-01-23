using System;
using System.Collections;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Networking;
using NativeWebSocket;
using System.Collections.Generic;
using TMPro;

public class TestServerManualy : MonoBehaviour
{
    [Header("Server Settings")]
    [SerializeField] private string serverHost = "localhost";
    [SerializeField] private int serverPort = 8000;

    [Header("UI References")]
    [SerializeField] private TMP_Text statusText;
    [SerializeField] private TMP_Text messagesText;
    [SerializeField] private Button connectButton;
    [SerializeField] private Button disconnectButton;
    [SerializeField] private TMP_InputField messageInput;
    [SerializeField] private Button sendButton;
    [SerializeField] private Button httpTestButton;

    private WebSocket websocket;
    private string wsUrl;
    private string httpBaseUrl;
    private GameObject loadedObject = null;

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
            AppendMessage("[!] 이미 연결되어 있습니다.");
            return;
        }

        try
        {
            UpdateUI("연결 중...", false);
            AppendMessage($"-> 연결 시도: {wsUrl}");

            websocket = new WebSocket(wsUrl);

            websocket.OnOpen += () =>
            {
                Debug.Log("WebSocket 연결됨");
                UpdateUI("[OK] 연결됨!", true);
                AppendMessage("[OK] WebSocket 연결 성공!");
            };

            websocket.OnMessage += (bytes) =>
            {
                string message = System.Text.Encoding.UTF8.GetString(bytes);
                Debug.Log($"수신: {message}");
                AppendMessage($"<- 수신: {message}");
            };

            websocket.OnError += (errorMsg) =>
            {
                Debug.LogError($"WebSocket 오류: {errorMsg}");
                AppendMessage($"[X] 오류: {errorMsg}");
            };

            websocket.OnClose += (closeCode) =>
            {
                Debug.Log("WebSocket 연결 종료");
                UpdateUI("연결 해제됨", false);
                AppendMessage("<- 연결 종료됨");
            };

            await websocket.Connect();
        }
        catch (Exception e)
        {
            Debug.LogError($"연결 실패: {e.Message}");
            UpdateUI("[X] 연결 실패", false);
            AppendMessage($"[X] 연결 실패: {e.Message}");
        }
    }

    async void OnDisconnectClicked()
    {
        if (websocket == null || websocket.State != WebSocketState.Open)
        {
            AppendMessage("[!] 연결되어 있지 않습니다.");
            return;
        }

        try
        {
            UpdateUI("연결 해제 중...", false);
            AppendMessage("-> 연결 해제 중...");
            await websocket.Close();
        }
        catch (Exception e)
        {
            Debug.LogError($"연결 해제 오류: {e.Message}");
            AppendMessage($"[X] 해제 오류: {e.Message}");
        }
    }

    async void OnSendClicked()
    {
        if (websocket == null || websocket.State != WebSocketState.Open)
        {
            AppendMessage("[!] 먼저 서버에 연결하세요.");
            return;
        }

        string message = messageInput.text.Trim();

        if (string.IsNullOrEmpty(message))
        {
            AppendMessage("[!] 메시지를 입력하세요.");
            return;
        }

        try
        {
            await websocket.SendText(message);
            AppendMessage($"-> 전송: {message}");
            Debug.Log($"전송: {message}");
            messageInput.text = "";
        }
        catch (Exception e)
        {
            Debug.LogError($"전송 실패: {e.Message}");
            AppendMessage($"[X] 전송 실패: {e.Message}");
        }
    }

    void OnHttpTestClicked()
    {
        StartCoroutine(TestHttpGet("base.obj"));
    }

    IEnumerator TestHttpGet(string fileName)
    {
        // 이미 로드됨
        if (loadedObject != null)
        {
            Debug.Log("[!] 이미 오브젝트가 로드되어 있습니다.");
            yield break;
        }

        string url = $"{httpBaseUrl}/cadverse/resources/{fileName}";

        using (UnityWebRequest request = UnityWebRequest.Get(url))
        {
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                string objContent = request.downloadHandler.text;
                Debug.Log($"[OK] HTTP 성공, OBJ 파일 로드 중...");

                Mesh mesh = ParseOBJ(objContent);

                GameObject obj = new GameObject(fileName);
                obj.AddComponent<MeshFilter>().mesh = mesh;
                obj.AddComponent<MeshRenderer>().material = new Material(Shader.Find("Standard"));

                obj.transform.position = new Vector3(0, 1, 2);
                obj.transform.localScale = Vector3.one * 0.01f;

                loadedObject = obj;  // ← 저장

                Debug.Log($"[OK] {fileName} 월드에 추가됨!");

                Camera.main.transform.position = new Vector3(-3f, 3f, -0.1f);  // 카메라를 뒤로
                Camera.main.transform.LookAt(obj.transform);  // 오브젝트 바라보기
            }
            else
            {
                Debug.LogError($"[X] HTTP 실패: {request.error}");
            }
        }
    }
    // OBJ 파일 파싱 (간단 버전)
    Mesh ParseOBJ(string objText)
    {
        List<Vector3> vertices = new List<Vector3>();
        List<int> triangles = new List<int>();

        string[] lines = objText.Split('\n');

        foreach (string line in lines)
        {
            string[] parts = line.Trim().Split(' ');

            if (parts.Length == 0) continue;

            // 정점 좌표 (v x y z)
            if (parts[0] == "v")
            {
                float x = float.Parse(parts[1]);
                float y = float.Parse(parts[2]);
                float z = float.Parse(parts[3]);
                vertices.Add(new Vector3(x, z, y)); // Y와 Z 축 교환
            }
            // 면 정보 (f v1 v2 v3)
            else if (parts[0] == "f")
            {
                // OBJ는 1부터 시작, Unity는 0부터
                int v1 = int.Parse(parts[1].Split('/')[0]) - 1;
                int v2 = int.Parse(parts[2].Split('/')[0]) - 1;
                int v3 = int.Parse(parts[3].Split('/')[0]) - 1;

                triangles.Add(v1);
                triangles.Add(v2);
                triangles.Add(v3);
            }
        }

        // 메시 생성
        Mesh mesh = new Mesh();
        mesh.vertices = vertices.ToArray();
        mesh.triangles = triangles.ToArray();
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

        return mesh;
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
        messagesText.text = $"[{timestamp}] {message}\n";
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
