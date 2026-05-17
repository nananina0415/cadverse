using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.EnhancedTouch;
using Touch = UnityEngine.InputSystem.EnhancedTouch.Touch;

public class SimulationManager : MonoBehaviour
{
    public enum AppMode { None, Select, Drag, View }
    public AppMode currentMode = AppMode.None;

    void OnEnable()  => EnhancedTouchSupport.Enable();
    void OnDisable() => EnhancedTouchSupport.Disable();

    void Update()
    {
        var mouse = Mouse.current;
        if (mouse != null && (mouse.leftButton.wasPressedThisFrame || mouse.leftButton.isPressed))
        {
            var pos = mouse.position.ReadValue();
            if (!EventSystem.current.IsPointerOverGameObject())
                RouteTouchInput(pos.x, pos.y);
        }

        foreach (var touch in Touch.activeTouches)
        {
            if (touch.phase == UnityEngine.InputSystem.TouchPhase.Began ||
                touch.phase == UnityEngine.InputSystem.TouchPhase.Moved)
            {
                if (!EventSystem.current.IsPointerOverGameObject(touch.touchId))
                    RouteTouchInput(touch.screenPosition.x, touch.screenPosition.y);
            }
        }
    }

    void RouteTouchInput(float x, float y)
    {
        switch (currentMode)
        {
            case AppMode.Select: IdentifyPart(x, y); break;
            case AppMode.Drag:   ForceTouch(x, y);   break;
        }
    }

    void IdentifyPart(float x, float y)
    {
        Debug.Log($"부품 식별 좌표: {x}, {y}");
        // TODO: 레이캐스트 → 파트 이름 → AppManager.Net으로 UserIn 전송
    }

    void ForceTouch(float x, float y)
    {
        Debug.Log($"물리 조작 좌표: {x}, {y}");
        // TODO: 레이캐스트 → 히트 포인트 → TouchStart/Touching/TouchEnd UserIn 전송
    }
}
