using System;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using CADverse.Utils;
using CADverse.Communication;
using CADverse.AR;
using CADverse.Model;

namespace CADverse.QrScan
{
    public class QrScanMain : MonoBehaviour
    {
        [SerializeField] private QrScanner qrScanner;
        [SerializeField] private ServerProxy serverProxy;
        [SerializeField] private ARManager arManager;
        [SerializeField] private ModelManager modelManager;
        private CancellationTokenSource _cancellationTokenSource;

        void Start()
        {
            // URP 카메라 데이터 자동 추가 (안전장치)
            var cam = Camera.main;
            if (cam != null && cam.GetComponent<UniversalAdditionalCameraData>() == null)
            {
                Debug.Log("[QrScanMain] Adding missing UniversalAdditionalCameraData to Main Camera.");
                cam.gameObject.AddComponent<UniversalAdditionalCameraData>();
            }

            // 컴포넌트 찾기
            if (qrScanner == null)
            {
                qrScanner = FindFirstObjectByType<QrScanner>();
                if (qrScanner == null)
                {
                    LogError("QrScanner 컴포넌트를 찾을 수 없습니다!");
                    return;
                }
            }

            if (serverProxy == null)
            {
                serverProxy = FindFirstObjectByType<ServerProxy>();
                if (serverProxy == null)
                {
                    LogError("ServerProxy 컴포넌트를 찾을 수 없습니다!");
                    return;
                }
            }

            if (arManager == null)
            {
                arManager = FindFirstObjectByType<ARManager>();
                if (arManager == null)
                {
                    LogError("ARManager 컴포넌트를 찾을 수 없습니다!");
                    return;
                }
            }

            if (modelManager == null)
            {
                modelManager = FindFirstObjectByType<ModelManager>();
                if (modelManager == null)
                {
                    LogError("ModelManager 컴포넌트를 찾을 수 없습니다!");
                    return;
                }
            }

            // 비동기 스캔 루프 시작
            _cancellationTokenSource = new CancellationTokenSource();
            _ = StartScanLoop(_cancellationTokenSource.Token);
            Debug.Log("[QrScanMain] 비동기 스캔 루프 시작.");
        }

        private async Task StartScanLoop(CancellationToken token)
        {
            string qrPayload = null;

            // QR 스캔 루프
            while (!token.IsCancellationRequested && string.IsNullOrEmpty(qrPayload))
            {
                Debug.Log("[QrScanMain] QR 스캔 대기 중...");
                try
                {
                    qrPayload = await qrScanner.ScanOnceAsync(token);

                    if (!string.IsNullOrEmpty(qrPayload))
                    {
                        LogAndShowToast("QR 스캔 성공!", true);
                        Debug.Log($"[QrScanMain] QR 스캔 성공: {qrPayload}");
                        break;
                    }
                    else
                    {
                        Debug.LogWarning("[QrScanMain] QR 스캔 실패. 재시도 중...");
                        await Task.Delay(1000, token);
                    }
                }
                catch (OperationCanceledException)
                {
                    Debug.Log("[QrScanMain] QR 스캔 루프 취소됨.");
                    return;
                }
                catch (Exception ex)
                {
                    LogError($"QR 스캔 오류: {ex.Message}");
                    await Task.Delay(3000, token);
                }
            }

            // QR 스캔 성공 후 서버 연결 및 모델 로딩
            if (!string.IsNullOrEmpty(qrPayload) && !token.IsCancellationRequested)
            {
                Debug.Log("[QrScanMain] 서버 연결 및 모델 로딩 시작.");

                try
                {
                    qrScanner.CancelScan();

                    // 1. ServerProxy 초기화
                    serverProxy.Initialize(qrPayload);
                    Debug.Log($"[QrScanMain] ServerProxy 초기화됨: {qrPayload}");

                    // 2. 서버에서 QR 패턴 다운로드 (서버와 동일한 QR 이미지 보장)
                    LogAndShowToast("서버에서 QR 패턴 다운로드 중...", true);
                    string qrPattern = await serverProxy.DownloadQrPatternAsync();
                    if (string.IsNullOrEmpty(qrPattern))
                    {
                        LogError("서버 QR 패턴 다운로드 실패");
                        return;
                    }
                    Debug.Log($"[QrScanMain] QR 패턴 다운로드 완료: {qrPattern.Length} chars");

                    // 3. QR 패턴을 Texture2D로 변환
                    Texture2D serverQrImage = CreateTextureFromQrPattern(qrPattern);
                    if (serverQrImage == null)
                    {
                        LogError("QR 패턴 → 텍스처 변환 실패");
                        return;
                    }
                    Debug.Log($"[QrScanMain] QR 텍스처 생성: {serverQrImage.width}x{serverQrImage.height}");

                    // 4. ModelManager 초기화 (테스트 모드)
                    await modelManager.InitializeModels(serverProxy);
                    Debug.Log("[QrScanMain] ModelManager 모델 초기화 완료.");

                    // 5. 서버 QR 이미지를 AR 마커로 등록
                    arManager.RegisterARMarker(serverQrImage, qrPayload, modelManager);
                    LogAndShowToast("모델 로드 완료. QR을 비추세요.", true);

                    // 6. WebSocket 연결 시작 (시뮬레이션 상태 수신용)
                    await serverProxy.ConnectWebSocketAsync();
                    Debug.Log("[QrScanMain] WebSocket 연결됨.");
                }
                catch (Exception ex)
                {
                    LogError($"서버 연결 오류: {ex.Message}");
                    Debug.LogError($"[QrScanMain] 서버 통신 오류: {ex.Message}\n{ex.StackTrace}");
                }
            }
        }

