using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
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
        public static P2PNet        Net     { get; private set; }
        public static QRScanner     Scanner { get; private set; }
        public static List<Server>  Servers { get; } = new();

        static AppManager _instance;

        ARTrackedImageManager              _imageManager;
        ARScene                            _scene;
        CancellationTokenSource            _recvCts;
        readonly ConcurrentQueue<System.Action> _mainQueue = new();
        readonly List<RectTransform> _activeToasts = new();

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

            foreach (var s in Servers) s.Dispose();
            Servers.Clear();

            _scene?.Dispose();
            _scene = null;
            try
            {
                _scene = await ARScene.Create(addr, _imageManager);
                ShowToast($"씬 생성 완료, {_scene.MeshCount}개 메시");

                var server = await Task.Run(() => new Server(Net, addr));
                Servers.Add(server);

                var cts = _recvCts;
                _ = Task.Run(() => ReceiveLoop(server, cts.Token));
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

        void ReceiveLoop(Server server, CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                Frame f;
                try { f = server.SimFrame(); }
                catch { break; }

                if (f is ReloadFrame)
                    _mainQueue.Enqueue(() => { _ = ReloadSceneAsync(server.Addr); });
                else if (f is StateFrame s)
                    _mainQueue.Enqueue(() => HandleStateFrame(s));
            }
        }

        void HandleStateFrame(StateFrame s)
        {
            _scene?.ApplyState(s);

            if (s.EventFeedback != null)
            {
                foreach (var ev in s.EventFeedback)
                {
                    if (!string.IsNullOrEmpty(ev.Message))
                        ShowToast(ev.Message);
                    // 사운드 재생은 D-3에서 별도 컴포넌트로 처리 — 일단 로그만 남긴다
                    if (!string.IsNullOrEmpty(ev.SoundId))
                        Debug.Log($"[EventFeedback] sound={ev.SoundId} type={ev.SoundType} vol={ev.Volume:F2} pitch={ev.Pitch:F2}");
                }
            }

            if (s.Warnings != null)
                foreach (var w in s.Warnings) Debug.LogWarning($"[sim] {w}");

            if (s.Diagnostics != null)
                foreach (var d in s.Diagnostics) Debug.Log($"[sim/{d.Severity}] {d.Code}: {d.Message}");
        }

        static TMP_FontAsset _font;
        static TMP_FontAsset Font => _font ??= Resources.Load<TMP_FontAsset>("Font/Pretendard-Regular SDF");

        const float ToastShift = 0.14f; // 토스트 높이(0.13) + 간격(0.01)

        void ShowToast(string msg)
        {
            foreach (var existing in _activeToasts)
            {
                existing.anchorMin += new Vector2(0, ToastShift);
                existing.anchorMax += new Vector2(0, ToastShift);
            }

            var canvasGO = new GameObject("Toast");
            var canvas   = canvasGO.AddComponent<Canvas>();
            canvas.renderMode   = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 200;
            canvasGO.AddComponent<CanvasScaler>();

            var textGO = new GameObject("Text");
            textGO.transform.SetParent(canvasGO.transform, false);
            var rt       = textGO.AddComponent<RectTransform>();
            rt.anchorMin = new Vector2(0.1f, 0.06f);
            rt.anchorMax = new Vector2(0.9f, 0.19f);
            rt.offsetMin = rt.offsetMax = Vector2.zero;
            var tmp       = textGO.AddComponent<TextMeshProUGUI>();
            tmp.font      = Font;
            tmp.text      = msg;
            tmp.alignment = TextAlignmentOptions.Center;
            tmp.fontSize  = 28f;
            tmp.color     = Color.white;

            _activeToasts.Add(rt);
            StartCoroutine(ToastRoutine(canvasGO, tmp, rt));
        }

        IEnumerator ToastRoutine(GameObject go, TextMeshProUGUI tmp, RectTransform rt)
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
            _activeToasts.Remove(rt);
            Destroy(go);
        }

        void OnDestroy()
        {
            _recvCts?.Cancel();
            foreach (var s in Servers) s.Dispose();
            Servers.Clear();
            _scene?.Dispose();
            Net?.Dispose();
            Net = null;
        }

    }
}
