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
}
