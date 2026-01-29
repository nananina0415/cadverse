using UnityEngine;
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using UnityEngine.XR.ARSubsystems;
using CADverse.Communication;
using CADverse.Utils;

namespace CADverse.Model
{
    public class ModelManager : MonoBehaviour
    {
        [SerializeField] private ServerProxy _serverProxy;

        // 로드된 모델 (objectName -> GameObject)
        private readonly Dictionary<string, GameObject> _loadedModels = new Dictionary<string, GameObject>();

        // 생성된 모델 인스턴스 (TrackableId -> GameObject)
        private readonly Dictionary<TrackableId, GameObject> _spawnedModelInstances = new Dictionary<TrackableId, GameObject>();

        // 모델이 마커에 배치되었는지 여부
        private bool _isModelPlaced = false;

        // 루트 모델 오브젝트 (모든 파트를 담는 부모)
        private GameObject _rootModelObject;

        void Awake()
        {
            if (_serverProxy == null)
            {
                _serverProxy = FindFirstObjectByType<ServerProxy>();
                if (_serverProxy == null)
                {
                    Debug.LogError("[ModelManager] ServerProxy not found in scene!");
                }
            }
        }

        /// <summary>
        /// 서버에서 오브젝트 목록을 가져와 모든 모델을 로드합니다.
        /// </summary>
        public async Task InitializeModels(ServerProxy serverProxy)
        {
            _serverProxy = serverProxy;

            Debug.Log("[ModelManager] 서버에서 오브젝트 목록 가져오는 중...");

            // 1. 서버에서 오브젝트 목록 가져오기
            ObjectList objectList = await _serverProxy.GetObjectListAsync();
            if (objectList == null || objectList.objects == null || objectList.objects.Count == 0)
            {
                Debug.LogWarning("[ModelManager] 서버에 오브젝트가 없습니다. 테스트 큐브 사용.");
                _rootModelObject = CreateTestCube(0.1f);
                _rootModelObject.SetActive(false);
                return;
            }

            Debug.Log($"[ModelManager] 오브젝트 목록: {string.Join(", ", objectList.objects)}");

            // 2. 루트 오브젝트 생성
            _rootModelObject = new GameObject("CADverse_Model_Root");
            _rootModelObject.SetActive(false);

            // 3. 각 오브젝트 다운로드 및 로드
            foreach (string objectName in objectList.objects)
            {
                Debug.Log($"[ModelManager] 모델 다운로드 중: {objectName}");
                GameObject model = await LoadModelAsync(objectName);
                if (model != null)
                {
                    model.transform.SetParent(_rootModelObject.transform, false);
                    _loadedModels[objectName] = model;
                    Debug.Log($"[ModelManager] 모델 로드 완료: {objectName}");
                }
                else
                {
                    Debug.LogWarning($"[ModelManager] 모델 로드 실패: {objectName}");
                }
            }

            // 4. 전체 모델의 바운딩 박스 계산 및 중심 정렬
            CenterModelAtOrigin();

            Debug.Log($"[ModelManager] 총 {_loadedModels.Count}개 모델 초기화 완료.");
        }

        /// <summary>
        /// 테스트용 정육면체를 생성합니다.
        /// </summary>
        private GameObject CreateTestCube(float sizeMeters)
        {
            GameObject cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cube.name = "TestCube_10cm";
            cube.transform.localScale = new Vector3(sizeMeters, sizeMeters, sizeMeters);

            var renderer = cube.GetComponent<MeshRenderer>();
            if (renderer != null)
            {
                Material mat = renderer.material;
                if (mat.HasProperty("_BaseColor"))
                    mat.SetColor("_BaseColor", Color.red);
                else if (mat.HasProperty("_Color"))
                    mat.SetColor("_Color", Color.red);
            }

            Debug.Log($"[ModelManager] 테스트 큐브 생성됨: {sizeMeters * 100}cm");
            return cube;
        }

