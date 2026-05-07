# HTTP/3 → 단순 QUIC 파일 전송 교체 계획

## 개요
H3 (`h3`, `h3_iroh`) 를 제거하고, iroh QUIC uni stream으로 파일 요청/응답을 직접 구현.

프로토콜:
1. 클라 → `FILE_ALPN`으로 서버에 연결
2. 클라 → `open_uni` 로 경로 문자열 전송 (예: `/local_sim_qr.txt`)
3. 서버 → `open_uni` 로 파일 내용(바이트) 전송

---

## 변경 파일 목록

### 1. `p2p/core/Cargo.toml`
**제거:**
- `h3 = "0.0.8"`
- `http = "1"`
- `bytes = "1"`
- `tokio-util = "0.7"`
- `futures = "0.3"`

### 2. `p2p/core/src/h3_iroh.rs`
**파일 전체 삭제**

### 3. `p2p/core/src/lib.rs`
**제거:**
- `mod h3_iroh;`
- `serve_h3_response` 함수 전체
- `request_http` 함수 전체
- `P2PNet.http_rx` 필드
- `P2PNet.accept_http_conn` 메서드
- `HTTP_ALPN` 상수
- `accept_loop` 내 `HTTP_ALPN` 분기

**추가:**
```rust
const FILE_ALPN: &[u8] = b"cv-file/0";
```

`create_endpoint` alpns 목록에 `FILE_ALPN` 추가:
```rust
.alpns(vec![COORD_ALPN.to_vec(), DATA_ALPN.to_vec(), FILE_ALPN.to_vec()])
```

`P2PNet` 구조체에 `file_rx` 추가:
```rust
file_rx: Arc<tokio::sync::Mutex<mpsc::Receiver<iroh::endpoint::Connection>>>,
```

`join_p2p_net` / `join_as_client` 에 `file_tx`/`file_rx` 채널 생성 및 `accept_loop` 전달.

`accept_loop` 에 FILE_ALPN 분기 추가:
```rust
} else if alpn == FILE_ALPN {
    let _ = file_tx.send(conn).await;
}
```

`P2PNet` 에 두 메서드 추가:
```rust
// 서버용: 파일 요청 연결 수락
pub async fn accept_file_conn(&self) -> Option<iroh::endpoint::Connection> {
    self.file_rx.lock().await.recv().await
}

// 클라용: 파일 요청
pub async fn request_file(&self, addr: NodeAddr, path: &str) -> Result<Vec<u8>> {
    let conn = self.node.endpoint.connect(addr, FILE_ALPN).await?;
    let mut send = conn.open_uni().await?;
    send.write_all(path.as_bytes()).await?;
    send.finish()?;
    let mut recv = conn.accept_uni().await?;
    let data = recv.read_to_end(64 * 1024 * 1024).await?;
    Ok(data)
}
```

### 4. `server/src/net.rs`
**제거:**
- `p2p_core::serve_h3_response` 호출 및 관련 로직
- `[h3::serve]` 관련 로그

**변경:** `notice_sim_online` 내부의 HTTP acceptor 루프를 FILE acceptor 루프로 교체:
```rust
self.async_rt.spawn(async move {
    loop {
        let Some(conn) = net.accept_file_conn().await else { break };
        let folder = folder.clone();
        tokio::spawn(async move {
            if let Err(e) = serve_file(conn, &folder).await {
                println!("[file] serve error: {e}");
            }
        });
    }
});
```

**추가:** `serve_file` 함수:
```rust
async fn serve_file(conn: p2p_core::RawConn, folder: &std::path::Path) -> anyhow::Result<()> {
    let mut recv = conn.accept_uni().await?;
    let path_bytes = recv.read_to_end(1024).await?;
    let path = String::from_utf8(path_bytes)?;
    println!("[FILE] {path}");
    let file_path = if path == "/local_sim_qr.txt" {
        crate::qr_path()
    } else {
        folder.join(path.trim_start_matches('/'))
    };
    let data = std::fs::read(&file_path).unwrap_or_default();
    let mut send = conn.open_uni().await?;
    send.write_all(&data).await?;
    send.finish()?;
    Ok(())
}
```

> `p2p_core::RawConn` 은 `iroh::endpoint::Connection` 의 타입 별칭 — net.rs 가 내부 타입에 직접 의존하지 않도록.
> 또는 그냥 `iroh::endpoint::Connection` 을 직접 써도 무방.

### 5. `p2p/unity-ffi/src/lib.rs`
**변경:** `cv_request_http` → `cv_request_file` (함수명 변경, 내부 로직만 교체):
```rust
#[unsafe(no_mangle)]
pub extern "C" fn cv_request_file(
    net: *mut FfiNet,
    addr_json: *const c_char,
    path: *const c_char,
    out: *mut u8,
    out_len: u32,
) -> i32 {
    // ... (기존 cv_request_http 와 동일, request_http → request_file 만 변경)
    match net.rt.block_on(net.net.request_file(addr, &path)) { ... }
}
```

### 6. `client/Assets/Script/P2PNet.cs`
**변경:**
```csharp
// 기존
[DllImport(Lib)] static extern int cv_request_http(...);

// 변경
[DllImport(Lib)] static extern int cv_request_file(...);
```

`RequestHttp` 메서드 내부에서 `cv_request_http` → `cv_request_file` 호출로 변경.
메서드 이름(`RequestHttp`)은 유지 → ARScene.cs 수정 불필요.

---

## 변경 불필요한 파일
- `client/Assets/Script/ARScene.cs` — `net.RequestHttp(...)` 호출 그대로 사용 가능
- `client/Assets/Script/AppManager.cs`
- `server/src/main.rs`
- `server/src/sim.rs`

---

## 빌드 순서
1. `p2p/core` 빌드 확인
2. `server` 빌드 확인
3. `p2p/unity-ffi` Windows debug 빌드 → `client/Assets/Plugins/` 복사
4. `p2p/unity-ffi` Android release 빌드 → `client/Assets/Plugins/Android/` 복사
5. Unity 빌드
