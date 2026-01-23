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
        private bool _isTouching = false; // 부품을 터치 중인지 여부

        // 힘 화살표 시각화
        private ForceArrowVisualizer _forceArrow;
        private Vector3 _touchStartWorldPoint;

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
            bool isTouchEnd = false;
            Vector2 touchPosition = Vector2.zero;

            // 터치 입력
            if (UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches.Count > 0)
            {
                var touch = UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches[0];
                touchPosition = touch.screenPosition;

                if (touch.phase == UnityEngine.InputSystem.TouchPhase.Began)
                {
                    hasTouch = true;
                }
                else if (touch.phase == UnityEngine.InputSystem.TouchPhase.Moved)
                {
                    HandleTouchMove(touchPosition);
                    return;
                }
                else if (touch.phase == UnityEngine.InputSystem.TouchPhase.Ended)
                {
                    isTouchEnd = true;
                }
            }
            // 마우스 입력 (에디터 테스트용)
            else if (Mouse.current != null)
            {
                if (Mouse.current.leftButton.wasPressedThisFrame)
                {
                    hasTouch = true;
                    touchPosition = Mouse.current.position.ReadValue();
                }
                else if (Mouse.current.leftButton.isPressed)
                {
                    touchPosition = Mouse.current.position.ReadValue();
                    HandleTouchMove(touchPosition);
                    return;
                }
                else if (Mouse.current.leftButton.wasReleasedThisFrame)
                {
                    isTouchEnd = true;
                }
            }

            if (hasTouch)
            {
                Debug.Log($"[ARInteraction] 터치 시작: {touchPosition}");
                HandleTouchStart(touchPosition);
            }
            else if (isTouchEnd)
            {
                Debug.Log("[ARInteraction] 터치 종료");
                HandleTouchEnd();
            }
        }

        private void HandleTouchStart(Vector2 screenPos)
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

                // 좌표 정보
                Vector3 worldHitPoint = hit.point;
                Vector3 localHitPoint = hitObject.transform.InverseTransformPoint(worldHitPoint);

                // 부품 인덱스 찾기
                int partIndex = GetPartIndex(hitObject);

                if (showDebugInfo)
                {
                    Debug.Log($"[ARInteraction] ===== 부품 터치 =====");
                    Debug.Log($"[ARInteraction] 부품: {hitObject.name}");
                    Debug.Log($"[ARInteraction] 인덱스: {partIndex}");
                    Debug.Log($"[ARInteraction] 월드 좌표: {worldHitPoint}");
                    Debug.Log($"[ARInteraction] 로컬 좌표: {localHitPoint}");
                    Debug.Log($"[ARInteraction] 부모: {hitObject.transform.parent?.name ?? "없음"}");
                }

                // 터치 시작 플래그 설정
                _isTouching = true;

                // 터치 시작점 저장
                _touchStartWorldPoint = worldHitPoint;

                // 화살표 초기화
                if (_forceArrow == null)
                {
                    var arrowObj = new GameObject("ForceArrow");
                    _forceArrow = arrowObj.AddComponent<ForceArrowVisualizer>();
                }

                // 서버로 전송
                SendPartTouchToServer(partIndex, localHitPoint);

                // 토스트 메시지
                AndroidToast.Show(
                    $"선택: {hitObject.name} [#{partIndex}]\n" +
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

        private int GetPartIndex(GameObject partObject)
        {
            // CompositeModel에서 파트 인덱스 찾기
            // partObject는 실제 메쉬이므로, 부모(wrapper)를 찾아야 함
            Transform wrapper = partObject.transform.parent;

            if (wrapper == null)
            {
                Debug.LogWarning("[ARInteraction] 부품의 wrapper를 찾을 수 없음");
                return -1;
            }

            // CompositeModel 찾기
            CompositeModel model = wrapper.GetComponentInParent<CompositeModel>();
            if (model == null)
            {
                Debug.LogWarning("[ARInteraction] CompositeModel을 찾을 수 없음");
                return -1;
            }

            // 인덱스 찾기
            for (int i = 0; i < model.GetPartCount(); i++)
            {
                if (model.GetPart(i) == wrapper.gameObject)
                {
                    return i;
                }
            }

            Debug.LogWarning($"[ARInteraction] '{wrapper.name}' 인덱스를 찾을 수 없음");
            return -1;
        }

        private void SendPartTouchToServer(int partIndex, Vector3 localPoint)
        {
            if (partIndex < 0)
            {
                Debug.LogWarning("[ARInteraction] 유효하지 않은 부품 인덱스");
                return;
            }

            // 카메라 위치와 방향 (fingerPoint, z_direction)
            Camera cam = Camera.main;
            if (cam == null) return;

            Vector3 fingerPoint = cam.transform.position;
            Vector3 zDirection = cam.transform.forward;

            // InteractByScreen.TouchStart JSON 생성
            string json = $@"{{
  ""type"": ""TouchStart"",
  ""payload"": {{
    ""targetPartIndex"": {partIndex},
    ""actionPoint"": {{
      ""x"": {localPoint.x:F6},
      ""y"": {localPoint.y:F6},
      ""z"": {localPoint.z:F6}
    }},
    ""fingerPoint"": {{
      ""x"": {fingerPoint.x:F6},
      ""y"": {fingerPoint.y:F6},
      ""z"": {fingerPoint.z:F6}
    }},
    ""z_direction"": {{
      ""x"": {zDirection.x:F6},
      ""y"": {zDirection.y:F6},
      ""z"": {zDirection.z:F6}
    }}
  }}
}}";

            SendToServer(json, "TouchStart");
        }

        private void HandleTouchMove(Vector2 screenPos)
        {
            // 부품을 터치 중이 아니면 무시
            if (!_isTouching) return;

            Camera cam = Camera.main;
            if (cam == null) return;

            Vector3 fingerPoint = cam.transform.position;
            Vector3 zDirection = cam.transform.forward;

            // 작용점을 스크린 좌표로 변환
            Vector2 actionPointScreen = cam.WorldToScreenPoint(_touchStartWorldPoint);

            // 2D 화살표 표시: 작용점(스크린) → 현재 터치 위치(스크린)
            if (_forceArrow != null)
            {
                _forceArrow.ShowArrow(actionPointScreen, screenPos);
            }

            // Touching JSON 생성
            string json = $@"{{
  ""type"": ""Touching"",
  ""payload"": {{
    ""fingerPoint"": {{
      ""x"": {fingerPoint.x:F6},
      ""y"": {fingerPoint.y:F6},
      ""z"": {fingerPoint.z:F6}
    }},
    ""z_direction"": {{
      ""x"": {zDirection.x:F6},
      ""y"": {zDirection.y:F6},
      ""z"": {zDirection.z:F6}
    }}
  }}
}}";

            SendToServer(json, "Touching");
        }

        private void HandleTouchEnd()
        {
            // 부품을 터치 중이 아니면 무시
            if (!_isTouching)
            {
                return;
            }

            // 터치 종료 플래그 리셋
            _isTouching = false;

            // 화살표 숨기기
            if (_forceArrow != null)
            {
                _forceArrow.Hide();
            }

            // TouchEnd JSON 생성
            string json = "{\n  \"type\": \"TouchEnd\",\n  \"payload\": {}\n}";

            SendToServer(json, "TouchEnd");

            // 선택 해제
            RestorePreviousSelection();
        }

        private void SendToServer(string json, string msgType)
        {
            var simServer = FindFirstObjectByType<CADverse.Communication.SimServer>();
            if (simServer != null && simServer.IsConnected)
            {
                simServer.SendRawMessage(json);
                Debug.Log($"[ARInteraction] {msgType} 전송");
            }
            else
            {
                Debug.LogWarning("[ARInteraction] SimServer 연결되지 않음");
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
