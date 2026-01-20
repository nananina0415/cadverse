//! QR 코드 생성 및 터미널 출력 모듈

use anyhow::Result;
use local_ip_address::local_ip;
use qrcode::QrCode;

/// 로컬 IP 주소를 가져옵니다
pub fn get_local_ip() -> Result<String> {
    let ip = local_ip()?;
    Ok(ip.to_string())
}

/// 서버 연결 정보를 QR 코드로 터미널에 출력합니다
///
/// ## 인자
/// - `port`: 서버 포트 번호
///
/// ## QR 코드 내용
/// `ip:port` 형식 (예: "192.168.0.10:3000")
pub fn display_qr_code(port: u16) -> Result<()> {
    // 로컬 IP 가져오기
    let ip = get_local_ip()?;
    let server_info = format!("{}:{}", ip, port);

    println!("\n╔════════════════════════════════════════════╗");
    println!("║  CADverse Simulation Server               ║");
    println!("╠════════════════════════════════════════════╣");
    println!("║  Server Address: {:<25}║", server_info);
    println!("╠════════════════════════════════════════════╣");
    println!("║  Scan QR code to connect:                 ║");
    println!("╚════════════════════════════════════════════╝\n");

    // QR 코드 생성
    let code = QrCode::new(server_info.as_bytes())?;

    // ASCII 아트로 출력
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
    fn test_display_qr_code() {
        display_qr_code(3000).unwrap();
    }
}
