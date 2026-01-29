using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using System;
using System.Collections;
using Unity.Jobs;
using CADverse.Model;
using CADverse.Utils;

namespace CADverse.AR
{
    public class ARManager : MonoBehaviour
    {
        [SerializeField] private ARTrackedImageManager _arTrackedImageManager;
        [SerializeField] private float qrPhysicalSizeMeters = 0.05f; // QR 코드 실제 크기 (미터)

        private MutableRuntimeReferenceImageLibrary _runtimeReferenceImageLibrary;
        private ModelManager _modelManager;
        private string _registeredMarkerName;
        private bool _imageRegistered = false;

        void Awake()
        {
            if (_arTrackedImageManager == null)
            {
                _arTrackedImageManager = FindFirstObjectByType<ARTrackedImageManager>();
                if (_arTrackedImageManager == null)
                {
                    Debug.LogError("[ARManager] ARTrackedImageManager not found in scene!");
                }
            }
        }

        void OnEnable()
        {
            if (_arTrackedImageManager != null)
            {
                _arTrackedImageManager.trackablesChanged.AddListener(OnTrackablesChanged);
            }
        }

        void OnDisable()
        {
            if (_arTrackedImageManager != null)
            {
                _arTrackedImageManager.trackablesChanged.RemoveListener(OnTrackablesChanged);
            }
        }

        public void RegisterARMarker(Texture2D qrImage, string qrContent, ModelManager modelManager)
        {
            _modelManager = modelManager;
            _registeredMarkerName = qrContent;

            // 코루틴으로 이미지 등록 (첫 프레임 이후 실행 필요)
            StartCoroutine(RegisterImageCoroutine(qrImage, qrContent));
        }

        private IEnumerator RegisterImageCoroutine(Texture2D qrImage, string qrContent)
        {
            // 중요: 첫 프레임 이후에 실행해야 함
            yield return null;

            if (_arTrackedImageManager == null)
            {
                Debug.LogError("[ARManager] Cannot register marker, ARTrackedImageManager is null.");
                yield break;
            }

            // 런타임 라이브러리 생성
            if (_runtimeReferenceImageLibrary == null)
            {
                _runtimeReferenceImageLibrary = _arTrackedImageManager.CreateRuntimeLibrary() as MutableRuntimeReferenceImageLibrary;
                if (_runtimeReferenceImageLibrary == null)
                {
                    Debug.LogError("[ARManager] Failed to create MutableRuntimeReferenceImageLibrary.");
                    yield break;
                }
                Debug.Log("[ARManager] Created MutableRuntimeReferenceImageLibrary.");
            }

            // 이미지가 읽기 가능한지 확인
            if (!qrImage.isReadable)
            {
                Debug.LogError("[ARManager] QR image is not readable. Cannot add to library.");
                yield break;
            }

            Debug.Log($"[ARManager] Adding image to library: {qrContent}, size: {qrImage.width}x{qrImage.height}, physical size: {qrPhysicalSizeMeters}m");

            // 이미지 등록
            AddReferenceImageJobState jobState = _runtimeReferenceImageLibrary.ScheduleAddImageWithValidationJob(
                qrImage, qrContent, qrPhysicalSizeMeters);

            // Job 완료 대기
            yield return new WaitUntil(() => jobState.jobHandle.IsCompleted);
            jobState.jobHandle.Complete();

            // 등록 결과 확인
            if (jobState.status == AddReferenceImageJobStatus.Success)
            {
                Debug.Log($"[ARManager] 이미지 등록 성공: {qrContent}");
                _imageRegistered = true;

                // 라이브러리 할당 및 활성화
                _arTrackedImageManager.referenceLibrary = _runtimeReferenceImageLibrary;
                _arTrackedImageManager.enabled = true;

                // 라이브러리 상태 확인
                int imageCount = _runtimeReferenceImageLibrary.count;
                Debug.Log($"[ARManager] 라이브러리 이미지 수: {imageCount}");
                Debug.Log($"[ARManager] ARTrackedImageManager enabled: {_arTrackedImageManager.enabled}");
                Debug.Log($"[ARManager] ARTrackedImageManager subsystem running: {_arTrackedImageManager.subsystem?.running}");

                string msg = $"마커등록 OK! {qrImage.width}x{qrImage.height}, {qrPhysicalSizeMeters*100}cm";
                Debug.Log($"[ARManager] {msg}");
                AndroidToast.Show(msg, false);

                // 추적 상태 모니터링 시작
                StartCoroutine(MonitorTrackingStatus());
            }
            else
            {
                Debug.LogError($"[ARManager] 이미지 등록 실패: {jobState.status}");
                AndroidToast.Show($"AR 마커 등록 실패: {jobState.status}", true);
            }
        }

