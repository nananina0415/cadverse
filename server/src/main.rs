mod utils;
mod net;
mod sim;
mod watchdog;


const MAX_NAME_BYTES: usize = 64;

#[repr(usize)]
pub enum UIMenu {
    Exit            = 0,
    StartSimulation = 1,
    StopSimulation  = 2,
    EnterSimulation = 3,
    ShowGroupInfo   = 4,
    WrongInput,
}

impl From<usize> for UIMenu {
    fn from(v: usize) -> UIMenu {
        match v {
            0 => UIMenu::Exit,
            1 => UIMenu::StartSimulation,
            2 => UIMenu::StopSimulation,
            3 => UIMenu::EnterSimulation,
            4 => UIMenu::ShowGroupInfo,
            _ => UIMenu::WrongInput,
        }
    }
}

use net::{NetSetting, NetThread};
use utils::{TripleBuffer, input};
use sim::{UserIn, SimOut, SimThread, SimIoBuf};
use UIMenu::*;

fn main() {
    printsh!("사용자 이름: ");
    let name = input::<String>();

    printsh!("그룹 이름: ");
    let net_id = input::<String>();

    let password = format!("{:06}", rand::Rng::gen_range(&mut rand::thread_rng(), 0..1_000_000));
    println!("그룹 비밀번호: {password}");

    let net_setting = NetSetting {
        net_id,
        password,
        name,
        peer_type: p2p_core::PeerType::MidServer,
    };

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

    let mut sim_io = Some(SimIoBuf {
        userin_r,
        userin_swap,
        simout_w,
        simout_swap,
    });
    
    // 서버 스레드 실행
    let net = NetThread::new(&net_setting, userin_w, simout_r);

    let mut sim: Option<SimThread> = None;

    // 사용자 입력 루프
    loop {
        println!("1. 시뮬레이션 시작  2. 시뮬레이션 종료  3. 시뮬레이션 입장  4. 그룹 정보  0. 종료");
        printsh!("> ");
        match input::<usize>().into() {
            StartSimulation => {
                if let Some(io) = sim_io.take() {
                    setup_python();
                    printsh!("시뮬레이션 데이터가 있는 폴더: ");
                    let sim_folder = match std::path::absolute(input::<std::path::PathBuf>()) {
                        Ok(p) => p,
                        Err(e) => { println!("폴더 경로 오류: {e}"); continue; }
                    };
                    println!("시뮬레이션을 시작합니다. ({})", sim_folder.display());
                    match SimThread::new(sim_folder.clone(), io) {
                        Ok(s) => {
                            sim = Some(s);
                            if let Err(e) = net.notice_sim_online(sim_folder) {
                                println!("시뮬레이션 온라인 알림 실패: {e}");
                            }
                        }
                        Err((e, io)) => {
                            println!("시뮬레이션 시작 실패: {e}");
                            sim_io = Some(io);
                        }
                    }
                    println!("시뮬레이션이 시작되었습니다.");
                } else {
                    println!("이미 시뮬레이션이 실행 중입니다.");
                }
            }
            StopSimulation => {
                if let Some(s) = sim.take() {
                    sim_io = Some(s.stop());
                    if let Err(e) = net.notice_sim_offline() {
                        println!("시뮬레이션 오프라인 알림 실패: {e}");
                    }
                }
                else {
                    println!("실행 중인 시뮬레이션이 없습니다.");
                }
                println!("시뮬레이션이 종료되었습니다.");
            }
            EnterSimulation => {
                show_group_info(&net_setting, &net.peer_list()); // 나중에 현재 시뮬 실행중인 사용자만 보일것.
                printsh!("어떤 그룹원의 시뮬레이션에 참가하시겠습니까?: ");
                let name = input::<String>();
                if let Some(addr) = net.sim_info(&name) {
                    show_qr(format!("{addr:?}"));
                } else {
                    println!("그룹원이 존재하지 않거나 시뮬레이션이 실행 중이지 않습니다");
                    continue;
                }
            }
            ShowGroupInfo => {
                show_group_info(&net_setting, &net.peer_list());
            }
            Exit => {
                break;
            }
            WrongInput => {
                // 보이자마자 리프레시될텐데, 일단 그냥 둬.
                println!("잘못된 입력입니다.");
            }
        }
    }
}


