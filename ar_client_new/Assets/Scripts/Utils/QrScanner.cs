using System;
using System.Collections;
using System.Threading;
using System.Threading.Tasks;
using Unity.Collections;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

#if CADVERSE_ENABLE_ZXING
using ZXing;
using ZXing.Common;
#endif

namespace CADverse.Utils
{
    /// <summary>
    /// 단발성 QR 스캔을 담당하는 유틸리티. 카메라 권한 확보 → 프레임 캡처 → QR 해석까지 관리한다.
    /// 실제 디코더는 ZXing 등을 Scripting Define Symbol(CADVERSE_ENABLE_ZXING)로 활성화했을 때 동작한다.
    /// </summary>
    public sealed class QrScanner : MonoBehaviour
{
    [Header("AR Camera Dependency")]
    [SerializeField] private ARCameraManager cameraManager;
    [SerializeField] private RawImage previewImage;

    [Header("Behaviour")]
    [SerializeField] [Tooltip("초 단위 타임아웃. 0 이하면 무제한 대기")]
    private float scanTimeoutSeconds = 30f; // Increased to 30s
    [SerializeField] private bool requestCameraPermission = true;

    [Header("Editor Mock")]
    [SerializeField] private bool allowEditorMock = true;
    [SerializeField] [TextArea] private string editorMockPayload = "http://127.0.0.1:8000/cadverse";

    private TaskCompletionSource<string> _scanCompletion;
    private CancellationTokenSource _scanCancellation;
    private Texture2D _previewTexture;
    private Texture2D _lastScannedQRImage;

    public bool IsScanning => _scanCompletion != null && !_scanCompletion.Task.IsCompleted;

    /// <summary>
    /// 마지막으로 스캔한 QR 코드 이미지 (AR 마커 등록용)
    /// </summary>
    public Texture2D LastScannedQRImage => _lastScannedQRImage;

    private void Awake()
    {
#if CADVERSE_ENABLE_ZXING
        Debug.Log("[QrScanner] CADVERSE_ENABLE_ZXING defined. ZXing decoder is ACTIVE.");
#else
        Debug.LogWarning("[QrScanner] CADVERSE_ENABLE_ZXING NOT defined. ZXing decoder is INACTIVE.");
#endif

        if (cameraManager == null)
        {
            cameraManager = FindFirstObjectByType<ARCameraManager>();
        }
    }

    /// <summary>
    /// QR 스캔을 한 번 수행하고 텍스트 결과를 반환한다.
    /// </summary>
    public Task<string> ScanOnceAsync(CancellationToken cancellationToken = default)
    {
        if (cameraManager == null)
        {
            throw new InvalidOperationException("ARCameraManager 참조가 필요합니다.");
        }

        if (IsScanning)
        {
            throw new InvalidOperationException("이미 QR 스캔이 진행 중입니다.");
        }

        _scanCompletion = new TaskCompletionSource<string>();
        _scanCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

        StartCoroutine(ScanRoutine(_scanCancellation.Token));
        return _scanCompletion.Task;
    }

    public void CancelScan()
    {
        _scanCancellation?.Cancel();
    }

    private IEnumerator ScanRoutine(CancellationToken token)
    {
        if (requestCameraPermission)
        {
            yield return EnsureCameraPermission();
            if (!_scanCompletion.TrySetCanceledIfRequested(token))
            {
                // continue
            }
            else
            {
                CleanupScan();
                yield break;
            }
        }

#if UNITY_EDITOR
        if (allowEditorMock && !string.IsNullOrEmpty(editorMockPayload))
        {
            _scanCompletion.TrySetResult(editorMockPayload);
            CleanupScan();
            yield break;
        }
#endif

        var startTime = Time.realtimeSinceStartup;

        while (!token.IsCancellationRequested)
        {
            string decodedText = TryDecodeLatestFrame(out bool updatedPreview);
            if (!string.IsNullOrEmpty(decodedText))
            {
                _scanCompletion.TrySetResult(decodedText);
                CleanupScan();
                yield break;
            }

            if (scanTimeoutSeconds > 0f && Time.realtimeSinceStartup - startTime >= scanTimeoutSeconds)
            {
                _scanCompletion.TrySetException(new TimeoutException("QR 스캔 타임아웃"));
                CleanupScan();
                yield break;
            }

            yield return null;
        }

        _scanCompletion.TrySetCanceled();
        CleanupScan();
    }

    private IEnumerator EnsureCameraPermission()
    {
#if (UNITY_ANDROID || UNITY_IOS) && !UNITY_EDITOR
        if (!Application.HasUserAuthorization(UserAuthorization.WebCam))
        {
            yield return Application.RequestUserAuthorization(UserAuthorization.WebCam);
        }
#else
        yield break;
#endif
    }

