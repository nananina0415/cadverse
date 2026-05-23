using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Cadverse
{
    // ── 서버에서 받은 SimFrame ──────────────────────────────
    public abstract class Frame {}

    public class StateFrame : Frame
    {
        public double      Timestamp;
        public SimObject[] Objects;

        // py_sim 확장 출력 — SimFrame() 호출만으로도 채워지는 핵심 항목
        public EventFeedback[] EventFeedback;
        public DiagnosticItem[] Diagnostics;
        public string[]         Warnings;

        // SimFrameAndInfo() 호출 시에만 채워진다.
        // 정보 표시 모드 같은 깊은 처리에 필요한 값들.
        public InteractionTelemetry?                       InteractionTelemetry;
        public ContactTelemetry?                           Telemetry;
        public Dictionary<string, JointTelemetry>          JointTelemetry;
        public Dictionary<string, ActuatorTelemetry>       ActuatorTelemetry;
        public Dictionary<string, GearTelemetry>           GearTelemetry;
        public Dictionary<string, AssemblyGuideTelemetry>  AssemblyTelemetry;
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

    // ── SimFrameAndInfo() 전용 typed telemetry ───────────────
    // Python runtime_types.InteractionTelemetry 미러
    public struct InteractionTelemetry
    {
        public string   Mode;
        public string   TargetBody;
        public string   DriveBody;
        public string   DriveJoint;
        public Vector3? AxisWorld;    // Unity 좌표로 변환됨
        public Vector3? PivotWorld;   // Unity 좌표로 변환됨
    }

    // Python runtime_types.ContactTelemetry 미러
    public struct ContactTelemetry
    {
        public int    ContactCount;
        public double MaxContactForce;
        public string MaxPairBodyA;
        public string MaxPairBodyB;
    }

    // Python Vec3 미러 — 시뮬 좌표 그대로 보관. UI 사용 시 CoordConvert.SimPosToUnity(...) 변환 필요.
    public struct SimVec3 { public float X, Y, Z; }

    // Python runtime_types.JointTelemetry 미러 (교육용 joint 측정)
    public struct JointTelemetry
    {
        public string   JointType;
        public double?  Angle;            // rad
        public double?  Position;         // m
        public double?  AngularVelocity;  // rad/s
        public double?  LinearVelocity;   // m/s
        public SimVec3? ReactionForce;    // 시뮬 좌표 — UI 변환 필요
        public SimVec3? ReactionTorque;   // 시뮬 좌표 — UI 변환 필요
        public double?  EstimatedPower;
    }

    // Python runtime_types.ActuatorTelemetry 미러
    public struct ActuatorTelemetry
    {
        public string  ActuatorType;
        public string  TargetJoint;
        public double? CommandedSpeed;
        public double? CommandedTorque;
        public double? AppliedTorque;
        public double? EstimatedPower;
    }

    // Python runtime_types.GearTelemetry 미러 — JSON 키가 snake_case라 명시 매핑
    public struct GearTelemetry
    {
        [JsonProperty("applied_efficiency")] public double AppliedEfficiency;
        [JsonProperty("loss_torque")]        public double LossTorque;
        [JsonProperty("backlash_deadband")]  public double BacklashDeadband;
    }

    // Python runtime_types.AssemblyGuideTelemetry 미러
    public struct AssemblyGuideTelemetry
    {
        public bool    ActiveSnap;
        public string  SnapCandidate;
        public double  SnapErrorPos;
        public double  SnapErrorAngle;
        public string  SnapMode;
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

        // SimFrame()과 동일하게 1회 read하지만, Newtonsoft로 dict telemetry까지 typed로 풀어 반환한다.
        // 정보 표시 모드처럼 부품별 측정값이 필요한 시점에서만 호출한다.
        // SimFrame()과 동시에 부르면 안 된다 — 같은 _conn을 공유한다.
        public Frame SimFrameAndInfo()
        {
            var data = _conn.Recv();
            var json = Encoding.UTF8.GetString(data);

            if (json.Contains("\"type\":\"reload\""))
                return new ReloadFrame();

            JObject jo;
            try { jo = JObject.Parse(json); }
            catch { return new StateFrame { Objects = Array.Empty<SimObject>() }; }

            // parts → SimObject[]
            var objs = Array.Empty<SimObject>();
            if (jo["objects"] is JArray jobjs)
            {
                objs = new SimObject[jobjs.Count];
                for (int i = 0; i < jobjs.Count; i++)
                {
                    var o = jobjs[i];
                    var pos = new float[] {
                        (float)(o["position"]?[0] ?? 0f),
                        (float)(o["position"]?[1] ?? 0f),
                        (float)(o["position"]?[2] ?? 0f),
                    };
                    var rot = new float[] {
                        (float)(o["rotation"]?[0] ?? 1f),
                        (float)(o["rotation"]?[1] ?? 0f),
                        (float)(o["rotation"]?[2] ?? 0f),
                        (float)(o["rotation"]?[3] ?? 0f),
                    };
                    objs[i] = new SimObject {
                        Name     = (string)o["name"] ?? "",
                        Position = CoordConvert.SimPosToUnity(pos),
                        Rotation = CoordConvert.SimRotToUnity(rot),
                    };
                }
            }

            // EventFeedback / Diagnostics / Warnings — Newtonsoft로 직접 deserialize
            var evs   = jo["eventFeedback"]?.ToObject<EventFeedback[]>(_jsonSerializer) ?? Array.Empty<EventFeedback>();
            var diags = jo["diagnostics"]  ?.ToObject<DiagnosticItem[]>(_jsonSerializer) ?? Array.Empty<DiagnosticItem>();
            var warns = jo["warnings"]     ?.ToObject<string[]>(_jsonSerializer)         ?? Array.Empty<string>();

            // 단일 telemetry — 좌표 변환 포함해서 수동 매핑
            InteractionTelemetry? interaction = null;
            if (jo["interactionTelemetry"] is JObject jin)
            {
                interaction = new InteractionTelemetry {
                    Mode       = (string)jin["mode"],
                    TargetBody = (string)jin["targetBody"],
                    DriveBody  = (string)jin["driveBody"],
                    DriveJoint = (string)jin["driveJoint"],
                    AxisWorld  = SimVec3ToUnity(jin["axisWorld"]),
                    PivotWorld = SimVec3ToUnity(jin["pivotWorld"]),
                };
            }

            ContactTelemetry? contact = null;
            if (jo["telemetry"] is JObject jct)
            {
                contact = new ContactTelemetry {
                    ContactCount    = (int)(jct["contact_count"] ?? 0),
                    MaxContactForce = (double)(jct["max_contact_force"] ?? 0.0),
                    MaxPairBodyA    = (string)jct["max_pair"]?["bodyA"],
                    MaxPairBodyB    = (string)jct["max_pair"]?["bodyB"],
                };
            }

            // dict telemetry — Newtonsoft가 Dictionary 그대로 deserialize
            var joints     = jo["jointTelemetry"]   ?.ToObject<Dictionary<string, JointTelemetry>>(_jsonSerializer);
            var actuators  = jo["actuatorTelemetry"]?.ToObject<Dictionary<string, ActuatorTelemetry>>(_jsonSerializer);
            var gears      = jo["gearTelemetry"]   ?.ToObject<Dictionary<string, GearTelemetry>>(_jsonSerializer);
            var assemblies = jo["assemblyTelemetry"]?.ToObject<Dictionary<string, AssemblyGuideTelemetry>>(_jsonSerializer);

            return new StateFrame {
                Timestamp           = (double)(jo["timestamp"] ?? 0.0),
                Objects             = objs,
                EventFeedback       = evs,
                Diagnostics         = diags,
                Warnings            = warns,
                InteractionTelemetry= interaction,
                Telemetry           = contact,
                JointTelemetry      = joints,
                ActuatorTelemetry   = actuators,
                GearTelemetry       = gears,
                AssemblyTelemetry   = assemblies,
            };
        }

        static Vector3? SimVec3ToUnity(JToken t)
        {
            if (!(t is JObject jv)) return null;
            return CoordConvert.SimPosToUnity(new float[] {
                (float)(jv["x"] ?? 0f),
                (float)(jv["y"] ?? 0f),
                (float)(jv["z"] ?? 0f),
            });
        }

        // 대부분 telemetry 키가 camelCase라 PascalCase 필드를 자동 매핑한다.
        // snake_case 필드(GearTelemetry 등)는 struct에 [JsonProperty] 명시로 override.
        // CamelCaseNamingStrategy(processDictionaryKeys=false, overrideSpecifiedNames=false):
        //   - dict 키(JointTelemetry name 등)는 원본 유지
        //   - JsonProperty 명시한 이름은 변환하지 않음
        static readonly JsonSerializer _jsonSerializer = JsonSerializer.Create(
            new JsonSerializerSettings {
                MissingMemberHandling = MissingMemberHandling.Ignore,
                ContractResolver = new Newtonsoft.Json.Serialization.DefaultContractResolver {
                    NamingStrategy = new Newtonsoft.Json.Serialization.CamelCaseNamingStrategy(false, false)
                },
            }
        );

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
