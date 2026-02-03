using UnityEngine;
using UnityEngine.EventSystems;
using CADverse.Communication;

namespace CADverse.Input
{
    /// <summary>
    /// 터치 입력을 레이캐스트하여 서버로 전송하는 컨트롤러
    /// </summary>
    public class TouchInputController : MonoBehaviour
    {
        [SerializeField] private ServerProxy _serverProxy;
        [SerializeField] private Camera _arCamera;
        [SerializeField] private LayerMask _modelLayerMask = -1; // 기본: 모든 레이어

        private bool _isTouching = false;
        private int _currentPartIndex = -1;

        void Awake()
        {
            if (_serverProxy == null)
            {
                _serverProxy = FindFirstObjectByType<ServerProxy>();
            }
            if (_arCamera == null)
            {
                _arCamera = Camera.main;
            }
        }

        void Update()
        {
            // 터치 입력 처리
            if (UnityEngine.Input.touchCount > 0)
            {
                Touch touch = UnityEngine.Input.GetTouch(0);

                // UI 위의 터치는 무시
                if (touch.phase == TouchPhase.Began && IsPointerOverUI(touch.fingerId))
                {
                    Debug.Log("[TouchInput] UI 위 터치 - 무시");
                    return;
                }

                Debug.Log($"[TouchInput] Touch detected: phase={touch.phase}, pos={touch.position}");
                ProcessTouch(touch.position, touch.phase);
            }
#if UNITY_EDITOR
            // 에디터에서 마우스 입력으로 테스트
            else if (UnityEngine.Input.GetMouseButtonDown(0))
            {
                if (IsPointerOverUI(-1))
                {
                    Debug.Log("[TouchInput] UI 위 클릭 - 무시");
                    return;
                }
                Debug.Log($"[TouchInput] Mouse down: pos={UnityEngine.Input.mousePosition}");
                ProcessTouch(UnityEngine.Input.mousePosition, TouchPhase.Began);
            }
            else if (UnityEngine.Input.GetMouseButton(0))
            {
                ProcessTouch(UnityEngine.Input.mousePosition, TouchPhase.Moved);
            }
            else if (UnityEngine.Input.GetMouseButtonUp(0))
            {
                Debug.Log("[TouchInput] Mouse up");
                ProcessTouch(UnityEngine.Input.mousePosition, TouchPhase.Ended);
            }
#endif
        }

        /// <summary>
        /// 터치/마우스가 UI 위에 있는지 확인
        /// </summary>
        private bool IsPointerOverUI(int fingerId)
        {
            if (EventSystem.current == null) return false;

            if (fingerId >= 0)
            {
                return EventSystem.current.IsPointerOverGameObject(fingerId);
            }
            else
            {
                return EventSystem.current.IsPointerOverGameObject();
            }
        }

        private void ProcessTouch(Vector2 screenPos, TouchPhase phase)
        {
            if (_arCamera == null || _serverProxy == null) return;

            Vector3 cameraPos = _arCamera.transform.position;
            Vector3 cameraForward = _arCamera.transform.forward;

            switch (phase)
            {
                case TouchPhase.Began:
                    HandleTouchStart(screenPos, cameraPos, cameraForward);
                    break;

                case TouchPhase.Moved:
                case TouchPhase.Stationary:
                    if (_isTouching)
                    {
                        HandleTouching(cameraPos, cameraForward);
                    }
                    break;

                case TouchPhase.Ended:
                case TouchPhase.Canceled:
                    HandleTouchEnd();
                    break;
            }
        }

        private void HandleTouchStart(Vector2 screenPos, Vector3 cameraPos, Vector3 cameraForward)
        {
            Ray ray = _arCamera.ScreenPointToRay(screenPos);

            if (Physics.Raycast(ray, out RaycastHit hit, 10f, _modelLayerMask))
            {
                // 히트된 오브젝트의 부품 인덱스 추출
                _currentPartIndex = GetPartIndex(hit.collider.gameObject);

                // 로컬 좌표로 변환
                Vector3 localHitPoint = hit.collider.transform.InverseTransformPoint(hit.point);

                string json = TouchInput.CreateTouchStart(_currentPartIndex, localHitPoint, cameraPos, cameraForward);
                _ = _serverProxy.SendMessageAsync(json);

                _isTouching = true;
                Debug.Log($"[TouchInput] TouchStart: part={_currentPartIndex}, point={localHitPoint}");
            }
        }

        private void HandleTouching(Vector3 cameraPos, Vector3 cameraForward)
        {
            string json = TouchInput.CreateTouching(cameraPos, cameraForward);
            _ = _serverProxy.SendMessageAsync(json);
            Debug.Log($"[TouchInput] Touching: cam={cameraPos}, dir={cameraForward}");
        }

        private void HandleTouchEnd()
        {
            if (_isTouching)
            {
                string json = TouchInput.CreateTouchEnd();
                _ = _serverProxy.SendMessageAsync(json);

                _isTouching = false;
                _currentPartIndex = -1;
                Debug.Log("[TouchInput] TouchEnd");
            }
        }

        /// <summary>
        /// GameObject에서 부품 인덱스를 추출한다.
        /// (부모 루트에서의 sibling index 사용)
        /// </summary>
        private int GetPartIndex(GameObject obj)
        {
            // 모델 루트의 자식 인덱스 반환
            Transform parent = obj.transform.parent;
            if (parent != null)
            {
                for (int i = 0; i < parent.childCount; i++)
                {
                    if (parent.GetChild(i) == obj.transform)
                    {
                        return i;
                    }
                }
            }
            return 0;
        }
    }
}
