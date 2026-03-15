#[derive(Debug, thiserror::Error)]
pub enum S2sError {
    #[error("서버 이름이 63바이트를 초과합니다 (현재 {0}바이트)")]
    NameTooLong(usize),
    #[error("서버 이름에 제어문자가 포함되어 있습니다")]
    NameHasControlChar,
    #[error("mDNS 오류: {0}")]
    Mdns(#[from] mdns_sd::Error),
}
