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

        ARScene(ARTrackedImageManager manager, GameObject root)
        {
            _manager = manager;
            _root = root;
            manager.trackedImagesChanged += OnTrackedImagesChanged;
        }

        public static async Task<ARScene> Create(Addr addr, ARTrackedImageManager manager)
        {
            var net = AppManager.Net;

            // (1) QR 마커 텍스처 → AR 라이브러리 등록
            byte[] qrData = await Task.Run(() => net.RequestHttp(addr.RawJson, "/local_sim_qr.txt"));
            var texture = BuildQrTexture(Encoding.UTF8.GetString(qrData));

            var lib = manager.CreateRuntimeLibrary(null) as MutableRuntimeReferenceImageLibrary;
            if (lib == null)
                throw new InvalidOperationException("이 기기는 런타임 마커 등록을 지원하지 않습니다.");

            var jobState = lib.ScheduleAddImageWithValidationJob(texture, "sim_marker", 0.05f);
            while (!jobState.jobHandle.IsCompleted)
                await Task.Yield();
            jobState.jobHandle.Complete();
            manager.referenceLibrary = lib;
            UnityEngine.Object.Destroy(texture);

            // (2) 메타데이터 파싱
            byte[] metaData = await Task.Run(() => net.RequestHttp(addr.RawJson, "/metadata.json"));
            var transforms = ParseTransforms(Encoding.UTF8.GetString(metaData));

            // (3) _root 생성
            var root = new GameObject("_root");
            root.transform.localRotation = Quaternion.Euler(90f, 180f, 0f); // ※ 런타임 검증 필요
            root.SetActive(false);

            var mat = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            mat.color = new Color(0.749f, 0.749f, 0.749f);

            // (4) 파트별 OBJ 다운로드 → 메시 생성
            foreach (var kvp in transforms)
            {
                string name = kvp.Key;
                float[] matrix = kvp.Value;

                byte[] objData = await Task.Run(() => net.RequestHttp(addr.RawJson, $"/meshes/{name}.obj"));
                var mesh = ObjParser.Parse(objData);

                var go = new GameObject(name);
                go.AddComponent<MeshFilter>().mesh = mesh;
                go.AddComponent<MeshRenderer>().material = mat;
                go.transform.SetParent(root.transform, false);

                var m = CoordConvert.FusionToUnity(matrix);
                go.transform.localPosition = new Vector3(m.m03, m.m13, m.m23);
                go.transform.localRotation = m.rotation;
                go.transform.localScale = new Vector3(
                    new Vector3(m.m00, m.m10, m.m20).magnitude,
                    new Vector3(m.m01, m.m11, m.m21).magnitude,
                    new Vector3(m.m02, m.m12, m.m22).magnitude
                );
            }

            return new ARScene(manager, root);
        }

        void OnTrackedImagesChanged(ARTrackedImagesChangedEventArgs e)
        {
            foreach (var img in e.added)
                if (img.referenceImage.name == "sim_marker")
                {
                    _root.transform.SetParent(img.transform, false);
                    _root.SetActive(img.trackingState == TrackingState.Tracking);
                }

            foreach (var img in e.updated)
                if (img.referenceImage.name == "sim_marker")
                    _root.SetActive(img.trackingState == TrackingState.Tracking);

            foreach (var img in e.removed)
                if (img.referenceImage.name == "sim_marker")
                    _root.SetActive(false);
        }

        public void Dispose()
        {
            _manager.trackedImagesChanged -= OnTrackedImagesChanged;
            _manager.referenceLibrary = _manager.CreateRuntimeLibrary(null);
            UnityEngine.Object.Destroy(_root);
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
