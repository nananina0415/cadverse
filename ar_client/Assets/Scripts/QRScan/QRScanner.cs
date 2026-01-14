using System;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace CADverse.QRScan
{
    /// <summary>
    /// AR 카메라를 사용한 QR 코드 스캐너
    /// </summary>
    public class QRScanner : MonoBehaviour
    {
        [Header("AR Components")]
        [SerializeField] private Camera arCamera;

        [Header("Scan Settings")]
        [SerializeField] private float scanInterval = 0.5f; // 스캔 간격 (초)

        // 스캔 상태
        public bool IsScanning { get; private set; }

        // 이벤트
        public event Action<string> OnQRCodeDetected;
        public event Action<string> OnScanError;

        private float _lastScanTime;
        private Texture2D _texture;
        private ARCameraManager _arCameraManager;
        private ARCameraBackground _arCameraBackground;

        private void Awake()
        {
            // AR Camera에서 컴포넌트 가져오기
            if (arCamera != null)
            {
                _arCameraManager = arCamera.GetComponent<ARCameraManager>();
                _arCameraBackground = arCamera.GetComponent<ARCameraBackground>();
            }

            // 자동으로 찾기 (설정 안 했을 경우)
            if (_arCameraManager == null)
            {
                _arCameraManager = FindFirstObjectByType<ARCameraManager>();
            }

            if (_arCameraBackground == null)
            {
                _arCameraBackground = FindFirstObjectByType<ARCameraBackground>();
            }
        }

        /// <summary>
        /// QR 코드 스캔 시작
        /// </summary>
        public void StartScanning()
        {
            if (IsScanning)
            {
                Debug.LogWarning("[QRScanner] Already scanning");
                return;
            }

            IsScanning = true;
            _lastScanTime = 0f;
            Debug.Log("[QRScanner] Started scanning");
        }

        /// <summary>
        /// QR 코드 스캔 중지
        /// </summary>
        public void StopScanning()
        {
            IsScanning = false;
            Debug.Log("[QRScanner] Stopped scanning");
        }

        private void Update()
        {
            if (!IsScanning)
            {
                return;
            }

            // 스캔 간격 체크
            if (Time.time - _lastScanTime < scanInterval)
            {
                return;
            }

            _lastScanTime = Time.time;

            // AR 카메라 이미지에서 QR 코드 스캔
            TryScanQRCode();
        }

        private void TryScanQRCode()
        {
            try
            {
                // AR 카메라 이미지 가져오기
                if (!_arCameraManager.TryAcquireLatestCpuImage(out XRCpuImage image))
                {
                    return;
                }

                // CPU 이미지를 Texture2D로 변환
                if (_texture == null || _texture.width != image.width || _texture.height != image.height)
                {
                    _texture = new Texture2D(image.width, image.height, TextureFormat.RGB24, false);
                }

                // 이미지 변환 파라미터
                var conversionParams = new XRCpuImage.ConversionParams
                {
                    inputRect = new RectInt(0, 0, image.width, image.height),
                    outputDimensions = new Vector2Int(image.width, image.height),
                    outputFormat = TextureFormat.RGB24,
                    transformation = XRCpuImage.Transformation.None
                };

                // NativeArray로 변환
                var rawTextureData = _texture.GetRawTextureData<byte>();
                image.Convert(conversionParams, rawTextureData);
                _texture.Apply();

                // 이미지 해제
                image.Dispose();

                // ZXing으로 QR 코드 디코딩
                var result = DecodeQRCode(_texture);

                if (!string.IsNullOrEmpty(result))
                {
                    Debug.Log($"[QRScanner] QR Code detected: {result}");
                    StopScanning();
                    OnQRCodeDetected?.Invoke(result);
                }
            }
            catch (Exception e)
            {
                Debug.LogError($"[QRScanner] Scan error: {e.Message}");
                OnScanError?.Invoke(e.Message);
            }
        }

        /// <summary>
        /// ZXing을 사용하여 QR 코드 디코딩
        /// TODO: ZXing 라이브러리 필요 (NuGet 또는 Unity Package)
        /// </summary>
        private string DecodeQRCode(Texture2D texture)
        {
            // TODO: ZXing.Net 사용
            // var reader = new ZXing.BarcodeReader();
            // var result = reader.Decode(texture.GetPixels32(), texture.width, texture.height);
            // return result?.Text;

            // 임시: ZXing 없이 더미 데이터 반환 (테스트용)
            Debug.LogWarning("[QRScanner] ZXing not implemented yet. Returning dummy data.");
            return "192.168.0.10:3000"; // 더미 서버 주소
        }

        private void OnDestroy()
        {
            if (_texture != null)
            {
                Destroy(_texture);
            }
        }
    }
}
