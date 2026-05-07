
// UIManager.cs에서 사용한 이름들을 이런식으로 적어둘 것
// void onMenuButtonClick() {}

using UnityEngine;

public class UIHandler : MonoBehaviour
{
    // UIManager.cs에서 사용한 이름들을 이런식으로 적어둘 것
    // 규칙: on + 컴포넌트 이름(SelectMenuButton) + 작동 내용(Click)

    public void onSelectMenuButtonClick()
    {
        Debug.Log("UI 작동: Select 모드 (기어/부품 선택 활성화)");
        // TODO: 타겟 부품 지정 및 하이라이트 로직 추가
    }

    public void onDragMenuButtonClick()
    {
        Debug.Log("UI 작동: Drag 모드 (가상 스프링 물리 인터랙션 활성화)");
        // TODO: 선택된 부품 이동/회전 로직 추가 (Collider 충돌 방지 적용)
    }

    public void onViewMenuButtonClick()
    {
        Debug.Log("UI 작동: View 모드 (토크, 힘 등 물리 데이터 라벨 On/Off)");
        // TODO: Data Overlay UI 토글 로직 추가
    }

    public void onRefreshMenuButtonClick()
    {
        Debug.Log("UI 작동: Refresh (부품 위치 및 시뮬레이션 상태 초기화)");
        // TODO: 씬 내 모든 부품 Transform 초기화 로직 추가
    }
}
