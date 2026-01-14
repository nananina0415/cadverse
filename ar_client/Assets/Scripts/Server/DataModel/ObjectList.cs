using System;

namespace CADverse.Server.DataModel
{
    /// <summary>
    /// 서버 → 클라이언트: 오브젝트 리스트
    /// GET /cadverse/object 응답
    /// </summary>
    [Serializable]
    public class ObjectList
    {
        /// <summary>
        /// 시뮬레이션에 존재하는 오브젝트 이름 목록
        /// </summary>
        public string[] objects;
    }
}
