

// 예시
// using UnityEngine;
// using UnityEngine.UI;;
// 원래는 클래스안에 있는건데 생략
// menuButton.onClick.AddListener(UIHandler.onMenuButtonClick);

using UnityEngine;
using UnityEngine.UI;

public class UIManager : MonoBehaviour
{
    [Header("기능 핸들러 연결")]
    // UIHandler.cs 스크립트의 기능들을 가져오기 위한 변수
    public UIHandler uiHandler; 

    [Header("UI 컴포넌트 이름")]
    public Button selectMenuButton;
    public Button dragMenuButton;
    public Button viewMenuButton;
    public Button refreshMenuButton;

    [Header("반응형 UI 패널")]
    public GameObject portraitBottomBar;
    public GameObject landscapeRightBar;

    void Start()
    {
        // 원래는 클래스안에 있는건데 생략된 형태를 구체화
        // 규칙: 컴포넌트이름.onClick.AddListener(핸들러.on컴포넌트이름Click);
        
        if (selectMenuButton != null && uiHandler != null)
            selectMenuButton.onClick.AddListener(uiHandler.onSelectMenuButtonClick);
        
        if (dragMenuButton != null && uiHandler != null)
            dragMenuButton.onClick.AddListener(uiHandler.onDragMenuButtonClick);
        
        if (viewMenuButton != null && uiHandler != null)
            viewMenuButton.onClick.AddListener(uiHandler.onViewMenuButtonClick);
        
        if (refreshMenuButton != null && uiHandler != null)
            refreshMenuButton.onClick.AddListener(uiHandler.onRefreshMenuButtonClick);
    }

    void Update()
    {
        // 실시간 화면 방향 감지 및 패널 전환 (반응형 레이아웃)
        if (Screen.orientation == ScreenOrientation.Portrait || Screen.orientation == ScreenOrientation.PortraitUpsideDown)
        {
            portraitBottomBar.SetActive(true);
            landscapeRightBar.SetActive(false);
        }
        else if (Screen.orientation == ScreenOrientation.LandscapeLeft || Screen.orientation == ScreenOrientation.LandscapeRight)
        {
            portraitBottomBar.SetActive(false);
            landscapeRightBar.SetActive(true);
        }
    }
}
