using System;
using System.Collections;
using System.Threading.Tasks;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using ZXing;

namespace Cadverse
{
    public class QRScanner : MonoBehaviour
    {
        ARCameraManager _cameraManager;
        Action<Addr>    _onChanged;
        string          _lastId;
        BarcodeReaderGeneric _reader;

        public static QRScanner Create(ARCameraManager cameraManager, Action<Addr> onChanged)
        {
            var go = new GameObject("QRScanner");
            DontDestroyOnLoad(go);
            var scanner = go.AddComponent<QRScanner>();
            scanner._cameraManager = cameraManager;
            scanner._onChanged     = onChanged;
            scanner._reader        = new BarcodeReaderGeneric { AutoRotate = false };
            scanner._reader.Options.TryInverted = true;
            scanner.StartCoroutine(scanner.ScanLoop());
            return scanner;
        }

        // 메인 스레드에서 CPU 이미지를 byte[]로 변환 후 반환. 실패 시 null.
        (byte[] buffer, int width, int height)? AcquireFrame()
        {
            if (!_cameraManager.TryAcquireLatestCpuImage(out XRCpuImage image))
                return null;

            using (image)
            {
                var p      = new XRCpuImage.ConversionParams(image, TextureFormat.RGBA32);
                var native = new NativeArray<byte>(image.width * image.height * 4, Allocator.Temp);
                image.Convert(p, native);
                var buffer = native.ToArray();
                native.Dispose();
                return (buffer, image.width, image.height);
            }
        }

        // 백그라운드 스레드에서 호출. ZXing으로 QR 디코딩 후 Addr 반환. 실패 시 null.
        Addr Decode(byte[] buffer, int width, int height)
        {
            var src     = new RGBLuminanceSource(buffer, width, height, RGBLuminanceSource.BitmapFormat.RGBA32);
            var results = _reader.DecodeMultiple(src);
            if (results == null || results.Length != 1) return null;
            return Addr.TryParse(results[0].Text);
        }

        IEnumerator ScanLoop()
        {
            var wait = new WaitForSeconds(0.3f);
            while (true)
            {
                var frame = AcquireFrame();
                if (frame.HasValue)
                {
                    var (buf, w, h) = frame.Value;
                    var task = Task.Run(() => Decode(buf, w, h));
                    yield return new WaitUntil(() => task.IsCompleted);

                    var addr = task.Result;
                    if (addr != null && addr.Id != _lastId)
                    {
                        _lastId = addr.Id;
                        _onChanged?.Invoke(addr);
                    }
                }

                yield return wait;
            }
        }
    }
}
