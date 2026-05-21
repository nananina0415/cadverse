using UnityEngine;

public class UIHandler : MonoBehaviour
{
    public SimulationManager simManager;

    public void onSelectMenuButtonClick()
    {
        if (simManager == null)
        {
            Debug.LogWarning("[UIHandler] SimulationManager 연결 안 됨");
            return;
        }

        simManager.currentMode = SimulationManager.AppMode.Select;
        Debug.Log("[UIHandler] Mode 변경: Select");
    }

    public void onDragMenuButtonClick()
    {
        if (simManager == null)
        {
            Debug.LogWarning("[UIHandler] SimulationManager 연결 안 됨");
            return;
        }

        simManager.currentMode = SimulationManager.AppMode.Drag;
        Debug.Log("[UIHandler] Mode 변경: Drag");
    }

    public void onViewMenuButtonClick()
    {
        if (simManager == null)
        {
            Debug.LogWarning("[UIHandler] SimulationManager 연결 안 됨");
            return;
        }

        simManager.currentMode = SimulationManager.AppMode.View;
        Debug.Log("[UIHandler] Mode 변경: View");
    }

    public void onRefreshMenuButtonClick()
    {
        if (simManager == null)
        {
            Debug.LogWarning("[UIHandler] SimulationManager 연결 안 됨");
            return;
        }

        simManager.currentMode = SimulationManager.AppMode.None;
        Debug.Log("[UIHandler] Mode 변경: None");
    }
}