        /// <summary>
        /// 서버에서 받은 QR 패턴(0/1 문자열)을 Texture2D로 변환
        /// 여백 없이 QR 패턴만 생성 (AR 이미지 추적은 패턴 매칭이므로)
        /// </summary>
        private Texture2D CreateTextureFromQrPattern(string pattern)
        {
            try
            {
                string[] lines = pattern.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                if (lines.Length < 2)
                {
                    Debug.LogError("[QrScanMain] QR 패턴 파싱 실패: 데이터 부족");
                    return null;
                }

                // 첫 줄: 모듈 수
                int moduleCount = int.Parse(lines[0]);
                Debug.Log($"[QrScanMain] QR 모듈 수: {moduleCount}");

                // 텍스처 크기 (모듈당 16픽셀로 확대)
                int pixelsPerModule = 16;
                int textureSize = moduleCount * pixelsPerModule;

                Texture2D texture = new Texture2D(textureSize, textureSize, TextureFormat.RGBA32, false);
                Color32[] colors = new Color32[textureSize * textureSize];

                // 기본 흰색으로 초기화
                Color32 white = new Color32(255, 255, 255, 255);
                Color32 black = new Color32(0, 0, 0, 255);
                for (int i = 0; i < colors.Length; i++)
                {
                    colors[i] = white;
                }

                // QR 패턴 그리기
                for (int row = 0; row < moduleCount && row + 1 < lines.Length; row++)
                {
                    string line = lines[row + 1]; // 첫 줄은 모듈 수
                    for (int col = 0; col < moduleCount && col < line.Length; col++)
                    {
                        bool isDark = line[col] == '1';
                        if (!isDark) continue; // 흰색은 이미 초기화됨

                        // 모듈 영역 채우기
                        for (int dy = 0; dy < pixelsPerModule; dy++)
                        {
                            for (int dx = 0; dx < pixelsPerModule; dx++)
                            {
                                int px = col * pixelsPerModule + dx;
                                // Unity 텍스처는 좌하단이 원점이므로 Y 반전
                                int py = (moduleCount - 1 - row) * pixelsPerModule + dy;
                                if (px < textureSize && py < textureSize)
                                {
                                    colors[py * textureSize + px] = black;
                                }
                            }
                        }
                    }
                }

                texture.SetPixels32(colors);
                texture.Apply();

                Debug.Log($"[QrScanMain] QR 텍스처 생성 완료: {textureSize}x{textureSize} (모듈수:{moduleCount})");
                return texture;
            }
            catch (Exception ex)
            {
                Debug.LogError($"[QrScanMain] QR 패턴 → 텍스처 변환 오류: {ex.Message}");
                return null;
            }
        }

        void OnDestroy()
        {
            _cancellationTokenSource?.Cancel();
            _cancellationTokenSource?.Dispose();
        }

        private void LogAndShowToast(string message, bool showToast = false)
        {
            Debug.Log($"[QRMain] {message}");
            if (showToast)
            {
                AndroidToast.Show(message, false);
            }
        }

        private void LogError(string message)
        {
            Debug.LogError($"[QRMain] {message}");
            AndroidToast.Show(message, true);
        }
    }
}
