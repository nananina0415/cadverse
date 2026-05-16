mod utils;
mod net;
mod sim;
mod watchdog;
mod pipe;

use std::sync::{Arc, Mutex, mpsc};
use std::sync::atomic::Ordering;
use std::time::Duration;

use net::{NetSetting, NetThread};
use utils::TripleBuffer;
use sim::{UserIn, SimOut, SimThread, SimIoBuf};
use pipe::{PipeCmd, StatusMsg, MemberStatus};

struct AppState {
    username:   String,
    password:   String,
    model_dir:  std::path::PathBuf,
    net:        Option<NetThread>,
    sim:        Option<SimThread>,
    sim_io:     Option<SimIoBuf>,
    sim_error:  Option<String>,
    extracting: bool,
}

fn exe_dir() -> std::path::PathBuf {
    std::env::current_exe()
        .expect("실행 파일 경로 획득 실패")
        .parent()
        .expect("실행 파일 부모 디렉토리 획득 실패")
        .to_path_buf()
}

fn main() {
    let (cmd_tx, cmd_rx) = mpsc::channel::<PipeCmd>();
    let (status_tx, status_rx) = tokio::sync::watch::channel(StatusMsg::default());

    pipe::start(cmd_tx, status_rx);

    let (userin_r, userin_w, userin_swap) = TripleBuffer::new([
        Vec::<UserIn>::with_capacity(32),
        Vec::<UserIn>::with_capacity(32),
        Vec::<UserIn>::with_capacity(32),
    ]);
    let (simout_r, simout_w, simout_swap) = TripleBuffer::new([
        SimOut::default(),
        SimOut::default(),
        SimOut::default(),
    ]);

    let mut state = AppState {
        username:  String::new(),
        password:  String::new(),
        model_dir: std::path::PathBuf::new(),
        net:       None,
        sim:       None,
        sim_io:    Some(SimIoBuf { userin_r, userin_swap, simout_w, simout_swap }),
        sim_error:  None,
        extracting: false,
    };

    let shared_status: Arc<Mutex<StatusMsg>> = Arc::new(Mutex::new(StatusMsg::default()));

    let net_userin_w  = userin_w;
    let net_simout_r  = simout_r;
    let mut net_userin_w_opt  = Some(net_userin_w);
    let mut net_simout_r_opt  = Some(net_simout_r);

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
        let cmd = cmd_rx.recv_timeout(Duration::from_millis(500));
        if let Err(mpsc::RecvTimeoutError::Disconnected) = cmd { break; }
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

                #[cfg(debug_assertions)]
                let model_dir = exe_dir()
                    .parent().expect("target/debug 상위 없음")
                    .parent().expect("target 상위 없음")
                    .parent().expect("server 상위 없음")
                    .join("models").join(&username);
                #[cfg(not(debug_assertions))]
                let model_dir = exe_dir().join("models").join(&username);
                std::fs::create_dir_all(&model_dir).ok();
                eprintln!("[init] user={username} group={group} mode={mode} model_dir={}", model_dir.display());

                let net = NetThread::new(
                    &net_setting,
                    net_userin_w_opt.take().expect("userin_w 이미 소비됨"),
                    net_simout_r_opt.take().expect("simout_r 이미 소비됨"),
                );
                eprintln!("[init] NetThread 생성 완료");

                #[cfg(not(debug_assertions))]
                if !exe_dir().join("python_env").exists() {
                    eprintln!("[init] python_env 없음 → 압축 해제 시작");
                    state.extracting = true;
                    push_status(&state, &mut last_status, &status_tx);
                }

                setup_python();
                eprintln!("[init] setup_python 완료");

                state.extracting = false;
                state.username  = username;
                state.password  = pw;
                state.model_dir = model_dir;
                state.net       = Some(net);
                push_status(&state, &mut last_status, &status_tx);
            }

            Ok(PipeCmd::Pause) => {
                if let Some(s) = state.sim.take() {
                    eprintln!("[pause] 시뮬 정지 시작");
                    push_status(&state, &mut last_status, &status_tx);
                    let io = s.stop();
                    state.sim_io = Some(io);
                    eprintln!("[pause] 시뮬 정지 완료");
                    if let Some(net) = state.net.as_ref() {
                        let _ = net.notice_sim_offline();
                    }
                } else {
                    eprintln!("[pause] 실행 중인 시뮬 없음");
                    push_status(&state, &mut last_status, &status_tx);
                }
            }

            Ok(PipeCmd::Resume) => {
                push_status(&state, &mut last_status, &status_tx);
                if state.sim.is_none() {
                    let has_io  = state.sim_io.is_some();
                    let has_net = state.net.is_some();
                    eprintln!("[resume] 시뮬 시작 시도 (has_io={has_io} has_net={has_net})");
                    if let (Some(io), Some(net)) = (state.sim_io.take(), state.net.as_ref()) {
                        eprintln!("[resume] SimThread::new 호출 중...");
                        match SimThread::new(state.model_dir.clone(), io, status_tx.clone(), shared_status.clone()) {
                            Ok(s) => {
                                eprintln!("[resume] SimThread 생성 성공");
                                state.sim = Some(s);
                                push_status(&state, &mut last_status, &status_tx);
                                let _ = net.notice_sim_online(state.model_dir.clone());
                            }
                            Err((e, io)) => {
                                eprintln!("[resume] SimThread 생성 실패: {e}");
                                state.sim_io = Some(io);
                                state.sim_error = Some(e);
                                push_status(&state, &mut last_status, &status_tx);
                                state.sim_error = None;
                            }
                        }
                    } else {
                        eprintln!("[resume] io 또는 net 없어서 시작 불가");
                        push_status(&state, &mut last_status, &status_tx);
                    }
                } else {
                    eprintln!("[resume] 이미 시뮬 실행 중");
                    push_status(&state, &mut last_status, &status_tx);
                }
            }

            Ok(PipeCmd::QrShow) => {
                if let Some(net) = state.net.as_ref() {
                    if state.sim.is_some() {
                        show_qr(net.my_node_id());
                    }
                }
            }

            Ok(PipeCmd::QrHide) => {}

            _ => {}
        }
    }
}

