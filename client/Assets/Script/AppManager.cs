using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.XR.ARFoundation;

namespace Cadverse
{
    public class AppManager : MonoBehaviour
    {
        public static P2PNet      Net     { get; private set; }
        public static QRScanner   Scanner { get; private set; }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            var go = new GameObject("AppManager");
            DontDestroyOnLoad(go);
            go.AddComponent<AppManager>();
        }

        void Awake()
        {
            LoginManager.Create(this);
        }

        public void OnLoginComplete(P2PNet net)
        {
            Net = net;
            var cameraManager = FindAnyObjectByType<ARCameraManager>();
            Scanner = QRScanner.Create(cameraManager, OnQRChanged);
        }

        void OnQRChanged(Addr addr)
        {
            ShowToast("QR 스캔 성공");
        }

        void OnDestroy()
        {
            Net?.Dispose();
            Net = null;
        }

        // ── 토스트 ────────────────────────────────────────────────────────────

        void ShowToast(string message)
        {
            StartCoroutine(ToastRoutine(message));
        }

        IEnumerator ToastRoutine(string message)
        {
            // 캔버스
            var canvasGo = new GameObject("Toast");
            var canvas   = canvasGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 999;
            canvasGo.AddComponent<UnityEngine.UI.CanvasScaler>();

            // 텍스트
            var textGo = new GameObject("Text");
            textGo.transform.SetParent(canvasGo.transform, false);
            var tmp = textGo.AddComponent<TextMeshProUGUI>();
            tmp.text      = message;
            tmp.fontSize  = 36;
            tmp.alignment = TextAlignmentOptions.Center;

            var rect = textGo.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0.1f, 0.1f);
            rect.anchorMax = new Vector2(0.9f, 0.2f);
            rect.offsetMin = rect.offsetMax = Vector2.zero;

            // 1.5초 표시 후 페이드아웃
            yield return new WaitForSeconds(1.5f);

            float elapsed = 0f;
            while (elapsed < 0.5f)
            {
                elapsed += Time.deltaTime;
                tmp.alpha = 1f - elapsed / 0.5f;
                yield return null;
            }

            Destroy(canvasGo);
        }
    }
}
