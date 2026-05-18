import json, subprocess, threading


class RustServer:
    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._lock = threading.Lock()

    def _send(self, obj: dict):
        proc = self._proc
        if not proc or proc.poll() is not None:
            return
        try:
            with self._lock:
                proc.stdin.write((json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8'))
                proc.stdin.flush()
        except Exception:
            pass

    def init(self, username: str, group: str, password: str, mode: str):
        self._send({'cmd': 'init', 'username': username, 'group': group, 'password': password, 'mode': mode})

    def resume(self, model_path: str):
        self._send({'cmd': 'resume', 'model_path': model_path})

    def reload(self, model_path: str):
        self._send({'cmd': 'reload', 'model_path': model_path})

    def pause(self):
        self._send({'cmd': 'pause'})

    def import_model(self, username: str, import_root: str):
        self._send({'cmd': 'import', 'username': username, 'import_root': import_root})