/*
    Python::with_gil(|py| {
        let simulator = py.import("simulator").expect("simulator 패키지를 찾을 수 없음");
        let result: String = simulator
            .call_method0("hello")
            .expect("hello() 호출 실패")
            .extract()
            .expect("반환값 추출 실패");
        println!("{}", result);
    });
*/


fn show_qr(data: String) {
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
        let inches = cm / 2.54;
        (inches * dpi) as u32
    }

    std::thread::spawn(move || {
        let dpi = get_system_dpi();
        let target_size_px = cm_to_pixels(QR_SIZE_CM, dpi);

        let code = qrcode::QrCode::with_error_correction_level(data.as_bytes(), qrcode::EcLevel::M).unwrap();
        let qr_modules = code.render::<char>()
            .quiet_zone(false)
            .module_dimensions(1, 1)
            .build();

        let qr_lines: Vec<&str> = qr_modules.lines().collect();
        let qr_module_count = qr_lines.first().map(|l| l.chars().count()).unwrap_or(0);

        let module_size = (target_size_px as f32 / qr_module_count as f32).ceil() as usize;
        let module_size = module_size.max(1);

        let qr_size = module_size * qr_module_count;
        let margin = module_size * 2;
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

        let title = format!("CADverse QR - {} ({:.1}cm)", data, QR_SIZE_CM);
        let mut window = match minifb::Window::new(
            &title,
            window_size, window_size,
            minifb::WindowOptions {
                scale: minifb::Scale::X1,
                scale_mode: minifb::ScaleMode::Center,
                resize: false,
                ..minifb::WindowOptions::default()
            },
        ) {
            Ok(w) => w,
            Err(e) => { eprintln!("QR 창 생성 실패: {e}"); return; }
        };
        window.set_target_fps(30);
        while window.is_open() && !window.is_key_down(minifb::Key::Escape) {
            window.update_with_buffer(&buffer, window_size, window_size).unwrap_or_else(|e| {
                eprintln!("QR 버퍼 업데이트 오류: {e}");
            });
        }
    });
}


fn show_group_info(setting: &NetSetting, peers: &[p2p_core::PeerInfo]) {
    println!("그룹명: {}  사용자명: {}  비밀번호: {}", setting.net_id, setting.name, setting.password);

    let group_peers: Vec<_> = peers.iter()
        .filter(|p| !matches!(p.peer_type, p2p_core::PeerType::ArClient { .. }))
        .collect();

    println!("=== 그룹원 목록 ({}) ===", group_peers.len());
    for p in group_peers {
        let sim = if matches!(p.peer_type, p2p_core::PeerType::SimServer) { " [시뮬 실행중]" } else { "" };
        println!("  {}{}", p.name, sim);
    }

}

pub fn setup_python() {
    #[cfg(debug_assertions)]
    {
        let conda_prefix = std::env::var("CONDA_PREFIX")
            .expect("CONDA_PREFIX not set. Activate the cadverse environment first.");
        unsafe {
            std::env::set_var("PYTHONHOME", &conda_prefix);
            std::env::set_var("PYTHONPATH", format!("{}/Lib/site-packages", conda_prefix));
        }
    }

    #[cfg(not(debug_assertions))]
    {
        let exe_dir = std::env::current_exe()
            .unwrap()
            .parent()
            .unwrap()
            .to_path_buf();
        let python_env = exe_dir.join("python_env");
        if !python_env.exists() {
            let bundle = exe_dir.join("python_env.tar.gz");
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