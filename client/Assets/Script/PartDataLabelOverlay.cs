using System.Collections.Generic;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace Cadverse
{
    /// <summary>
    /// 부품 주변에 실시간 물리 데이터 라벨을 표시하는 독립 UI 컴포넌트.
    ///
    /// 레이어 규칙:
    /// - P2PNet / P2PConn / Server를 직접 참조하지 않는다.
    /// - 네트워크 수신을 하지 않는다.
    /// - 시뮬레이션 계산을 하지 않는다.
    /// - StateFrame에 이미 들어온 값과 외부에서 전달받은 Transform만 화면에 표시한다.
    /// </summary>
    public class PartDataLabelOverlay : MonoBehaviour
    {
        public static PartDataLabelOverlay Instance { get; private set; }

        const float LabelWidth = 430f;
        const float LabelHeight = 210f;
        const float ScreenOffsetX = 28f;
        const float ScreenOffsetY = 36f;

        Canvas _canvas;
        RectTransform _labelPanel;
        TextMeshProUGUI _labelText;

        public static PartDataLabelOverlay Ensure()
        {
            if (Instance != null)
                return Instance;

            var go = new GameObject("PartDataLabelOverlay");
            DontDestroyOnLoad(go);
            return go.AddComponent<PartDataLabelOverlay>();
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

        public void Clear()
        {
            if (_labelText != null)
                _labelText.text = "";

            SetVisible(false);
        }

        /// <summary>
        /// 현재 조작/표시 대상 부품의 Transform 주변에 라벨을 표시한다.
        /// targetTransform은 AppManager 또는 ARScene 쪽에서 찾아서 넘겨준다.
        /// </summary>
        public void UpdateFromState(StateFrame state, Transform targetTransform)
        {
            if (state == null || targetTransform == null)
            {
                Clear();
                return;
            }

            if (_canvas == null || _labelText == null || _labelPanel == null)
                BuildUi();

            Camera cam = Camera.main;
            if (cam == null)
            {
                Clear();
                return;
            }

            Vector3 screenPos = cam.WorldToScreenPoint(targetTransform.position);

            if (screenPos.z <= 0f)
            {
                Clear();
                return;
            }

            SetVisible(true);

            _labelPanel.position = new Vector3(
                screenPos.x + ScreenOffsetX,
                screenPos.y + ScreenOffsetY,
                0f
            );

            string targetName = ResolveTargetName(state, targetTransform);
            _labelText.text = BuildLabelText(state, targetName);
        }

        void BuildUi()
        {
            if (_canvas != null)
                return;

            _canvas = gameObject.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            _canvas.sortingOrder = 190;

            var scaler = gameObject.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1080f, 1920f);
            scaler.matchWidthOrHeight = 0.5f;

            gameObject.AddComponent<GraphicRaycaster>();

            var panelGo = new GameObject("LabelPanel");
            panelGo.transform.SetParent(transform, false);

            _labelPanel = panelGo.AddComponent<RectTransform>();
            _labelPanel.sizeDelta = new Vector2(LabelWidth, LabelHeight);
            _labelPanel.pivot = new Vector2(0f, 0f);

            var bg = panelGo.AddComponent<Image>();
            bg.color = new Color(1f, 1f, 1f, 0.9f);

            var textGo = new GameObject("LabelText");
            textGo.transform.SetParent(panelGo.transform, false);

            var textRt = textGo.AddComponent<RectTransform>();
            textRt.anchorMin = Vector2.zero;
            textRt.anchorMax = Vector2.one;
            textRt.offsetMin = new Vector2(14f, 10f);
            textRt.offsetMax = new Vector2(-14f, -10f);

            _labelText = textGo.AddComponent<TextMeshProUGUI>();
            _labelText.fontSize = 21f;
            _labelText.color = Color.black;
            _labelText.alignment = TextAlignmentOptions.TopLeft;
            _labelText.enableWordWrapping = true;
            _labelText.overflowMode = TextOverflowModes.Ellipsis;
        }

        string BuildLabelText(StateFrame state, string targetName)
        {
            InteractionTelemetry? interaction = state.InteractionTelemetry;

            string mode = interaction.HasValue ? ValueOrNone(interaction.Value.Mode) : "-";
            string driveBody = interaction.HasValue ? ValueOrNone(interaction.Value.DriveBody) : "-";
            string driveJoint = interaction.HasValue ? interaction.Value.DriveJoint : null;

            JointTelemetry? joint = TryGetJointTelemetry(state, driveJoint);
            ActuatorTelemetry? actuator = TryGetActuatorTelemetry(state, driveJoint);
            ContactTelemetry? contact = state.Telemetry;

            var sb = new StringBuilder(256);

            sb.AppendLine($"Target: {ValueOrNone(targetName)}");
            sb.AppendLine($"Mode: {mode}");
            sb.AppendLine($"DriveBody: {driveBody}");
            sb.AppendLine($"DriveJoint: {ValueOrNone(driveJoint)}");
            sb.AppendLine();

            sb.AppendLine($"angularVelocity: {FormatNullable(joint?.AngularVelocity, " rad/s")}");
            sb.AppendLine($"linearVelocity: {FormatNullable(joint?.LinearVelocity, " m/s")}");
            sb.AppendLine($"estimatedPower: {FormatNullable(joint?.EstimatedPower, " W")}");
            sb.AppendLine();

            sb.AppendLine($"appliedTorque: {FormatNullable(actuator?.AppliedTorque, " Nm")}");
            sb.AppendLine($"commandedTorque: {FormatNullable(actuator?.CommandedTorque, " Nm")}");

            if (contact.HasValue)
            {
                sb.AppendLine();
                sb.AppendLine($"maxContactForce: {contact.Value.MaxContactForce:0.##} N");

                if (!string.IsNullOrEmpty(contact.Value.MaxPairBodyA) || !string.IsNullOrEmpty(contact.Value.MaxPairBodyB))
                {
                    sb.AppendLine(
                        $"maxPair: {ValueOrNone(contact.Value.MaxPairBodyA)} / {ValueOrNone(contact.Value.MaxPairBodyB)}"
                    );
                }
            }

            return sb.ToString();
        }

        string ResolveTargetName(StateFrame state, Transform targetTransform)
        {
            if (state.InteractionTelemetry.HasValue)
            {
                var interaction = state.InteractionTelemetry.Value;

                if (!string.IsNullOrEmpty(interaction.TargetBody))
                    return interaction.TargetBody;

                if (!string.IsNullOrEmpty(interaction.DriveBody))
                    return interaction.DriveBody;
            }

            return targetTransform != null ? targetTransform.name : "-";
        }

        JointTelemetry? TryGetJointTelemetry(StateFrame state, string driveJoint)
        {
            if (state.JointTelemetry == null || string.IsNullOrEmpty(driveJoint))
                return null;

            if (state.JointTelemetry.TryGetValue(driveJoint, out JointTelemetry telemetry))
                return telemetry;

            return null;
        }

        ActuatorTelemetry? TryGetActuatorTelemetry(StateFrame state, string driveJoint)
        {
            if (state.ActuatorTelemetry == null || string.IsNullOrEmpty(driveJoint))
                return null;

            foreach (KeyValuePair<string, ActuatorTelemetry> pair in state.ActuatorTelemetry)
            {
                var telemetry = pair.Value;

                if (telemetry.TargetJoint == driveJoint)
                    return telemetry;
            }

            return null;
        }

        static string FormatNullable(double? value, string unit)
        {
            return value.HasValue ? $"{value.Value:0.##}{unit}" : "-";
        }

        static string ValueOrNone(string value)
        {
            return string.IsNullOrEmpty(value) ? "-" : value;
        }
    }
}