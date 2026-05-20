using System;
using System.Threading.Tasks;
using UnityEngine;

namespace Cadverse
{
    public class LoginManager : MonoBehaviour
    {
        const ushort AR_CLIENT_PORT  = 9001;
        const int    CONNECT_TIMEOUT_MS = 30_000;

        AppManager _app;
        LoginPanel _loginPanel;

        public static LoginManager Create(AppManager app)
        {
            var go = new GameObject("LoginManager");
            DontDestroyOnLoad(go);
            var lm = go.AddComponent<LoginManager>();
            lm._app        = app;
            lm._loginPanel = LoginPanel.Create(lm);
            DontDestroyOnLoad(lm._loginPanel.gameObject);
            return lm;
        }

        public async void ConnectAsync(string groupName, string pw, string name)
        {
#if UNITY_EDITOR
            if (groupName == "1" && pw == "1" && name == "1")
            {
                Destroy(_loginPanel.gameObject);
                Destroy(gameObject);
                _app.OnLoginComplete(null);
                return;
            }
#endif
            var connectTask = Task.Run(() => new P2PNet(groupName, pw, name, AR_CLIENT_PORT));
            var timeoutTask = Task.Delay(CONNECT_TIMEOUT_MS);

            if (await Task.WhenAny(connectTask, timeoutTask) == timeoutTask)
            {
                _loginPanel.ShowError("연결 시간이 초과됐습니다. 다시 시도해주세요.");
                return;
            }

            P2PNet net;
            try
            {
                net = await connectTask;
            }
            catch (Exception e)
            {
                Debug.LogError($"[LoginManager] 연결 실패: {e.Message}");
                _loginPanel.ShowError("연결에 실패했습니다. 다시 시도해주세요.");
                return;
            }

            Destroy(_loginPanel.gameObject);
            Destroy(gameObject);
            _app.OnLoginComplete(net);
        }
    }
}
