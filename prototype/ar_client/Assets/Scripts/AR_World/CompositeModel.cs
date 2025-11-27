using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 전체 모델을 구성하는 개별 파츠(Unity GameObject) 인스턴스들을 보관하는 컨테이너 클래스.
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
public class CompositeModel : MonoBehaviour
{
    private List<GameObject> _parts = new List<GameObject>();

    /// <summary>
    /// 파츠를 모델에 추가한다.
    /// </summary>
    public void AddPart(GameObject part)
    {
        if (part == null)
        {
            throw new System.ArgumentNullException(nameof(part));
        }

        _parts.Add(part);
        part.transform.SetParent(transform, worldPositionStays: false);
    }

    /// <summary>
    /// 모든 파츠를 반환한다.
    /// </summary>
    public List<GameObject> GetAllParts()
    {
        return new List<GameObject>(_parts);
    }

    /// <summary>
    /// 인덱스로 파츠를 가져온다.
    /// </summary>
    public GameObject GetPart(int index)
    {
        if (index < 0 || index >= _parts.Count)
        {
            return null;
        }

        return _parts[index];
    }

    /// <summary>
    /// 파츠 개수를 반환한다.
    /// </summary>
    public int GetPartCount()
    {
        return _parts.Count;
    }

    /// <summary>
    /// 모든 파츠를 제거한다.
    /// </summary>
    public void ClearParts()
    {
        foreach (var part in _parts)
        {
            if (part != null)
            {
                Destroy(part);
            }
        }

        _parts.Clear();
    }
}
