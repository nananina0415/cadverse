using System;
using System.Collections;
using System.Threading;
using System.Threading.Tasks;
using Unity.Collections;
using UnityEngine;
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
    /// QR 이미지는 서버에서 직접 다운로드하므로 여기서는 텍스트 디코딩만 담당한다.
    /// </summary>
    public sealed class QrScanner : MonoBehaviour
    {
        [Header("AR Camera Dependency")]
        [SerializeField] private ARCameraManager cameraManager;

        [Header("Behaviour")]
        [SerializeField]
        [Tooltip("초 단위 타임아웃. 0 이하면 무제한 대기")]
        private float scanTimeoutSeconds = 15f;
        [SerializeField] private bool requestCameraPermission = true;

        [Header("Editor Mock")]
        [SerializeField] private bool allowEditorMock = true;
        [SerializeField][TextArea] private string editorMockPayload = "192.168.0.1:3000";

        private TaskCompletionSource<string> _scanCompletion;
        private CancellationTokenSource _scanCancellation;

        public bool IsScanning => _scanCompletion != null && !_scanCompletion.Task.IsCompleted;

        private void Awake()
        {
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
                if (_scanCompletion.TrySetCanceledIfRequested(token))
                {
                    CleanupScan();
                    yield break;
                }
            }

#if UNITY_EDITOR
            if (allowEditorMock && !string.IsNullOrEmpty(editorMockPayload))
            {
                Debug.Log($"[QrScanner] Editor Mock: {editorMockPayload}");
                _scanCompletion.TrySetResult(editorMockPayload);
                CleanupScan();
                yield break;
            }
#endif

            var startTime = Time.realtimeSinceStartup;

            while (!token.IsCancellationRequested)
            {
                string decodedText = TryDecodeLatestFrame();
                if (!string.IsNullOrEmpty(decodedText))
                {
                    Debug.Log($"[QrScanner] 디코딩 성공: {decodedText}");
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

        private string TryDecodeLatestFrame()
        {
            if (!cameraManager.TryAcquireLatestCpuImage(out var cpuImage))
            {
                return null;
            }

            using (cpuImage)
            {
                var conversionParams = new XRCpuImage.ConversionParams
                {
                    inputRect = new RectInt(0, 0, cpuImage.width, cpuImage.height),
                    outputDimensions = new Vector2Int(cpuImage.width, cpuImage.height),
                    outputFormat = TextureFormat.R8,
                    transformation = XRCpuImage.Transformation.MirrorY
                };

                int bufferSize = cpuImage.GetConvertedDataSize(conversionParams);
                var buffer = new NativeArray<byte>(bufferSize, Allocator.Temp);
                cpuImage.Convert(conversionParams, buffer);

                string decodedText = DecodeBuffer(buffer, conversionParams.outputDimensions.x, conversionParams.outputDimensions.y);
                buffer.Dispose();

                return decodedText;
            }
        }

        private string DecodeBuffer(NativeArray<byte> buffer, int width, int height)
        {
#if CADVERSE_ENABLE_ZXING
            byte[] managedBuffer = new byte[buffer.Length];
            buffer.CopyTo(managedBuffer);

            var luminanceSource = new RGBLuminanceSource(managedBuffer, width, height, RGBLuminanceSource.BitmapFormat.Gray8);
            var binarizer = new HybridBinarizer(luminanceSource);
            var binaryBitmap = new BinaryBitmap(binarizer);

            var reader = new MultiFormatReader();
            var hints = new System.Collections.Generic.Dictionary<DecodeHintType, object>
            {
                { DecodeHintType.POSSIBLE_FORMATS, new System.Collections.Generic.List<BarcodeFormat> { BarcodeFormat.QR_CODE } },
                { DecodeHintType.TRY_HARDER, true },
                { DecodeHintType.ALSO_INVERTED, true }
            };

            try
            {
                var result = reader.decode(binaryBitmap, hints);
                return result?.Text;
            }
            catch
            {
                return null;
            }
#else
#if UNITY_EDITOR
            if (allowEditorMock && !string.IsNullOrEmpty(editorMockPayload))
            {
                return editorMockPayload;
            }
#endif
            return null;
#endif
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
