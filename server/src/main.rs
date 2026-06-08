mod utils;
mod net;
mod sim;
mod watchdog;
mod pipe;

use std::sync::{Arc, Mutex, mpsc, atomic::Ordering};
use std::time::Duration;
use sha2::{Sha256, Digest};

/// 모델 폴더의 metadata.json SHA256(앞 16자 hex). 파일 못 읽으면 빈 문자열.
fn compute_model_hash(model_path: &std::path::Path) -> String {
    let p = model_path.join("metadata.json");
    match std::fs::read(&p) {
        Ok(bytes) => {
            let h = Sha256::digest(&bytes);
            format!("{:x}", h)[..16].to_string()
        }
        Err(_) => String::new(),
    }
}

use net::{NetSetting, NetThread};
use utils::TripleBuffer;
use sim::{UserIn, SimFrame, SimManager, SimIoBuf};
use pipe::{PipeCmd, StatusMsg, MemberStatus};

struct AppState {
    username:       String,
    password:       String,
    net:            Option<NetThread>,
    sim_manager:    Option<SimManager>,
    extracting:     bool,
    importing:      bool,
    import_error:   Option<String>,
    net_error:      Option<String>,
    f3z_done_rx:    Option<mpsc::Receiver<String>>,
    f3z_ready_path: Option<String>,
}

fn exe_dir() -> std::path::PathBuf {
    std::env::current_exe()
        .expect("실행 파일 경로 획득 실패")
        .parent()
        .expect("실행 파일 부모 디렉토리 획득 실패")
        .to_path_buf()
}

