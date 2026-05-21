using System;
using System.Text;
using UnityEngine;

namespace Cadverse
{
    // ── 서버에서 받은 SimFrame ──────────────────────────────
    public abstract class Frame {}

    public class StateFrame : Frame
    {
        public double      Timestamp;
        public SimObject[] Objects;
    }

    public class ReloadFrame : Frame {}

    public struct SimObject
    {
        public string     Name;
        public Vector3    Position;   // Unity 좌표로 변환됨
        public Quaternion Rotation;   // Unity 회전으로 변환됨
    }

    // ── 특정 서버 피어와의 연결 + 프로토콜 변환 ──────────────
    // 호출자가 Task.Run 등으로 블로킹 호출을 감싸야 함.
    public class Server : IDisposable
    {
        public Addr Addr { get; }
        readonly P2PConn _conn;

        // 블로킹: P2PNet.ConnectQuic 자체가 블로킹.
        public Server(P2PNet net, Addr addr)
        {
            Addr  = addr;
            _conn = net.ConnectQuic(addr.RawJson);
        }

        // ── Send ────────────────────────────────────────────
        public bool SendTouchStart(int partIndex, Vector3 action, Vector3 finger, Vector3 zDir)
        {
            var msg = new _TouchStartMsg {
                payload = new _TouchStartPayload {
                    targetPartIndex = partIndex,
                    actionPoint = _Vec3.FromArr(CoordConvert.UnityPosToSim(action)),
                    fingerPoint = _Vec3.FromArr(CoordConvert.UnityPosToSim(finger)),
                    z_direction = _Vec3.FromArr(CoordConvert.UnityDirToSim(zDir)),
                }
            };
            return SendJson(JsonUtility.ToJson(msg));
        }

        public bool SendTouching(Vector3 finger, Vector3 zDir)
        {
            var msg = new _TouchingMsg {
                payload = new _TouchingPayload {
                    fingerPoint = _Vec3.FromArr(CoordConvert.UnityPosToSim(finger)),
                    z_direction = _Vec3.FromArr(CoordConvert.UnityDirToSim(zDir)),
                }
            };
            return SendJson(JsonUtility.ToJson(msg));
        }

        public bool SendTouchEnd()
        {
            return SendJson(JsonUtility.ToJson(new _TouchEndMsg()));
        }

        bool SendJson(string json)
        {
            var bytes = Encoding.UTF8.GetBytes(json);
            return _conn.Send(bytes);
        }

        // ── Recv ────────────────────────────────────────────
        // 블로킹 1회. 서버는 State(SimOut)과 Reload 두 종류를 같은 conn에 보냄.
        // - State: {"timestamp":..., "objects":[{name, position[3], rotation[4]}]}
        // - Reload: {"type":"reload"}
        public Frame SimFrame()
        {
            var data = _conn.Recv();
            var json = Encoding.UTF8.GetString(data);

            if (json.Contains("\"type\":\"reload\""))
                return new ReloadFrame();

            var raw = JsonUtility.FromJson<_RawState>(json);
            if (raw == null || raw.objects == null)
                return new StateFrame { Timestamp = raw?.timestamp ?? 0.0, Objects = Array.Empty<SimObject>() };

            var objs = new SimObject[raw.objects.Length];
            for (int i = 0; i < raw.objects.Length; i++)
            {
                var o = raw.objects[i];
                objs[i] = new SimObject {
                    Name     = o.name,
                    Position = CoordConvert.SimPosToUnity(o.position),
                    Rotation = CoordConvert.SimRotToUnity(o.rotation),
                };
            }
            return new StateFrame { Timestamp = raw.timestamp, Objects = objs };
        }

        public void Dispose() => _conn?.Dispose();

        // ── 직렬화 클래스 (서버 포맷) ─────────────────────────
        [Serializable] struct _Vec3
        {
            public float x, y, z;
            public static _Vec3 FromArr(float[] a) => new _Vec3 { x = a[0], y = a[1], z = a[2] };
        }

        [Serializable] class _TouchStartPayload
        {
            public float targetPartIndex;
            public _Vec3 actionPoint;
            public _Vec3 fingerPoint;
            public _Vec3 z_direction;
        }

        [Serializable] class _TouchingPayload
        {
            public _Vec3 fingerPoint;
            public _Vec3 z_direction;
        }

        [Serializable] class _TouchEndPayload {}

        [Serializable] class _TouchStartMsg { public string type = "TouchStart"; public _TouchStartPayload payload; }
        [Serializable] class _TouchingMsg   { public string type = "Touching";   public _TouchingPayload   payload; }
        [Serializable] class _TouchEndMsg   { public string type = "TouchEnd";   public _TouchEndPayload   payload = new _TouchEndPayload(); }

        [Serializable] class _RawState  { public double timestamp; public _RawObject[] objects; }
        [Serializable] class _RawObject { public string name; public float[] position; public float[] rotation; }
    }
}
