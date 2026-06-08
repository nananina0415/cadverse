using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace Cadverse
{
    // QR(addrId)별 raw 자산(metadata, OBJ, qr.txt 등)을 메모리 + 디스크 2단 LRU로 캐싱.
    // ARScene이 메시를 만들 때 RequestHttp 대신 GetOrFetch를 거쳐 같은 QR 재인식 시
    // 다운로드를 건너뛴다. 메시 자체는 캐싱하지 않고 byte[] 단계에서 멈춰 메모리 부담을 제한.
    //
    // 시작 시 Cleanup으로 디스크 전체 비우고 (clean start), 종료 시 OnApplicationQuit에서도 비운다.
    public sealed class AssetCache
    {
        readonly P2PNet _net;
        readonly string _diskRoot;
        readonly int    _memMaxEntries;
        readonly long   _diskMaxBytes;

        // memory LRU: addrId → (path → bytes). _memOrder의 tail이 most-recently-used.
        readonly Dictionary<string, Dictionary<string, byte[]>> _mem = new();
        readonly LinkedList<string> _memOrder = new();
        readonly object _lock = new();

        public AssetCache(P2PNet net, string diskRoot,
                          int memMaxEntries = 2,
                          long diskMaxBytes = 200L * 1024 * 1024)
        {
            _net           = net;
            _diskRoot      = diskRoot;
            _memMaxEntries = memMaxEntries;
            _diskMaxBytes  = diskMaxBytes;
            try { Directory.CreateDirectory(_diskRoot); } catch {}
        }

        // 앱 시작/종료 시 호출. 디스크 전부 제거.
        public static void Cleanup(string diskRoot)
        {
            try
            {
                if (Directory.Exists(diskRoot))
                    Directory.Delete(diskRoot, recursive: true);
            }
            catch (System.Exception e) { Debug.LogWarning($"[AssetCache] cleanup 실패: {e.Message}"); }
        }

        // 캐시 키는 (modelHash, path). 같은 모델이면 어느 server에서 받든 캐시 공유.
        // 메모리 → 디스크 → 네트워크 순서로 try. 블로킹 — Task.Run 안에서 호출할 것.
        public byte[] GetOrFetch(string modelHash, Addr addr, string path)
        {
            string id = string.IsNullOrEmpty(modelHash) ? addr.Id : modelHash;
            lock (_lock)
            {
                if (_mem.TryGetValue(id, out var byPath) && byPath.TryGetValue(path, out var bytes))
                {
                    PromoteLru(id);
                    return bytes;
                }
            }

            var diskBytes = TryReadDisk(id, path);
            if (diskBytes != null)
            {
                lock (_lock) PutMem(id, path, diskBytes);
                return diskBytes;
            }

            var fetched = _net.RequestHttp(addr.RawJson, path);
            TryWriteDisk(id, path, fetched);
            lock (_lock) PutMem(id, path, fetched);
            return fetched;
        }

        // ── memory LRU ──────────────────────────────────────────
        void PutMem(string id, string path, byte[] bytes)
        {
            if (!_mem.TryGetValue(id, out var byPath))
            {
                byPath = new Dictionary<string, byte[]>();
                _mem[id] = byPath;
            }
            byPath[path] = bytes;
            PromoteLru(id);
            EvictMemIfNeeded();
        }

        void PromoteLru(string id)
        {
            _memOrder.Remove(id);
            _memOrder.AddLast(id);
        }

        void EvictMemIfNeeded()
        {
            while (_memOrder.Count > _memMaxEntries)
            {
                var oldest = _memOrder.First.Value;
                _memOrder.RemoveFirst();
                _mem.Remove(oldest);
            }
        }

        // ── disk layer ─────────────────────────────────────────
        string DiskDir(string id) => Path.Combine(_diskRoot, id);
        string DiskPath(string id, string path)
            => Path.Combine(DiskDir(id), path.TrimStart('/').Replace('/', '_'));

        byte[] TryReadDisk(string id, string path)
        {
            try
            {
                var p = DiskPath(id, path);
                return File.Exists(p) ? File.ReadAllBytes(p) : null;
            }
            catch { return null; }
        }

        void TryWriteDisk(string id, string path, byte[] bytes)
        {
            try
            {
                Directory.CreateDirectory(DiskDir(id));
                File.WriteAllBytes(DiskPath(id, path), bytes);
                EvictDiskIfNeeded();
            }
            catch (System.Exception e) { Debug.LogWarning($"[AssetCache] disk write 실패: {e.Message}"); }
        }

        // 디스크 총량이 한도를 넘으면 가장 오래된 mtime 디렉터리부터 삭제.
        void EvictDiskIfNeeded()
        {
            try
            {
                if (!Directory.Exists(_diskRoot)) return;
                var dirs = new List<DirectoryInfo>();
                long total = 0;
                foreach (var d in new DirectoryInfo(_diskRoot).GetDirectories())
                {
                    long size = 0;
                    foreach (var f in d.GetFiles("*", SearchOption.AllDirectories)) size += f.Length;
                    dirs.Add(d);
                    total += size;
                }
                if (total <= _diskMaxBytes) return;
                dirs.Sort((a, b) => a.LastWriteTimeUtc.CompareTo(b.LastWriteTimeUtc));
                foreach (var d in dirs)
                {
                    if (total <= _diskMaxBytes) break;
                    long size = 0;
                    foreach (var f in d.GetFiles("*", SearchOption.AllDirectories)) size += f.Length;
                    try { d.Delete(recursive: true); total -= size; } catch {}
                }
            }
            catch (System.Exception e) { Debug.LogWarning($"[AssetCache] disk evict 실패: {e.Message}"); }
        }
    }
}
