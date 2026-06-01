use std::ffi::{CStr, CString};
use std::fs::OpenOptions;
use std::io::Write;
use std::os::raw::c_char;
use std::panic::{self, AssertUnwindSafe};
use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};

use p2p_core::{Connection, JoinForm, NetId, Password, PeerType};

// ── 에러 분류 + 정적 메시지 ─────────────────────────────────────────────────
pub const ERR_OK:            i32 = 0;
pub const ERR_NAME_CONFLICT: i32 = 1;
pub const ERR_GENERIC:       i32 = 2;

static MSG_NAME_CONFLICT: &CStr = c"이미 같은 이름의 사용자가 그룹에 있습니다";
static MSG_GENERIC:       &CStr = c"네트워크 참가 실패";

// ── 핸들 구조체 ──────────────────────────────────────────────────────────────

pub struct FfiNet {
    rt: Arc<tokio::runtime::Runtime>,
    net: p2p_core::P2PNet,
}

pub struct FfiConn {
    rt: Arc<tokio::runtime::Runtime>,
    conn: Connection,
}

/// FFI 가입 결과. handle이 null이면 error_kind / error_message로 원인 확인.
/// error_message는 Rust 정적 lifetime C 문자열이므로 호출자가 free하지 않는다.
#[repr(C)]
pub struct JoinResult {
    pub handle: *mut FfiNet,
    pub error_kind: i32,
    pub error_message: *const c_char,
}

impl Default for JoinResult {
    fn default() -> Self {
        Self {
            handle: std::ptr::null_mut(),
            error_kind: ERR_GENERIC,
            error_message: MSG_GENERIC.as_ptr(),
        }
    }
}

// ── 로깅 + panic hook ────────────────────────────────────────────────────────

static LOG_PATH: OnceLock<Mutex<Option<PathBuf>>> = OnceLock::new();
static PANIC_HOOK_INSTALLED: OnceLock<()> = OnceLock::new();

fn log_path() -> &'static Mutex<Option<PathBuf>> {
    LOG_PATH.get_or_init(|| Mutex::new(None))
}

fn write_log(msg: &str) {
    let path_opt = log_path().lock().ok().and_then(|g| g.clone());
    match path_opt {
        Some(path) => {
            if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(&path) {
                let _ = f.write_all(msg.as_bytes());
                if !msg.ends_with('\n') {
                    let _ = f.write_all(b"\n");
                }
            } else {
                eprintln!("{msg}");
            }
        }
        None => eprintln!("{msg}"),
    }
}

fn install_panic_hook_once() {
    PANIC_HOOK_INSTALLED.get_or_init(|| {
        panic::set_hook(Box::new(|info| {
            let bt = std::backtrace::Backtrace::force_capture();
            let msg = format!("[panic] {info}\nbacktrace:\n{bt}\n");
            write_log(&msg);
        }));
    });
}

/// catch_unwind으로 panic을 FFI 경계 안에서 잡는다. panic 시 R::default()를 반환하고
/// panic 메시지/backtrace는 panic hook이 로그 파일에 기록한다.
fn ffi_call<R: Default>(f: impl FnOnce() -> R) -> R {
    install_panic_hook_once();
    match panic::catch_unwind(AssertUnwindSafe(f)) {
        Ok(v) => v,
        Err(_) => {
            write_log("[ffi_call] panic caught at FFI boundary; returning default\n");
            R::default()
        }
    }
}

// ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

fn from_cstr(ptr: *const c_char) -> String {
    if ptr.is_null() {
        return String::new();
    }
    unsafe { CStr::from_ptr(ptr).to_string_lossy().into_owned() }
}

// ── FFI 함수 ─────────────────────────────────────────────────────────────────

/// native 로그 파일 경로를 설정한다. Unity persistentDataPath 안의 절대 경로를 권장.
/// 빈 문자열을 넘기면 로깅이 해제되고 stderr로 떨어진다.
#[unsafe(no_mangle)]
pub extern "C" fn cv_set_log_path(path: *const c_char) {
    install_panic_hook_once();
    let s = from_cstr(path);
    if let Ok(mut guard) = log_path().lock() {
        *guard = if s.is_empty() { None } else { Some(PathBuf::from(s)) };
    }
    write_log("[cv_set_log_path] 로그 파일 활성화\n");
}

/// P2P 네트워크에 참가한다.
///
/// - `udp_port == 0` → MidServer
/// - `udp_port > 0`  → ArClient { udp_port }
///
/// 결과는 out_result에 채워서 반환한다 (struct return ABI 의존 제거).
/// 성공 시 out_result.handle != null, 실패 시 handle == null + error_kind/message.
/// 반환된 핸들은 반드시 cv_net_free로 해제해야 한다.
#[unsafe(no_mangle)]
pub extern "C" fn cv_join(
    net_id: *const c_char,
    pw: *const c_char,
    name: *const c_char,
    udp_port: u16,
    out_result: *mut JoinResult,
) {
    if out_result.is_null() {
        return;
    }
    let result = ffi_call(|| join_inner(net_id, pw, name, udp_port));
    unsafe { *out_result = result; }
}

