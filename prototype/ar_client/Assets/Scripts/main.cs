using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.EnhancedTouch;
using CADverse.Communication;
using CADverse.Utils;

// AR Foundation - 좌표 변환 (x,z,y) 고정
public class Main : MonoBehaviour
{
    [Header("Server")]
    [SerializeField] private SimServer simServer;

    [Header("AR Components")]
    [SerializeField] private ARPlaneManager arPlaneManager;
    [SerializeField] private ARRaycastManager arRaycastManager;
    [SerializeField] private Camera arCamera;

    [Header("Debug")]
    [SerializeField] private bool useQrScan = false;
    [SerializeField] private string debugServerAddress = "192.168.219.100:8000/cadverse";

    private CompositeModel _loadedModel;
    private ARAnchor _modelAnchor;
    private bool _isModelPlaced = false;
    private bool _qrScanRequested = false;
    private List<ARRaycastHit> _raycastHits = new List<ARRaycastHit>();

    void Start()
    {
        EnhancedTouchSupport.Enable();
        TouchSimulation.Enable();

        simServer.OnConnected += HandleServerConnected;
        simServer.OnDisconnected += HandleServerDisconnected;
        simServer.OnError += HandleServerError;

        if (useQrScan)
        {
            AndroidToast.Show("화면을 터치하여 QR 스캔 시작", true);
        }
        else
        {
            var qrScanner = FindFirstObjectByType<CADverse.Utils.QrScanner>();
            if (qrScanner != null) qrScanner.enabled = false;
            simServer.ConnectByQrCode(debugServerAddress);
        }
    }

    private async void HandleServerConnected()
    {
        AndroidToast.Show("✅ 서버 연결 성공!", true);

        try
        {
            _loadedModel = await simServer.LoadModel();
            AndroidToast.Show($"✅ 모델 로드 완료!\n바닥을 터치하세요", true);
            InitializeModel();
        }
        catch (Exception ex)
        {
            Debug.LogError($"[Main] 모델 로드 실패: {ex.Message}");
        }
    }

    private void HandleServerDisconnected()
    {
        Debug.LogWarning("[Main] Server disconnected");
    }

    private void HandleServerError(string error)
    {
        Debug.LogError("[Main] Server error: " + error);
    }

    void Update()
    {
        bool hasTouch = false;
        Vector2 touchPosition = Vector2.zero;

        if (UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches.Count > 0)
        {
            var touch = UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches[0];
            if (touch.phase == UnityEngine.InputSystem.TouchPhase.Began)
            {
                hasTouch = true;
                touchPosition = touch.screenPosition;
            }
        }
        else if (Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame)
        {
            hasTouch = true;
            touchPosition = Mouse.current.position.ReadValue();
        }

        if (useQrScan && !simServer.IsConnected && !_qrScanRequested && hasTouch)
        {
            _qrScanRequested = true;
            simServer.ConnectByQrScan();
            return;
        }

        if (_loadedModel != null && simServer.IsConnected)
        {
            UpdateModelState();
        }

        if (!_isModelPlaced && _loadedModel != null && hasTouch)
        {
            PlaceModelOnPlane(touchPosition);
        }
        else if (_isModelPlaced && hasTouch)
        {
            SendUserInputToServer(touchPosition);
        }
    }

    private void UpdateModelState()
    {
        var states = simServer.GetLatestModelState();

        for (int i = 0; i < states.Count && i < _loadedModel.GetPartCount(); i++)
        {
            GameObject part = _loadedModel.GetPart(i);
            if (part != null)
            {
                // Position은 그대로 사용
                part.transform.localPosition = states[i].pos;
                part.transform.localRotation = states[i].GetQuaternion();
            }
        }
    }

    private void InitializeModel()
    {
        if (_loadedModel == null) return;

        for (int i = 0; i < _loadedModel.GetPartCount(); i++)
        {
            GameObject part = _loadedModel.GetPart(i);
            if (part == null) continue;

            MeshRenderer renderer = part.GetComponent<MeshRenderer>();
            if (renderer != null)
            {
                renderer.enabled = true;
                if (renderer.material == null)
                {
                    renderer.material = new Material(Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("UI/Default"));
                }
                renderer.material.color = new Color(1f, 0f, 0f, 1f);
            }
        }

        _loadedModel.transform.localScale = Vector3.one * 0.001f;
        _loadedModel.gameObject.SetActive(false); // 숨김
    }

    private void PlaceModelOnPlane(Vector2 screenPoint)
    {
        if (_loadedModel == null || arRaycastManager == null) return;

        if (arRaycastManager.Raycast(screenPoint, _raycastHits, TrackableType.PlaneWithinPolygon))
        {
            Pose hitPose = _raycastHits[0].pose;

            if (_modelAnchor != null)
            {
                Destroy(_modelAnchor.gameObject);
            }

            // 앵커 생성
            GameObject anchorGO = new GameObject("ModelAnchor");
            anchorGO.transform.position = hitPose.position;
            anchorGO.transform.rotation = hitPose.rotation;
            _modelAnchor = anchorGO.AddComponent<ARAnchor>();

            // 모델을 앵커의 자식으로
            _loadedModel.transform.SetParent(_modelAnchor.transform, false);
            _loadedModel.transform.localPosition = Vector3.zero;
            // X축 -90도 회전으로 좌표계 변환 (x,z,y)
            _loadedModel.transform.localRotation = Quaternion.Euler(-90, 0, 0);

            _loadedModel.gameObject.SetActive(true);

            _isModelPlaced = true;

            AndroidToast.Show($"✅ 모델 배치 완료!", true);
            Debug.Log($"[Main] 모델 배치: {hitPose.position}");
        }
        else
        {
            AndroidToast.Show("바닥을 찾을 수 없습니다", false);
            Debug.LogWarning("[Main] AR Plane 감지 실패");
        }
    }

    private void SendUserInputToServer(Vector2 touchPosition)
    {
        if (_loadedModel == null) return;

        Ray ray = arCamera.ScreenPointToRay(touchPosition);
        if (Physics.Raycast(ray, out RaycastHit hit))
        {
            simServer.SendUserInput(hit.point, ray.direction.normalized);
            Debug.Log($"[Main] User input: {hit.point}");
        }
    }

    void OnDestroy()
    {
        EnhancedTouchSupport.Disable();
        TouchSimulation.Disable();

        if (simServer != null)
        {
            simServer.OnConnected -= HandleServerConnected;
            simServer.OnDisconnected -= HandleServerDisconnected;
            simServer.OnError -= HandleServerError;
        }
    }
}
