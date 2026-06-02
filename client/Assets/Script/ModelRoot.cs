using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace Cadverse
{
    // 한 QR(addr)에 대응되는 모델 시각화 단위.
    // GameObject 루트 + 파트들 + 자기 마커가 인식됐을 때의 attach 로직만 책임진다.
    // ARTrackedImageManager는 영구 SceneManager 하나가 보유하고, SceneManager가
    // referenceImage.name(= addr.Id)으로 어떤 ModelRoot로 dispatch할지 결정한다.
    //
    // 활성/비활성 전환은 SetVisible(bool)만 토글한다.
    //   visible=true  : _root.SetActive(true) — 마커 transform을 따라 화면에 보임
    //   visible=false : _root.SetActive(false) — 자원은 유지, 시각화만 끔
    //
    // 마커 텍스처는 SceneManager가 라이브러리에 등록한 뒤 ModelRoot에 owner 권한을 넘긴다.
    // Dispose가 mesh/material/texture/gameObject 정리를 담당.
    public sealed class ModelRoot : IDisposable
    {
        public string AddrId   { get; }
        public int    MeshCount { get; }

        readonly GameObject              _root;
        readonly Texture2D               _markerTexture;
        readonly Dictionary<string, int> _partIndex;
        ARAnchor      _anchor;
        TrackingState _lastTrackingState = TrackingState.None;

        internal ModelRoot(string addrId, GameObject root, Texture2D markerTexture,
                           Dictionary<string, int> partIndex, int meshCount)
        {
            AddrId         = addrId;
            _root          = root;
            _markerTexture = markerTexture;
            _partIndex     = partIndex;
            MeshCount      = meshCount;
        }

        // raycast hit name → 서버 partIndex
        public int IndexOf(string name)
            => _partIndex != null && _partIndex.TryGetValue(name, out int idx) ? idx : -1;

        public void SetVisible(bool visible)
        {
            if (_root == null) return;
            _root.SetActive(visible);
        }

        public bool IsVisible => _root != null && _root.activeSelf;

        // ── ARTrackedImage 이벤트 dispatcher (SceneManager가 호출) ───────────────
        internal void OnImageAdded(ARTrackedImage img)
        {
            AppManager.Toast(img.trackingState == TrackingState.Tracking
                ? "마커 감지 성공"
                : $"마커 감지됨 (상태: {img.trackingState})");
            if (img.trackingState == TrackingState.Tracking)
                AttachToMarker(img.transform);
        }

        internal void OnImageUpdated(ARTrackedImage img)
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

        internal void OnImageRemoved()
        {
            AppManager.Toast("마커 제거됨");
            AttachToAnchor();
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

            var anchorGO = new GameObject($"SimAnchor_{AddrId}");
            anchorGO.transform.SetPositionAndRotation(_root.transform.position, _root.transform.rotation);
            _anchor = anchorGO.AddComponent<ARAnchor>();
            _root.transform.SetParent(_anchor.transform, true);
        }

        // Server가 변환을 마친 Unity 좌표로 들어온다.
        public void ApplyState(StateFrame s)
        {
            if (s?.Objects == null || _root == null) return;
            foreach (var obj in s.Objects)
            {
                var t = _root.transform.Find(obj.Name);
                if (t == null) continue;
                t.localPosition = obj.Position;
                t.localRotation = obj.Rotation;
            }
        }

        public void Dispose()
        {
            if (_anchor != null) UnityEngine.Object.Destroy(_anchor.gameObject);
            if (_root != null)          UnityEngine.Object.Destroy(_root);
            if (_markerTexture != null) UnityEngine.Object.Destroy(_markerTexture);
        }
    }
}
