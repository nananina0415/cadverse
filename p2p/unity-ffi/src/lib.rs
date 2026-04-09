use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::sync::Arc;

use p2p_core::{Connection, JoinForm, NetId, Password, PeerType};

// ── 핸들 구조체 ──────────────────────────────────────────────────────────────

/// Unity에서 P2P 네트워크 핸들로 사용하는 불투명 포인터 대상.
/// Box::into_raw / Box::from_raw로 수명을 관리한다.
pub struct FfiNet {
    rt: Arc<tokio::runtime::Runtime>,
    net: p2p_core::P2PNet,
}

/// QUIC 연결 핸들.
pub struct FfiConn {
    rt: Arc<tokio::runtime::Runtime>,
    conn: Connection,
}

// ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

fn from_cstr(ptr: *const c_char) -> String {
    if ptr.is_null() {
        return String::new();
    }
    unsafe { CStr::from_ptr(ptr).to_string_lossy().into_owned() }
}

// ── FFI 함수 ─────────────────────────────────────────────────────────────────

/// P2P 네트워크에 참가한다.
///
/// - `udp_port == 0` → MidServer (시뮬 없는 클라이언트 앱 등)
/// - `udp_port > 0`  → ArClient { udp_port }
///
/// 성공하면 FfiNet 포인터, 실패하면 null 반환.
/// 반환된 포인터는 반드시 cv_net_free로 해제해야 한다.
#[unsafe(no_mangle)]
pub extern "C" fn cv_join(
    net_id: *const c_char,
    pw: *const c_char,
    name: *const c_char,
    udp_port: u16,
) -> *mut FfiNet {
    let net_id = from_cstr(net_id);
    let pw = from_cstr(pw);
    let name = from_cstr(name);

    let peer_type = if udp_port > 0 {
        PeerType::ArClient { udp_port }
    } else {
        PeerType::MidServer
    };

    let rt = match tokio::runtime::Runtime::new() {
        Ok(r) => Arc::new(r),
        Err(e) => {
            eprintln!("[cv_join] tokio runtime 생성 실패: {e}");
            return std::ptr::null_mut();
        }
    };

    let net = match rt.block_on(p2p_core::join_p2p_net(JoinForm {
        net_id: NetId(net_id),
        pw: Password(pw),
        my_name: name,
        peer_type,
    })) {
        Ok(n) => n,
        Err(e) => {
            eprintln!("[cv_join] 네트워크 참가 실패: {e}");
            return std::ptr::null_mut();
        }
    };

    Box::into_raw(Box::new(FfiNet { rt, net }))
}

/// FfiNet을 해제한다.
#[unsafe(no_mangle)]
pub extern "C" fn cv_net_free(net: *mut FfiNet) {
    if !net.is_null() {
        unsafe { drop(Box::from_raw(net)); }
    }
}

/// 현재 피어 목록을 JSON 문자열로 반환한다.
///
/// 반환된 포인터는 반드시 cv_string_free로 해제해야 한다.
///
/// JSON 스키마:
/// ```json
/// [{ "addr": <NodeAddr>, "name": "...", "peer_type": "SimServer"|"MidServer"|{"ArClient":{"udp_port":N}} }]
/// ```
#[unsafe(no_mangle)]
pub extern "C" fn cv_get_peers_json(net: *mut FfiNet) -> *mut c_char {
    if net.is_null() {
        return std::ptr::null_mut();
    }
    let net = unsafe { &*net };
    let peers = net.net.get_peers();
    let json = match serde_json::to_string(&peers) {
        Ok(j) => j,
        Err(e) => {
            eprintln!("[cv_get_peers_json] 직렬화 실패: {e}");
            return std::ptr::null_mut();
        }
    };
    match CString::new(json) {
        Ok(s) => s.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

/// cv_get_peers_json이 반환한 문자열을 해제한다.
#[unsafe(no_mangle)]
pub extern "C" fn cv_string_free(s: *mut c_char) {
    if !s.is_null() {
        unsafe { drop(CString::from_raw(s)); }
    }
}

/// QUIC(UDP) 연결을 맺는다. addr_json은 PeerInfo.addr 필드 값 그대로 사용.
///
/// 블로킹 함수 — 메인 스레드에서 호출하지 말 것.
/// 반환된 포인터는 반드시 cv_conn_free로 해제해야 한다.
#[unsafe(no_mangle)]
pub extern "C" fn cv_connect_udp(
    net: *mut FfiNet,
    addr_json: *const c_char,
) -> *mut FfiConn {
    if net.is_null() || addr_json.is_null() {
        return std::ptr::null_mut();
    }
    let net = unsafe { &*net };
    let addr: p2p_core::NodeAddr = match serde_json::from_str(&from_cstr(addr_json)) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("[cv_connect_udp] addr 역직렬화 실패: {e}");
            return std::ptr::null_mut();
        }
    };
    match net.rt.block_on(net.net.connect_udp(addr)) {
        Ok(conn) => Box::into_raw(Box::new(FfiConn { rt: net.rt.clone(), conn })),
        Err(e) => {
            eprintln!("[cv_connect_udp] 연결 실패: {e}");
            std::ptr::null_mut()
        }
    }
}

