using UnityEngine;
using UnityEngine.EventSystems; 
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

    void Update()
    {
        if (currentMode == AppMode.None || currentMode == AppMode.View)
            return;

        // 모바일 터치 우선 처리
        if (Input.touchCount > 0)
        {
            Touch touch = Input.GetTouch(0);

            if (!IsPointerOverUI(touch.fingerId))
            {
                RouteTouchInput(touch.position, touch.phase);
            }

            return;
        }

#if UNITY_EDITOR
        // PC 마우스 테스트용
        if (Input.GetMouseButtonDown(0))
        {
            if (!IsPointerOverUI())
                RouteTouchInput(Input.mousePosition, TouchPhase.Began);
        }
        else if (Input.GetMouseButton(0))
        {
            if (!IsPointerOverUI())
                RouteTouchInput(Input.mousePosition, TouchPhase.Moved);
        }
        else if (Input.GetMouseButtonUp(0))
        {
            if (!IsPointerOverUI())
                RouteTouchInput(Input.mousePosition, TouchPhase.Ended);
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

    void RouteTouchInput(Vector2 touchPos, TouchPhase phase)
    {
        if (currentMode == AppMode.None || currentMode == AppMode.View) return;

        switch (phase)
        {
            case TouchPhase.Began:
                HandleTouchStart(touchPos);
                break;
            case TouchPhase.Moved:
            case TouchPhase.Stationary:
                HandleTouching(touchPos);
                break;
            case TouchPhase.Ended:
            case TouchPhase.Canceled:
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