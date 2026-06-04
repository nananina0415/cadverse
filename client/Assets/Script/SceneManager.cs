using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace Cadverse
{
    // 영구 1개. ARTrackedImageManager + 공유 MutableRuntimeReferenceImageLibrary 보유.
    // 각 QR을 ModelRoot로 추가하면 그 marker도 같은 라이브러리에 등록되어 한 manager에서
    // 동시 추적된다 — AR Foundation의 "manager 1개" 제약을 우회.
    //
    // marker name = addr.Id. trackablesChanged 이벤트가 발사되면 이름으로 ModelRoot를
    // 찾아 dispatch한다. 활성/비활성은 ModelRoot.SetVisible로만 토글.
    public sealed class SceneManager
    {
        readonly ARTrackedImageManager                   _manager;
        readonly MutableRuntimeReferenceImageLibrary     _lib;
        readonly Dictionary<string, ModelRoot>           _models = new();

        // marker physicalSize는 m 단위 — 서버가 띄우는 QR 창 크기와 일치해야 모델 스케일이 맞다.
        const float MARKER_PHYSICAL_SIZE_M = 0.10f;

        public SceneManager(ARTrackedImageManager manager)
        {
            _manager = manager;
            _lib = manager.CreateRuntimeLibrary(null) as MutableRuntimeReferenceImageLibrary;
            if (_lib == null)
                throw new InvalidOperationException("이 기기는 런타임 마커 등록을 지원하지 않습니다.");

            manager.enabled = false;
            manager.referenceLibrary = _lib;
            manager.enabled = true;

            manager.trackablesChanged.AddListener(OnTrackedImagesChanged);
        }

        public ModelRoot Get(string addrId)
            => _models.TryGetValue(addrId, out var m) ? m : null;

        public async Task<ModelRoot> AddModelAsync(Addr addr, AssetCache cache = null)
        {
            if (_models.TryGetValue(addr.Id, out var existing))
                return existing;   // 이미 등록됨 — 그대로 재사용

            var net = AppManager.Net;
            byte[] Fetch(string path)
                => cache != null ? cache.GetOrFetch(addr, path) : net.RequestHttp(addr.RawJson, path);

            // (1) QR 마커 텍스처 생성 + 라이브러리에 등록
            byte[] qrData = await RequestWithTimeout(() => Fetch("/local_sim_qr.txt"));
            var texture = BuildQrTexture(Encoding.UTF8.GetString(qrData));

            var jobState = _lib.ScheduleAddImageWithValidationJob(texture, addr.Id, MARKER_PHYSICAL_SIZE_M);
            while (!jobState.jobHandle.IsCompleted) await Task.Yield();
            jobState.jobHandle.Complete();
            if (jobState.status != AddReferenceImageJobStatus.Success)
            {
                UnityEngine.Object.Destroy(texture);
                throw new InvalidOperationException($"마커 이미지 등록 실패: {jobState.status}");
            }

            // (2) metadata + 메시 다운로드 → root GameObject 구성
            byte[] metaData = await RequestWithTimeout(() => Fetch("/metadata.json"));
            var transforms = ParseBodies(Encoding.UTF8.GetString(metaData));

            var root = new GameObject($"_root_{addr.Id}");
            root.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            root.SetActive(false);

            var baseMat = Resources.Load<Material>("Materials/SimMesh");
            if (baseMat == null)
            {
                UnityEngine.Object.Destroy(root);
                UnityEngine.Object.Destroy(texture);
                throw new InvalidOperationException("Materials/SimMesh 에셋을 찾을 수 없습니다.");
            }

            var partIndex = new Dictionary<string, int>();
            int simIdx = 0;
            foreach (var kvp in transforms)
            {
                string name  = kvp.Key;
                float[] pose = kvp.Value;

                byte[] objData = await RequestWithTimeout(() => Fetch($"/meshes/{name}.obj"));
                var mesh = ObjParser.Parse(objData);

                // 파트별 구분색 — golden ratio로 hue 분포(인접 idx도 충분히 다름),
                // saturation/value를 낮춰 탁한 파스텔 톤(쨍하지 않음).
                var partMat = new Material(baseMat);
                var color   = PartColor(simIdx);
                partMat.color = color;
                if (partMat.HasProperty("_BaseColor")) partMat.SetColor("_BaseColor", color);

                var go = new GameObject(name);
                go.AddComponent<MeshFilter>().mesh         = mesh;
                go.AddComponent<MeshRenderer>().material   = partMat;
                go.AddComponent<MeshCollider>().sharedMesh = mesh;
                go.transform.SetParent(root.transform, false);

                go.transform.localPosition = new Vector3(pose[0], pose[2], pose[1]);
                go.transform.localRotation = new Quaternion(-pose[4], -pose[6], -pose[5], pose[3]);
                go.transform.localScale    = Vector3.one;

                partIndex[name] = simIdx++;
            }

            var model = new ModelRoot(addr.Id, root, texture, partIndex, transforms.Count);
            _models[addr.Id] = model;
            return model;
        }

        public void RemoveModel(string addrId)
        {
            if (!_models.TryGetValue(addrId, out var m)) return;
            _models.Remove(addrId);
            m.Dispose();
            // 라이브러리의 이미지는 제거할 수 없지만 ModelRoot가 없으니
            // 이벤트 dispatcher에서 무시된다. 부담은 미미.
        }

        void OnTrackedImagesChanged(ARTrackablesChangedEventArgs<ARTrackedImage> e)
        {
            foreach (var img in e.added)
                if (_models.TryGetValue(img.referenceImage.name, out var m))
                    m.OnImageAdded(img);

            foreach (var img in e.updated)
                if (_models.TryGetValue(img.referenceImage.name, out var m))
                    m.OnImageUpdated(img);

            foreach (var kvp in e.removed)
                if (_models.TryGetValue(kvp.Value.referenceImage.name, out var m))
                    m.OnImageRemoved();
        }

        // 파트 인덱스 → 구분색. golden ratio로 hue를 분포해 인접 idx도 색차가 큰 톤을 만든다.
        // saturation/value를 낮춰 탁한 파스텔(쨍하지 않음).
        static Color PartColor(int idx)
        {
            const float GOLDEN = 0.61803398875f;
            const float SAT    = 0.45f;
            const float VAL    = 0.85f;
            float h = (idx * GOLDEN + 0.13f) % 1f;   // +0.13: 첫 색이 단조로운 빨강에서 시작하지 않도록 살짝 시프트
            return Color.HSVToRGB(h, SAT, VAL);
        }

        static async Task<byte[]> RequestWithTimeout(Func<byte[]> fn, int timeoutMs = 10_000)
        {
            var task    = Task.Run(fn);
            var timeout = Task.Delay(timeoutMs);
            if (await Task.WhenAny(task, timeout) == timeout)
                throw new TimeoutException("서버 응답 시간 초과 (10s)");
            return await task;
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

        [Serializable] class _MetaBodies { public _MetaBody[] bodies; }
        [Serializable] class _MetaBody   { public string name; public _MetaPose pose; }
        [Serializable] class _MetaPose   { public float[] pos; public float[] rot; }

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
