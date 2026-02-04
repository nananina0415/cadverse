using System;
using System.Collections.Generic;
using UnityEngine;

namespace CADverse.Communication
{
    /// <summary>
    /// GET /cadverse/object 응답
    /// </summary>
    [Serializable]
    public class ObjectList
    {
        public List<string> objects;
    }

    /// <summary>
    /// 오브젝트의 위치와 회전 정보 (WebSocket에서 수신)
    /// </summary>
    [Serializable]
    public class ObjectTransform
    {
        public string name;
        public float[] position;  // [x, y, z]
        public float[] rotation;  // [x, y, z, w] (quaternion)

        public Vector3 GetPosition()
        {
            if (position == null || position.Length < 3) return Vector3.zero;
            return new Vector3(position[0], position[1], position[2]);
        }

        public Quaternion GetRotation()
        {
            if (rotation == null || rotation.Length < 4) return Quaternion.identity;
            return new Quaternion(rotation[0], rotation[1], rotation[2], rotation[3]);
        }
    }

    /// <summary>
    /// 시뮬레이션 상태 (WebSocket에서 수신)
    /// </summary>
    [Serializable]
    public class SimulationState
    {
        public double timestamp;
        public List<ObjectTransform> objects;
    }

    // ===== 클라이언트 → 서버 터치 입력 메시지 =====

    /// <summary>
    /// 3D 벡터 (JSON 직렬화용)
    /// </summary>
    [Serializable]
    public class Vec3
    {
        public float x;
        public float y;
        public float z;

        public Vec3() { }
        public Vec3(Vector3 v) { x = v.x; y = v.y; z = v.z; }
        public Vec3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
    }

    /// <summary>
    /// TouchStart 페이로드
    /// </summary>
    [Serializable]
    public class TouchStartPayload
    {
        public int targetPartIndex;
        public Vec3 actionPoint;
        public Vec3 fingerPoint;
        public Vec3 z_direction;
    }

    /// <summary>
    /// Touching 페이로드
    /// </summary>
    [Serializable]
    public class TouchingPayload
    {
        public Vec3 fingerPoint;
        public Vec3 z_direction;
    }

    /// <summary>
    /// TouchEnd 페이로드 (빈 객체)
    /// </summary>
    [Serializable]
    public class TouchEndPayload { }

    /// <summary>
    /// 터치 입력 메시지 베이스
    /// </summary>
    [Serializable]
    public class TouchInputMessage<T>
    {
        public string type;
        public T payload;
    }

    /// <summary>
    /// 터치 입력 메시지 헬퍼
    /// </summary>
    public static class TouchInput
    {
        public static string CreateTouchStart(int partIndex, Vector3 actionPoint, Vector3 cameraPos, Vector3 cameraForward)
        {
            var msg = new TouchInputMessage<TouchStartPayload>
            {
                type = "TouchStart",
                payload = new TouchStartPayload
                {
                    targetPartIndex = partIndex,
                    actionPoint = new Vec3(actionPoint),
                    fingerPoint = new Vec3(cameraPos),
                    z_direction = new Vec3(cameraForward)
                }
            };
            return JsonUtility.ToJson(msg);
        }

        public static string CreateTouching(Vector3 cameraPos, Vector3 cameraForward)
        {
            var msg = new TouchInputMessage<TouchingPayload>
            {
                type = "Touching",
                payload = new TouchingPayload
                {
                    fingerPoint = new Vec3(cameraPos),
                    z_direction = new Vec3(cameraForward)
                }
            };
            return JsonUtility.ToJson(msg);
        }

        public static string CreateTouchEnd()
        {
            var msg = new TouchInputMessage<TouchEndPayload>
            {
                type = "TouchEnd",
                payload = new TouchEndPayload()
            };
            return JsonUtility.ToJson(msg);
        }
    }
}
