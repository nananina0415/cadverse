using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.EnhancedTouch;
using CADverse.Communication;
using CADverse.Utils;

// AR Foundation - 정적 모델 로딩
public class Main : MonoBehaviour
{
    [Header("Server")]
    [SerializeField] private SimServer simServer;

    [Header("AR Components")]
    [SerializeField] private ARTrackedImageManager arTrackedImageManager;
    [SerializeField] private Camera arCamera;

    [Header("Debug")]
    [SerializeField] private bool useQrScan = false;
    [SerializeField] private string debugServerAddress = "192.168.219.100:8000/cadverse";

    private CompositeModel _loadedModel;
    private bool _isModelPlaced = false;
    private bool _qrScanRequested = false;
    private ARTrackedImage _trackedQRImage;
    private MutableRuntimeReferenceImageLibrary _runtimeImageLibrary;
    private QrScanner _qrScanner;

    void Start()
    {
        EnhancedTouchSupport.Enable();
        TouchSimulation.Enable();

        simServer.OnConnected += HandleServerConnected;
        simServer.OnDisconnected += HandleServerDisconnected;
        simServer.OnError += HandleServerError;
        simServer.OnModelStateUpdated += HandleModelStateUpdated;

        // AR Tracked Image 이벤트 등록
        if (arTrackedImageManager != null)
        {
            arTrackedImageManager.trackablesChanged.AddListener(OnTrackablesChanged);

            // 런타임 이미지 라이브러리 생성
            _runtimeImageLibrary = arTrackedImageManager.CreateRuntimeLibrary() as MutableRuntimeReferenceImageLibrary;
            if (_runtimeImageLibrary != null)
            {
                arTrackedImageManager.referenceLibrary = _runtimeImageLibrary;
                arTrackedImageManager.enabled = true;
                Debug.Log("[Main] 런타임 이미지 라이브러리 생성됨");
            }
        }

        _qrScanner = FindFirstObjectByType<QrScanner>();

        if (useQrScan)
        {
            AndroidToast.Show("화면을 터치하여 QR 스캔 시작", true);
        }
        else
        {
            if (_qrScanner != null) _qrScanner.enabled = false;
            simServer.ConnectByQrCode(debugServerAddress);
        }
    }

    private async void HandleServerConnected()
    {
        AndroidToast.Show("✅ 서버 연결 성공!", true);

        // QR 이미지를 AR 마커로 등록
        RegisterQRImageAsMarker();

        try
        {
            _loadedModel = await simServer.LoadModel();
            AndroidToast.Show($"✅ 모델 로드 완료!\nQR 마커를 비추세요", true);
            InitializeModel();
        }
        catch (Exception ex)
        {
            Debug.LogError($"[Main] 모델 로드 실패: {ex.Message}");
            AndroidToast.Show($"❌ 모델 로드 실패: {ex.Message}", true);
        }
    }

    private void RegisterQRImageAsMarker()
    {
        if (_runtimeImageLibrary == null)
        {
            Debug.LogWarning("[Main] 런타임 이미지 라이브러리가 없습니다");
            return;
        }

        if (_qrScanner == null || _qrScanner.LastScannedQRImage == null)
        {
            Debug.LogWarning("[Main] 스캔된 QR 이미지가 없습니다");
            return;
        }

        Texture2D qrImage = _qrScanner.LastScannedQRImage;

        // QR 이미지 물리적 크기 (미터 단위, 약 5cm 가정)
        float qrPhysicalSize = 0.05f;

        // 런타임으로 이미지 등록
        var jobHandle = _runtimeImageLibrary.ScheduleAddImageWithValidationJob(
            qrImage,
            "scanned_qr",
            qrPhysicalSize
        );

        Debug.Log($"[Main] QR 이미지를 AR 마커로 등록 중... ({qrImage.width}x{qrImage.height})");
    }

    private void HandleServerDisconnected()
    {
        Debug.LogWarning("[Main] Server disconnected");
        AndroidToast.Show("⚠️ 서버 연결 끊김", false);
    }

    private void HandleServerError(string error)
    {
        Debug.LogError("[Main] Server error: " + error);
        AndroidToast.Show($"❌ 오류: {error}", true);
        _qrScanRequested = false; // 에러 발생 시 재시도 가능하게 리셋
    }

    private void HandleModelStateUpdated()
    {
        // 모델이 배치된 상태에서만 업데이트
        if (_isModelPlaced && _loadedModel != null)
        {
            UpdateModelFromServer();
        }
    }

