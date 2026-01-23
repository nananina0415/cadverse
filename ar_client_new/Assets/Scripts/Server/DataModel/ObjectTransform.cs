using System;
using UnityEngine;

namespace CADverse.Server.DataModel
{
    /// <summary>
    /// 오브젝트의 위치와 회전 정보
    /// </summary>
    [Serializable]
    public class ObjectTransform
    {
        /// <summary>
        /// 오브젝트 이름
        /// </summary>
        public string name;

        /// <summary>
        /// 위치 [x, y, z]
        /// </summary>
        public float[] position;

        /// <summary>
        /// 회전 (쿼터니언) [x, y, z, w]
        /// </summary>
        public float[] rotation;

        /// <summary>
        /// Unity Vector3로 변환
        /// </summary>
        public Vector3 GetPosition()
        {
            return new Vector3(position[0], position[1], position[2]);
        }

        /// <summary>
        /// Unity Quaternion으로 변환
        /// </summary>
        public Quaternion GetRotation()
        {
            return new Quaternion(rotation[0], rotation[1], rotation[2], rotation[3]);
        }
    }
}
