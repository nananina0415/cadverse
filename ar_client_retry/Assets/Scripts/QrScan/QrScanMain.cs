using UnityEngine;
using UnityEngine.Rendering.Universal;
using CADverse.QrScan;
using CADverse.Utils; // For AndroidToast
using UnityEngine.XR.ARFoundation; // For ARSession

namespace CADverse.Main
{
    public class QrScanMain : MonoBehaviour
    {
            if (_arSession == null)
            {
                AndroidToast.Show("ARSession 컴포넌트를 찾을 수 없습니다! 씬에 추가되었는지 확인하세요.", true);
                Debug.LogError("[QrScanMain] ARSession 컴포넌트를 찾을 수 없습니다! 씬에 추가되었는지 확인하세요.");
            }

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

            // 이벤트 구독
            qrScanner.OnQrCodeScanned += HandleQrCodeScanned;
            qrScanner.OnScanError += HandleScanError;

            // 스캔 시작
            qrScanner.StartScanning();
            Debug.Log("[QrScanMain] QrScanner 스캔 시작 명령");
        }

        void Update()
        {
            // ARSession 상태 주기적으로 토스트로 표시 (디버깅용)
            if (Time.time - _lastSessionStateToastTime > _sessionStateToastMinInterval)
            {
                AndroidToast.Show($"ARSession 상태: {ARSession.state}", false);
                _lastSessionStateToastTime = Time.time;
            }

            // ARSession이 Tracking 상태에 도달하면 초점 모드를 한 번만 설정 (현재 비활성화)
            // if (!_focusModeSet && ARSession.state == ARSessionState.Tracking)
            // {
            //     if (qrScanner != null)
            //     {
            //         qrScanner.SetCameraFocusModeContinuous();
            //         _focusModeSet = true; // 한 번 설정했으므로 다시 설정하지 않음
            //     }
            // }
        }

        private void HandleQrCodeScanned(string text, Texture2D image)
        {
            Debug.Log($"[QrScanMain] QR 코드 스캔 성공: {text}");
            AndroidToast.Show($"QR 스캔 성공: {text}", true);
            
            // TODO: 스캔된 텍스트와 이미지를 사용하여 다음 로직 처리 (예: 서버 연결, 이미지 표시)
        }

        private void HandleScanError(string error)
        {
            Debug.LogError($"[QrScanMain] QR 코드 스캔 오류: {error}");
            AndroidToast.Show($"스캔 오류: {error}", true);
        }

        void OnDestroy()
        {
            // 이벤트 구독 해제
            if (qrScanner != null)
            {
                qrScanner.OnQrCodeScanned -= HandleQrCodeScanned;
                qrScanner.OnScanError -= HandleScanError;
            }
        }
    }
}
