/*
 * 이 파일은 NetWork.cs에서 제거된 코드들을 보관합니다.
 * 향후 필요시 참고용으로 사용할 수 있습니다.
 */

using System;
using UnityEngine;

namespace CADverse.Deprecated
{
    /// <summary>
    /// [제거됨] 기존 NetWork.cs의 자동 시작 로직
    ///
    /// 이유: SimServer에서 명시적으로 Connect()를 호출하도록 변경
    /// Communication 레이어에서 연결 시점을 제어하는 것이 더 적절함
    /// </summary>
    public class AutoStartExample
    {
        // private void Start()
        // {
        //     ConnectWebSocket();
        // }
    }

    /// <summary>
    /// [제거됨] OnPoseDataReceived 이벤트
    ///
    /// 이유: ModelStateMessage로 대체됨
    /// 단순 문자열 대신 타입 안전한 DTO 사용
    /// </summary>
    public class OldPoseDataEvent
    {
        // public event Action<string> OnPoseDataReceived;
        //
        // private void HandleWebSocketMessage(string message)
        // {
        //     OnPoseDataReceived?.Invoke(message);
        // }
    }

    /// <summary>
    /// [제거됨] MonoBehaviour 기반 ServerConnection
    ///
    /// 이유: MonoBehaviour가 필요 없는 순수 연결 로직
    /// Communication/SimServer에서 MonoBehaviour로 관리하는 것이 더 적절함
    /// </summary>
    public class MonoBehaviourConnectionExample
    {
        // public sealed class NetWork : MonoBehaviour
        // {
        //     // Update() 메서드
        //     // OnDestroy() 메서드
        //     // Coroutine 재접속 로직
        // }
    }

    /// <summary>
    /// [TODO] 향후 추가 예정 기능
    /// </summary>
    public class FutureFeatures
    {
        /*
         * 1. 연결 상태 모니터링
         *    - 네트워크 품질 측정
         *    - 지연 시간(latency) 측정
         *    - 패킷 손실률 추적
         *
         * 2. 메시지 큐 관리
         *    - 오프라인 시 메시지 버퍼링
         *    - 재연결 시 자동 재전송
         *
         * 3. 압축 및 최적화
         *    - JSON 압축 (gzip)
         *    - 바이너리 프로토콜 지원 (MessagePack, Protobuf)
         *
         * 4. 보안
         *    - TLS/SSL 인증서 검증
         *    - 토큰 기반 인증
         */
    }
}
