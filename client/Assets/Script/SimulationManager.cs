using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.EnhancedTouch;
using EnhancedTouch = UnityEngine.InputSystem.EnhancedTouch.Touch;
using System;
using System.Text;
using Cadverse;

public class SimulationManager : MonoBehaviour
{
    public enum AppMode { None, Select, Drag, View }
    public AppMode currentMode = AppMode.None;

    // 서버 네트워크 연결 객체
    public P2PConn serverConn;

    // 현재 드래그 중인 부품 이름
    private string activePartName = null;

    void OnEnable()
    {
        EnhancedTouchSupport.Enable();
    }

    void OnDisable()
    {
        EnhancedTouchSupport.Disable();
    }

    void Update()
    {
        if (currentMode == AppMode.None || currentMode == AppMode.View)
            return;

        // 모바일 / 터치 입력: New Input System EnhancedTouch 사용
        foreach (var touch in EnhancedTouch.activeTouches)
        {
            UnityEngine.TouchPhase phase = ConvertTouchPhase(touch.phase);
            bool overUI = IsPointerOverUI(touch.touchId);

            Debug.Log($"[SimulationManager] touch phase={phase}, mode={currentMode}, overUI={overUI}, pos={touch.screenPosition}");

            if (!overUI)
            {
                RouteTouchInput(touch.screenPosition, phase);
            }

            return;
        }

#if UNITY_EDITOR
        // PC 마우스 테스트용: New Input System Mouse 사용
        var mouse = Mouse.current;
        if (mouse == null)
            return;

        Vector2 pos = mouse.position.ReadValue();

        if (mouse.leftButton.wasPressedThisFrame)
        {
            if (!IsPointerOverUI())
                RouteTouchInput(pos, UnityEngine.TouchPhase.Began);
        }
        else if (mouse.leftButton.isPressed)
        {
            if (!IsPointerOverUI())
                RouteTouchInput(pos, UnityEngine.TouchPhase.Moved);
        }
        else if (mouse.leftButton.wasReleasedThisFrame)
        {
            if (!IsPointerOverUI())
                RouteTouchInput(pos, UnityEngine.TouchPhase.Ended);
        }
#endif
    }

    bool IsPointerOverUI(int fingerId = -1)
    {
        if (EventSystem.current == null)
        {
            Debug.LogWarning("[SimulationManager] EventSystem.current가 없습니다. UI 판정 생략");
            return false;
        }

        if (fingerId >= 0)
            return EventSystem.current.IsPointerOverGameObject(fingerId);

        return EventSystem.current.IsPointerOverGameObject();
    }

    UnityEngine.TouchPhase ConvertTouchPhase(UnityEngine.InputSystem.TouchPhase phase)
    {
        switch (phase)
        {
            case UnityEngine.InputSystem.TouchPhase.Began:
                return UnityEngine.TouchPhase.Began;

            case UnityEngine.InputSystem.TouchPhase.Moved:
                return UnityEngine.TouchPhase.Moved;

            case UnityEngine.InputSystem.TouchPhase.Stationary:
                return UnityEngine.TouchPhase.Stationary;

            case UnityEngine.InputSystem.TouchPhase.Ended:
                return UnityEngine.TouchPhase.Ended;

            case UnityEngine.InputSystem.TouchPhase.Canceled:
                return UnityEngine.TouchPhase.Canceled;

            default:
                return UnityEngine.TouchPhase.Moved;
        }
    }


    void RouteTouchInput(Vector2 touchPos, UnityEngine.TouchPhase phase)
    {
        if (currentMode == AppMode.None || currentMode == AppMode.View) return;

        switch (phase)
        {
            case UnityEngine.TouchPhase.Began:
                HandleTouchStart(touchPos);
                break;
            case UnityEngine.TouchPhase.Moved:
            case UnityEngine.TouchPhase.Stationary:
                HandleTouching(touchPos);
                break;
            case UnityEngine.TouchPhase.Ended:
            case UnityEngine.TouchPhase.Canceled:
                HandleTouchEnd();
                break;
        }
    }

