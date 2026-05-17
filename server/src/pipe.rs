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
}

#[derive(Debug, Serialize, Clone, PartialEq)]
pub struct MemberStatus {
    pub name: String,
    pub is_me: bool,
    pub server: bool,
    pub client: bool,
    pub sim: bool,
}

#[derive(Debug, Serialize, Clone, PartialEq, Default)]
pub struct StatusMsg {
    pub sim_running: bool,
    pub paused: bool,
    pub reloading: bool,
    pub extracting: bool,
    pub password: String,
    pub members: Vec<MemberStatus>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sim_error: Option<String>,
}

pub fn start(cmd_tx: mpsc::Sender<PipeCmd>, status_rx: watch::Receiver<StatusMsg>) {
    // 플러그인→서버: stdin에서 JSON 줄 읽기 (blocking)
    std::thread::spawn(move || {
        let reader = std::io::BufReader::new(std::io::stdin());
        for line in reader.lines() {
            let Ok(l) = line else { break };
            let trimmed = l.trim().to_string();
            if trimmed.is_empty() { continue; }
            match serde_json::from_str::<PipeCmd>(&trimmed) {
                Ok(cmd) => { let _ = cmd_tx.send(cmd); }
                Err(_) => {}
            }
        }
    });

    // 서버→플러그인: 상태 변화 감지 후 stdout에 JSON 줄 쓰기
    std::thread::spawn(move || {
        let mut stdout = std::io::stdout();
        let mut last = StatusMsg::default();
        loop {
            std::thread::sleep(std::time::Duration::from_millis(50));
            let current = status_rx.borrow().clone();
            if current == last { continue; }
            last = current.clone();
            let json = match serde_json::to_string(&current) {
                Ok(j) => j + "\n",
                Err(_) => continue,
            };
            if stdout.write_all(json.as_bytes()).is_err() { break; }
            let _ = stdout.flush();
        }
    });
}
