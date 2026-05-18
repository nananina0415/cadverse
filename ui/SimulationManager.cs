using UnityEngine;
using UnityEngine.EventSystems; 
using System;
using System.Collections.Generic; 
using System.Text; 
using Cadverse; 

public class SimulationManager : MonoBehaviour
{
    public enum AppMode { None, Select, Drag, View }
    public AppMode currentMode = AppMode.None;

    // 서버 네트워크 연결 객체
    public P2PConn serverConn;

    // 부품 이름과 서버용 ID 매핑 표
    private Dictionary<string, float> partIdMap = new Dictionary<string, float>
    {
        { "EXPORT_shaft", 0.0f },
        { "base", 1.0f },
        { "5972K315_Ball_Bearing", 2.0f }
    };

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
            float partIndex = GetPartIndex(hit.collider.gameObject);

            TouchStartWrapper data = new TouchStartWrapper
            {
                payload = new TouchStartPayload
                {
                    targetPartIndex = partIndex,
                    actionPoint = new Vec3(hit.point),
                    fingerPoint = new Vec3(ray.origin),
                    z_direction = new Vec3(ray.direction)
                }
            };

            SendToServer(JsonUtility.ToJson(data));
        }
    }

    void HandleTouching(Vector2 touchPos)
    {
        Ray ray = Camera.main.ScreenPointToRay(touchPos);

        TouchingWrapper data = new TouchingWrapper
        {
            payload = new TouchingPayload
            {
                fingerPoint = new Vec3(ray.origin),
                z_direction = new Vec3(ray.direction)
            }
        };

        SendToServer(JsonUtility.ToJson(data));
    }

    void HandleTouchEnd()
    {
        TouchEndWrapper data = new TouchEndWrapper();
        SendToServer(JsonUtility.ToJson(data));
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

    float GetPartIndex(GameObject obj)
    {
        string hitName = obj.name;

        if (partIdMap.ContainsKey(hitName))
        {
            return partIdMap[hitName];
        }

        Debug.LogWarning($"매핑 표에 없는 부품: {hitName}");
        return -1.0f; 
    }
}

// ── JSON 직렬화용 클래스 구조 ──────────────────

[Serializable]
public struct Vec3
{
    public float x;
    public float y;
    public float z;
    public Vec3(Vector3 v) { x = v.x; y = v.y; z = v.z; }
}

[Serializable]
public class TouchStartPayload
{
    public float targetPartIndex;
    public Vec3 actionPoint;
    public Vec3 fingerPoint;
    public Vec3 z_direction;
}

[Serializable]
public class TouchingPayload
{
    public Vec3 fingerPoint;
    public Vec3 z_direction;
}

[Serializable]
public class TouchEndPayload { }

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
    public TouchEndPayload payload = new TouchEndPayload();
}