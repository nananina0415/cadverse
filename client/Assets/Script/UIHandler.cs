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

    public void onRefreshMenuButtonClick()
    {
        if (simManager != null) simManager.currentMode = SimulationManager.AppMode.None;
    }

    public void onInfoMenuButtonClick()
    {
        Cadverse.AppManager.NeedsFullInfo = !Cadverse.AppManager.NeedsFullInfo;

        if (Cadverse.AppManager.NeedsFullInfo)
        {
            Cadverse.PartDataLabelOverlay.Ensure().SetVisible(true);
            Cadverse.StatusOverlay.Ensure().SetVisible(true);
            Debug.Log("[UIHandler] Info display mode enabled");
        }
        else
        {
            Cadverse.PartDataLabelOverlay.Instance?.Clear();
            Cadverse.StatusOverlay.Instance?.Clear();
            Debug.Log("[UIHandler] Info display mode disabled");
        }
    }
}
