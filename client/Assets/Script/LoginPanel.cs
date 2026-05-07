using UnityEngine;
using UnityEngine.UI;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem.UI;
using TMPro;

namespace Cadverse
{
    public class LoginPanel : MonoBehaviour
    {
        TMP_InputField  _groupInput;
        TMP_InputField  _pwInput;
        TMP_InputField  _nameInput;
        Button          _connectBtn;
        TextMeshProUGUI _btnLabel;
        TextMeshProUGUI _errorText;
        TextMeshProUGUI _loadingText;

        LoginManager _app;

        static TMP_FontAsset _font;
        static TMP_FontAsset Font => _font ??= Resources.Load<TMP_FontAsset>("Font/Pretendard-Regular SDF");

        // ── 진입점 ────────────────────────────────────────────────────────────

        public static LoginPanel Create(LoginManager app)
        {
            if (FindAnyObjectByType<EventSystem>() == null)
            {
                var esGO = new GameObject("EventSystem");
                esGO.AddComponent<EventSystem>();
                esGO.AddComponent<InputSystemUIInputModule>();
            }

            var canvasGO = new GameObject("LoginCanvas");
            var canvas = canvasGO.AddComponent<Canvas>();
            canvas.renderMode   = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 100;

            var scaler = canvasGO.AddComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ConstantPixelSize;
            scaler.scaleFactor = 1f;

            canvasGO.AddComponent<GraphicRaycaster>();

            var panel = canvasGO.AddComponent<LoginPanel>();
            panel._app = app;
            panel.BuildUI(canvasGO.transform);
            return panel;
        }

        // ── UI 생성 ───────────────────────────────────────────────────────────

        void BuildUI(Transform root)
        {
            var backdrop = MakeRect("Backdrop", root);
            Stretch(backdrop);
            backdrop.gameObject.AddComponent<Image>().color = new Color(0f, 0f, 0f, 0.85f);

            var card = MakeRect("Card", backdrop);
            card.anchorMin = card.anchorMax = card.pivot = new Vector2(0.5f, 0.5f);
            card.sizeDelta = new Vector2(640f, 800f);
            card.gameObject.AddComponent<Image>().color = Hex(0x1E2D3E);

            var layout = card.gameObject.AddComponent<VerticalLayoutGroup>();
            layout.padding               = new RectOffset(40, 40, 48, 48);
            layout.spacing               = 20f;
            layout.childForceExpandWidth  = true;
            layout.childForceExpandHeight = false;
            layout.childControlWidth      = true;
            layout.childControlHeight     = true;

            AddLabel(card, "CADverse", 36f, FontStyles.Bold, Color.white, 56f);

            _groupInput = AddInput(card, "그룹 이름");
            _pwInput    = AddInput(card, "비밀번호", password: true);
            _nameInput  = AddInput(card, "사용자 이름");

            var btnGO = new GameObject("ConnectBtn");
            btnGO.transform.SetParent(card, false);
            btnGO.AddComponent<LayoutElement>().preferredHeight = 56f;
            var btnImg  = btnGO.AddComponent<Image>();
            btnImg.color = Hex(0x26786D);
            _connectBtn  = btnGO.AddComponent<Button>();
            _connectBtn.targetGraphic = btnImg;
            var btnColors = ColorBlock.defaultColorBlock;
            btnColors.highlightedColor = Hex(0x2E9087);
            btnColors.pressedColor     = Hex(0x1A5751);
            _connectBtn.colors = btnColors;
            _connectBtn.onClick.AddListener(OnConnectClicked);

            var btnLabelRT = MakeRect("Label", btnGO.transform);
            Stretch(btnLabelRT);
            _btnLabel           = btnLabelRT.gameObject.AddComponent<TextMeshProUGUI>();
            _btnLabel.font      = Font;
            _btnLabel.text      = "연결";
            _btnLabel.fontSize  = 22f;
            _btnLabel.fontStyle = FontStyles.Bold;
            _btnLabel.alignment = TextAlignmentOptions.Center;
            _btnLabel.color     = Color.white;

            _errorText = AddLabel(card, "", 15f, FontStyles.Normal, Hex(0xEF4444), 28f);
            _errorText.gameObject.SetActive(false);

            _loadingText = AddLabel(card, "연결 중…", 15f, FontStyles.Normal, Hex(0x99CEC9), 28f);
            _loadingText.gameObject.SetActive(false);
        }

