use std::sync::mpsc;
use std::io::{BufRead, Write};
use tokio::sync::watch;
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum PipeCmd {
    Init { username: String, group: String, password: String, mode: String },
    Resume { model_path: String },
    Reload  { model_path: String },
    Pause,
    QrShow,
    QrHide,
    Import { username: String, import_root: String },
}

#[derive(Debug, Serialize, Clone, PartialEq)]
pub struct MemberStatus {
    pub name: String,
    pub is_me: bool,
    pub server: bool,
    pub client: bool,
    pub sim: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub qr: Option<String>,
}

#[derive(Debug, Serialize, Clone, PartialEq, Default)]
pub struct StatusMsg {
    pub sim_running: bool,
    pub paused: bool,
    pub reloading: bool,
    pub extracting: bool,
    pub importing: bool,
    pub password: String,
    pub members: Vec<MemberStatus>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sim_error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub import_error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub net_error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub f3z_ready_path: Option<String>,
}

pub fn start(
    cmd_tx: mpsc::Sender<PipeCmd>,
    status_rx: watch::Receiver<StatusMsg>,
    log_rx: mpsc::Receiver<String>,
) {
    // 플러그인→서버: stdin에서 JSON 줄 읽기 (blocking)
    std::thread::spawn(move || {
        let reader = std::io::BufReader::new(std::io::stdin());
        for line in reader.lines() {
            let Ok(l) = line else {
                eprintln!("[pipe] stdin 끊김");
                break;
            };
            let trimmed = l.trim().to_string();
            if trimmed.is_empty() { continue; }
            match serde_json::from_str::<PipeCmd>(&trimmed) {
                Ok(cmd) => { let _ = cmd_tx.send(cmd); }
                Err(e) => eprintln!("[pipe] 파싱 오류: {e} | {trimmed}"),
            }
        }
        eprintln!("[pipe] stdin 스레드 종료");
    });

    // 서버→플러그인: 로그 이벤트 + 상태 변화를 stdout에 JSON 줄 쓰기
    std::thread::spawn(move || {
        let mut stdout = std::io::stdout();
        let mut last = StatusMsg::default();
        loop {
            // 로그 메시지 즉시 flush
            while let Ok(msg) = log_rx.try_recv() {
                let json = serde_json::json!({"log": msg}).to_string() + "\n";
                if stdout.write_all(json.as_bytes()).is_err() {
                    eprintln!("[pipe] stdout 끊김 (log)");
                    return;
                }
                let _ = stdout.flush();
            }

            std::thread::sleep(std::time::Duration::from_millis(50));
            let current = status_rx.borrow().clone();
            if current == last { continue; }
            last = current.clone();
            let json = match serde_json::to_string(&current) {
                Ok(j) => j + "\n",
                Err(_) => continue,
            };
            if stdout.write_all(json.as_bytes()).is_err() {
                eprintln!("[pipe] stdout 끊김 (status)");
                break;
            }
            let _ = stdout.flush();
        }
        eprintln!("[pipe] stdout 스레드 종료");
    });
}
