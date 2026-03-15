use s2s::{ServerName, ServerToServer};
use std::io;
use std::io::Write;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    print!("Enter your server name: ");
    std::io::stdout().flush()?;
    let name = io::stdin().lines().next().unwrap().unwrap();
    let port = 50505;
    let server_name = ServerName::new(&name)?;
    let s2s_service = ServerToServer::new(server_name, port)?;
    loop {
        println!("{:?}", s2s_service.get_server_list());
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
}
