using System.Threading.Tasks;
using TMPro;
using UnityEngine;
using UnityEngine.XR.ARFoundation;

namespace Cadverse
{
    public class AppManager : MonoBehaviour
    {
        public static P2PNet      Net     { get; private set; }
        public static QRScanner   Scanner { get; private set; }

        ARTrackedImageManager _imageManager;
        ARScene               _scene;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Bootstrap()
        {
            var go = new GameObject("AppManager");
            DontDestroyOnLoad(go);
            go.AddComponent<AppManager>();
        }

        void Awake()
        {
            LoginManager.Create(this);
        }

        public void OnLoginComplete(P2PNet net)
        {
            Net = net;
            _imageManager = FindAnyObjectByType<ARTrackedImageManager>();
            var cameraManager = FindAnyObjectByType<ARCameraManager>();
            Scanner = QRScanner.Create(cameraManager, OnQRChanged);
        }

        async void OnQRChanged(Addr addr)
        {
            _scene?.Dispose();
            _scene = null;
            _scene = await ARScene.Create(addr, _imageManager);
        }

        void OnDestroy()
        {
            _scene?.Dispose();
            Net?.Dispose();
            Net = null;
        }

    }
}
