using System;
using System.Collections.Generic;
using UnityEngine;

namespace CADverse.Communication
{
    /// <summary>
    /// 서버 통신 데이터 모델
    /// server_client_interface.json 스키마 구현
    /// </summary>

    [Serializable]
    public class PartState
    {
        public Vector3 pos;
        public QuaternionDTO rot;

        public Quaternion GetQuaternion()
        {
            // PyChrono 쿼터니언 (e0=w, e1=x, e2=y, e3=z) → Unity Quaternion (x, y, z, w)
            return new Quaternion(rot.e1, rot.e2, rot.e3, rot.e0);
        }
    }

    [Serializable]
    public class QuaternionDTO
    {
        public float e0; // w
        public float e1; // x
        public float e2; // y
        public float e3; // z

        public QuaternionDTO(float e0, float e1, float e2, float e3)
        {
            this.e0 = e0;
            this.e1 = e1;
            this.e2 = e2;
            this.e3 = e3;
        }

        public static QuaternionDTO FromQuaternion(Quaternion q)
        {
            return new QuaternionDTO(q.w, q.x, q.y, q.z);
        }
    }

    /// <summary>
    /// 서버 → 클라이언트: 모델 상태 메시지
    /// </summary>
    [Serializable]
    public class ModelStateMessage
    {
        public float sim_time;
        public List<PartState> parts;

        public static ModelStateMessage FromJson(string json)
        {
            // JSON 객체 파싱 (새 형식: {"sim_time": ..., "parts": [...]})
            var message = JsonUtility.FromJson<ModelStateMessageDTO>(json);
            return new ModelStateMessage
            {
                sim_time = message.sim_time,
                parts = new List<PartState>(message.parts)
            };
        }

        [Serializable]
        private class ModelStateMessageDTO
        {
            public float sim_time;
            public PartState[] parts;
        }
    }

    /// <summary>
    /// 클라이언트 → 서버: 사용자 입력 메시지
    /// </summary>
    [Serializable]
    public class UserInputMessage
    {
        public Vector3 point;
        public Vector3 direction;

        public UserInputMessage(Vector3 point, Vector3 direction)
        {
            this.point = point;
            this.direction = direction;
        }

        public string ToJson()
        {
            return JsonUtility.ToJson(this);
        }
    }

    /// <summary>
    /// Unity JsonUtility는 배열을 직접 역직렬화하지 못하므로 헬퍼 사용
    /// </summary>
    public static class JsonHelper
    {
        public static T[] FromJson<T>(string json)
        {
            string wrappedJson = "{\"items\":" + json + "}";
            Wrapper<T> wrapper = JsonUtility.FromJson<Wrapper<T>>(wrappedJson);
            return wrapper.items;
        }

        [Serializable]
        private class Wrapper<T>
        {
            public T[] items;
        }
    }
}