fn build_status(state: &AppState) -> StatusMsg {
    let sim_running = state.sim.is_some();
    let reloading = state.sim.as_ref()
        .map(|s| s.reloading.load(Ordering::Relaxed))
        .unwrap_or(false);
    let sim_error = state.sim_error.clone();

    let mut members: Vec<MemberStatus> = vec![MemberStatus {
        name:   state.username.clone(),
        is_me:  true,
        server: state.net.is_some(),
        client: false,
        sim:    sim_running,
    }];

    if let Some(net) = state.net.as_ref() {
        for peer in net.peer_list() {
            let is_ar = matches!(peer.peer_type, p2p_core::PeerType::ArClient { .. });
            if let Some(existing) = members.iter_mut().find(|m| m.name == peer.name) {
                if is_ar { existing.client = true; }
                else {
                    existing.server = true;
                    if matches!(peer.peer_type, p2p_core::PeerType::SimServer) {
                        existing.sim = true;
                    }
                }
                continue;
            }
            members.push(MemberStatus {
                name:   peer.name.clone(),
                is_me:  false,
                server: !is_ar,
                client: is_ar,
                sim:    !is_ar && matches!(peer.peer_type, p2p_core::PeerType::SimServer),
            });
        }
    }

    StatusMsg {
        sim_running,
        paused: false,
        reloading,
        extracting: state.extracting,
        password: state.password.clone(),
        members,
        sim_error,
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

    std::thread::spawn(move || {
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
        let qr_size    = module_size * qr_module_count;
        let margin     = module_size * 2;
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
        window.set_target_fps(30);
        while window.is_open() && !window.is_key_down(minifb::Key::Escape) {
            window.update_with_buffer(&buffer, window_size, window_size).unwrap_or(());
        }
    });
}

pub(crate) fn qr_path() -> std::path::PathBuf {
    exe_dir().join("local_sim_qr.txt")
}

pub(crate) fn save_local_sim_qr_txt(addr: &p2p_core::NodeAddr) {
    let code = match qrcode::QrCode::with_error_correction_level(addr.id.as_bytes(), qrcode::EcLevel::M) {
        Ok(c) => c,
        Err(e) => { eprintln!("[save_local_sim_qr_txt] QR 생성 실패: {e}"); return; }
    };
    let width = code.width();
    let content = code.to_colors()
        .chunks(width)
        .map(|row| row.iter().map(|c| if *c == qrcode::Color::Dark { '1' } else { '0' }).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n");
    let _ = std::fs::write(qr_path(), content);
}

pub fn setup_python() {
    #[cfg(debug_assertions)]
    {
        let conda_base = std::env::var("CONDA_BASE")
            .expect("CONDA_BASE not set. Run setup-dev-env.ps1 first.");
        let conda_env = format!("{}/envs/cadverse", conda_base);
        unsafe {
            std::env::set_var("PYTHONHOME", &conda_env);
            std::env::set_var("PYTHONPATH", format!("{}/Lib/site-packages", conda_env));
            std::env::set_var("CONDA_PREFIX", &conda_env);
        }
    }

    #[cfg(not(debug_assertions))]
    {
        let python_env = exe_dir().join("python_env");
        if !python_env.exists() {
            let bundle = exe_dir().join("python_env.tar.gz");
            assert!(bundle.exists(), "python_env.tar.gz not found next to executable");
            std::fs::create_dir_all(&python_env).unwrap();
            let status = std::process::Command::new("tar")
                .args(["-xzf", bundle.to_str().unwrap(), "-C", python_env.to_str().unwrap()])
                .status()
                .expect("tar failed");
            assert!(status.success(), "Failed to unpack python_env.tar.gz");
        }
        unsafe { std::env::set_var("PYTHONHOME", &python_env) };
    }
}