        // ── 이벤트 ────────────────────────────────────────────────────────────

        void OnConnectClicked()
        {
            var groupName = _groupInput.text.Trim();
            var pw        = _pwInput.text;
            var name      = _nameInput.text.Trim();

            if (string.IsNullOrEmpty(groupName) || string.IsNullOrEmpty(pw) || string.IsNullOrEmpty(name))
            {
                ShowError("모든 항목을 입력해주세요.");
                return;
            }

            SetLoading(true);
            _app.ConnectAsync(groupName, pw, name);
        }

        // ── 공개 상태 전환 ─────────────────────────────────────────────────────

        public void ShowError(string msg)
        {
            _errorText.text = msg;
            _errorText.gameObject.SetActive(true);
            _loadingText.gameObject.SetActive(false);
            _connectBtn.interactable = true;
            _btnLabel.text = "연결";
        }

        public void SetLoading(bool on)
        {
            _connectBtn.interactable = !on;
            _btnLabel.text           = on ? "" : "연결";
            _loadingText.gameObject.SetActive(on);
            _errorText.gameObject.SetActive(false);
        }

        // ── 헬퍼 ─────────────────────────────────────────────────────────────

        static RectTransform MakeRect(string name, Transform parent)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            return go.AddComponent<RectTransform>();
        }

        static void Stretch(RectTransform rt)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = rt.offsetMax = Vector2.zero;
        }

        TMP_InputField AddInput(RectTransform parent, string placeholder, bool password = false)
        {
            var containerGO = new GameObject(placeholder);
            containerGO.transform.SetParent(parent, false);
            containerGO.AddComponent<LayoutElement>().preferredHeight = 56f;
            containerGO.AddComponent<Image>().color = Hex(0x111B27);

            var field = containerGO.AddComponent<TMP_InputField>();

            var areaRT = MakeRect("Text Area", containerGO.transform);
            areaRT.anchorMin = Vector2.zero;
            areaRT.anchorMax = Vector2.one;
            areaRT.offsetMin = new Vector2(16f,  6f);
            areaRT.offsetMax = new Vector2(-16f, -6f);
            areaRT.gameObject.AddComponent<RectMask2D>();

            var phRT = MakeRect("Placeholder", areaRT);
            Stretch(phRT);
            var ph       = phRT.gameObject.AddComponent<TextMeshProUGUI>();
            ph.font      = Font;
            ph.text      = placeholder;
            ph.fontSize  = 18f;
            ph.color     = new Color(1f, 1f, 1f, 0.35f);
            ph.alignment = TextAlignmentOptions.MidlineLeft;

            var txtRT = MakeRect("Text", areaRT);
            Stretch(txtRT);
            var txt       = txtRT.gameObject.AddComponent<TextMeshProUGUI>();
            txt.font      = Font;
            txt.fontSize  = 18f;
            txt.color     = Color.white;
            txt.alignment = TextAlignmentOptions.MidlineLeft;

            field.textViewport  = areaRT;
            field.textComponent = txt;
            field.placeholder   = ph;

            if (password)
            {
                field.contentType = TMP_InputField.ContentType.Password;
                field.inputType   = TMP_InputField.InputType.Password;
            }

            return field;
        }

        TextMeshProUGUI AddLabel(RectTransform parent, string text, float size,
                                  FontStyles style, Color color, float height)
        {
            var go = new GameObject(string.IsNullOrEmpty(text) ? "Label" : text);
            go.transform.SetParent(parent, false);
            go.AddComponent<LayoutElement>().preferredHeight = height;
            var tmp       = go.AddComponent<TextMeshProUGUI>();
            tmp.font      = Font;
            tmp.text      = text;
            tmp.fontSize  = size;
            tmp.fontStyle = style;
            tmp.color     = color;
            tmp.alignment = TextAlignmentOptions.Center;
            return tmp;
        }

        static Color Hex(uint rgb) => new Color(
            ((rgb >> 16) & 0xFF) / 255f,
            ((rgb >>  8) & 0xFF) / 255f,
            ( rgb        & 0xFF) / 255f);
    }
}