    private string TryDecodeLatestFrame(out bool previewUpdated)
    {
        previewUpdated = false;

        if (!cameraManager.TryAcquireLatestCpuImage(out var cpuImage))
        {
            // 너무 자주 로그가 찍히지 않도록 필요할 때만 주석 해제
            // Debug.Log("[QrScanner] Failed to acquire CPU image");
            return null;
        }

        using (cpuImage)
        {
            // Debug.Log($"[QrScanner] Image acquired: {cpuImage.width}x{cpuImage.height} format={cpuImage.format}");

            var conversionParams = new XRCpuImage.ConversionParams
            {
                inputRect = new RectInt(0, 0, cpuImage.width, cpuImage.height),
                outputDimensions = new Vector2Int(cpuImage.width, cpuImage.height),
                outputFormat = TextureFormat.RGB24, // Changed from R8
                transformation = XRCpuImage.Transformation.MirrorY
            };

            int bufferSize = cpuImage.GetConvertedDataSize(conversionParams);
            var buffer = new NativeArray<byte>(bufferSize, Allocator.Temp);
            cpuImage.Convert(conversionParams, buffer);

            UpdatePreview(buffer, conversionParams.outputDimensions.x, conversionParams.outputDimensions.y);
            previewUpdated = previewImage != null;

            string decodedText = DecodeBuffer(buffer, conversionParams.outputDimensions.x, conversionParams.outputDimensions.y);

            // QR 인식 성공 시 이미지 저장
            if (!string.IsNullOrEmpty(decodedText))
            {
                Debug.Log($"[QrScanner] QR Decoded: {decodedText}");
                SaveQRImage(buffer, conversionParams.outputDimensions.x, conversionParams.outputDimensions.y);
            }

            buffer.Dispose();

            return decodedText;
        }
    }

    private void UpdatePreview(NativeArray<byte> buffer, int width, int height)
    {
        if (previewImage == null)
        {
            return;
        }

        if (_previewTexture == null || _previewTexture.width != width || _previewTexture.height != height)
        {
            _previewTexture = new Texture2D(width, height, TextureFormat.RGB24, false); // Changed from R8
            previewImage.texture = _previewTexture;
        }

        _previewTexture.LoadRawTextureData(buffer);
        _previewTexture.Apply();
    }

    private string DecodeBuffer(NativeArray<byte> buffer, int width, int height)
    {
#if CADVERSE_ENABLE_ZXING
        byte[] managedBuffer = new byte[buffer.Length];
        buffer.CopyTo(managedBuffer);

        // Create luminance source from RGB image data
        var luminanceSource = new RGBLuminanceSource(managedBuffer, width, height, RGBLuminanceSource.BitmapFormat.RGB24); // Changed from Gray8
        var binarizer = new HybridBinarizer(luminanceSource);
        var binaryBitmap = new BinaryBitmap(binarizer);

        // Use MultiFormatReader directly
        var reader = new MultiFormatReader();
        var hints = new System.Collections.Generic.Dictionary<DecodeHintType, object>
        {
            { DecodeHintType.POSSIBLE_FORMATS, new System.Collections.Generic.List<BarcodeFormat> { BarcodeFormat.QR_CODE } },
            { DecodeHintType.TRY_HARDER, true }
        };

        try
        {
            var result = reader.decode(binaryBitmap, hints);
            if (result != null)
            {
                return result.Text;
            }
            // Debug.Log("[QrScanner] ZXing decode failed (result null)");
            return null;
        }
        catch (Exception ex)
        {
             Debug.LogWarning($"[QrScanner] ZXing decode exception: {ex.Message}");
            return null;
        }
#else
        // Debug.LogWarning("[QrScanner] ZXing disabled in DecodeBuffer");
#if UNITY_EDITOR
        if (allowEditorMock && !string.IsNullOrEmpty(editorMockPayload))
        {
            return editorMockPayload;
        }
#endif
        return null;
#endif
    }

    private void SaveQRImage(NativeArray<byte> buffer, int width, int height)
    {
        // RGBA 형식으로 변환하여 저장
        _lastScannedQRImage = new Texture2D(width, height, TextureFormat.R8, false);
        _lastScannedQRImage.LoadRawTextureData(buffer);
        _lastScannedQRImage.Apply();

        Debug.Log($"[QrScanner] QR 이미지 저장됨: {width}x{height}");
    }

    private void CleanupScan()
    {
        _scanCancellation?.Dispose();
        _scanCancellation = null;
        _scanCompletion = null;
    }
    }

    internal static class TaskCompletionSourceExtensions
    {
        public static bool TrySetCanceledIfRequested<T>(this TaskCompletionSource<T> tcs, CancellationToken token)
        {
            if (token.IsCancellationRequested)
            {
                tcs.TrySetCanceled(token);
                return true;
            }

            return false;
        }
    }
}

