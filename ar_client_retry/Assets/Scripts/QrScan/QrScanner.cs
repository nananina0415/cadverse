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

namespace CADverse.QrScan // 네임스페이스 변경: Utils -> QrScan
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
        [SerializeField] private float scanInterval = 0.5f; // 스캔 주기 (초) -> 추가됨
        [SerializeField]
        [Tooltip("초 단위 타임아웃. 0 이하면 무제한 대기")]
        private float scanTimeoutSeconds = 15f; // 이전 프로젝트의 값 유지
        [SerializeField] private bool requestCameraPermission = true;

        [Header("Editor Mock")]
        [SerializeField] private bool allowEditorMock = true;
        [SerializeField][TextArea] private string editorMockPayload = "http://127.0.0.1:8000/cadverse";

        private TaskCompletionSource<string> _scanCompletion;
        private CancellationTokenSource _scanCancellation;
        private Texture2D _previewTexture;

        // --- 기존 프로젝트에서 복사한 추가 필드 및 이벤트 ---
        public event System.Action<string, Texture2D> OnQrCodeScanned; // System.Action으로 명시
        public event System.Action<string> OnScanError; // System.Action으로 명시

        private bool _isScanning = false;
        private float _lastScanTime;
        private float _lastToastTime; // 토스트 메시지 쓰로틀링용
        private const float _toastMinInterval = 0.0f; // 토스트 메시지 최소 간격 (초) -> 디버깅을 위해 0으로 유지 (이후 3.0f로 변경)

        // --- 샘플 코드에서 제거된 LastScannedQRImage 제거 ---
        // public Texture2D LastScannedQRImage => _lastScannedQRImage;


        public bool IsScanning => _isScanning; // 샘플 코드의 _scanCompletion 대신 _isScanning 사용 (지속 스캔)

        private void Awake()
        {
            if (cameraManager == null)
            {
                cameraManager = FindFirstObjectByType<ARCameraManager>(); // FindObjectOfType -> FindFirstObjectByType
            }

            if (cameraManager != null)
            {
                // AR Foundation의 focusMode 프로퍼티가 제거되었으므로, 해당 설정 코드 제거.
                // AR Foundation이 초점을 자동으로 관리하도록 맡김.
            }
            else
            {
                ShowToastWithThrottle("ARCameraManager를 찾을 수 없습니다. 카메라 피드에 문제가 있을 수 있습니다.", true);
                Debug.LogError("[QrScanner] ARCameraManager를 찾을 수 없습니다. 카메라 피드에 문제가 있을 수 있습니다.");
            }
        }

        /// <summary>
        /// QR 스캔을 한 번 수행하고 텍스트 결과를 반환한다. (-> 지속 스캔 시작으로 변경)
        /// </summary>
        public void StartScanning() // Task<string> ScanOnceAsync(CancellationToken cancellationToken = default) -> void StartScanning()
        {
            if (_isScanning) return;
            
            _isScanning = true;
            _lastScanTime = 0f;
            ShowToastWithThrottle("스캔 시작됨.");

            // -- 샘플 코드의 TaskCompletionSource, CancellationToken 관련 로직 제거 (지속 스캔) --
            // _scanCompletion = new TaskCompletionSource<string>();
            // _scanCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            // StartCoroutine(ScanRoutine(_scanCancellation.Token));

#if !CADVERSE_ENABLE_ZXING
            ShowToastWithThrottle("ZXing 라이브러리 비활성화! csc.rsp 확인", true);
            Debug.LogError("[QrScanner] ZXing 라이브러리가 활성화되지 않았습니다! (csc.rsp 확인)");
#endif
        }

        public void StopScanning() // CancelScan -> StopScanning
        {
            _isScanning = false;
            ShowToastWithThrottle("스캔 중지됨.");
            // _scanCancellation?.Cancel(); // 샘플 코드의 CancellationToken 관련 로직 제거
        }

        // --- 샘플 코드의 ScanRoutine 코루틴 제거 (지속 스캔) ---
        // private IEnumerator ScanRoutine(CancellationToken token) { ... }

        // --- 샘플 코드의 EnsureCameraPermission 코루틴 제거 (AR Foundation이 자동으로 처리) ---
        // private IEnumerator EnsureCameraPermission() { ... }

        private void Update() // 지속 스캔을 위해 Update 메서드 추가
        {
            if (!_isScanning) return;

            if (Time.time - _lastScanTime < scanInterval) return;

            _lastScanTime = Time.time;
            ShowToastWithThrottle("스캔 프레임 처리 중...");
            ScanFrame();
        }

        private void ScanFrame() // TryDecodeLatestFrame -> ScanFrame으로 이름 변경 및 로직 통합
        {
            // out bool previewUpdated 제거
            // previewUpdated = false;

            if (cameraManager == null)
            {
                ShowToastWithThrottle("카메라 매니저 미연결. 스캔 불가.", true);
                Debug.LogError("[QrScanner] cameraManager가 연결되지 않았습니다.");
                return;
            }

            ShowToastWithThrottle("CPU 이미지 획득 시도 중...", false);
            if (!cameraManager.TryAcquireLatestCpuImage(out var cpuImage)) // FindFirstObjectByType -> FindFirstObjectByType
            {
                ShowToastWithThrottle("카메라 이미지 획득 실패. (TryAcquireLatestCpuImage: false)", true);
                return;
            }

            ShowToastWithThrottle("CPU 이미지 획득 성공. 처리 중...", false);
            using (cpuImage)
            {
                ProcessImage(cpuImage); // ProcessImage 메서드 새로 정의
            }
        }

        private void ProcessImage(XRCpuImage image) // 새로 정의
        {
            try
            {
                // 변환 파라미터 설정 (Alpha8)
                var conversionParams = new XRCpuImage.ConversionParams
                {
                    // QR 박스 안에서만 인식 로직 추가 예정
                    inputRect = new RectInt(0, 0, image.width, image.height), // 초기값은 이미지 전체
                    outputDimensions = new Vector2Int(image.width, image.height),
                    outputFormat = TextureFormat.Alpha8, // RGB24 -> Alpha8 변경 (그레이스케일)
                    transformation = XRCpuImage.Transformation.MirrorY
                };

                int bufferSize = image.GetConvertedDataSize(conversionParams);
                var buffer = new NativeArray<byte>(bufferSize, Allocator.Temp);

                try
                {
                    image.Convert(conversionParams, buffer);

                    // 디코딩 시도
                    string resultText = Decode(buffer, conversionParams.outputDimensions.x, conversionParams.outputDimensions.y);

                    if (!string.IsNullOrEmpty(resultText))
                    {
                        ShowToastWithThrottle($"QR 코드 디코딩 성공: {resultText}", true);
                        // 성공! 텍스처 생성하여 이벤트 발생
                        Texture2D resultTexture = CreateTextureFromBuffer(buffer, conversionParams.outputDimensions.x, conversionParams.outputDimensions.y);
                        OnQrCodeScanned?.Invoke(resultText, resultTexture);
                        StopScanning(); // 스캔 성공 시 자동 중지
                    }
                }
                finally
                {
                    buffer.Dispose();
                }
            }
            catch (Exception ex)
            {
                ShowToastWithThrottle($"이미지 처리 오류: {ex.Message}", true);
                Debug.LogError($"[QrScanner] Error processing image: {ex.Message}");
                OnScanError?.Invoke(ex.Message);
            }
        }

        private string Decode(NativeArray<byte> buffer, int width, int height) // DecodeBuffer -> Decode로 이름 변경
        {
            try
            {
#if CADVERSE_ENABLE_ZXING
                // NativeArray -> byte[] 복사
                byte[] rawData = buffer.ToArray();

                // ZXing 디코딩
                var luminanceSource = new RGBLuminanceSource(rawData, width, height, RGBLuminanceSource.BitmapFormat.Gray8);
                var binarizer = new HybridBinarizer(luminanceSource);
                var binaryBitmap = new BinaryBitmap(binarizer);
                
                var reader = new MultiFormatReader();
                var hints = new System.Collections.Generic.Dictionary<ZXing.DecodeHintType, object>
                {
                    { ZXing.DecodeHintType.POSSIBLE_FORMATS, new System.Collections.Generic.List<ZXing.BarcodeFormat> { ZXing.BarcodeFormat.QR_CODE } },
                    { ZXing.DecodeHintType.TRY_HARDER, true }
                };

                var result = reader.decode(binaryBitmap, hints);
                if (result == null)
                {
                    ShowToastWithThrottle("QR 코드 디코딩 실패 (결과 없음).", false);
                }
                return result?.Text;
#else
                ShowToastWithThrottle("ZXing 비활성화. 디코딩 스킵.", false);
                return null;
#endif
            }
            catch (Exception ex)
            {
                ShowToastWithThrottle($"디코딩 중 예외 발생: {ex.Message}", true);
                Debug.LogWarning($"[QrScanner] Decode error: {ex.Message}");
                return null;
            }
        }

        private Texture2D CreateTextureFromBuffer(NativeArray<byte> buffer, int width, int height)
        {
            Texture2D texture = new Texture2D(width, height, TextureFormat.Alpha8, false);
            texture.LoadRawTextureData(buffer);
            texture.Apply();
            return texture;
        }

        // --- 샘플 코드의 CleanupScan 제거 ---
        // private void CleanupScan() { ... }

        // 토스트 메시지 쓰로틀링 유틸리티
        private void ShowToastWithThrottle(string message, bool isError = false)
        {
            if (Time.time - _lastToastTime > _toastMinInterval || isError)
            {
                CADverse.Utils.AndroidToast.Show($"[QR] {message}", isError);
                _lastToastTime = Time.time;
            }
        }
    }

    // --- 샘플 코드의 TaskCompletionSourceExtensions 제거 ---
    // internal static class TaskCompletionSourceExtensions { ... }
}