/// QUIC 연결로 데이터를 전송한다.
///
/// 블로킹 함수. 성공 시 1, 실패 시 0 반환.
#[unsafe(no_mangle)]
pub extern "C" fn cv_conn_send(
    conn: *mut FfiConn,
    data: *const u8,
    len: u32,
) -> i32 {
    if conn.is_null() || data.is_null() {
        return 0;
    }
    let conn = unsafe { &*conn };
    let bytes = unsafe { std::slice::from_raw_parts(data, len as usize) };
    match conn.rt.block_on(conn.conn.send(bytes)) {
        Ok(_) => 1,
        Err(e) => {
            eprintln!("[cv_conn_send] 전송 실패: {e}");
            0
        }
    }
}

/// QUIC 연결에서 데이터를 수신한다.
///
/// 블로킹 함수 — 데이터가 도착할 때까지 대기한다. 별도 스레드에서 호출할 것.
/// 성공 시 수신 바이트 수, 실패 시 -1 반환.
#[unsafe(no_mangle)]
pub extern "C" fn cv_conn_recv(
    conn: *mut FfiConn,
    out: *mut u8,
    out_len: u32,
) -> i32 {
    if conn.is_null() || out.is_null() {
        return -1;
    }
    let conn = unsafe { &*conn };
    match conn.rt.block_on(conn.conn.recv()) {
        Ok(bytes) => {
            let n = bytes.len().min(out_len as usize);
            unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), out, n); }
            n as i32
        }
        Err(e) => {
            eprintln!("[cv_conn_recv] 수신 실패: {e}");
            -1
        }
    }
}

/// FfiConn을 해제한다.
#[unsafe(no_mangle)]
pub extern "C" fn cv_conn_free(conn: *mut FfiConn) {
    if !conn.is_null() {
        unsafe { drop(Box::from_raw(conn)); }
    }
}

/// HTTP/3으로 파일을 요청한다. addr_json은 PeerInfo.addr 필드 값.
///
/// 블로킹 함수. 성공 시 수신 바이트 수, 실패 시 -1 반환.
/// out 버퍼가 부족하면 앞부분만 복사되므로 충분히 크게 잡을 것.
#[unsafe(no_mangle)]
pub extern "C" fn cv_request_http(
    net: *mut FfiNet,
    addr_json: *const c_char,
    path: *const c_char,
    out: *mut u8,
    out_len: u32,
) -> i32 {
    if net.is_null() || addr_json.is_null() || path.is_null() || out.is_null() {
        return -1;
    }
    let net = unsafe { &*net };
    let addr: p2p_core::NodeAddr = match serde_json::from_str(&from_cstr(addr_json)) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("[cv_request_http] addr 역직렬화 실패: {e}");
            return -1;
        }
    };
    let path = from_cstr(path);
    match net.rt.block_on(net.net.request_http(addr, &path)) {
        Ok(bytes) => {
            let n = bytes.len().min(out_len as usize);
            unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), out, n); }
            n as i32
        }
        Err(e) => {
            eprintln!("[cv_request_http] 요청 실패: {e}");
            -1
        }
    }
}
