using UnityEngine;

public class ARUIManager : MonoBehaviour
{
    public GameObject portraitBottomBar;
    public GameObject landscapeRightBar;

    void Update()
    {
        // 폰이 세로일 때: 하단 바 ON, 우측 바 OFF
        if (Screen.orientation == ScreenOrientation.Portrait || Screen.orientation == ScreenOrientation.PortraitUpsideDown)
        {
            portraitBottomBar.SetActive(true);
            landscapeRightBar.SetActive(false);
        }
        // 폰이 가로일 때: 하단 바 OFF, 우측 바 ON
        else if (Screen.orientation == ScreenOrientation.LandscapeLeft || Screen.orientation == ScreenOrientation.LandscapeRight)
        {
            portraitBottomBar.SetActive(false);
            landscapeRightBar.SetActive(true);
        }
    }
}