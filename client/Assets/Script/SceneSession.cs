using System;
using System.Collections.Concurrent;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.XR.ARFoundation;

namespace Cadverse
{
    // 한 QR(addr)에 대응되는 세션 단위.
    // ARScene + Server + 백그라운드 ReceiveLoop를 자신의 자원으로 보유하고,
    // Dispose 한 번으로 모두 정리한다.
    //
    // - IsActive=true면 들어온 frame을 메인 큐에 enqueue (시각화/이벤트 적용)
    // - IsActive=false(cold)면 frame을 받아내기만 하고 즉시 drop
    //   (서버 측 send 큐가 백업되지 않도록 drain은 유지)
    //
    // 어떤 단계든 throw는 LoadAsync 호출자가 받는다. 호출자는 Failed로 간주하고
    // 이 인스턴스를 그냥 Dispose만 하면 된다. 부분 회복은 시도하지 않는다.
    public sealed class SceneSession : IDisposable
    {
        public Addr    Addr   { get; }
        public ARScene Scene  { get; private set; }
        public Server  Server { get; private set; }

        // 활성 세션은 frame을 메인 큐에 push. 그 외는 drain 후 drop.
        public bool IsActive { get; set; } = true;

        readonly CancellationTokenSource        _cts = new();
        readonly ConcurrentQueue<Action>        _mainQueue;
        readonly Func<Addr, Task>               _onReload;       // ReloadFrame 수신 시 메인 스레드에서 호출
        readonly Action<StateFrame>             _onStateExtra;   // ApplyState 직후 부수 처리 (토스트/로그 등)
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
            ARTrackedImageManager manager,
            ConcurrentQueue<Action> mainQueue,
            Func<Addr, Task> onReload,
            Action<StateFrame> onStateExtra)
        {
            var s = new SceneSession(addr, mainQueue, onReload, onStateExtra);
            try
            {
                s.Scene  = await ARScene.Create(addr, manager);
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

                if (!IsActive) continue;   // cold: drain only

                if (f is ReloadFrame)
                {
                    _mainQueue.Enqueue(() => { _ = _onReload?.Invoke(Addr); });
                }
                else if (f is StateFrame state)
                {
                    var scene = Scene;
                    var extra = _onStateExtra;
                    _mainQueue.Enqueue(() =>
                    {
                        scene?.ApplyState(state);
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
            try { Scene?.Dispose(); }  catch {}
        }
    }
}
