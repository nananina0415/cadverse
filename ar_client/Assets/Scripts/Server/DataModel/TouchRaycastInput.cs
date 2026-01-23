using System;
using UnityEngine;

namespace CADverse.Server.DataModel
{
    /// <summary>
    /// 3D 벡터
    /// 자동 생성됨 - touch_raycast_input.ts에서 생성
    /// </summary>
    [Serializable]
    public class Vector3Data
    {
        public float x;
        public float y;
        public float z;

        public Vector3Data(Vector3 v)
        {
            x = v.x;
            y = v.y;
            z = v.z;
        }
    }

    /// <summary>
    /// TouchStart 페이로드
    /// 자동 생성됨 - touch_raycast_input.ts에서 생성
    /// </summary>
    [Serializable]
    public class TouchStartPayload
    {
        /// <summary>
        /// 터치한 부품의 인덱스
        /// </summary>
        public int targetPartIndex;

        /// <summary>
        /// 터치 지점 (부품 로컬 좌표)
        /// </summary>
        public Vector3Data actionPoint;

        /// <summary>
        /// 카메라 위치 (월드 좌표)
        /// </summary>
        public Vector3Data fingerPoint;

        /// <summary>
        /// 카메라 방향 (정규화된 벡터)
        /// </summary>
        public Vector3Data z_direction;
    }

    /// <summary>
    /// Touching 페이로드
    /// 자동 생성됨 - touch_raycast_input.ts에서 생성
    /// </summary>
    [Serializable]
    public class TouchingPayload
    {
        /// <summary>
        /// 변경된 카메라 위치 (월드 좌표)
        /// </summary>
        public Vector3Data fingerPoint;

        /// <summary>
        /// 변경된 카메라 방향 (정규화된 벡터)
        /// </summary>
        public Vector3Data z_direction;
    }

    /// <summary>
    /// TouchEnd 페이로드 (빈 객체)
    /// 자동 생성됨 - touch_raycast_input.ts에서 생성
    /// </summary>
    [Serializable]
    public class TouchEndPayload
    {
        // empty
    }

    /// <summary>
    /// TouchStart 메시지
    /// 자동 생성됨 - touch_raycast_input.ts에서 생성
    /// </summary>
    [Serializable]
    public class TouchStartMessage
    {
        public string type = "TouchStart";
        public TouchStartPayload payload;
    }

    /// <summary>
    /// Touching 메시지
    /// 자동 생성됨 - touch_raycast_input.ts에서 생성
    /// </summary>
    [Serializable]
    public class TouchingMessage
    {
        public string type = "Touching";
        public TouchingPayload payload;
    }

    /// <summary>
    /// TouchEnd 메시지
    /// 자동 생성됨 - touch_raycast_input.ts에서 생성
    /// </summary>
    [Serializable]
    public class TouchEndMessage
    {
        public string type = "TouchEnd";
        public TouchEndPayload payload;
    }
}
