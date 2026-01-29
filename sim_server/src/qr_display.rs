//! QR 코드 생성 및 GUI 창 출력 모듈
//! DPI를 감지하여 정확한 물리적 크기(센티미터)로 QR 코드를 표시합니다.

use anyhow::Result;
use local_ip_address::local_ip;
use minifb::{Key, Window, WindowOptions, Scale, ScaleMode};
use qrcode::{QrCode, EcLevel};
use std::thread;
use std::time::Duration;

/// 기본 QR 코드 물리적 크기 (센티미터)
const DEFAULT_QR_SIZE_CM: f32 = 5.0;

/// 로컬 IP 주소를 가져옵니다
pub fn get_local_ip() -> Result<String> {
    let ip = local_ip()?;
    Ok(ip.to_string())
}

/// 시스템 DPI를 감지합니다 (Windows)
#[cfg(target_os = "windows")]
fn get_system_dpi() -> f32 {
    use std::ptr;

    // Windows API를 통해 DPI 가져오기
    #[link(name = "user32")]
    extern "system" {
        fn GetDC(hwnd: *mut std::ffi::c_void) -> *mut std::ffi::c_void;
        fn GetDeviceCaps(hdc: *mut std::ffi::c_void, index: i32) -> i32;
        fn ReleaseDC(hwnd: *mut std::ffi::c_void, hdc: *mut std::ffi::c_void) -> i32;
    }

    const LOGPIXELSX: i32 = 88;

    unsafe {
        let hdc = GetDC(ptr::null_mut());
        if hdc.is_null() {
            println!("[QR Display] DPI 감지 실패, 기본값 96 사용");
            return 96.0;
        }
        let dpi = GetDeviceCaps(hdc, LOGPIXELSX) as f32;
        ReleaseDC(ptr::null_mut(), hdc);

        if dpi > 0.0 {
            println!("[QR Display] 감지된 DPI: {}", dpi);
            dpi
        } else {
            96.0
        }
    }
}

/// 시스템 DPI를 감지합니다 (기타 OS)
#[cfg(not(target_os = "windows"))]
fn get_system_dpi() -> f32 {
    // Linux/macOS의 경우 기본 96 DPI 사용
    // 실제 구현 시 xrandr 또는 NSScreen API 사용 가능
    println!("[QR Display] 기본 DPI 96 사용 (비-Windows)");
    96.0
}

/// 센티미터를 픽셀로 변환합니다
fn cm_to_pixels(cm: f32, dpi: f32) -> u32 {
    // 1 인치 = 2.54 cm
    let inches = cm / 2.54;
    (inches * dpi) as u32
}

