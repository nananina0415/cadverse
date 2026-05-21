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
        // PC 마우스 테스트용
        if (Input.GetMouseButtonDown(0))
        {
            if (!EventSystem.current.IsPointerOverGameObject())
                RouteTouchInput(Input.mousePosition, TouchPhase.Began);
        }
        else if (Input.GetMouseButton(0))
        {
            if (!EventSystem.current.IsPointerOverGameObject())
                RouteTouchInput(Input.mousePosition, TouchPhase.Moved);
        }
        else if (Input.GetMouseButtonUp(0))
        {
            if (!EventSystem.current.IsPointerOverGameObject())
                RouteTouchInput(Input.mousePosition, TouchPhase.Ended);
        }

        // 모바일 터치 구동용
        if (Input.touchCount > 0)
        {
            Touch touch = Input.GetTouch(0);

            if (!EventSystem.current.IsPointerOverGameObject(touch.fingerId))
            {
                RouteTouchInput(touch.position, touch.phase);
            }
        }
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
        Ray ray = Camera.main.ScreenPointToRay(touchPos);
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

        Ray ray = Camera.main.ScreenPointToRay(touchPos);

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