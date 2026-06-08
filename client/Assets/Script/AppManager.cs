using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
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
        public static List<Server>  Servers { get; } = new();   // ActiveServer만 노출 (호환용)
        public static ModelRoot     Scene   { get; private set; }   // 활성 ModelRoot — UI/SimulationManager의 IndexOf 호출에 사용

        public static volatile bool NeedsFullInfo = false;

        const int MAX_SESSIONS = 2;   // active 1 + cold 최대 1 (= 최근 2개)

        static AppManager _instance;

        ARTrackedImageManager   _imageManager;
        SceneManager            _sceneManager;
        AssetCache              _assetCache;
        readonly LinkedList<SceneSession>       _sessions  = new();   // head=oldest, tail=most recently active
        SceneSession                            _active;
        readonly ConcurrentQueue<System.Action> _mainQueue = new();
        readonly List<RectTransform>            _activeToasts = new();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            InitLogging();
            var go = new GameObject("AppManager");
            DontDestroyOnLoad(go);
            go.AddComponent<AppManager>();
        }

        // 디바이스 파일 로깅 — Unity 로그(Debug.Log/예외)는 cv_unity.log에,
        // native(.so) 로그는 cv_native.log에 append. adb pull로 회수한다.
        // Android 경로: /storage/emulated/0/Android/data/<bundleId>/files/
        static StreamWriter _unityLogWriter;
        static readonly object _unityLogLock = new();
        static void InitLogging()
        {
            try
            {
                var dir = Application.persistentDataPath;
                Directory.CreateDirectory(dir);

                var unityLog  = Path.Combine(dir, "cv_unity.log");
                var nativeLog = Path.Combine(dir, "cv_native.log");

                _unityLogWriter = new StreamWriter(unityLog, append: true) { AutoFlush = true };
                _unityLogWriter.WriteLine($"=== session start {System.DateTime.Now:O} ===");
                Application.logMessageReceivedThreaded += OnUnityLog;

                P2PNet.SetNativeLogPath(nativeLog);
                Debug.Log($"[Logging] unity={unityLog} native={nativeLog}");
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[Logging] init 실패: {e.Message}");
            }
        }

        static void OnUnityLog(string condition, string stackTrace, LogType type)
        {
            if (_unityLogWriter == null) return;
            try
            {
                lock (_unityLogLock)
                {
                    _unityLogWriter.WriteLine($"[{type}] {condition}");
                    if (type == LogType.Exception || type == LogType.Error)
                        _unityLogWriter.WriteLine(stackTrace);
                }
            }
            catch { }
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
            if (_imageManager != null)
                _sceneManager = new SceneManager(_imageManager);

            // AssetCache — 디스크는 시작 시 비우고(clean start) 새로 시작
            var cacheDir = Path.Combine(Application.persistentDataPath, "qr_cache");
            AssetCache.Cleanup(cacheDir);
            _assetCache = new AssetCache(net, cacheDir);

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

            // 이미 set에 있으면 active 토글만 — 즉시 전환 (다운로드/디코드 없음)
            var existing = FindSession(addr.Id);
            if (existing != null)
            {
                SetActive(existing);
                ShowToast("이전 세션 복귀");
                return;
            }

            SceneSession next;
            try
            {
                next = await SceneSession.LoadAsync(
                    addr, Net, _sceneManager, _mainQueue,
                    onReload:     ReloadSceneAsync,
                    onStateExtra: HandleStateExtras,
                    cache:        _assetCache);
            }
            catch (System.Exception e)
            {
                Debug.LogError($"[ARScene] {e.Message}");
                ShowToast($"씬 로드 실패: {e.Message}");
                Scanner?.InvalidateLast();
                return;
            }

            AddSession(next);
            SetActive(next);
            ShowToast($"씬 생성 완료, {next.Model.MeshCount}개 메시");
        }

        async Task ReloadSceneAsync(Addr addr)
        {
            Debug.Log($"[AppManager] ReloadSceneAsync 진입 addr={addr.Id.Substring(0, 8)}");
            // ReloadFrame 수신 시 같은 addr의 모델/세션을 새로 만든다.
            // 원래 active였으면 새 세션도 active로 유지, cold였으면 cold 유지 (사용자가 그 QR을
            // 다시 비추면 SessionSet hit으로 그때 active 전환).
            var existing = FindSession(addr.Id);
            bool wasActive = existing != null && existing == _active;
            if (existing != null) DropSession(existing);

            SceneSession next;
            try
            {
                next = await SceneSession.LoadAsync(
                    addr, Net, _sceneManager, _mainQueue,
                    onReload:     ReloadSceneAsync,
                    onStateExtra: HandleStateExtras,
                    cache:        _assetCache);
            }
            catch (System.Exception e)
            {
                Debug.LogError($"[ARScene] reload: {e.Message}");
                ShowToast($"모델 교체 실패: {e.Message}");
                Scanner?.InvalidateLast();
                return;
            }

            AddSession(next);
            if (wasActive)
            {
                SetActive(next);
                ShowToast($"모델 교체 완료, {next.Model.MeshCount}개 메시");
            }
            else
            {
                next.IsActive = false;   // cold 유지
            }
        }

        // ── SessionSet (LRU N=MAX_SESSIONS) ────────────────────────────
        SceneSession FindSession(string addrId)
        {
            foreach (var s in _sessions) if (s.Addr.Id == addrId) return s;
            return null;
        }

        // 새 세션을 set에 추가. 가득 차면 active가 아닌 가장 오래된 cold를 evict.
        void AddSession(SceneSession s)
        {
            while (_sessions.Count >= MAX_SESSIONS)
            {
                SceneSession victim = null;
                for (var node = _sessions.First; node != null; node = node.Next)
                {
                    if (node.Value != _active) { victim = node.Value; break; }
                }
                if (victim == null) break;  // 안전장치 — 활성 외에 evict할 게 없음
                DropSession(victim);
            }
            _sessions.AddLast(s);
        }

        void DropSession(SceneSession s)
        {
            _sessions.Remove(s);
            _sceneManager.RemoveModel(s.Addr.Id);
            s.Dispose();
        }

        // active 슬롯 교체. cold는 IsActive=false로, active만 IsActive=true.
        // Servers / Scene 외부 API도 동시에 갱신.
        void SetActive(SceneSession s)
        {
            _active = s;
            foreach (var sess in _sessions)
                sess.IsActive = (sess == s);

            Scene = s?.Model;
            Servers.Clear();
            if (s != null) Servers.Add(s.Server);

            // LRU promote — list의 tail로
            if (s != null && _sessions.Contains(s))
            {
                _sessions.Remove(s);
                _sessions.AddLast(s);
            }
        }

        // SceneSession이 ApplyState를 마친 뒤 호출. 토스트/로그/사운드 등 부수 효과 전용.
        void HandleStateExtras(StateFrame s)
        {
            if (s.EventFeedback != null)
            {
                foreach (var ev in s.EventFeedback)
                {
                    if (!string.IsNullOrEmpty(ev.Message))
                        ShowToast(ev.Message);
                    // 사운드 재생은 별도 컴포넌트로 처리 — 일단 로그만 남긴다
                    if (!string.IsNullOrEmpty(ev.SoundId))
                        Debug.Log($"[EventFeedback] sound={ev.SoundId} type={ev.SoundType} vol={ev.Volume:F2} pitch={ev.Pitch:F2}");
                }
            }

            if (s.Warnings != null)
                foreach (var w in s.Warnings) Debug.LogWarning($"[sim] {w}");

            if (s.Diagnostics != null)
                foreach (var d in s.Diagnostics) Debug.Log($"[sim/{d.Severity}] {d.Code}: {d.Message}");

            // TODO(UI): 정보 표시 모드 진입 시 NeedsFullInfo=true 토글.
            // 그러면 s.InteractionTelemetry / s.Telemetry / s.JointTelemetry[name] /
            // s.ActuatorTelemetry[name] / s.GearTelemetry[name] / s.AssemblyTelemetry[name]
            // 가 채워져 들어온다. 객체 클릭 시 hit.collider.name 으로 lookup해서 패널에 표시.
            // SimVec3 필드(reactionForce/Torque/axisWorld/pivotWorld)는 CoordConvert.SimPosToUnity 변환 필요.
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

        void OnApplicationQuit()
        {
            // 디스크 캐시 비우기 (다음 실행 시 clean start와 함께 작동)
            try
            {
                var cacheDir = Path.Combine(Application.persistentDataPath, "qr_cache");
                AssetCache.Cleanup(cacheDir);
            }
            catch (System.Exception e) { Debug.LogWarning($"[AssetCache] quit cleanup: {e.Message}"); }
        }

        void OnDestroy()
        {
            // 모든 세션 정리
            foreach (var s in _sessions) { _sceneManager?.RemoveModel(s.Addr.Id); s.Dispose(); }
            _sessions.Clear();
            _active = null;
            Scene = null;
            Servers.Clear();

            Net?.Dispose();
            Net = null;
        }

    }
}
