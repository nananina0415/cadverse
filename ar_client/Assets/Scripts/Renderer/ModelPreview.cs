using System.Threading.Tasks;
using UnityEngine;
using CADverse.Server;

namespace CADverse.Renderer
{
    /// <summary>
    /// QR 스캔 화면에서 서버에서 가져온 3D 모델을 미리보기로 표시
    /// </summary>
    public class ModelPreview : MonoBehaviour
    {
        [Header("Settings")]
        [SerializeField] private float distanceFromCamera = 0.5f;
        [SerializeField] private float rotationSpeed = 30f;
        [SerializeField] private float modelScale = 0.1f;

        [Header("Material")]
        [SerializeField] private Material previewMaterial;

        private GameObject _modelObject;
        private Camera _mainCamera;

        private void Awake()
        {
            _mainCamera = Camera.main;

            // Default material if not assigned
            if (previewMaterial == null)
            {
                // URP에서는 "Universal Render Pipeline/Lit" 사용
                Shader shader = Shader.Find("Universal Render Pipeline/Lit");
                if (shader == null)
                {
                    // Fallback: Standard shader
                    shader = Shader.Find("Standard");
                }

                if (shader != null)
                {
                    previewMaterial = new Material(shader);
                    previewMaterial.color = new Color(0.8f, 0.8f, 0.8f, 1f);
                }
                else
                {
                    UnityEngine.Debug.LogError("[ModelPreview] Failed to find shader");
                }
            }
        }

        private void Update()
        {
            if (_modelObject != null && _mainCamera != null)
            {
                // 카메라 앞 고정 위치에 배치
                Vector3 targetPosition = _mainCamera.transform.position +
                                        _mainCamera.transform.forward * distanceFromCamera;
                _modelObject.transform.position = targetPosition;

                // 천천히 회전
                _modelObject.transform.Rotate(Vector3.up, rotationSpeed * Time.deltaTime, Space.World);
            }
        }

        /// <summary>
        /// 서버에서 첫 번째 모델을 가져와서 표시
        /// </summary>
        public async Task LoadPreviewModel(string serverIp, int serverPort)
        {
            try
            {
                // HTTP 클라이언트 생성
                using var httpClient = new System.Net.Http.HttpClient();
                var baseUrl = $"http://{serverIp}:{serverPort}";

                // 오브젝트 목록 가져오기
                UnityEngine.Debug.Log($"[ModelPreview] Fetching object list from {baseUrl}");
                var listResponse = await httpClient.GetStringAsync($"{baseUrl}/cadverse/object");
                var objectList = JsonUtility.FromJson<Server.DataModel.ObjectList>(listResponse);

                if (objectList.objects == null || objectList.objects.Length == 0)
                {
                    UnityEngine.Debug.LogWarning("[ModelPreview] No objects available");
                    return;
                }

                // 첫 번째 오브젝트 가져오기
                string objectName = objectList.objects[0];
                UnityEngine.Debug.Log($"[ModelPreview] Loading object: {objectName}");

                var objResponse = await httpClient.GetStringAsync($"{baseUrl}/cadverse/object/{objectName}");

                // OBJ 파싱하여 Mesh 생성
                Mesh mesh = OBJLoader.LoadFromString(objResponse);

                // GameObject 생성
                _modelObject = new GameObject($"Preview_{objectName}");
                _modelObject.transform.SetParent(transform);

                // MeshFilter와 MeshRenderer 추가
                var meshFilter = _modelObject.AddComponent<MeshFilter>();
                meshFilter.mesh = mesh;

                var meshRenderer = _modelObject.AddComponent<MeshRenderer>();
                meshRenderer.material = previewMaterial;

                // 크기 조정
                _modelObject.transform.localScale = Vector3.one * modelScale;

                UnityEngine.Debug.Log($"[ModelPreview] Model loaded successfully: {objectName}");
            }
            catch (System.Exception e)
            {
                UnityEngine.Debug.LogError($"[ModelPreview] Failed to load model: {e.Message}");
            }
        }

        /// <summary>
        /// 미리보기 모델 제거
        /// </summary>
        public void ClearPreview()
        {
            if (_modelObject != null)
            {
                Destroy(_modelObject);
                _modelObject = null;
                UnityEngine.Debug.Log("[ModelPreview] Preview cleared");
            }
        }

        private void OnDestroy()
        {
            ClearPreview();
        }
    }
}
