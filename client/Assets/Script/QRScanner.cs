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

            var result = results[0];

            // BYTE_SEGMENTS: byte-mode QR의 실제 decoded payload. RawBytes/Text는 binary에 신뢰 불가.
            // RawBytes = raw bit array (payload 아님), Text = 개행문자 변환으로 binary 오염 (ZXing.Net #235)
            if (result.ResultMetadata != null &&
                result.ResultMetadata.TryGetValue(ResultMetadataType.BYTE_SEGMENTS, out var segsObj) &&
                segsObj is System.Collections.Generic.IList<byte[]> segs &&
                segs.Count > 0)
            {
                int total = 0;
                foreach (var s in segs) total += s.Length;
                var raw = new byte[total];
                int pos = 0;
                foreach (var s in segs) { Buffer.BlockCopy(s, 0, raw, pos, s.Length); pos += s.Length; }
                if (raw.Length == 32) return Addr.FromRawKey(raw);
            }

            return Addr.TryParse(result.Text);
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
