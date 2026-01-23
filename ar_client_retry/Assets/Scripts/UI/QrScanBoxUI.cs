using UnityEngine;
using UnityEngine.UI;

namespace CADverse.UI
{
    public class QrScanBoxUI : MonoBehaviour
    {
        [Header("QR Scan Box Settings")]
        [SerializeField] private float boxSizeRatio = 0.5f; // 화면 너비/높이에 대한 박스 크기 비율 (기존 0.7 -> 0.5)
        [SerializeField] private float borderWidth = 10f; // 테두리 두께
        [SerializeField] private Color borderColor = Color.green; // 테두리 색상
        [SerializeField] private Color overlayColor = new Color(0, 0, 0, 0.7f); // 오버레이 색상 (스캔 박스 외부)

        private RectTransform _rectTransform;

        void Awake()
        {
            _rectTransform = GetComponent<RectTransform>();
            if (_rectTransform == null)
            {
                Debug.LogError("[QrScanBoxUI] RectTransform component not found!");
                enabled = false;
                return;
            }

            // 부모 Canvas의 Image 컴포넌트에 오버레이 색상 설정 (만약 있다면)
            Image panelImage = GetComponent<Image>();
            if (panelImage != null)
            {
                panelImage.color = overlayColor;
            }

            DrawScanBoxFrame();
        }

        private void DrawScanBoxFrame()
        {
            // 부모 패널의 크기 가져오기 (Canvas Scaler 적용된 크기)
            Rect parentRect = _rectTransform.rect;
            float width = parentRect.width;
            float height = parentRect.height;

            // 박스 크기 계산
            float targetSize = Mathf.Min(width, height) * boxSizeRatio;
            float halfSize = targetSize / 2f;

            // 4개의 테두리 업데이트 또는 생성
            UpdateBorder("TopBorder", 0, halfSize - borderWidth / 2f, targetSize, borderWidth);
            UpdateBorder("BottomBorder", 0, -halfSize + borderWidth / 2f, targetSize, borderWidth);
            UpdateBorder("LeftBorder", -halfSize + borderWidth / 2f, 0, borderWidth, targetSize);
            UpdateBorder("RightBorder", halfSize - borderWidth / 2f, 0, borderWidth, targetSize);
        }

        private void UpdateBorder(string name, float x, float y, float width, float height)
        {
            Transform child = transform.Find(name);
            GameObject borderGO;
            RectTransform borderRect;
            Image borderImage;

            if (child == null)
            {
                // 없으면 생성
                borderGO = new GameObject(name);
                borderGO.transform.SetParent(transform, false);
                borderRect = borderGO.AddComponent<RectTransform>();
                borderImage = borderGO.AddComponent<Image>();
            }
            else
            {
                // 있으면 재사용
                borderGO = child.gameObject;
                borderRect = borderGO.GetComponent<RectTransform>();
                borderImage = borderGO.GetComponent<Image>();
            }

            // 속성 설정
            borderRect.anchorMin = new Vector2(0.5f, 0.5f);
            borderRect.anchorMax = new Vector2(0.5f, 0.5f);
            borderRect.pivot = new Vector2(0.5f, 0.5f);
            borderRect.anchoredPosition = new Vector2(x, y);
            borderRect.sizeDelta = new Vector2(width, height);
            
            if (borderImage != null)
            {
                borderImage.color = borderColor;
            }
        }

        // Editor에서 값 변경 시 바로 반영되도록
#if UNITY_EDITOR
        void OnValidate()
        {
            // OnValidate 중에 씬 객체를 수정하면 오류가 발생할 수 있으므로 딜레이 호출 사용
            UnityEditor.EditorApplication.delayCall += () =>
            {
                if (this == null) return; // 객체가 파괴되었을 수 있음

                if (_rectTransform == null)
                {
                    _rectTransform = GetComponent<RectTransform>();
                }

                Image panelImage = GetComponent<Image>();
                if (panelImage != null)
                {
                    panelImage.color = overlayColor;
                }
                
                // Editor에서는 즉시 반영되도록 다시 그리기
                if (gameObject.activeInHierarchy) // 활성화된 상태에서만
                {
                     DrawScanBoxFrame();
                }
            };
        }
#endif
    }
}
