using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace Cadverse
{
    public class ARScene : IDisposable
    {
        readonly ARTrackedImageManager _manager;
        readonly GameObject _root;
        readonly Texture2D  _markerTexture;
        ARAnchor    _anchor;
        public int MeshCount;
        TrackingState _lastTrackingState = TrackingState.None;

        ARScene(ARTrackedImageManager manager, GameObject root, Texture2D markerTexture)
        {
            _manager       = manager;
            _root          = root;
            _markerTexture = markerTexture;
            manager.trackablesChanged.AddListener(OnTrackedImagesChanged);
        }

        static async Task<byte[]> RequestWithTimeout(System.Func<byte[]> fn, int timeoutMs = 10_000)
        {
            var task    = Task.Run(fn);
            var timeout = Task.Delay(timeoutMs);
            if (await Task.WhenAny(task, timeout) == timeout)
                throw new TimeoutException("서버 응답 시간 초과 (10s)");
            return await task;
        }

        public static async Task<ARScene> Create(Addr addr, ARTrackedImageManager manager)
        {
            var net = AppManager.Net;

            // (1) QR 마커 텍스처 → AR 라이브러리 등록
            byte[] qrData = await RequestWithTimeout(() => net.RequestHttp(addr.RawJson, "/local_sim_qr.txt"));
            var texture = BuildQrTexture(Encoding.UTF8.GetString(qrData));

            var lib = manager.CreateRuntimeLibrary(null) as MutableRuntimeReferenceImageLibrary;
            if (lib == null)
                throw new InvalidOperationException("이 기기는 런타임 마커 등록을 지원하지 않습니다.");

            var jobState = lib.ScheduleAddImageWithValidationJob(texture, "sim_marker", 0.05f);
            while (!jobState.jobHandle.IsCompleted)
                await Task.Yield();
            jobState.jobHandle.Complete();
            if (jobState.status != AddReferenceImageJobStatus.Success)
                throw new InvalidOperationException($"마커 이미지 등록 실패: {jobState.status}");

            // (2) 메타데이터 파싱
            byte[] metaData = await RequestWithTimeout(() => net.RequestHttp(addr.RawJson, "/metadata.json"));
            var transforms = ParseBodies(Encoding.UTF8.GetString(metaData));

            // (3) _root 생성
            var root = new GameObject("_root");
            root.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            root.SetActive(false);

            var mat = Resources.Load<Material>("Materials/SimMesh");
            if (mat == null)
                throw new InvalidOperationException("Materials/SimMesh 에셋을 찾을 수 없습니다.");
            mat = new Material(mat);

            // (4) 파트별 OBJ 다운로드 → 메시 생성
            foreach (var kvp in transforms)
            {
                string name  = kvp.Key;
                float[] pose = kvp.Value; // [px, py, pz, rw, rx, ry, rz]

                byte[] objData = await RequestWithTimeout(() => net.RequestHttp(addr.RawJson, $"/meshes/{name}.obj"));
                var mesh = ObjParser.Parse(objData);

                var go = new GameObject(name);
                go.AddComponent<MeshFilter>().mesh      = mesh;
                go.AddComponent<MeshRenderer>().material = mat;
                go.transform.SetParent(root.transform, false);

                // Fusion(X,Y,Z) m → Unity(X,Z,Y), quaternion(w,x,y,z) → (-x,-z,-y,w)
                go.transform.localPosition = new Vector3(pose[0], pose[2], pose[1]);
                go.transform.localRotation = new Quaternion(-pose[4], -pose[6], -pose[5], pose[3]);
                go.transform.localScale    = Vector3.one;
            }

            // (5) ARScene 생성(리스너 등록) → referenceLibrary 설정 (순서 중요)
            var scene = new ARScene(manager, root, texture);
            scene.MeshCount = transforms.Count;
            manager.enabled = false;
            manager.referenceLibrary = lib;
            manager.enabled = true;
            return scene;
        }

        void OnTrackedImagesChanged(ARTrackablesChangedEventArgs<ARTrackedImage> e)
        {
            foreach (var img in e.added)
                if (img.referenceImage.name == "sim_marker")
                {
                    AppManager.Toast(img.trackingState == TrackingState.Tracking
                        ? "마커 감지 성공"
                        : $"마커 감지됨 (상태: {img.trackingState})");
                    if (img.trackingState == TrackingState.Tracking)
                        AttachToMarker(img.transform);
                }

            foreach (var img in e.updated)
                if (img.referenceImage.name == "sim_marker")
                {
                    if (img.trackingState != _lastTrackingState)
                    {
                        _lastTrackingState = img.trackingState;
                        AppManager.Toast(img.trackingState == TrackingState.Tracking
                            ? "마커 추적 재개"
                            : $"마커 추적 중단 ({img.trackingState})");
                    }

                    if (img.trackingState == TrackingState.Tracking)
                        AttachToMarker(img.transform);
                    else
                        AttachToAnchor();
                }

            foreach (var kvp in e.removed)
                if (kvp.Value.referenceImage.name == "sim_marker")
                {
                    AppManager.Toast("마커 제거됨");
                    AttachToAnchor();
                }
        }

        void AttachToMarker(Transform markerTransform)
        {
            if (_anchor != null)
            {
                UnityEngine.Object.Destroy(_anchor.gameObject);
                _anchor = null;
            }
            bool firstPlacement = !_root.activeSelf;
            _root.transform.SetParent(markerTransform, false);
            _root.transform.localPosition = Vector3.zero;
            _root.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            _root.SetActive(true);
            if (firstPlacement)
                AppManager.Toast("모델 배치 완료");
        }

        void AttachToAnchor()
        {
            if (_anchor != null) return;
            if (!_root.activeSelf) return;

            var anchorGO = new GameObject("SimAnchor");
            anchorGO.transform.SetPositionAndRotation(_root.transform.position, _root.transform.rotation);
            _anchor = anchorGO.AddComponent<ARAnchor>();
            _root.transform.SetParent(_anchor.transform, true);
        }

        public void Dispose()
        {
            _manager.trackablesChanged.RemoveListener(OnTrackedImagesChanged);
            _manager.referenceLibrary = _manager.CreateRuntimeLibrary(null);
            if (_anchor != null) UnityEngine.Object.Destroy(_anchor.gameObject);
            UnityEngine.Object.Destroy(_root);
            UnityEngine.Object.Destroy(_markerTexture);
        }

        // "0"/"1" 그리드 → Texture2D (1=검정, 0=흰색, 모듈당 10px)
        static Texture2D BuildQrTexture(string txt)
        {
            var lines = txt.Split('\n');
            int rows = lines.Length;
            while (rows > 0 && lines[rows - 1].Trim().Length == 0) rows--;
            int cols = lines[0].Trim().Length;
            const int px = 10;

            var tex = new Texture2D(cols * px, rows * px, TextureFormat.RGB24, false);
            for (int r = 0; r < rows; r++)
            {
                string line = lines[r].Trim();
                for (int c = 0; c < cols && c < line.Length; c++)
                {
                    var color = line[c] == '1' ? Color.black : Color.white;
                    for (int dy = 0; dy < px; dy++)
                        for (int dx = 0; dx < px; dx++)
                            tex.SetPixel(c * px + dx, (rows - 1 - r) * px + dy, color);
                }
            }
            tex.Apply();
            return tex;
        }

        // Server가 변환을 마친 Unity 좌표로 들어온다.
        public void ApplyState(StateFrame s)
        {
            if (s?.Objects == null) return;
            foreach (var obj in s.Objects)
            {
                var t = _root.transform.Find(obj.Name);
                if (t == null) continue;
                t.localPosition = obj.Position;
                t.localRotation = obj.Rotation;
            }
        }

        [System.Serializable] class _MetaBodies { public _MetaBody[] bodies; }
        [System.Serializable] class _MetaBody   { public string name; public _MetaPose pose; }
        [System.Serializable] class _MetaPose   { public float[] pos; public float[] rot; }

        // metadata.json "bodies" 배열 → {파트명: float[7]} (pos xyz + rot wxyz)
        static Dictionary<string, float[]> ParseBodies(string json)
        {
            var result = new Dictionary<string, float[]>();
            var meta = JsonUtility.FromJson<_MetaBodies>(json);
            if (meta?.bodies == null) return result;
            foreach (var b in meta.bodies)
            {
                if (b?.name == null || b.pose?.pos?.Length < 3 || b.pose?.rot?.Length < 4) continue;
                result[b.name] = new float[]
                {
                    b.pose.pos[0], b.pose.pos[1], b.pose.pos[2],
                    b.pose.rot[0], b.pose.rot[1], b.pose.rot[2], b.pose.rot[3]
                };
            }
            return result;
        }
    }
}
