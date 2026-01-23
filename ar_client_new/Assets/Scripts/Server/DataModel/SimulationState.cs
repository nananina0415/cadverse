using System;

namespace CADverse.Server.DataModel
{
    /// <summary>
    /// 서버 → 클라이언트: 시뮬레이션 상태
    /// WebSocket을 통해 수신
    /// </summary>
    [Serializable]
    public class SimulationState
    {
        /// <summary>
        /// 시뮬레이션 타임스탬프
        /// </summary>
        public double timestamp;

        /// <summary>
        /// 모든 오브젝트의 변환 정보
        /// </summary>
        public ObjectTransform[] objects;
    }
}
