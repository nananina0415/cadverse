using System;
using System.Threading.Tasks;
using UnityEngine;

namespace Cadverse
{
    public class AppManager : MonoBehaviour
    {
        const ushort AR_CLIENT_PORT = 9001;
        const int    CONNECT_TIMEOUT_MS = 30_000;

        public static P2PNet Net { get; private set; }

        LoginPanel _loginPanel;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            var go = new GameObject("AppManager");
            DontDestroyOnLoad(go);
            go.AddComponent<AppManager>();
        }

        void Awake()
        {
            _loginPanel = LoginPanel.Create(this);
            DontDestroyOnLoad(_loginPanel.gameObject);
        }

        public async void ConnectAsync(string groupName, string pw, string name)
        {
            var connectTask = Task.Run(() => new P2PNet(groupName, pw, name, AR_CLIENT_PORT));
            var timeoutTask = Task.Delay(CONNECT_TIMEOUT_MS);

            if (await Task.WhenAny(connectTask, timeoutTask) == timeoutTask)
            {
                _loginPanel.ShowError("연결 시간이 초과됐습니다. 다시 시도해주세요.");
                return;
            }

            try
            {
                Net = await connectTask;
            }
            catch (Exception e)
            {
                Debug.LogError($"[AppManager] 연결 실패: {e.Message}");
                _loginPanel.ShowError("연결에 실패했습니다. 다시 시도해주세요.");
                return;
            }

            Destroy(_loginPanel.gameObject);
        }

        void OnDestroy()
        {
            Net?.Dispose();
            Net = null;
        }
    }
}
