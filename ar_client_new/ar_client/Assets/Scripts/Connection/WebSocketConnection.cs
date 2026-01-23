using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using NativeWebSocket;

namespace CADverse.Connection
{
    /// <summary>
    /// 순수 WebSocket 통신을 담당하는 저수준 클래스.
    /// 어떤 메시지를 주고받는지는 알 필요 없이, 단순히 WebSocket 연결/송수신만 처리한다.
    /// Unity 메인 스레드에서 DispatchMessageQueue()를 호출해야 이벤트가 발생한다.
    /// </summary>
    public sealed class WebSocketConnection : IDisposable
    {
        private WebSocket _webSocket;
        private readonly string _url;
        private readonly Queue<byte[]> _messageQueue = new Queue<byte[]>();
        private readonly object _queueLock = new object();

        // 이벤트
        public event Action OnConnected;
        public event Action OnDisconnected;
        public event Action<string> OnError;
        public event Action<byte[]> OnMessageReceived;

        /// <summary>
        /// WebSocket 연결을 생성한다 (연결은 아직 시작하지 않음).
        /// </summary>
        /// <param name="url">WebSocket URL (예: "ws://192.168.0.1:8000/ws")</param>
        public WebSocketConnection(string url)
        {
            if (string.IsNullOrWhiteSpace(url))
            {
                throw new ArgumentException("WebSocket URL은 비어있을 수 없습니다.", nameof(url));
            }

            _url = url;
        }

        /// <summary>
        /// WebSocket URL을 반환한다.
        /// </summary>
        public string Url => _url;

        /// <summary>
        /// WebSocket이 연결되어 있는지 확인한다.
        /// </summary>
        public bool IsConnected => _webSocket != null && _webSocket.State == WebSocketState.Open;

        /// <summary>
        /// WebSocket 연결을 시작한다.
        /// </summary>
        public async Task ConnectAsync()
        {
            if (_webSocket != null && _webSocket.State == WebSocketState.Open)
            {
                return; // 이미 연결됨
            }

            _webSocket = new WebSocket(_url);

            _webSocket.OnOpen += HandleOpen;
            _webSocket.OnClose += HandleClose;
            _webSocket.OnError += HandleError;
            _webSocket.OnMessage += HandleMessage;

            await _webSocket.Connect();
        }

        /// <summary>
        /// WebSocket 연결을 종료한다.
        /// </summary>
        public async Task DisconnectAsync()
        {
            if (_webSocket != null)
            {
                _webSocket.OnOpen -= HandleOpen;
                _webSocket.OnClose -= HandleClose;
                _webSocket.OnError -= HandleError;
                _webSocket.OnMessage -= HandleMessage;

                if (_webSocket.State == WebSocketState.Open)
                {
                    await _webSocket.Close();
                }

                _webSocket = null;
            }
        }

        /// <summary>
        /// 텍스트 메시지를 전송한다.
        /// </summary>
        public async Task SendTextAsync(string text)
        {
            if (!IsConnected)
            {
                throw new InvalidOperationException("WebSocket이 연결되지 않았습니다.");
            }

            await _webSocket.SendText(text);
        }

        /// <summary>
        /// 바이너리 메시지를 전송한다.
        /// </summary>
        public async Task SendBytesAsync(byte[] bytes)
        {
            if (!IsConnected)
            {
                throw new InvalidOperationException("WebSocket이 연결되지 않았습니다.");
            }

            await _webSocket.Send(bytes);
        }

        /// <summary>
        /// Unity 메인 스레드에서 호출하여 메시지 큐를 처리한다.
        /// 일반적으로 MonoBehaviour의 Update()에서 호출한다.
        /// </summary>
        public void DispatchMessageQueue()
        {
            _webSocket?.DispatchMessageQueue();

            // 수신된 메시지 이벤트 발생
            lock (_queueLock)
            {
                while (_messageQueue.Count > 0)
                {
                    var message = _messageQueue.Dequeue();
                    OnMessageReceived?.Invoke(message);
                }
            }
        }

        // ===== WebSocket 이벤트 핸들러 =====

        private void HandleOpen()
        {
            OnConnected?.Invoke();
        }

        private void HandleClose(WebSocketCloseCode code)
        {
            OnDisconnected?.Invoke();
        }

        private void HandleError(string error)
        {
            OnError?.Invoke(error);
        }

        private void HandleMessage(byte[] bytes)
        {
            // 메시지를 큐에 추가 (Unity 메인 스레드에서 처리하기 위해)
            lock (_queueLock)
            {
                _messageQueue.Enqueue(bytes);
            }
        }

        public void Dispose()
        {
            DisconnectAsync().Wait();
        }
    }
}