/// 서버 연결 정보를 QR 코드로 GUI 창에 출력합니다
///
/// ## 인자
/// - `port`: 서버 포트 번호
/// - `qr_size_cm`: QR 코드 물리적 크기 (센티미터), None이면 기본값 5cm
///
/// ## QR 코드 내용
/// `ip:port` 형식 (예: "192.168.0.10:3000")
pub fn display_qr_code(port: u16, qr_size_cm: Option<f32>) -> Result<()> {
    // 로컬 IP 가져오기
    let ip = get_local_ip()?;
    let server_info = format!("{}:{}", ip, port);

    // DPI 감지
    let dpi = get_system_dpi();
    let target_size_cm = qr_size_cm.unwrap_or(DEFAULT_QR_SIZE_CM);
    let target_size_px = cm_to_pixels(target_size_cm, dpi);

    println!("\n╔════════════════════════════════════════════╗");
    println!("║  CADverse Simulation Server                ║");
    println!("╠════════════════════════════════════════════╣");
    println!("║  Server Address: {:<25} ║", server_info);
    println!("║  QR Size: {:.1} cm ({} px @ {} DPI)         ║", target_size_cm, target_size_px, dpi);
    println!("╠════════════════════════════════════════════╣");
    println!("║  QR 코드 창이 열립니다...                  ║");
    println!("╚════════════════════════════════════════════╝\n");

    // QR 코드 생성 - 명시적으로 에러 정정 레벨 M 설정
    // ZXing과 동일한 설정: EcLevel::M, 바이트 모드 (as_bytes)
    let code = QrCode::with_error_correction_level(server_info.as_bytes(), EcLevel::M)?;
    println!("[QR Display] QR 버전: {:?}, EC: M", code.version());
    let qr_modules = code.render::<char>()
        .quiet_zone(false)  // 여백 제거 - QR 코드만
        .module_dimensions(1, 1)
        .build();

    // QR 모듈 수 계산
    let qr_lines: Vec<&str> = qr_modules.lines().collect();
    let qr_module_count = qr_lines.first().map(|l| l.chars().count()).unwrap_or(0);

    // 각 모듈의 픽셀 크기 계산 (QR 코드 자체가 target_size_cm가 되도록)
    let module_size = (target_size_px as f32 / qr_module_count as f32).ceil() as usize;
    let module_size = module_size.max(1); // 최소 1픽셀

    // QR 코드 크기 (여백 없음)
    let qr_size = module_size * qr_module_count;

    // 창 크기 = QR 코드 + 여백 (시각적 구분용)
    let margin = module_size * 2; // 2모듈 크기의 여백
    let window_size = qr_size + margin * 2;

    // 실제 QR 크기 계산 (cm)
    let actual_qr_size_cm = (qr_size as f32 / dpi) * 2.54;

    println!("[QR Display] QR 모듈 수: {}x{}", qr_module_count, qr_lines.len());
    println!("[QR Display] 모듈당 픽셀: {}", module_size);
    println!("[QR Display] QR 코드 크기: {} px ({:.2} cm)", qr_size, actual_qr_size_cm);
    println!("[QR Display] 창 크기: {}x{} px (여백 포함)", window_size, window_size);

    // 이미지 버퍼 생성 (ARGB 형식)
    let mut buffer: Vec<u32> = vec![0xFFFFFFFF; window_size * window_size]; // 흰색 배경

    // QR 코드를 버퍼에 그리기 (여백 오프셋 적용)
    for (y, line) in qr_lines.iter().enumerate() {
        for (x, ch) in line.chars().enumerate() {
            let color = if ch == '█' || ch == '#' {
                0xFF000000 // 검정 (ARGB)
            } else {
                0xFFFFFFFF // 흰색 (ARGB)
            };

            // 모듈 영역을 채우기 (여백 오프셋 적용)
            for dy in 0..module_size {
                for dx in 0..module_size {
                    let px = margin + x * module_size + dx;
                    let py = margin + y * module_size + dy;
                    if px < window_size && py < window_size {
                        buffer[py * window_size + px] = color;
                    }
                }
            }
        }
    }

    // 별도 스레드에서 GUI 창 열기
    let server_info_clone = server_info.clone();
    thread::spawn(move || {
        let title = format!("CADverse QR - {} ({:.1}cm)", server_info_clone, target_size_cm);

        let mut window = match Window::new(
            &title,
            window_size,
            window_size,
            WindowOptions {
                scale: Scale::X1,
                scale_mode: ScaleMode::Center,
                resize: false,
                ..WindowOptions::default()
            },
        ) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("[QR Display] 창 생성 실패: {}", e);
                return;
            }
        };

        window.set_target_fps(30);

        println!("[QR Display] QR 코드 창 열림. ESC 또는 창 닫기로 종료.");

        while window.is_open() && !window.is_key_down(Key::Escape) {
            window.update_with_buffer(&buffer, window_size, window_size).unwrap_or_else(|e| {
                eprintln!("[QR Display] 버퍼 업데이트 오류: {}", e);
            });
            thread::sleep(Duration::from_millis(33));
        }

        println!("[QR Display] QR 코드 창 닫힘.");
    });

    // 창이 열릴 때까지 약간 대기
    thread::sleep(Duration::from_millis(500));

    Ok(())
}

/// 서버 연결 정보를 QR 코드로 터미널에 출력합니다 (레거시 호환)
pub fn display_qr_code_terminal(port: u16) -> Result<()> {
    let ip = get_local_ip()?;
    let server_info = format!("{}:{}", ip, port);

    println!("\n╔════════════════════════════════════════════╗");
    println!("║  CADverse Simulation Server               ║");
    println!("╠════════════════════════════════════════════╣");
    println!("║  Server Address: {:<25}║", server_info);
    println!("╠════════════════════════════════════════════╣");
    println!("║  Scan QR code to connect:                 ║");
    println!("╚════════════════════════════════════════════╝\n");

    let code = QrCode::new(server_info.as_bytes())?;
    let string = code
        .render::<char>()
        .quiet_zone(false)
        .module_dimensions(2, 1)
        .build();

    println!("{}", string);
    println!("\n");

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_local_ip() {
        let ip = get_local_ip().unwrap();
        println!("Local IP: {}", ip);
        assert!(!ip.is_empty());
    }

    #[test]
    fn test_cm_to_pixels() {
        // 96 DPI에서 2.54cm = 1인치 = 96픽셀
        assert_eq!(cm_to_pixels(2.54, 96.0), 96);

        // 96 DPI에서 5cm
        let px = cm_to_pixels(5.0, 96.0);
        println!("5cm @ 96 DPI = {} px", px);
        assert!(px > 0);
    }

    #[test]
    fn test_get_system_dpi() {
        let dpi = get_system_dpi();
        println!("System DPI: {}", dpi);
        assert!(dpi > 0.0);
    }
}
