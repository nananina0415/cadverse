using UnityEngine;

public class UIHandler : MonoBehaviour
{
    public SimulationManager simManager;

    public void onSelectMenuButtonClick()
    {
        Debug.Log("버튼 클릭됨: Select"); 
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.Select;
        else Debug.LogError("🚨 에러: Inspector 창에서 Sim Manager 빈칸이 비어있습니다!");
    }

    public void onDragMenuButtonClick()
    {
        Debug.Log("버튼 클릭됨: Drag");
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.Drag;
        else Debug.LogError("🚨 에러: Inspector 창에서 Sim Manager 빈칸이 비어있습니다!");
    }

    public void onViewMenuButtonClick()
    {
        Debug.Log("버튼 클릭됨: View");
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.View;
        else Debug.LogError("🚨 에러: Inspector 창에서 Sim Manager 빈칸이 비어있습니다!");
    }

    public void onRefreshMenuButtonClick()
    {
        Debug.Log("버튼 클릭됨: Refresh");
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.None;
        else Debug.LogError("🚨 에러: Inspector 창에서 Sim Manager 빈칸이 비어있습니다!");
    }
}