using UnityEngine;
using UnityEngine.EventSystems; // UI 터치 제외 판정을 위해 필수

public class SimulationManager : MonoBehaviour
{
    // 1. 앱의 조작 상태 정의
    public enum AppMode { None, Select, Drag, View }
    public AppMode currentMode = AppMode.None;

    void Update()
    {
        // --- [A] 유니티 에디터(PC 마우스) 테스트용 ---
        if (Input.GetMouseButtonDown(0) || Input.GetMouseButton(0))
        {
            // 마우스 커서가 UI(버튼) 위에 있지 않을 때만 실행
            if (!EventSystem.current.IsPointerOverGameObject())
            {
                RouteTouchInput(Input.mousePosition.x, Input.mousePosition.y);
            }
        }

        // --- [B] 스마트폰(모바일 터치) 실제 구동용 ---
        if (Input.touchCount > 0)
        {
            Touch touch = Input.GetTouch(0);

            // 터치한 곳이 UI(버튼) 위가 아닐 때만 실행
            if (!EventSystem.current.IsPointerOverGameObject(touch.fingerId))
            {
                if (touch.phase == TouchPhase.Began || touch.phase == TouchPhase.Moved)
                {
                    RouteTouchInput(touch.position.x, touch.position.y);
                }
            }
        }
    }

    // 2. 현재 모드에 따라 알맞은 함수로 좌표 배달
    void RouteTouchInput(float x, float y)
    {
        switch (currentMode)
        {
            case AppMode.Select:
                IdentifyPart(x, y);
                break;
            case AppMode.Drag:
                ForceTouch(x, y);
                break;
            // None이나 View 모드에서는 허공을 터치해도 아무 일도 일어나지 않음
        }
    }

    // 3. 실제 물리 연산이 들어갈 '입구' 함수들 (로그 출력으로 테스트)
    void IdentifyPart(float x, float y) 
    { 
        Debug.Log($"부품 식별 좌표 전달: {x}, {y}"); 
    }

    void ForceTouch(float x, float y) 
    { 
        Debug.Log($"물리 조작 좌표 전달: {x}, {y}"); 
    }
}