    void HandleTouchStart(Vector2 touchPos)
    {
        Camera cam = Camera.main;
        if (cam == null)
        {
            Debug.LogWarning("[SimulationManager] Camera.main을 찾지 못했습니다.");
            return;
        }

        Ray ray = cam.ScreenPointToRay(touchPos);
        RaycastHit hit;

        if (Physics.Raycast(ray, out hit))
        {
            activePartName = hit.collider.gameObject.name;

            Vector3 actionPointLocal = hit.collider.transform.InverseTransformPoint(hit.point);

            TouchStartWrapper data = new TouchStartWrapper
            {
                payload = new TouchStartPayload
                {
                    target = new PartTarget
                    {
                        partName = activePartName
                    },
                    actionPointLocal = new Vec3(actionPointLocal),
                    fingerPointWorld = new Vec3(ray.origin),
                    cameraForwardWorld = new Vec3(ray.direction)
                }
            };

            Debug.Log($"TouchStart 대상 부품: {activePartName}, localPoint={actionPointLocal}");
            SendToServer(JsonUtility.ToJson(data));
        }
        else
        {
            Debug.LogWarning($"[SimulationManager] Raycast 실패: touchPos={touchPos}, rayOrigin={ray.origin}, rayDir={ray.direction}");
        }
    }

    void HandleTouching(Vector2 touchPos)
    {
        if (string.IsNullOrEmpty(activePartName)) return;

        Camera cam = Camera.main;
        if (cam == null)
        {
            Debug.LogWarning("[SimulationManager] Camera.main을 찾지 못했습니다.");
            return;
        }

        Ray ray = cam.ScreenPointToRay(touchPos);

        TouchingWrapper data = new TouchingWrapper
        {
            payload = new TouchingPayload
            {
                target = new PartTarget
                {
                    partName = activePartName
                },
                fingerPointWorld = new Vec3(ray.origin),
                cameraForwardWorld = new Vec3(ray.direction)
            }
        };

        SendToServer(JsonUtility.ToJson(data));
    }

    void HandleTouchEnd()
    {
        if (string.IsNullOrEmpty(activePartName)) return;

        TouchEndWrapper data = new TouchEndWrapper
        {
            payload = new TouchEndPayload
            {
                target = new PartTarget
                {
                    partName = activePartName
                }
            }
        };

        SendToServer(JsonUtility.ToJson(data));
        activePartName = null;
    }

    void SendToServer(string json)
    {
        Debug.Log($"서버로 전송 시도: {json}");
        
        if (serverConn != null)
        {
            byte[] sendBytes = Encoding.UTF8.GetBytes(json);
            bool success = serverConn.Send(sendBytes);
            
            if (!success) Debug.LogWarning("서버 전송 실패");
        }
        else
        {
            Debug.LogWarning("serverConn이 연결되지 않았습니다.");
        }
    }
}


// ── JSON 직렬화용 클래스 구조 ──────────────────

[Serializable]
public struct Vec3
{
    public float x;
    public float y;
    public float z;

    public Vec3(Vector3 v)
    {
        x = v.x;
        y = v.y;
        z = v.z;
    }
}

[Serializable]
public class PartTarget
{
    public string partName;
}

[Serializable]
public class TouchStartPayload
{
    public PartTarget target;
    public Vec3 actionPointLocal;
    public Vec3 fingerPointWorld;
    public Vec3 cameraForwardWorld;
}

[Serializable]
public class TouchingPayload
{
    public PartTarget target;
    public Vec3 fingerPointWorld;
    public Vec3 cameraForwardWorld;
}

[Serializable]
public class TouchEndPayload
{
    public PartTarget target;
}

[Serializable]
public class TouchStartWrapper
{
    public string type = "TouchStart";
    public TouchStartPayload payload;
}

[Serializable]
public class TouchingWrapper
{
    public string type = "Touching";
    public TouchingPayload payload;
}

[Serializable]
public class TouchEndWrapper
{
    public string type = "TouchEnd";
    public TouchEndPayload payload;
}