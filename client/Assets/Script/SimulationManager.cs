using Cadverse;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.EnhancedTouch;
using Touch = UnityEngine.InputSystem.EnhancedTouch.Touch;

public class SimulationManager : MonoBehaviour
{
    // None      : 입력 무시
    // Select    : 객체 클릭 → 모델 정보 표시 (UI 작성자가 채울 자리)
    // Drag      : 객체 잡고 끌기 → TouchStart/Touching/TouchEnd 전송 + 화살표 시각화
    // Transform : 모델 확대/축소/회전/이동 (이동은 QR 법선축만) — 추후 구현
    public enum AppMode { None, Select, Drag, Transform }
    public AppMode currentMode = AppMode.None;

    DragArrow _arrow;
    bool      _dragActive;
    int       _activeTouchId = -1;   // 어떤 손가락이 드래그 중인지 (마우스면 -2)
    const int MouseTouchId = -2;

    void OnEnable()  => EnhancedTouchSupport.Enable();
    void OnDisable() => EnhancedTouchSupport.Disable();

    void Update()
    {
        HandleMouse();
        HandleTouches();
    }

    // ── Input dispatch ──────────────────────────────────────

    void HandleMouse()
    {
        var mouse = Mouse.current;
        if (mouse == null) return;

        Vector2 pos = mouse.position.ReadValue();

        if (mouse.leftButton.wasPressedThisFrame)
        {
            if (!EventSystem.current.IsPointerOverGameObject())
                OnTouchBegan(MouseTouchId, pos);
        }
        else if (mouse.leftButton.isPressed && _activeTouchId == MouseTouchId)
        {
            OnTouchMoved(pos);
        }
        else if (mouse.leftButton.wasReleasedThisFrame && _activeTouchId == MouseTouchId)
        {
            OnTouchEnded();
        }
    }

    void HandleTouches()
    {
        foreach (var t in Touch.activeTouches)
        {
            int id = t.touchId;
            Vector2 pos = t.screenPosition;

            switch (t.phase)
            {
                case UnityEngine.InputSystem.TouchPhase.Began:
                    if (!EventSystem.current.IsPointerOverGameObject(id))
                        OnTouchBegan(id, pos);
                    break;
                case UnityEngine.InputSystem.TouchPhase.Moved:
                case UnityEngine.InputSystem.TouchPhase.Stationary:
                    if (_activeTouchId == id) OnTouchMoved(pos);
                    break;
                case UnityEngine.InputSystem.TouchPhase.Ended:
                case UnityEngine.InputSystem.TouchPhase.Canceled:
                    if (_activeTouchId == id) OnTouchEnded();
                    break;
            }
        }
    }

    // ── Mode-aware handlers ─────────────────────────────────

    void OnTouchBegan(int id, Vector2 screenPos)
    {
#if UNITY_EDITOR
        Debug.Log($"[Touch] Began id={id} pos={screenPos} mode={currentMode}");
#endif
        switch (currentMode)
        {
            case AppMode.Drag:
                DragBegan(id, screenPos);
                break;
            case AppMode.Select:
                // TODO(UI): 객체 클릭 → 모델 정보 패널 표시. 정보 표시 모드 진입 시
                //           AppManager.NeedsFullInfo = true 로 토글해서 SimFrameAndInfo()를 받아야 함.
                break;
            case AppMode.Transform:
                // TODO: 확대/축소/회전/이동 모드. 위치 이동은 QR 법선축만.
                break;
        }
    }

    void OnTouchMoved(Vector2 screenPos)
    {
        if (currentMode == AppMode.Drag && _dragActive) DragMoved(screenPos);
    }

    void OnTouchEnded()
    {
#if UNITY_EDITOR
        Debug.Log($"[Touch] Ended mode={currentMode} dragActive={_dragActive}");
#endif
        if (currentMode == AppMode.Drag && _dragActive) DragEnded();
        _activeTouchId = -1;
    }

    // ── Drag implementation ─────────────────────────────────

    void DragBegan(int id, Vector2 screenPos)
    {
        var cam = Camera.main;
        if (cam == null) return;

        Ray ray = cam.ScreenPointToRay(screenPos);
        if (!Physics.Raycast(ray, out RaycastHit hit))
        {
#if UNITY_EDITOR
            Debug.Log($"[Drag] raycast miss. ray.origin={ray.origin} dir={ray.direction}");
#endif
            return;
        }

        int partIdx = AppManager.Scene?.IndexOf(hit.collider.name) ?? -1;
#if UNITY_EDITOR
        Debug.Log($"[Drag] hit name={hit.collider.name} idx={partIdx} point={hit.point}");
#endif
        if (partIdx < 0) return;

        var server = ActiveServer();
        if (server == null)
        {
#if UNITY_EDITOR
            Debug.LogWarning("[Drag] active Server 없음 — 입력 전송 안 됨");
#endif
            return;
        }

        // finger를 action(hit.point)과 동일하게 보내 첫 프레임 spring 길이 0으로 시작.
        // 이전엔 ray.origin(= 카메라 위치)을 finger로 보내 항상 폰 쪽으로 끌리는 힘이 가해졌음.
        bool ok = server.SendTouchStart(partIdx, hit.point, hit.point, ray.direction);
#if UNITY_EDITOR
        Debug.Log($"[Drag] SendTouchStart ok={ok} partIdx={partIdx}");
#endif

        if (_arrow == null) _arrow = DragArrow.Create();
        _arrow.Show(hit.point);

        _dragActive    = true;
        _activeTouchId = id;
    }

    void DragMoved(Vector2 screenPos)
    {
        var cam = Camera.main;
        if (cam == null) return;

        Ray ray = cam.ScreenPointToRay(screenPos);
        // DragArrow가 계산한 tip(= 모델점 지나는 평면 ⊥ cam.forward와 ray의 교차점)을
        // 시뮬 finger로 그대로 송신. 시각화와 시뮬 force가 항상 일치.
        Vector3 tip = _arrow != null ? _arrow.UpdateTip(ray) : ray.origin;
        ActiveServer()?.SendTouching(tip, ray.direction);
    }

    void DragEnded()
    {
        ActiveServer()?.SendTouchEnd();
        _arrow?.Hide();
        _dragActive = false;
    }

    static Server ActiveServer()
        => AppManager.Servers.Count > 0 ? AppManager.Servers[0] : null;
}
