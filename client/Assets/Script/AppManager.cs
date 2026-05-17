using System.Collections;
using System.Collections.Concurrent;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR.ARFoundation;

namespace Cadverse
{
    public class AppManager : MonoBehaviour
    {
        public static P2PNet      Net     { get; private set; }
        public static QRScanner   Scanner { get; private set; }

        static AppManager _instance;

        ARTrackedImageManager              _imageManager;
        ARScene                            _scene;
        Addr                               _currentAddr;
        CancellationTokenSource            _recvCts;
        readonly ConcurrentQueue<System.Action> _mainQueue = new();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            var go = new GameObject("AppManager");
            DontDestroyOnLoad(go);
            go.AddComponent<AppManager>();
        }

        void Awake()
        {
            _instance = this;
            LoginManager.Create(this);
        }

        public static void Toast(string msg) => _instance?.ShowToast(msg);

        public void OnLoginComplete(P2PNet net)
        {
            Net = net;
            _imageManager = FindAnyObjectByType<ARTrackedImageManager>();
            var cameraManager = FindAnyObjectByType<ARCameraManager>();
            if (cameraManager != null)
                Scanner = QRScanner.Create(cameraManager, OnQRChanged);
        }

        void Update()
        {
            while (_mainQueue.TryDequeue(out var action)) action();
        }

        async void OnQRChanged(Addr addr)
        {
            ShowToast("QR 인식됨");
            _recvCts?.Cancel();
            _recvCts = new CancellationTokenSource();
            _currentAddr = addr;
            _scene?.Dispose();
            _scene = null;
            try
            {
                _scene = await ARScene.Create(addr, _imageManager);
                ShowToast($"씬 생성 완료, {_scene.MeshCount}개 메시");
                var cts = _recvCts;
                _ = Task.Run(() => ReceiveLoop(addr, cts.Token));
            }
            catch (System.Exception e)
            {
                Debug.LogError($"[ARScene] {e.Message}");
                ShowToast($"씬 로드 실패: {e.Message}");
            }
        }

        async Task ReloadSceneAsync(Addr addr)
        {
            _scene?.Dispose();
            _scene = null;
            try
            {
                _scene = await ARScene.Create(addr, _imageManager);
                ShowToast($"모델 교체 완료, {_scene.MeshCount}개 메시");
            }
            catch (System.Exception e)
            {
                Debug.LogError($"[ARScene] reload: {e.Message}");
                ShowToast($"모델 교체 실패: {e.Message}");
            }
        }

        void ReceiveLoop(Addr addr, CancellationToken ct)
        {
            P2PConn conn;
            try { conn = Net.ConnectQuic(addr.RawJson); }
            catch { return; }
            using (conn)
            {
                while (!ct.IsCancellationRequested)
                {
                    byte[] data;
                    try { data = conn.Recv(); }
                    catch { break; }

                    var json = Encoding.UTF8.GetString(data);
                    if (json.Contains("\"type\":\"reload\""))
                        _mainQueue.Enqueue(() => { _ = ReloadSceneAsync(addr); });
                    else
                        _mainQueue.Enqueue(() => _scene?.ApplySimOut(json));
                }
            }
        }

        static TMP_FontAsset _font;
        static TMP_FontAsset Font => _font ??= Resources.Load<TMP_FontAsset>("Font/Pretendard-Regular SDF");

        void ShowToast(string msg)
        {
            var canvasGO = new GameObject("Toast");
            var canvas   = canvasGO.AddComponent<Canvas>();
            canvas.renderMode   = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 200;
            canvasGO.AddComponent<CanvasScaler>();

            var textGO = new GameObject("Text");
            textGO.transform.SetParent(canvasGO.transform, false);
            var rt        = textGO.AddComponent<RectTransform>();
            rt.anchorMin  = new Vector2(0.1f, 0.08f);
            rt.anchorMax  = new Vector2(0.9f, 0.22f);
            rt.offsetMin  = rt.offsetMax = Vector2.zero;
            var tmp       = textGO.AddComponent<TextMeshProUGUI>();
            tmp.font      = Font;
            tmp.text      = msg;
            tmp.alignment = TextAlignmentOptions.Center;
            tmp.fontSize  = 28f;
            tmp.color     = Color.white;

            StartCoroutine(ToastRoutine(canvasGO, tmp));
        }

        IEnumerator ToastRoutine(GameObject go, TextMeshProUGUI tmp)
        {
            yield return new WaitForSeconds(1.4f);
            float elapsed = 0f;
            var   c       = tmp.color;
            while (elapsed < 0.6f)
            {
                elapsed += Time.deltaTime;
                c.a      = 1f - elapsed / 0.6f;
                tmp.color = c;
                yield return null;
            }
            Destroy(go);
        }

        void OnDestroy()
        {
            _recvCts?.Cancel();
            _scene?.Dispose();
            Net?.Dispose();
            Net = null;
        }

    }
}
