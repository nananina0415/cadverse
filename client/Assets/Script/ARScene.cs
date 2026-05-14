using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
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
            var transforms = ParseTransforms(Encoding.UTF8.GetString(metaData));

            // (3) _root 생성
            var root = new GameObject("_root");
            root.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            root.SetActive(false);

            var mat = Resources.Load<Material>("Materials/SimMesh");
            if (mat == null)
                throw new InvalidOperationException("Materials/SimMesh 에셋을 찾을 수 없습니다.");
            mat = new Material(mat);

            // (4) 파트별 OBJ 다운로드 → 메시 생성
            bool firstMesh = true;
            foreach (var kvp in transforms)
            {
                string name   = kvp.Key;
                float[] matrix = kvp.Value;

                byte[] objData = await RequestWithTimeout(() => net.RequestHttp(addr.RawJson, $"/meshes/{name}.obj"));
                var mesh = ObjParser.Parse(objData);

                var go = new GameObject(name);
                go.AddComponent<MeshFilter>().mesh     = mesh;
                go.AddComponent<MeshRenderer>().material = mat;
                go.transform.SetParent(root.transform, false);

                var m = CoordConvert.FusionToUnity(matrix);
                go.transform.localPosition = new Vector3(m.m03, m.m13, m.m23);
                go.transform.localRotation = m.rotation;
                go.transform.localScale    = new Vector3(
                    new Vector3(m.m00, m.m10, m.m20).magnitude,
                    new Vector3(m.m01, m.m11, m.m21).magnitude,
                    new Vector3(m.m02, m.m12, m.m22).magnitude
                );

                if (firstMesh)
                {
                    AppManager.Toast($"{name} pos={go.transform.localPosition} scale={go.transform.localScale}");
                    firstMesh = false;
                }
            }

            // (5) ARScene 생성(리스너 등록) → referenceLibrary 설정 (순서 중요)
            var scene = new ARScene(manager, root, texture);
            scene.MeshCount = transforms.Count;
            manager.referenceLibrary = lib;
            manager.enabled = true;
            return scene;
        }

        void OnTrackedImagesChanged(ARTrackablesChangedEventArgs<ARTrackedImage> e)
        {
            AppManager.Toast($"trackables: +{e.added.Count} ~{e.updated.Count}");

            foreach (var img in e.added)
                if (img.referenceImage.name == "sim_marker")
                {
                    AppManager.Toast($"마커 added: {img.trackingState}");
                    if (img.trackingState == TrackingState.Tracking)
                        AttachToMarker(img.transform);
                }

            foreach (var img in e.updated)
                if (img.referenceImage.name == "sim_marker")
                {
                    if (img.trackingState != _lastTrackingState)
                    {
                        _lastTrackingState = img.trackingState;
                        AppManager.Toast($"마커 updated: {img.trackingState}");
                    }
                    if (img.trackingState == TrackingState.Tracking)
                        AttachToMarker(img.transform);
                    else
                        AttachToAnchor();
                }

            foreach (var kvp in e.removed)
                if (kvp.Value.referenceImage.name == "sim_marker")
                    AttachToAnchor();
        }

        void AttachToMarker(Transform markerTransform)
        {
            if (_anchor != null)
            {
                UnityEngine.Object.Destroy(_anchor.gameObject);
                _anchor = null;
            }
            _root.transform.SetParent(markerTransform, false);
            _root.transform.localPosition = Vector3.zero;
            _root.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            _root.SetActive(true);
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

        // metadata.json "transforms" 섹션 → {파트명: float[16]}
        static Dictionary<string, float[]> ParseTransforms(string json)
        {
            var result = new Dictionary<string, float[]>();
            var section = Regex.Match(json, @"""transforms""\s*:\s*\{(.*?)\}", RegexOptions.Singleline);
            if (!section.Success) return result;

            foreach (Match m in Regex.Matches(section.Groups[1].Value,
                @"""([^""]+)""\s*:\s*\[([^\]]+)\]", RegexOptions.Singleline))
            {
                string[] parts = m.Groups[2].Value.Split(',');
                var floats = new float[parts.Length];
                for (int i = 0; i < parts.Length; i++)
                    floats[i] = float.Parse(parts[i].Trim(), CultureInfo.InvariantCulture);
                result[m.Groups[1].Value] = floats;
            }
            return result;
        }
    }
}