    void Update()
    {
        bool hasTouch = false;

        if (UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches.Count > 0)
        {
            var touch = UnityEngine.InputSystem.EnhancedTouch.Touch.activeTouches[0];
            if (touch.phase == UnityEngine.InputSystem.TouchPhase.Began)
            {
                hasTouch = true;
            }
        }
        else if (Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame)
        {
            hasTouch = true;
        }

        if (hasTouch)
        {
            // 1. QR 스캔 모드이고 아직 연결 안됨
            if (useQrScan && !simServer.IsConnected)
            {
                if (!_qrScanRequested)
                {
                    _qrScanRequested = true;
                    AndroidToast.Show("QR 스캔 시작...", false); // MainManager에 이미 있으므로 SimServer에서 제거하는게 나을 수도 있음.
                    simServer.ConnectByQrScan();
                }
                return;
            }

            // 2. 모델 로드 확인
            if (_loadedModel == null)
            {
                if (!simServer.IsConnected)
                {
                    // QR 모드가 아닌데 연결 안됨 -> 자동 연결 실패했을 수 있음
                    if (!useQrScan)
                    {
                        AndroidToast.Show("서버 연결 시도 중...", false);
                        simServer.ConnectByQrCode(debugServerAddress);
                    }
                    else
                    {
                         AndroidToast.Show("서버에 연결되지 않았습니다.", false);
                    }
                }
                else
                {
                    AndroidToast.Show("모델을 불러오는 중입니다...", false);
                }
                return;
            }

            // 3. 모델 배치
            // 현재는 OnTrackablesChanged에서 처리되므로, 터치로 모델을 직접 배치하지 않음
            // 이 로직은 주석 처리하거나 제거
            // if (!_isModelPlaced && _trackedQRImage != null)
            // {
            //     PlaceModelOnQRMarker();
            // }
        }

        // QR 마커가 추적되고 있으면 모델 위치 업데이트
        if (_isModelPlaced && _trackedQRImage != null && _loadedModel != null)
        {
            UpdateModelPosition();
        }
    }

    private void InitializeModel()
    {
        if (_loadedModel == null) return;

        // 모든 파트(wrapper)에 Material 설정
        for (int i = 0; i < _loadedModel.GetPartCount(); i++)
        {
            GameObject partWrapper = _loadedModel.GetPart(i);
            if (partWrapper == null) continue;

            // Wrapper의 첫 번째 자식(실제 메쉬)에 Material 설정
            if (partWrapper.transform.childCount > 0)
            {
                GameObject partMesh = partWrapper.transform.GetChild(0).gameObject;
                MeshRenderer renderer = partMesh.GetComponent<MeshRenderer>();
                if (renderer != null)
                {
                    renderer.enabled = true;
                    if (renderer.material == null)
                    {
                        renderer.material = new Material(Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("UI/Default"));
                    }
                    renderer.material.color = new Color(1f, 0f, 0f, 1f); // 빨강
                }
            }
        }

        _loadedModel.transform.localScale = Vector3.one;  // OBJ에서 이미 미터 변환됨
        _loadedModel.gameObject.SetActive(false); // 숨김
    }

    private void OnTrackablesChanged(ARTrackablesChangedEventArgs<ARTrackedImage> eventArgs)
    {
        // 새로 추가된 이미지 처리
        foreach (var trackedImage in eventArgs.added)
        {
            HandleTrackedImage(trackedImage);
        }

        // 업데이트된 이미지 처리
        foreach (var trackedImage in eventArgs.updated)
        {
            HandleTrackedImage(trackedImage);
        }
    }

    private void HandleTrackedImage(ARTrackedImage trackedImage)
    {
        // 모델이 아직 배치되지 않았고, 이미지 추적 상태가 좋을 때만 배치
        if (!_isModelPlaced && _loadedModel != null && trackedImage.trackingState == TrackingState.Tracking)
        {
            _trackedQRImage = trackedImage;
            PlaceModelOnQRMarker();
        }
        // 이미 배치되었으면 추적 중인 이미지 업데이트
        else if (_isModelPlaced && trackedImage.trackingState == TrackingState.Tracking)
        {
            _trackedQRImage = trackedImage;
        }
    }

    private void PlaceModelOnQRMarker()
    {
        if (_loadedModel == null || _trackedQRImage == null) return;

        // 모델을 QR 마커의 자식으로 설정
        _loadedModel.transform.SetParent(_trackedQRImage.transform, false);
        _loadedModel.transform.localPosition = Vector3.zero;
        // X축 -90도 회전으로 좌표계 변환 (x,z,y)
        _loadedModel.transform.localRotation = Quaternion.Euler(-90, 0, 0);

        _loadedModel.gameObject.SetActive(true);
        _isModelPlaced = true;

        AndroidToast.Show($"✅ QR 마커에 모델 배치 완료!", true);
        Debug.Log($"[Main] QR 마커에 모델 배치: {_trackedQRImage.transform.position}, 파트 수: {_loadedModel.GetPartCount()}");
    }

    private void UpdateModelPosition()
    {
        // QR 마커가 추적 중이면 자동으로 따라감 (부모-자식 관계이므로)
        if (_trackedQRImage.trackingState != TrackingState.Tracking)
        {
            Debug.LogWarning("[Main] QR 마커 추적 손실");
        }
    }


    public void UpdateModelFromServer()
    {
        var states = simServer.GetLatestModelState();

        for (int i = 0; i < states.Count && i < _loadedModel.GetPartCount(); i++)
        {
            var part = _loadedModel.GetPart(i);
            var state = states[i];

            // 위치와 회전 업데이트
            part.transform.localPosition = new Vector3(
                state.pos.x,
                state.pos.y,
                state.pos.z
            );
            part.transform.localRotation = state.GetQuaternion();
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

        if (arTrackedImageManager != null)
        {
            arTrackedImageManager.trackablesChanged.RemoveListener(OnTrackablesChanged);
        }
    }
}
