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
        if (currentMode == AppMode.Drag && _dragActive) DragEnded();
        _activeTouchId = -1;
    }

    // ── Drag implementation ─────────────────────────────────

    void DragBegan(int id, Vector2 screenPos)
    {
        var cam = Camera.main;
        if (cam == null) return;

        Ray ray = cam.ScreenPointToRay(screenPos);
        if (!Physics.Raycast(ray, out RaycastHit hit)) return;

        int partIdx = AppManager.Scene?.IndexOf(hit.collider.name) ?? -1;
        if (partIdx < 0) return;

        var server = ActiveServer();
        if (server == null) return;

        server.SendTouchStart(partIdx, hit.point, ray.origin, ray.direction);

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
        ActiveServer()?.SendTouching(ray.origin, ray.direction);
        _arrow?.UpdateTip(ray);
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
