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
        int  _reloadTriggered;   // 0/1 (Interlocked)

        void TriggerReloadOnce()
        {
            if (System.Threading.Interlocked.CompareExchange(ref _reloadTriggered, 1, 0) != 0) return;
            _mainQueue.Enqueue(() => { _ = _onReload?.Invoke(Addr); });
        }

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

                if (f is ReloadFrame)
                {
                    // 보조 경로 — hash 기반 detect로도 충분하지만 호환용으로 유지.
                    TriggerReloadOnce();
                }
                else if (f is StateFrame state)
                {
                    // hash mismatch → 이 세션은 더 이상 유효 X. 한 번만 trigger하고 receiver는 곧 dispose됨.
                    if (!string.IsNullOrEmpty(state.MetadataHash)
                        && !string.IsNullOrEmpty(Model?.Hash)
                        && state.MetadataHash != Model.Hash)
                    {
                        TriggerReloadOnce();
                        continue;
                    }

                    if (!_isActive) continue;   // 정상 state는 active만 처리
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