fn main() {
    // 패닉 정보 + 백트레이스를 panic.log와 stderr 둘 다에 출력.
    // exe_dir()는 hook 밖에서 캡쳐 (hook 안에서 expect가 또 패닉하면 무한 루프).
    // 주의: Rust 1.78+ unsafe precondition 패닉은 non-unwinding이라 이 hook을 건너뛸 수 있다.
    //       그래도 일반 panic은 모두 잡힌다.
    let panic_log = exe_dir().join("panic.log");
    std::panic::set_hook(Box::new(move |info| {
        let bt = std::backtrace::Backtrace::force_capture();
        let msg = format!("[PANIC]\n{info}\n[BACKTRACE]\n{bt}\n");
        let _ = std::fs::write(&panic_log, &msg);
        eprint!("{msg}");
    }));

    setup_python();
    pyo3::prepare_freethreaded_python();

    let (cmd_tx, cmd_rx) = mpsc::channel::<PipeCmd>();
    let (status_tx, status_rx) = tokio::sync::watch::channel(StatusMsg::default());
    let (log_tx, log_rx) = mpsc::channel::<String>();

    pipe::start(cmd_tx, status_rx, log_rx);

    let (userin_r, userin_w, userin_swap) = TripleBuffer::new([
        Vec::<UserIn>::with_capacity(32),
        Vec::<UserIn>::with_capacity(32),
        Vec::<UserIn>::with_capacity(32),
    ]);
    // simout은 String을 포함한 SimOut을 reader가 직렬화 중에 침범당하는 race가
    // 자체 구현에서 발견돼, 검증된 triple_buffer crate으로 교체.
    let (simout_w, simout_r) = triple_buffer::triple_buffer(&SimFrame::default());

    let sim_io_buf = SimIoBuf { userin_r, userin_swap, simout_w };

    let mut state = AppState {
        username:       String::new(),
        password:       String::new(),
        net:            None,
        sim_manager:    Some(SimManager::new(sim_io_buf)),
        extracting:     false,
        importing:      false,
        import_error:   None,
        net_error:      None,
        f3z_done_rx:    None,
        f3z_ready_path: None,
    };

    let shared_status: Arc<Mutex<StatusMsg>> = Arc::new(Mutex::new(StatusMsg::default()));

    let net_userin_w = userin_w;
    let net_simout_r = simout_r;
    let mut net_userin_w_opt = Some(net_userin_w);
    let mut net_simout_r_opt = Some(net_simout_r);

    let mut last_status = StatusMsg::default();

    let push_status = {
        let shared = shared_status.clone();
        move |state: &AppState, last: &mut StatusMsg, tx: &tokio::sync::watch::Sender<StatusMsg>| {
            let s = build_status(state);
            if s != *last {
                *last = s.clone();
                *shared.lock().unwrap() = s.clone();
                let _ = tx.send(s);
            }
        }
    };

    loop {
        // f3z 백그라운드 다운로드 완료 체크
        if let Some(rx) = state.f3z_done_rx.as_ref() {
            if let Ok(path) = rx.try_recv() {
                eprintln!("[f3z] 다운로드 완료: {path}");
                state.f3z_done_rx = None;
                state.f3z_ready_path = Some(path);
                push_status(&state, &mut last_status, &status_tx);
                state.f3z_ready_path = None;
            }
        }

        let cmd = cmd_rx.recv_timeout(Duration::from_millis(500));
        if let Err(mpsc::RecvTimeoutError::Disconnected) = cmd {
            eprintln!("[main] 커맨드 채널 끊김 → 종료");
            break;
        }
        if let Err(mpsc::RecvTimeoutError::Timeout) = cmd {
            push_status(&state, &mut last_status, &status_tx);
            continue;
        }
        eprintln!("[cmd] {:?}", cmd);
        match cmd {
            Ok(PipeCmd::Init { username, group, password, mode }) => {
                if net_userin_w_opt.is_none() {
                    eprintln!("[init] 이미 초기화됨, 무시");
                    push_status(&state, &mut last_status, &status_tx);
                    continue;
                }
                let pw = if mode == "create" {
                    format!("{:06}", rand::Rng::gen_range(&mut rand::thread_rng(), 0..1_000_000))
                } else {
                    password
                };

                let net_setting = NetSetting {
                    net_id:    group.clone(),
                    password:  pw.clone(),
                    name:      username.clone(),
                    peer_type: p2p_core::PeerType::MidServer,
                };
                eprintln!("[init] user={username} group={group} mode={mode}");

                match NetThread::new(
                    &net_setting,
                    net_userin_w_opt.take().expect("userin_w 이미 소비됨"),
                    net_simout_r_opt.take().expect("simout_r 이미 소비됨"),
                    log_tx.clone(),
                ) {
                    Ok(net) => {
                        eprintln!("[init] NetThread 생성 완료");
                        state.username = username;
                        state.password = pw;
                        state.net      = Some(net);
                        state.net_error = None;
                    }
                    Err(e) => {
                        eprintln!("[init] NetThread 생성 실패: {e}");
                        state.net_error = Some(e.to_string());
                    }
                }
                push_status(&state, &mut last_status, &status_tx);
            }

            Ok(PipeCmd::Resume { model_path }) => {
                eprintln!("[resume] model_path={model_path}");
                if state.net.is_none() {
                    eprintln!("[resume] net 없음, 무시");
                    push_status(&state, &mut last_status, &status_tx);
                    continue;
                }
                if let Some(mgr) = state.sim_manager.as_ref() {
                    // 항상 자기 모델로 시작 — 기존 sim(특히 직전 import sim)을 먼저 정지해
                    // start 실패해도 import sim이 계속 돌지 않게 한다.
                    mgr.stop();
                    push_status(&state, &mut last_status, &status_tx);
                    let path = std::path::Path::new(&model_path);
                    match mgr.start(path) {
                        Ok(()) => {
                            eprintln!("[resume] 시뮬 시작 완료");
                            if let Some(net) = state.net.as_ref() {
                                net.set_model_hash(compute_model_hash(path));
                                let _ = net.notice_sim_online(path.to_path_buf());
                            }
                        }
                        Err(e) => eprintln!("[resume] 시뮬 시작 실패: {e}"),
                    }
                }
                push_status(&state, &mut last_status, &status_tx);
            }

            Ok(PipeCmd::Reload { model_path }) => {
                eprintln!("[reload] model_path={model_path}");
                if let Some(mgr) = state.sim_manager.as_ref() {
                    mgr.reloading.store(true, Ordering::Relaxed);
                    push_status(&state, &mut last_status, &status_tx);
                    let path = std::path::Path::new(&model_path);
                    match mgr.start(path) {
                        Ok(()) => eprintln!("[reload] 완료"),
                        Err(e) => eprintln!("[reload] 실패: {e}"),
                    }
                    mgr.reloading.store(false, Ordering::Relaxed);
                }
                push_status(&state, &mut last_status, &status_tx);
            }

            Ok(PipeCmd::Pause) => {
                eprintln!("[pause] 시뮬 정지 요청");
                if let Some(mgr) = state.sim_manager.as_ref() {
                    mgr.stop();
                    if let Some(net) = state.net.as_ref() {
                        let _ = net.notice_sim_offline();
                    }
                }
                push_status(&state, &mut last_status, &status_tx);
            }

            Ok(PipeCmd::QrShow) => {
                if let Some(net) = state.net.as_ref() {
                    let is_running = state.sim_manager.as_ref()
                        .map(|m| m.is_running())
                        .unwrap_or(false);
                    if is_running {
                        show_qr(net.my_node_id());
                    }
                }
            }

            Ok(PipeCmd::QrHide) => {}

            Ok(PipeCmd::Import { username, import_root }) => {
                eprintln!("[import] username={username} import_root={import_root}");
                if state.net.is_none() {
                    eprintln!("[import] net 없음, 무시");
                    push_status(&state, &mut last_status, &status_tx);
                    continue;
                }
                state.importing    = true;
                state.import_error = None;
                push_status(&state, &mut last_status, &status_tx);

                let result = state.net.as_ref().unwrap()
                    .import_remote_model(&username, std::path::PathBuf::from(&import_root));

                state.importing = false;
                match result {
                    Ok((path, f3z_info)) => {
                        eprintln!("[import] 완료: {}", path.display());

                        // 가져온 모델로 시뮬 교체 — 기존 시뮬 정지 + 새 path로 재시작.
                        // 이후 사용자가 자기 Fusion 모델을 저장하면 documentSaved → reload로
                        // 자기 모델로 자연스럽게 돌아온다.
                        if let Some(mgr) = state.sim_manager.as_ref() {
                            mgr.stop();
                            mgr.reloading.store(true, Ordering::Relaxed);
                            push_status(&state, &mut last_status, &status_tx);

                            match mgr.start(&path) {
                                Ok(()) => {
                                    eprintln!("[import] 시뮬 교체 완료");
                                    if let Some(net) = state.net.as_ref() {
                                        net.set_model_hash(compute_model_hash(&path));
                                        let _ = net.notice_sim_online(path.clone());
                                    }
                                }
                                Err(e) => eprintln!("[import] 시뮬 교체 실패: {e}"),
                            }
                            mgr.reloading.store(false, Ordering::Relaxed);
                        }

                        // f3z 백그라운드 다운로드 시작
                        if let Some((addr, hash)) = f3z_info {
                            let f3z_path = std::path::PathBuf::from(&import_root)
                                .join(format!("{}.f3z", hash));
                            let (tx, rx) = mpsc::channel();
                            state.f3z_done_rx = Some(rx);
                            if let Some(net) = state.net.as_ref() {
                                net.download_f3z_background(addr, f3z_path, tx);
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("[import] 실패: {e}");
                        state.import_error = Some(e.to_string());
                    }
                }
                push_status(&state, &mut last_status, &status_tx);
            }

            _ => {}
        }
    }
}

fn build_status(state: &AppState) -> StatusMsg {
    let (sim_running, reloading, sim_error) = match state.sim_manager.as_ref() {
        Some(m) => (m.is_running(), m.is_reloading(), m.take_error()),
        None    => (false, false, None),
    };

    let mut members: Vec<MemberStatus> = vec![MemberStatus {
        name:   state.username.clone(),
        is_me:  true,
        server: state.net.is_some(),
        client: false,
        sim:    sim_running,
        qr:     None,
    }];

    if let Some(net) = state.net.as_ref() {
        for peer in net.peer_list() {
            let is_ar = matches!(peer.peer_type, p2p_core::PeerType::ArClient { .. });
            let is_sim = !is_ar && matches!(peer.peer_type, p2p_core::PeerType::SimServer);
            if let Some(existing) = members.iter_mut().find(|m| m.name == peer.name) {
                if is_ar { existing.client = true; }
                else {
                    existing.server = true;
                    if is_sim {
                        existing.sim = true;
                        existing.qr = addr_to_qr_rows(&peer.addr);
                    }
                }
                continue;
            }
            members.push(MemberStatus {
                name:   peer.name.clone(),
                is_me:  false,
                server: !is_ar,
                client: is_ar,
                sim:    is_sim,
                qr:     if is_sim { addr_to_qr_rows(&peer.addr) } else { None },
            });
        }
    }

    StatusMsg {
        sim_running,
        paused: false,
        reloading,
        extracting:     state.extracting,
        importing:      state.importing,
        password:       state.password.clone(),
        members,
        sim_error,
        import_error:   state.import_error.clone(),
        net_error:      state.net_error.clone(),
        f3z_ready_path: state.f3z_ready_path.clone(),
    }
}

fn show_qr(data: Vec<u8>) {
    const QR_SIZE_CM: f32 = 5.0;

    #[cfg(target_os = "windows")]
    fn get_system_dpi() -> f32 {
        use std::ptr;
        #[link(name = "user32")]
        unsafe extern "system" {
            fn GetDC(hwnd: *mut std::ffi::c_void) -> *mut std::ffi::c_void;
            fn GetDeviceCaps(hdc: *mut std::ffi::c_void, index: i32) -> i32;
            fn ReleaseDC(hwnd: *mut std::ffi::c_void, hdc: *mut std::ffi::c_void) -> i32;
        }
        const LOGPIXELSX: i32 = 88;
        unsafe {
            let hdc = GetDC(ptr::null_mut());
            if hdc.is_null() { return 96.0; }
            let dpi = GetDeviceCaps(hdc, LOGPIXELSX) as f32;
            ReleaseDC(ptr::null_mut(), hdc);
            if dpi > 0.0 { dpi } else { 96.0 }
        }
    }

    #[cfg(not(target_os = "windows"))]
    fn get_system_dpi() -> f32 { 96.0 }

    fn cm_to_pixels(cm: f32, dpi: f32) -> u32 {
        ((cm / 2.54) * dpi) as u32
    }

    #[cfg(windows)]
    fn com_init() {
        #[link(name = "ole32")]
        unsafe extern "system" { fn CoInitializeEx(p: *mut std::ffi::c_void, dw: u32) -> i32; }
        unsafe { let _ = CoInitializeEx(std::ptr::null_mut(), 0x2); }
    }

    #[cfg(windows)]
    fn set_topmost(hwnd: *mut std::ffi::c_void) {
        #[link(name = "user32")]
        unsafe extern "system" {
            fn SetWindowPos(hwnd: *mut std::ffi::c_void, insert: *mut std::ffi::c_void,
                            x: i32, y: i32, cx: i32, cy: i32, flags: u32) -> i32;
        }
        unsafe { let _ = SetWindowPos(hwnd, -1isize as *mut _, 0, 0, 0, 0, 0x0003); }
    }

    std::thread::spawn(move || {
        #[cfg(windows)] com_init();
        let dpi = get_system_dpi();
        let target_size_px = cm_to_pixels(QR_SIZE_CM, dpi);

        let Ok(code) = qrcode::QrCode::with_error_correction_level(&data, qrcode::EcLevel::M) else { return };
        let qr_modules = code.render::<char>()
            .quiet_zone(false)
            .module_dimensions(1, 1)
            .build();

        let qr_lines: Vec<&str> = qr_modules.lines().collect();
        let qr_module_count = qr_lines.first().map(|l| l.chars().count()).unwrap_or(0);
        let module_size = ((target_size_px as f32 / qr_module_count as f32).ceil() as usize).max(1);
        let qr_size     = module_size * qr_module_count;
        let margin      = module_size * 2;
        let window_size = qr_size + margin * 2;

        let mut buffer: Vec<u32> = vec![0xFFFFFFFF; window_size * window_size];
        for (y, line) in qr_lines.iter().enumerate() {
            for (x, ch) in line.chars().enumerate() {
                let color = if ch == '█' || ch == '#' { 0xFF000000u32 } else { 0xFFFFFFFFu32 };
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

        let title = format!("CADverse QR ({:.1}cm)", QR_SIZE_CM);
        let Ok(mut window) = minifb::Window::new(
            &title, window_size, window_size,
            minifb::WindowOptions { scale: minifb::Scale::X1, resize: false, ..Default::default() },
        ) else { return };
        #[cfg(windows)] set_topmost(window.get_window_handle());
        window.set_target_fps(30);
        while window.is_open() && !window.is_key_down(minifb::Key::Escape) {
            window.update_with_buffer(&buffer, window_size, window_size).unwrap_or(());
        }
    });
}

pub(crate) fn qr_path() -> std::path::PathBuf {
    exe_dir().join("local_sim_qr.txt")
}

fn addr_to_qr_rows(addr: &p2p_core::NodeAddr) -> Option<String> {
    let code = qrcode::QrCode::with_error_correction_level(addr.id.as_bytes(), qrcode::EcLevel::M).ok()?;
    let width = code.width();
    Some(code.to_colors()
        .chunks(width)
        .map(|row| row.iter().map(|c| if *c == qrcode::Color::Dark { '1' } else { '0' }).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n"))
}

pub(crate) fn save_local_sim_qr_txt(addr: &p2p_core::NodeAddr) {
    let Some(content) = addr_to_qr_rows(addr) else {
        eprintln!("[save_local_sim_qr_txt] QR 생성 실패");
        return;
    };
    let _ = std::fs::write(qr_path(), content);
}

pub fn setup_python() {
    #[cfg(debug_assertions)]
    {
        let conda_base = std::env::var("CONDA_BASE")
            .expect("CONDA_BASE not set. Run setup-dev-env.ps1 first.");
        let conda_env = format!("{}/envs/cadverse", conda_base);
        let current_path = std::env::var("PATH").unwrap_or_default();
        unsafe {
            std::env::set_var("PYTHONHOME", &conda_env);
            std::env::set_var("PYTHONPATH", format!("{}/Lib/site-packages", conda_env));
            std::env::set_var("CONDA_PREFIX", &conda_env);
            std::env::set_var("PATH", format!("{}/Library/bin;{}", conda_env, current_path));
        }
    }

    #[cfg(not(debug_assertions))]
    {
        // release 빌드: python_env unpack과 PATH 설정은 launcher(cad_plugin/CADverse.py)가
        // 처리한다. server 자체는 이미 풀려있다고 가정하고 PYTHONHOME / CONDA_PREFIX만 잡는다.
        // (DLL 로드는 OS가 main 진입 전에 끝내므로 PATH는 부모 프로세스가 설정해야 의미가 있다.)
        let python_env = exe_dir().join("python_env");
        assert!(
            python_env.exists(),
            "python_env not found next to executable. launcher가 unpack해야 한다 (CADverse.py 참고)."
        );
        unsafe {
            std::env::set_var("PYTHONHOME", &python_env);
            std::env::set_var("CONDA_PREFIX", &python_env);
        }
    }
}
