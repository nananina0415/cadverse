using UnityEngine;
using UnityEngine.UI;

namespace CADverse.AR_Interaction
{
    /// <summary>
    /// 스크린 상에 2D 화살표를 그리는 컴포넌트
    /// </summary>
    public class ForceArrowVisualizer : MonoBehaviour
    {
        private Canvas canvas;
        private RawImage arrowLine;
        private RectTransform lineRect;

        [SerializeField] private Color arrowColor = Color.red;
        [SerializeField] private float lineWidth = 5f;

        void Awake()
        {
            // Canvas 생성 (Screen Space Overlay)
            var canvasObj = new GameObject("ArrowCanvas");
            canvas = canvasObj.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 1000; // 최상위에 표시

            canvasObj.AddComponent<CanvasScaler>();
            canvasObj.AddComponent<GraphicRaycaster>();

            // 화살표 선 (RawImage)
            var lineObj = new GameObject("ArrowLine");
            lineObj.transform.SetParent(canvasObj.transform, false);

            arrowLine = lineObj.AddComponent<RawImage>();
            arrowLine.color = arrowColor;
            lineRect = lineObj.GetComponent<RectTransform>();

            arrowLine.enabled = false;
        }

        public void ShowArrow(Vector2 startScreen, Vector2 endScreen)
        {
            arrowLine.enabled = true;

            // 화살표 방향과 길이 계산
            Vector2 direction = endScreen - startScreen;
            float distance = direction.magnitude;

            // 선의 위치와 크기 설정
            lineRect.anchorMin = Vector2.zero;
            lineRect.anchorMax = Vector2.zero;
            lineRect.pivot = new Vector2(0, 0.5f);

            lineRect.anchoredPosition = startScreen;
            lineRect.sizeDelta = new Vector2(distance, lineWidth);

            // 회전 (각도 계산)
            float angle = Mathf.Atan2(direction.y, direction.x) * Mathf.Rad2Deg;
            lineRect.rotation = Quaternion.Euler(0, 0, angle);
        }

        public void Hide()
        {
            arrowLine.enabled = false;
        }

        void OnDestroy()
        {
            if (canvas != null)
            {
                Destroy(canvas.gameObject);
            }
        }
    }
}
