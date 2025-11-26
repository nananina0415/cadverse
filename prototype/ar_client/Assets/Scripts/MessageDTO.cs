using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 클라이언트 측 메시지 DTO (Data Transfer Object)
/// server_client_interface.json 스키마 구현
/// </summary>
namespace CADverse.Network
{
    [Serializable]
    public class Position
    {
        public float x;
        public float y;
        public float z;

        public Position(float x, float y, float z)
        {
            this.x = x;
            this.y = y;
            this.z = z;
        }

        public Vector3 ToVector3()
        {
            return new Vector3(x, y, z);
        }

        public static Position FromVector3(Vector3 v)
        {
            return new Position(v.x, v.y, v.z);
        }
    }

    [Serializable]
    public class Rotation
    {
        public float e0;
        public float e1;
        public float e2;
        public float e3;

        public Rotation(float e0, float e1, float e2, float e3)
        {
            this.e0 = e0;
            this.e1 = e1;
            this.e2 = e2;
            this.e3 = e3;
        }

        public Quaternion ToQuaternion()
        {
            return new Quaternion(e1, e2, e3, e0);
        }

        public static Rotation FromQuaternion(Quaternion q)
        {
            return new Rotation(q.w, q.x, q.y, q.z);
        }
    }

    [Serializable]
    public class PartState
    {
        public Position pos;
        public Rotation rot;
    }

    /// <summary>
    /// 서버 → 클라이언트: 모델 상태 메시지 (배열 형태)
    /// </summary>
    [Serializable]
    public class ModelStateMessage
    {
        public List<PartState> parts;

        public static ModelStateMessage FromJson(string json)
        {
            // JSON 배열을 직접 파싱
            var partStates = JsonHelper.FromJson<PartState>(json);
            return new ModelStateMessage { parts = new List<PartState>(partStates) };
        }
    }

    /// <summary>
    /// 클라이언트 → 서버: 사용자 입력 메시지
    /// </summary>
    [Serializable]
    public class UserInputMessage
    {
        public Position point;
        public Position direction;

        public UserInputMessage(Vector3 point, Vector3 direction)
        {
            this.point = Position.FromVector3(point);
            this.direction = Position.FromVector3(direction);
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
