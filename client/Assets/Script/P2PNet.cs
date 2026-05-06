using System;
using System.Runtime.InteropServices;

namespace Cadverse
{
    /// <summary>
    /// iroh NodeAddr의 JSON 래퍼.
    /// FFI에 넘길 때는 RawJson을 그대로 사용하고,
    /// 동일 피어 여부는 Id(공개키)로만 비교한다.
    /// </summary>
    public class Addr
    {
        public string RawJson { get; }
        public string Id      { get; }

        Addr(string rawJson, string id) { RawJson = rawJson; Id = id; }

        public static Addr TryParse(string json)
        {
            if (string.IsNullOrEmpty(json)) return null;
            var id = ExtractId(json);
            if (id == null) return null;
            return new Addr(json, id);
        }

        // {"id":"...","addrs":[...]} 에서 id 값만 추출
        static string ExtractId(string json)
        {
            const string key = "\"id\"";
            int k = json.IndexOf(key, StringComparison.Ordinal);
            if (k < 0) return null;
            int colon = json.IndexOf(':', k + key.Length);
            if (colon < 0) return null;
            int open = json.IndexOf('"', colon + 1);
            if (open < 0) return null;
            int close = json.IndexOf('"', open + 1);
            if (close < 0) return null;
            return json.Substring(open + 1, close - open - 1);
        }
    }


    /// <summary>
    /// unity-ffi (libunity_ffi.dll / libunity_ffi.so) P/Invoke 바인딩.
    ///
    /// 피어 목록 구조 (cv_get_peers_json 반환 JSON):
    /// [
    ///   {
    ///     "addr": <NodeAddr 직렬화>,
    ///     "name": "...",
    ///     "peer_type": "SimServer" | "MidServer" | { "ArClient": { "udp_port": N } }
    ///   }
    /// ]
    ///
    /// 사용 예:
    ///   var net  = new P2PNet("my-net", "password", "Player1", udpPort: 9000);
    ///   string json = net.GetPeersJson();
    ///   // json 파싱 후 SimServer 피어의 addr 추출
    ///   using var conn = net.ConnectQuic(addrJson);
    ///   conn.Send(System.Text.Encoding.UTF8.GetBytes("hello"));
    ///   byte[] data = conn.Recv();
    /// </summary>
    public sealed class P2PNet : IDisposable
    {
        // Unity는 플랫폼에 따라 자동으로 .dll / .so 확장자를 붙인다.
        const string Lib = "unity_ffi";

        [DllImport(Lib)] static extern IntPtr cv_join(string netId, string pw, string name, ushort udpPort);
        [DllImport(Lib)] static extern void   cv_net_free(IntPtr net);
        [DllImport(Lib)] static extern IntPtr cv_get_peers_json(IntPtr net);
        [DllImport(Lib)] static extern void   cv_string_free(IntPtr s);
        [DllImport(Lib)] static extern IntPtr cv_connect_udp(IntPtr net, string addrJson);
        [DllImport(Lib)] static extern int    cv_request_http(IntPtr net, string addrJson, string path, byte[] outBuf, uint outLen);

        IntPtr _handle;

        /// <summary>
        /// P2P 네트워크에 참가한다. 완료까지 수 초 이상 걸릴 수 있다.
        /// 메인 스레드 블로킹을 피하려면 Task.Run 안에서 생성할 것.
        /// </summary>
        /// <param name="udpPort">0 이면 MidServer, 양수이면 ArClient(해당 포트)로 등록.</param>
        public P2PNet(string netId, string pw, string name, ushort udpPort = 0)
        {
            _handle = cv_join(netId, pw, name, udpPort);
            if (_handle == IntPtr.Zero)
                throw new InvalidOperationException("cv_join 실패: 네트워크 참가 불가");
        }

        /// <summary>피어 목록을 JSON 문자열로 반환한다.</summary>
        public string GetPeersJson()
        {
            ThrowIfDisposed();
            IntPtr ptr = cv_get_peers_json(_handle);
            if (ptr == IntPtr.Zero) return "[]";
            string json = Marshal.PtrToStringAnsi(ptr) ?? "[]";
            cv_string_free(ptr);
            return json;
        }