        private void OnTrackablesChanged(ARTrackablesChangedEventArgs<ARTrackedImage> eventArgs)
        {
            // 이벤트 수신 로그
            int addedCount = 0, updatedCount = 0, removedCount = 0;
            foreach (var _ in eventArgs.added) addedCount++;
            foreach (var _ in eventArgs.updated) updatedCount++;
            foreach (var _ in eventArgs.removed) removedCount++;

            if (addedCount > 0 || updatedCount > 0 || removedCount > 0)
            {
                Debug.Log($"[ARManager] TrackablesChanged: added={addedCount}, updated={updatedCount}, removed={removedCount}");
            }

            // 새로 추가된 이미지 처리
            foreach (var trackedImage in eventArgs.added)
            {
                // 카메라와 마커 사이 거리 계산
                float distanceToCamera = Vector3.Distance(Camera.main.transform.position, trackedImage.transform.position);
                float detectedSizeCm = trackedImage.size.x * 100f;
                float registeredSizeCm = qrPhysicalSizeMeters * 100f;

                // 토스트로 핵심 정보 표시
                string msg = $"등록:{registeredSizeCm:F0}cm 감지:{detectedSizeCm:F1}cm 거리:{distanceToCamera * 100:F0}cm";
                AndroidToast.Show(msg, false);

                Debug.Log($"[ARManager] {msg}");

                if (trackedImage.trackingState == TrackingState.Tracking)
                {
                    PlaceModel(trackedImage);
                }
            }

            // 업데이트된 이미지 처리
            foreach (var trackedImage in eventArgs.updated)
            {
                if (trackedImage.trackingState == TrackingState.Tracking)
                {
                    PlaceModel(trackedImage);
                }
                else if (trackedImage.trackingState == TrackingState.Limited)
                {
                    Debug.Log($"[ARManager] AR 마커 추적 제한됨: {trackedImage.referenceImage.name}");
                }
            }

            // 제거된 이미지 처리
            foreach (var removed in eventArgs.removed)
            {
                Debug.Log($"[ARManager] AR 마커 손실: {removed.Key}");
                if (_modelManager != null)
                {
                    _modelManager.OnMarkerLost(removed.Key);
                }
            }
        }

        private IEnumerator MonitorTrackingStatus()
        {
            float elapsed = 0f;
            while (elapsed < 60f) // 60초간 모니터링
            {
                elapsed += 3f;

                int trackableCount = 0;
                foreach (var t in _arTrackedImageManager.trackables)
                {
                    trackableCount++;
                }

                bool subsystemRunning = _arTrackedImageManager.subsystem?.running ?? false;
                string status = $"[{elapsed:F0}s] 추적:{trackableCount} sub:{subsystemRunning}";
                Debug.Log($"[ARManager] {status}");

                // 항상 토스트 표시 (디버깅용)
                AndroidToast.Show(status, false);

                yield return new WaitForSeconds(3f);
            }
        }

        private void PlaceModel(ARTrackedImage trackedImage)
        {
            if (_modelManager == null)
            {
                Debug.LogWarning("[ARManager] ModelManager is null, cannot place model.");
                return;
            }

            // 모델 배치 - trackedImage의 Transform을 직접 전달
            _modelManager.PlaceModelAtMarker(trackedImage.trackableId, trackedImage.transform);
        }
    }
}