        /// <summary>
        /// 서버에서 OBJ 파일을 다운로드하고 GameObject로 변환합니다.
        /// </summary>
        private async Task<GameObject> LoadModelAsync(string objectName)
        {
            if (_serverProxy == null)
            {
                Debug.LogError("[ModelManager] ServerProxy is null, cannot download model.");
                return null;
            }

            string objContent = await _serverProxy.DownloadObjectMeshAsync(objectName);

            if (string.IsNullOrEmpty(objContent))
            {
                Debug.LogError($"[ModelManager] Failed to download OBJ content for {objectName}");
                return null;
            }

            try
            {
                GameObject modelObject = ObjCommunication.ParseToGameObject(objContent, objectName);
                return modelObject;
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ModelManager] Failed to parse OBJ for {objectName}: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// 전체 모델의 바운딩 박스 중심을 원점으로 이동
        /// </summary>
        private void CenterModelAtOrigin()
        {
            if (_rootModelObject == null) return;

            // 모든 MeshRenderer의 바운딩 박스 합산
            Bounds combinedBounds = new Bounds(Vector3.zero, Vector3.zero);
            bool boundsInitialized = false;

            foreach (var renderer in _rootModelObject.GetComponentsInChildren<MeshRenderer>())
            {
                if (!boundsInitialized)
                {
                    combinedBounds = renderer.bounds;
                    boundsInitialized = true;
                }
                else
                {
                    combinedBounds.Encapsulate(renderer.bounds);
                }
            }

            if (boundsInitialized)
            {
                // 바운딩 박스 중심을 원점으로 이동
                Vector3 offset = -combinedBounds.center;
                foreach (Transform child in _rootModelObject.transform)
                {
                    child.localPosition += offset;
                }

                Debug.Log($"[ModelManager] 모델 중심 정렬 완료. 크기: {combinedBounds.size * 1000}mm, 오프셋: {offset * 1000}mm");
            }
        }

        /// <summary>
        /// AR 마커 위치에 모델을 배치합니다.
        /// </summary>
        public void PlaceModelAtMarker(TrackableId trackableId, Transform markerTransform)
        {
            // 이미 배치된 경우 위치만 업데이트
            if (_spawnedModelInstances.TryGetValue(trackableId, out GameObject existingInstance))
            {
                if (!existingInstance.activeSelf)
                {
                    existingInstance.SetActive(true);
                }
                return;
            }

            // 아직 모델이 배치되지 않았으면 배치
            if (!_isModelPlaced && _rootModelObject != null)
            {
                // 마커의 자식으로 설정
                _rootModelObject.transform.SetParent(markerTransform, false);
                _rootModelObject.transform.localPosition = Vector3.zero;
                _rootModelObject.transform.localRotation = Quaternion.identity;

                _rootModelObject.SetActive(true);
                _spawnedModelInstances.Add(trackableId, _rootModelObject);
                _isModelPlaced = true;

                Debug.Log($"[ModelManager] Model placed at AR marker: {trackableId}");
                AndroidToast.Show("모델 배치 완료!", false);
            }
        }

        /// <summary>
        /// 시뮬레이션 상태 수신 시 모델 업데이트
        /// </summary>
        private void OnSimulationStateReceived(SimulationState state)
        {
            if (state.objects == null) return;

            foreach (var objTransform in state.objects)
            {
                if (_loadedModels.TryGetValue(objTransform.name, out GameObject modelObject))
                {
                    modelObject.transform.localPosition = objTransform.GetPosition();
                    modelObject.transform.localRotation = objTransform.GetRotation();
                }
            }
        }

        /// <summary>
        /// AR 마커가 손실되었을 때 호출됩니다.
        /// </summary>
        public void OnMarkerLost(TrackableId trackableId)
        {
            if (_spawnedModelInstances.TryGetValue(trackableId, out GameObject instance))
            {
                instance.SetActive(false);
                Debug.Log($"[ModelManager] Model hidden due to marker loss: {trackableId}");
            }
        }

        void OnDestroy()
        {
            if (_serverProxy != null)
            {
                _serverProxy.OnSimulationStateReceived -= OnSimulationStateReceived;
            }

            foreach (var instance in _spawnedModelInstances.Values)
            {
                if (instance != null)
                {
                    Destroy(instance);
                }
            }
            _spawnedModelInstances.Clear();

            if (_rootModelObject != null)
            {
                Destroy(_rootModelObject);
            }
        }
    }
}
