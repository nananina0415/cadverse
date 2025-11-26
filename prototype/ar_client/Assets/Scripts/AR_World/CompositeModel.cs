/// <summary>
/// 전체 모델을 구성하는 개별 파츠(Unity GameObject/Component) 인스턴스들을 보관하는 컨테이너 클래스.
/// </summary>
/// <remarks>
/// 이 클래스는 파츠 인스턴스에 대한 **접근자 역할**만을 수행합니다.
/// <list type="bullet">
/// <item> **포함 책임:** 파츠 등록, ID 기반 검색, 전체 파츠 목록 반환.</item>
/// <item> **배제 책임:** 월드에 모델이나 파츠 오브젝트 추가,
///         모델 상태 갱신, 서버 통신, 파츠의 개별 동작 로직.
/// </item>
/// </list>
/// 파츠의 상태 갱신은 중앙 로직 또는 ModelStateSetter와 같은 외부 객체에서 담당합니다.
/// </remarks>
///
/// TODO: 레코드로 변경
public class CompositeModel : MonoBehaviour
{
    // ... 클래스 내용
}
