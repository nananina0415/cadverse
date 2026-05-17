using UnityEngine;

public class UIHandler : MonoBehaviour
{
    public SimulationManager simManager;

    public void onSelectMenuButtonClick()
    {
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.Select;
    }

    public void onDragMenuButtonClick()
    {
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.Drag;
    }

    public void onViewMenuButtonClick()
    {
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.View;
    }

    public void onRefreshMenuButtonClick()
    {
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.None;
    }
}
