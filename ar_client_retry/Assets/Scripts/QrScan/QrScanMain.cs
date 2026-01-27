using System;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using CADverse.Utils; // For AndroidToast
using UnityEngine.XR.ARFoundation; // For ARSession

namespace CADverse.Main // 네임스페이스를 CADverse.Main으로 변경
{
    public class QrScanMain : MonoBehaviour
    {
        [SerializeField] private QrScanner qrScanner;
        private CancellationTokenSource _cancellationTokenSource; // 스캔 취소 토큰

        void Start()
        {
            // URP 카메라 데이터 자동 추가 (안전장치)
            var cam = Camera.main;
            if (cam != null && cam.GetComponent<UniversalAdditionalCameraData>() == null)
            {
                Debug.Log("[QrScanMain] Adding missing UniversalAdditionalCameraData to Main Camera.");
                cam.gameObject.AddComponent<UniversalAdditionalCameraData>();
            }
            
            // QrScanner 컴포넌트 찾기 및 연결 확인
            if (qrScanner == null)
            {
                qrScanner = FindFirstObjectByType<QrScanner>();
                if (qrScanner == null)
                {
                    AndroidToast.Show("QrScanner 컴포넌트를 찾을 수 없습니다! 씬에 추가되었는지 확인하세요.", true);
                    Debug.LogError("[QrScanMain] QrScanner 컴포넌트를 찾을 수 없습니다! 씬에 추가되었는지 확인하세요.");
                    return;
                }
            }
            
            // 비동기 스캔 루프 시작
            _cancellationTokenSource = new CancellationTokenSource();
            _ = StartScanLoop(_cancellationTokenSource.Token); // Task 반환값을 무시하고 비동기 루프 시작
            Debug.Log("[QrScanMain] 비동기 스캔 루프 시작.");
            AndroidToast.Show("QR 스캔 루프 시작", false);
        }

        private async Task StartScanLoop(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                AndroidToast.Show("QR 스캔 대기 중...", false);
                try
                {
                    // ARSessionState.SessionTracking 대기 로직 제거 (사용자 요청)

                    AndroidToast.Show("QR 스캔 시작 (ScanOnceAsync 호출)...", false);
                    // QrScanner의 ScanOnceAsync 호출 (타임아웃은 QrScanner 내부에서 처리)
                    string qrPayload = await qrScanner.ScanOnceAsync(token);

                    if (!string.IsNullOrEmpty(qrPayload))
                    {
                        AndroidToast.Show($"QR 스캔 성공: {qrPayload}", true); // 파싱 값 출력
                        Debug.Log($"[QrScanMain] QR 스캔 성공: {qrPayload}");
                        // TODO: 스캔 성공 후 추가 작업 (예: 서버 연결 등)
                        
                        // 성공 후에는 잠시 멈췄다가 다시 스캔 (지속 재시도)
                        await Task.Delay(5000, token); // 5초 대기 후 다시 스캔 시도
                    }
                    else // ScanOnceAsync가 null을 반환한 경우 (내부 타임아웃 등)
                    {
                        AndroidToast.Show("QR 스캔 실패 (결과 없음). 재시도 중...", false);
                        Debug.LogWarning("[QrScanMain] QR 스캔 실패 (결과 없음).");
                        await Task.Delay(1000, token); // 1초 대기 후 재시도
                    }
                }
                catch (OperationCanceledException)
                {
                    AndroidToast.Show("QR 스캔 루프 취소됨.", false);
                    Debug.Log("[QrScanMain] QR 스캔 루프 취소됨.");
                    break;
                }
                catch (Exception ex)
                {
                    AndroidToast.Show($"QR 스캔 중 오류 발생: {ex.Message}. 재시도 중...", true);
                    Debug.LogError($"[QrScanMain] QR 스캔 루프 오류: {ex.Message}");
                    await Task.Delay(3000, token); // 3초 대기 후 재시도
                }
            }
        }

        void OnDestroy()
        {
            // 씬 파괴 시 스캔 루프 취소
            _cancellationTokenSource?.Cancel();
            _cancellationTokenSource?.Dispose();
        }
    }
}