fn join_inner(
    net_id: *const c_char,
    pw: *const c_char,
    name: *const c_char,
    udp_port: u16,
) -> JoinResult {
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
            write_log(&format!("[cv_join] tokio runtime 생성 실패: {e}\n"));
            return JoinResult::default();
        }
    };

    match rt.block_on(p2p_core::join_as_client(JoinForm {
        net_id: NetId(net_id),
        pw: Password(pw),
        my_name: name,
        peer_type,
    })) {
        Ok(net) => JoinResult {
            handle: Box::into_raw(Box::new(FfiNet { rt, net })),
            error_kind: ERR_OK,
            error_message: std::ptr::null(),
        },
        Err(e) => {
            let msg = e.to_string();
            let (kind, c_msg) = if msg.contains("같은 이름") {
                (ERR_NAME_CONFLICT, MSG_NAME_CONFLICT.as_ptr())
            } else {
                write_log(&format!("[cv_join] 네트워크 참가 실패: {e}\n"));
                (ERR_GENERIC, MSG_GENERIC.as_ptr())
            };
            JoinResult {
                handle: std::ptr::null_mut(),
                error_kind: kind,
                error_message: c_msg,
            }
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_net_free(net: *mut FfiNet) {
    ffi_call(|| {
        if !net.is_null() {
            unsafe { drop(Box::from_raw(net)); }
        }
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_get_peers_json(net: *mut FfiNet) -> *mut c_char {
    ffi_call(|| {
        if net.is_null() {
            return std::ptr::null_mut();
        }
        let net = unsafe { &*net };
        let peers = net.net.get_peers();
        let json = match serde_json::to_string(&peers) {
            Ok(j) => j,
            Err(e) => {
                write_log(&format!("[cv_get_peers_json] 직렬화 실패: {e}\n"));
                return std::ptr::null_mut();
            }
        };
        match CString::new(json) {
            Ok(s) => s.into_raw(),
            Err(_) => std::ptr::null_mut(),
        }
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_string_free(s: *mut c_char) {
    ffi_call(|| {
        if !s.is_null() {
            unsafe { drop(CString::from_raw(s)); }
        }
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_connect_udp(
    net: *mut FfiNet,
    addr_json: *const c_char,
) -> *mut FfiConn {
    ffi_call(|| {
        if net.is_null() || addr_json.is_null() {
            return std::ptr::null_mut();
        }
        let net = unsafe { &*net };
        let addr: p2p_core::NodeAddr = match serde_json::from_str(&from_cstr(addr_json)) {
            Ok(a) => a,
            Err(e) => {
                write_log(&format!("[cv_connect_udp] addr 역직렬화 실패: {e}\n"));
                return std::ptr::null_mut();
            }
        };
        match net.rt.block_on(net.net.connect_udp(addr)) {
            Ok(conn) => Box::into_raw(Box::new(FfiConn { rt: net.rt.clone(), conn })),
            Err(e) => {
                write_log(&format!("[cv_connect_udp] 연결 실패: {e}\n"));
                std::ptr::null_mut()
            }
        }
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_conn_send(
    conn: *mut FfiConn,
    data: *const u8,
    len: u32,
) -> i32 {
    ffi_call(|| {
        if conn.is_null() || data.is_null() {
            return 0;
        }
        let conn = unsafe { &*conn };
        let bytes = unsafe { std::slice::from_raw_parts(data, len as usize) };
        match conn.rt.block_on(conn.conn.send(bytes)) {
            Ok(_) => 1,
            Err(e) => {
                write_log(&format!("[cv_conn_send] 전송 실패: {e}\n"));
                0
            }
        }
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_conn_recv(
    conn: *mut FfiConn,
    out: *mut u8,
    out_len: u32,
) -> i32 {
    // -1 = 실패. R::default()는 0이라 직접 처리.
    install_panic_hook_once();
    match panic::catch_unwind(AssertUnwindSafe(|| {
        if conn.is_null() || out.is_null() {
            return -1i32;
        }
        let conn = unsafe { &*conn };
        match conn.rt.block_on(conn.conn.recv()) {
            Ok(bytes) => {
                let n = bytes.len().min(out_len as usize);
                unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), out, n); }
                n as i32
            }
            Err(e) => {
                write_log(&format!("[cv_conn_recv] 수신 실패: {e}\n"));
                -1
            }
        }
    })) {
        Ok(v) => v,
        Err(_) => {
            write_log("[cv_conn_recv] panic caught at FFI boundary\n");
            -1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_conn_free(conn: *mut FfiConn) {
    ffi_call(|| {
        if !conn.is_null() {
            unsafe { drop(Box::from_raw(conn)); }
        }
    })
}

#[unsafe(no_mangle)]
pub extern "C" fn cv_request_file(
    net: *mut FfiNet,
    addr_json: *const c_char,
    path: *const c_char,
    out: *mut u8,
    out_len: u32,
) -> i32 {
    install_panic_hook_once();
    match panic::catch_unwind(AssertUnwindSafe(|| {
        if net.is_null() || addr_json.is_null() || path.is_null() || out.is_null() {
            return -1i32;
        }
        let net = unsafe { &*net };
        let addr: p2p_core::NodeAddr = match serde_json::from_str(&from_cstr(addr_json)) {
            Ok(a) => a,
            Err(e) => {
                write_log(&format!("[cv_request_file] addr 역직렬화 실패: {e}\n"));
                return -1;
            }
        };
        let path = from_cstr(path);
        match net.rt.block_on(net.net.request_file(addr, &path)) {
            Ok(bytes) => {
                let n = bytes.len().min(out_len as usize);
                unsafe { std::ptr::copy_nonoverlapping(bytes.as_ptr(), out, n); }
                n as i32
            }
            Err(e) => {
                write_log(&format!("[cv_request_file] 요청 실패 ({path}): {e}\n"));
                -1
            }
        }
    })) {
        Ok(v) => v,
        Err(_) => {
            write_log("[cv_request_file] panic caught at FFI boundary\n");
            -1
        }
    }
}
