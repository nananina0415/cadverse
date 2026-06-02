using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;

namespace Cadverse
{
    // 한 QR(addr)에 대응되는 세션.
    // Server + 백그라운드 ReceiveLoop 자원만 보유. 모델 시각화는 영구 SceneManager 안의
    // ModelRoot가 담당한다 (ModelRoot는 빌려 쓴다 — 소유는 SceneManager).
    //
    // IsActive=true  : frame을 메인 큐에 enqueue → ApplyState + onStateExtra
    //                  ModelRoot.SetVisible(true)
    // IsActive=false : frame을 받아내기만 하고 drop (server send 큐 백업 방지)
    //                  ModelRoot.SetVisible(false)
    //
    // Dispose는 server/recv 정리만. ModelRoot는 SceneManager가 RemoveModel로 정리.
    public sealed class SceneSession : IDisposable
    {
        public Addr      Addr   { get; }
        public ModelRoot Model  { get; private set; }
        public Server    Server { get; private set; }

        public bool IsActive
        {
            get => _isActive;
            set
            {
                _isActive = value;
                Model?.SetVisible(value);
            }
        }
        bool _isActive;

        readonly CancellationTokenSource     _cts = new();
        readonly ConcurrentQueue<Action>     _mainQueue;
        readonly Func<Addr, Task>            _onReload;
        readonly Action<StateFrame>          _onStateExtra;
        Task _recvTask;
        bool _disposed;

        SceneSession(Addr addr, ConcurrentQueue<Action> mainQueue,
                     Func<Addr, Task> onReload, Action<StateFrame> onStateExtra)
        {
            Addr          = addr;
            _mainQueue    = mainQueue;
            _onReload     = onReload;
            _onStateExtra = onStateExtra;
        }

        public static async Task<SceneSession> LoadAsync(
            Addr addr,
            P2PNet net,
            SceneManager sceneManager,
            ConcurrentQueue<Action> mainQueue,
            Func<Addr, Task> onReload,
            Action<StateFrame> onStateExtra,
            AssetCache cache = null)
        {
            var s = new SceneSession(addr, mainQueue, onReload, onStateExtra);
            try
            {
                s.Model  = await sceneManager.AddModelAsync(addr, cache);
                s.Server = await Task.Run(() => new Server(net, addr));
                s._recvTask = Task.Run(() => s.ReceiveLoop());
                return s;
            }
            catch
            {
                s.Dispose();
                throw;
            }
        }

        void ReceiveLoop()
        {
            var ct = _cts.Token;
            while (!ct.IsCancellationRequested)
            {
                Frame f;
                try
                {
                    f = AppManager.NeedsFullInfo ? Server.SimFrameAndInfo() : Server.SimFrame();
                }
                catch { break; }

                if (!_isActive) continue;   // cold: drain only

                if (f is ReloadFrame)
                {
                    _mainQueue.Enqueue(() => { _ = _onReload?.Invoke(Addr); });
                }
                else if (f is StateFrame state)
                {
                    var model = Model;
                    var extra = _onStateExtra;
                    _mainQueue.Enqueue(() =>
                    {
                        model?.ApplyState(state);
                        extra?.Invoke(state);
                    });
                }
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            try { _cts.Cancel(); } catch {}
            try { Server?.Dispose(); } catch {}
            // ModelRoot는 SceneManager.RemoveModel이 정리 (호출자 책임).
        }
    }
}
