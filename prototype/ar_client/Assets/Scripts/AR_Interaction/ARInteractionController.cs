using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.EnhancedTouch;
using CADverse.Utils;

namespace CADverse.AR_Interaction
{
    /// <summary>
    /// AR 모델과의 상호작용을 처리하는 컨트롤러
    /// - 터치로 부품 선택
    /// - 선택된 부품 강조 (색상 변경)
    /// - 충돌 좌표 출력 (월드 & 로컬)
    /// </summary>
    public class ARInteractionController : MonoBehaviour
    {
        [Header("Settings")]
        [SerializeField] private Color highlightColor = Color.yellow;
        [SerializeField] private bool showDebugInfo = true;

        private GameObject _selectedPart;
        private Color _originalColor;
        private Material _originalMaterial;

        void Start()
        {
            EnhancedTouchSupport.Enable();

            Debug.Log("[ARInteraction] ===== ARInteractionController 시작 =====");
            Debug.Log($"[ARInteraction] Camera.main: {Camera.main?.name ?? "NULL!"}");
            Debug.Log($"[ARInteraction] Highlight Color: {highlightColor}");

            AndroidToast.Show("AR 인터랙션 활성화", false);
        }

        void Update()
        {
            bool hasTouch = false;
            Vector2 touchPosition = Vector2.zero;

            // 터치 입력
            if (UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches.Count > 0)
            {
                var touch = UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches[0];
                if (touch.phase == UnityEngine.InputSystem.TouchPhase.Began)
                {
                    hasTouch = true;
                    touchPosition = touch.screenPosition;
                }
            }
            // 마우스 입력 (에디터 테스트용)
            else if (Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame)
            {
                hasTouch = true;
                touchPosition = Mouse.current.position.ReadValue();
            }

            if (hasTouch)
            {
                Debug.Log($"[ARInteraction] 터치 감지: {touchPosition}");
                HandleTouch(touchPosition);
            }
        }

        private void HandleTouch(Vector2 screenPos)
        {
            // Camera 체크
            if (Camera.main == null)
            {
                Debug.LogError("[ARInteraction] Camera.main이 null입니다!");
                AndroidToast.Show("카메라 오류", false);
                return;
            }

            Ray ray = Camera.main.ScreenPointToRay(screenPos);
            Debug.Log($"[ARInteraction] Ray: origin={ray.origin}, direction={ray.direction}");

            RaycastHit hit;

            if (Physics.Raycast(ray, out hit, Mathf.Infinity))
            {
                Debug.Log($"[ARInteraction] ★ Raycast HIT! Object: {hit.collider.gameObject.name}");

                GameObject hitObject = hit.collider.gameObject;

                // 이전 선택 복원
                RestorePreviousSelection();

                // 새 부품 선택
                SelectPart(hitObject);

                // 좌표 정보 출력
                Vector3 worldHitPoint = hit.point;
                Vector3 localHitPoint = hitObject.transform.InverseTransformPoint(worldHitPoint);

                if (showDebugInfo)
                {
                    Debug.Log($"[ARInteraction] ===== 부품 선택 =====");
                    Debug.Log($"[ARInteraction] 부품: {hitObject.name}");
                    Debug.Log($"[ARInteraction] 월드 좌표: {worldHitPoint}");
                    Debug.Log($"[ARInteraction] 로컬 좌표: {localHitPoint}");
                    Debug.Log($"[ARInteraction] 부모: {hitObject.transform.parent?.name ?? "없음"}");
                }

                // 토스트 메시지
                AndroidToast.Show(
                    $"선택: {hitObject.name}\n" +
                    $"로컬: ({localHitPoint.x:F3}, {localHitPoint.y:F3}, {localHitPoint.z:F3})",
                    false
                );
            }
            else
            {
                Debug.Log("[ARInteraction] Raycast MISS - 아무것도 안 맞음");

                // 빈 공간 클릭 시 선택 해제
                RestorePreviousSelection();

                if (showDebugInfo)
                {
                    Debug.Log("[ARInteraction] 선택 해제");
                }
            }
        }

        private void SelectPart(GameObject part)
        {
            _selectedPart = part;

            // MeshRenderer 찾기 (자식에 있을 수 있음)
            MeshRenderer renderer = part.GetComponent<MeshRenderer>();
            if (renderer == null)
            {
                renderer = part.GetComponentInChildren<MeshRenderer>();
            }

            if (renderer != null)
            {
                // 원본 저장
                _originalMaterial = renderer.material;
                _originalColor = renderer.material.color;

                // 강조 색상 적용
                renderer.material.color = highlightColor;

                Debug.Log($"[ARInteraction] '{part.name}' 강조 (색상: {highlightColor})");
            }
        }

        private void RestorePreviousSelection()
        {
            if (_selectedPart != null)
            {
                MeshRenderer renderer = _selectedPart.GetComponent<MeshRenderer>();
                if (renderer == null)
                {
                    renderer = _selectedPart.GetComponentInChildren<MeshRenderer>();
                }

                if (renderer != null && _originalMaterial != null)
                {
                    renderer.material.color = _originalColor;
                }

                Debug.Log($"[ARInteraction] '{_selectedPart.name}' 강조 해제");
                _selectedPart = null;
            }
        }

        void OnDestroy()
        {
            EnhancedTouchSupport.Disable();
        }
    }
}
