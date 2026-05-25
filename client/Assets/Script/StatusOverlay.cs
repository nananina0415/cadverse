using System;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Cadverse
{
    /// <summary>
    /// AR 화면 위에 진단 / 경고 / 이벤트 피드백 / 접촉 정보를 표시하는 보조 UI 컴포넌트.
    ///
    /// 레이어 규칙:
    /// - 네트워크 / P2P / 서버 연결을 직접 다루지 않는다.
    /// - 시뮬레이션 계산을 하지 않는다.
    /// - StateFrame에 이미 들어온 값을 화면 표시용 문자열로 변환하는 역할만 담당한다.
    /// - AppManager 또는 다른 상위 흐름에서 UpdateFromState(...)를 호출해준다.
    /// </summary>
    public class StatusOverlay : MonoBehaviour
    {
        public static StatusOverlay Instance { get; private set; }

        const int MaxDiagnostics = 4;
        const int MaxWarnings = 4;
        const int MaxEvents = 4;

        Canvas _canvas;
        RectTransform _panel;
        TextMeshProUGUI _text;

        public static StatusOverlay Ensure()
        {
            if (Instance != null)
                return Instance;

            var go = new GameObject("StatusOverlay");
            DontDestroyOnLoad(go);
            return go.AddComponent<StatusOverlay>();
        }

        void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            DontDestroyOnLoad(gameObject);
            BuildUi();
            SetVisible(false);
        }

        void OnDestroy()
        {
            if (Instance == this)
                Instance = null;
        }

        public void SetVisible(bool visible)
        {
            if (_canvas != null)
                _canvas.enabled = visible;
        }

        public void UpdateFromState(StateFrame state)
        {
            if (state == null)
                return;

            if (_text == null)
                BuildUi();

            SetVisible(true);
            _text.text = BuildText(state);
        }

        public void Clear()
        {
            if (_text != null)
                _text.text = "";

            SetVisible(false);
        }

        void BuildUi()
        {
            if (_canvas != null)
                return;

            _canvas = gameObject.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            _canvas.sortingOrder = 175;

            var scaler = gameObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080f, 1920f);
            scaler.matchWidthOrHeight = 0.5f;

            gameObject.AddComponent<GraphicRaycaster>();

            var panelGo = new GameObject("Panel");
            panelGo.transform.SetParent(transform, false);

            _panel = panelGo.AddComponent<RectTransform>();
            _panel.anchorMin = new Vector2(0.02f, 0.58f);
            _panel.anchorMax = new Vector2(0.62f, 0.96f);
            _panel.offsetMin = Vector2.zero;
            _panel.offsetMax = Vector2.zero;

            var bg = panelGo.AddComponent<Image>();
            bg.color = new Color(0f, 0f, 0f, 0.62f);

            var textGo = new GameObject("Text");
            textGo.transform.SetParent(panelGo.transform, false);

            var textRt = textGo.AddComponent<RectTransform>();
            textRt.anchorMin = Vector2.zero;
            textRt.anchorMax = Vector2.one;
            textRt.offsetMin = new Vector2(18f, 14f);
            textRt.offsetMax = new Vector2(-18f, -14f);

            _text = textGo.AddComponent<TextMeshProUGUI>();
            _text.fontSize = 22f;
            _text.color = Color.white;
            _text.alignment = TextAlignmentOptions.TopLeft;
            _text.enableWordWrapping = true;
            _text.overflowMode = TextOverflowModes.Ellipsis;
        }

        string BuildText(StateFrame state)
        {
            var sb = new StringBuilder(768);

            AppendDiagnostics(sb, state);
            AppendWarnings(sb, state);
            AppendEventFeedback(sb, state);
            AppendContact(sb, state);

            return sb.ToString();
        }

        void AppendDiagnostics(StringBuilder sb, StateFrame state)
        {
            sb.AppendLine("[Diagnostics]");

            if (state.Diagnostics == null || state.Diagnostics.Length == 0)
            {
                sb.AppendLine("None");
                sb.AppendLine();
                return;
            }

            int count = Math.Min(MaxDiagnostics, state.Diagnostics.Length);
            for (int i = 0; i < count; i++)
            {
                var d = state.Diagnostics[i];

                sb.AppendLine($"- {ValueOrNone(d.Severity)} / {ValueOrNone(d.Code)}");

                if (!string.IsNullOrEmpty(d.Target))
                    sb.AppendLine($"  target: {d.Target}");

                if (!string.IsNullOrEmpty(d.Message))
                    sb.AppendLine($"  {d.Message}");
            }

            if (state.Diagnostics.Length > MaxDiagnostics)
                sb.AppendLine($"... +{state.Diagnostics.Length - MaxDiagnostics} more");

            sb.AppendLine();
        }

        void AppendWarnings(StringBuilder sb, StateFrame state)
        {
            sb.AppendLine("[Warnings]");

            if (state.Warnings == null || state.Warnings.Length == 0)
            {
                sb.AppendLine("None");
                sb.AppendLine();
                return;
            }

            int count = Math.Min(MaxWarnings, state.Warnings.Length);
            for (int i = 0; i < count; i++)
            {
                if (!string.IsNullOrEmpty(state.Warnings[i]))
                    sb.AppendLine($"- {state.Warnings[i]}");
            }

            if (state.Warnings.Length > MaxWarnings)
                sb.AppendLine($"... +{state.Warnings.Length - MaxWarnings} more");

            sb.AppendLine();
        }

        void AppendEventFeedback(StringBuilder sb, StateFrame state)
        {
            sb.AppendLine("[Event Feedback]");

            if (state.EventFeedback == null || state.EventFeedback.Length == 0)
            {
                sb.AppendLine("None");
                sb.AppendLine();
                return;
            }

            int count = Math.Min(MaxEvents, state.EventFeedback.Length);
            for (int i = 0; i < count; i++)
            {
                var ev = state.EventFeedback[i];

                sb.AppendLine($"- {ValueOrNone(ev.Severity)} / {ValueOrNone(ev.EventType)}");

                if (!string.IsNullOrEmpty(ev.Target))
                    sb.AppendLine($"  target: {ev.Target}");

                if (!string.IsNullOrEmpty(ev.Message))
                    sb.AppendLine($"  {ev.Message}");

                if (!string.IsNullOrEmpty(ev.SoundId))
                    sb.AppendLine($"  sound: {ev.SoundId}");
            }

            if (state.EventFeedback.Length > MaxEvents)
                sb.AppendLine($"... +{state.EventFeedback.Length - MaxEvents} more");

            sb.AppendLine();
        }

        void AppendContact(StringBuilder sb, StateFrame state)
        {
            sb.AppendLine("[Contact]");

            if (!state.Telemetry.HasValue)
            {
                sb.AppendLine("No contact telemetry");
                return;
            }

            var t = state.Telemetry.Value;

            sb.AppendLine($"contactCount: {t.ContactCount}");
            sb.AppendLine($"maxForce: {t.MaxContactForce:0.###} N");

            if (!string.IsNullOrEmpty(t.MaxPairBodyA) || !string.IsNullOrEmpty(t.MaxPairBodyB))
                sb.AppendLine($"maxPair: {ValueOrNone(t.MaxPairBodyA)} / {ValueOrNone(t.MaxPairBodyB)}");
        }

        static string ValueOrNone(string value)
        {
            return string.IsNullOrEmpty(value) ? "-" : value;
        }
    }
}