        /// <summary>
        /// 지정한 피어에 QUIC 연결을 맺는다.
        /// addrJson = GetPeersJson()에서 파싱한 PeerInfo.addr 필드 값 그대로.
        /// 블로킹 — Task.Run 안에서 호출할 것.
        /// </summary>
        public P2PConn ConnectQuic(string addrJson)
        {
            ThrowIfDisposed();
            IntPtr conn = cv_connect_udp(_handle, addrJson);
            if (conn == IntPtr.Zero)
                throw new InvalidOperationException($"cv_connect_udp 실패: {addrJson}");
            return new P2PConn(conn);
        }

        /// <summary>
        /// HTTP/3으로 파일을 요청한다.
        /// path 예: "/metadata.json", "/meshes/part.obj"
        /// 블로킹 — Task.Run 안에서 호출할 것.
        /// </summary>
        /// <param name="maxBytes">수신 버퍼 크기 (기본 16 MB).</param>
        public byte[] RequestHttp(string addrJson, string path, int maxBytes = 16 * 1024 * 1024)
        {
            ThrowIfDisposed();
            byte[] buf = new byte[maxBytes];
            int n = cv_request_http(_handle, addrJson, path, buf, (uint)buf.Length);
            if (n < 0)
                throw new InvalidOperationException($"cv_request_http 실패: path={path}");
            byte[] result = new byte[n];
            Buffer.BlockCopy(buf, 0, result, 0, n);
            return result;
        }

        public void Dispose()
        {
            if (_handle != IntPtr.Zero)
            {
                cv_net_free(_handle);
                _handle = IntPtr.Zero;
            }
        }

        void ThrowIfDisposed()
        {
            if (_handle == IntPtr.Zero)
                throw new ObjectDisposedException(nameof(P2PNet));
        }
    }

    /// <summary>
    /// QUIC 연결 핸들.
    /// cv_conn_recv는 블로킹이므로 반드시 별도 스레드(Task.Run)에서 호출할 것.
    /// </summary>
    public sealed class P2PConn : IDisposable
    {
        const string Lib = "unity_ffi";

        [DllImport(Lib)] static extern int  cv_conn_send(IntPtr conn, byte[] data, uint len);
        [DllImport(Lib)] static extern int  cv_conn_recv(IntPtr conn, byte[] outBuf, uint outLen);
        [DllImport(Lib)] static extern void cv_conn_free(IntPtr conn);

        IntPtr _handle;

        internal P2PConn(IntPtr handle) { _handle = handle; }

        /// <summary>데이터를 전송한다. 성공 시 true.</summary>
        public bool Send(byte[] data)
        {
            ThrowIfDisposed();
            return cv_conn_send(_handle, data, (uint)data.Length) != 0;
        }

        /// <summary>
        /// 데이터가 도착할 때까지 블로킹 대기 후 반환한다.
        /// 메인 스레드에서 직접 호출하면 게임이 멈추므로 Task.Run 사용:
        ///   byte[] data = await Task.Run(() => conn.Recv());
        /// </summary>
        public byte[] Recv(int maxBytes = 65536)
        {
            ThrowIfDisposed();
            byte[] buf = new byte[maxBytes];
            int n = cv_conn_recv(_handle, buf, (uint)buf.Length);
            if (n < 0)
                throw new InvalidOperationException("cv_conn_recv 실패");
            byte[] result = new byte[n];
            Buffer.BlockCopy(buf, 0, result, 0, n);
            return result;
        }

        public void Dispose()
        {
            if (_handle != IntPtr.Zero)
            {
                cv_conn_free(_handle);
                _handle = IntPtr.Zero;
            }
        }

        void ThrowIfDisposed()
        {
            if (_handle == IntPtr.Zero)
                throw new ObjectDisposedException(nameof(P2PConn));
        }
    }
}
