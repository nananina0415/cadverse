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

        // py_sim 확장 출력 — 사용처가 있는 핵심 항목만 typed로 노출
        public EventFeedback[] EventFeedback;
        public DiagnosticItem[] Diagnostics;
        public string[]         Warnings;
    }

    public class ReloadFrame : Frame {}

    public struct SimObject
    {
        public string     Name;
        public Vector3    Position;   // Unity 좌표로 변환됨
        public Quaternion Rotation;   // Unity 회전으로 변환됨
    }

    // Python runtime_types.EventFeedback 미러 — soundId/soundType/volume/pitch
    // 가 있으면 클라가 알림음을 재생하고, message는 사용자에게 표시한다.
    public struct EventFeedback
    {
        public string EventType;
        public string Severity;
        public string Message;
        public string Target;
        public string SoundId;
        public string SoundType;
        public float  Volume;
        public float  Pitch;
    }

    // Python runtime_types.DiagnosticItem 미러
    public struct DiagnosticItem
    {
        public string Code;
        public string Severity;
        public string Message;
        public string Target;
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
            if (raw == null)
                return new StateFrame { Objects = Array.Empty<SimObject>() };

            var rawObjs = raw.objects ?? Array.Empty<_RawObject>();
            var objs = new SimObject[rawObjs.Length];
            for (int i = 0; i < rawObjs.Length; i++)
            {
                var o = rawObjs[i];
                objs[i] = new SimObject {
                    Name     = o.name,
                    Position = CoordConvert.SimPosToUnity(o.position),
                    Rotation = CoordConvert.SimRotToUnity(o.rotation),
                };
            }

            var rawEvs = raw.eventFeedback ?? Array.Empty<_RawEventFeedback>();
            var evs = new EventFeedback[rawEvs.Length];
            for (int i = 0; i < rawEvs.Length; i++)
            {
                var e = rawEvs[i];
                evs[i] = new EventFeedback {
                    EventType = e.eventType,
                    Severity  = e.severity,
                    Message   = e.message,
                    Target    = e.target,
                    SoundId   = e.soundId,
                    SoundType = e.soundType,
                    Volume    = e.volume,
                    Pitch     = e.pitch,
                };
            }

            var rawDiags = raw.diagnostics ?? Array.Empty<_RawDiagnostic>();
            var diags = new DiagnosticItem[rawDiags.Length];
            for (int i = 0; i < rawDiags.Length; i++)
            {
                var d = rawDiags[i];
                diags[i] = new DiagnosticItem {
                    Code     = d.code,
                    Severity = d.severity,
                    Message  = d.message,
                    Target   = d.target,
                };
            }

            return new StateFrame {
                Timestamp     = raw.timestamp,
                Objects       = objs,
                EventFeedback = evs,
                Diagnostics   = diags,
                Warnings      = raw.warnings ?? Array.Empty<string>(),
            };
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

        [Serializable] class _RawState
        {
            public double timestamp;
            public _RawObject[] objects;
            public _RawEventFeedback[] eventFeedback;
            public _RawDiagnostic[] diagnostics;
            public string[] warnings;
        }

        [Serializable] class _RawObject { public string name; public float[] position; public float[] rotation; }

        [Serializable] class _RawEventFeedback
        {
            public string eventType;
            public string severity;
            public string message;
            public string target;
            public string soundId;
            public string soundType;
            public float  volume;
            public float  pitch;
        }

        [Serializable] class _RawDiagnostic
        {
            public string code;
            public string severity;
            public string message;
            public string target;
        }
    }
}
