import adsk.core, adsk.fusion, traceback
import os, json, subprocess, threading, importlib
import tkinter as tk

from . import extract as _extract
from .server import RustServer

_handlers              = []
_palette               = None
_server_proc           = None
_server                = None
_server_error          = None
_send_queue            = []
_stopping              = False
_model_dir             = None
_doc_saved_handler     = None
_last_f3z_ready_path   = None  # 중복 import 방지

SERVER_DIED_EVENT  = 'cadverse_server_died'
PALETTE_SEND_EVENT = 'cadverse_palette_send'
F3Z_EXPORT_EVENT   = 'cadverse_f3z_export'
F3Z_IMPORT_EVENT   = 'cadverse_f3z_import'
PALETTE_ID         = 'cadverse_palette'

def _plugin_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def _plog(msg):
    try:
        with open(os.path.join(_plugin_dir(), 'plugin.log'), 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass

def _set_model_dir(username: str):
    global _model_dir
    if not username:
        return
    dbg = _debug_config()
    if dbg.get('models_dir'):
        models_base = os.path.normpath(os.path.join(_plugin_dir(), dbg['models_dir']))
    else:
        exe = _sim_server_exe()
        models_base = os.path.join(os.path.dirname(exe), 'models')
    _model_dir = os.path.join(models_base, username)
    _plog(f'[model_dir] {_model_dir}')
    os.makedirs(_model_dir, exist_ok=True)

def _debug_config() -> dict:
    path = os.path.join(_plugin_dir(), 'debug.json')
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def _sim_server_exe() -> str:
    dbg = _debug_config()
    if not dbg:
        return os.path.normpath(os.path.join(_plugin_dir(), '..', 'server', 'CADverse.exe'))
    override = dbg.get('server_exe')
    if override:
        return os.path.normpath(os.path.join(_plugin_dir(), override))
    return os.path.normpath(os.path.join(_plugin_dir(), '..', 'server', 'CADverse.exe'))

def _config_path() -> str:
    return os.path.join(_plugin_dir(), 'config.json')

def _load_config() -> dict:
    try:
        with open(_config_path()) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_config(cfg: dict):
    with open(_config_path(), 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def _sanitize_username(username: str) -> str:
    import re
    s = str(username or 'default_user')
    s = s.replace(' ', '_').replace(':', '_')
    s = re.sub(r'[^A-Za-z0-9가-힣_\-]', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    return s or 'default_user'

def _get_username_from_data_or_config(data: dict) -> str:
    candidates = [data.get('username'), data.get('user'), data.get('name')]
    cfg = _load_config()
    candidates.extend([cfg.get('username'), cfg.get('user'), cfg.get('name')])
    for c in candidates:
        if c is not None and str(c).strip():
            return _sanitize_username(str(c))
    return 'default_user'

class _DocumentSavedHandler(adsk.core.DocumentEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        if not _model_dir:
            return
        try:
            app = adsk.core.Application.get()
            product = app.activeProduct
            if not product or product.objectType != adsk.fusion.Design.classType():
                return
            _extract.run(None, _model_dir)
            _server.reload(_model_dir)
            _trigger_f3z_export_if_needed(app)
        except Exception as e:
            _plog(f'[DocSaved] extract 실패: {e}')


def _show_qr_window(rows=None, title='CADverse QR', label=''):
    if rows is None:
        path = os.path.join(os.path.dirname(_sim_server_exe()), 'local_sim_qr.txt')
        try:
            rows = [r for r in open(path, encoding='utf-8').read().splitlines() if r]
        except Exception:
            return
        if not rows:
            return
        label = _load_config().get('username', '')

    n_cols    = max(len(r) for r in rows)
    n_rows_qr = len(rows)

    PADDING         = 24   # 사방 고정 픽셀 패딩
    LABEL_FONT_SIZE = 18   # 라벨 폰트 (pt)

    root = tk.Tk()
    root.title(title)
    root.attributes('-topmost', True)
    root.configure(bg='white')

    # 라벨은 QR 위. canvas보다 먼저 pack해야 위쪽에 자리잡는다.
    if label:
        tk.Label(root, text=label, font=('Segoe UI', LABEL_FONT_SIZE), bg='white').pack(
            side=tk.TOP, padx=PADDING, pady=(PADDING, PADDING // 2)
        )

    canvas = tk.Canvas(root, bg='white', highlightthickness=0)
    canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=PADDING, pady=(0, PADDING))

    # 초기 QR 10cm + 패딩 * 2. 라벨이 있으면 그만큼 세로를 더 늘린다.
    # 클라이언트(ARScene)도 marker physicalSize를 0.10m로 잡아야 모델 스케일이 맞다.
    dpi              = root.winfo_fpixels('1i')
    qr_init_px       = int((10.0 / 2.54) * dpi)
    label_h_estimate = (LABEL_FONT_SIZE * 2 + PADDING // 2) if label else 0
    root_init_w      = qr_init_px + PADDING * 2
    root_init_h      = qr_init_px + PADDING * 2 + label_h_estimate
    root.geometry(f'{root_init_w}x{root_init_h}')

    def redraw(event=None):
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 2 or h < 2:
            return
        size  = min(w, h)
        cell  = max(1, size // max(n_cols, n_rows_qr))
        x_off = (w - n_cols * cell) // 2
        y_off = (h - n_rows_qr * cell) // 2
        canvas.delete('all')
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == '1':
                    x0 = x_off + x * cell
                    y0 = y_off + y * cell
                    canvas.create_rectangle(x0, y0, x0 + cell, y0 + cell, fill='black', outline='')

    canvas.bind('<Configure>', redraw)
    root.bind('<Escape>', lambda _: root.destroy())
    root.mainloop()


def _pipe_reader_thread():
    global _last_f3z_ready_path
    proc = _server_proc
    while proc and proc.poll() is None:
        try:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.decode('utf-8', errors='replace').strip()
            if not line:
                continue
            _plog(f'[rust->py*] {line[:80]}')
            try:
                data = json.loads(line)
                _send_to_palette('status', data)
                f3z_path = data.get('f3z_ready_path')
                if f3z_path and f3z_path != _last_f3z_ready_path:
                    _last_f3z_ready_path = f3z_path
                    try:
                        adsk.core.Application.get().fireCustomEvent(F3Z_IMPORT_EVENT, f3z_path)
                        _plog(f'[f3z] import 이벤트 발화: {f3z_path}')
                    except Exception:
                        _plog(f'[f3z] import event 발화 실패:\n{traceback.format_exc()}')
            except json.JSONDecodeError:
                pass
        except Exception as e:
            _plog(f'[reader] 예외: {e}')
            break
    if not _stopping:
        _send_to_palette('server_status', {'running': False, 'error': '서버 연결이 끊어졌습니다.'})

def _ensure_firewall_rule(exe: str):
    import ctypes
    rule_name = 'CADverse'
    result = subprocess.run(
        ['netsh', 'advfirewall', 'firewall', 'show', 'rule',
         f'name={rule_name}', 'dir=in', 'verbose'],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if exe.lower() not in (result.stdout or '').lower():
        cmd = (f'netsh advfirewall firewall add rule name="{rule_name}" '
               f'dir=in action=allow program="{exe}" enable=yes profile=any')
        ctypes.windll.shell32.ShellExecuteW(None, 'runas', 'cmd.exe', f'/c {cmd}', None, 0)

def _start_server():
    global _server_proc, _server
    exe = _sim_server_exe()
    if not os.path.exists(exe):
        raise FileNotFoundError(f'sim_server.exe 없음: {exe}')
    _ensure_firewall_rule(exe)
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', os.path.basename(exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=3,
        )
    except Exception:
        pass
    log_path = os.path.join(_plugin_dir(), 'server.log')
    log_file = open(log_path, 'w', encoding='utf-8')
    log_file.write(f'[plugin] 서버 시작: {exe}\n')
    log_file.flush()

    exe_dir = os.path.dirname(exe)
    norm_exe = os.path.normpath(exe).lower()
    is_debug = (os.sep + 'debug' + os.sep) in norm_exe or '/debug/' in norm_exe

    # server.exe 의존 DLL(SDL2.dll 등)은 OS가 main 함수 진입 전, exe 로딩 단계에서
    # 찾아 로드한다. server 내부 setup_python의 PATH 변경은 그 시점에는 너무 늦으므로
    # 부모 프로세스(여기) 단계에서 PATH를 미리 설정해 자식에게 상속시킨다.
    if is_debug:
        # debug 빌드: 시스템 conda env (CONDA_BASE/envs/cadverse) 사용
        conda_base = os.environ.get('CONDA_BASE')
        env_root = os.path.join(conda_base, 'envs', 'cadverse') if conda_base else None
        if env_root is None:
            log_file.write('[plugin] WARN: CONDA_BASE 미설정 — setup-dev-env.ps1 실행 필요\n')
    else:
        # release 빌드: exe 옆 python_env. 없으면 python_env.tar.gz를 풀어 만든다.
        env_root = os.path.join(exe_dir, 'python_env')
        if not os.path.exists(env_root):
            bundle = os.path.join(exe_dir, 'python_env.tar.gz')
            if not os.path.exists(bundle):
                log_file.write(f'[plugin] ERROR: python_env.tar.gz 없음: {bundle}\n')
                log_file.flush()
                raise FileNotFoundError(f'python_env.tar.gz 없음: {bundle}')
            log_file.write(f'[plugin] python_env unpack 시작: {bundle}\n')
            log_file.flush()
            os.makedirs(env_root, exist_ok=True)
            subprocess.run(
                ['tar', '-xzf', bundle, '-C', env_root],
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            log_file.write('[plugin] python_env unpack 완료\n')
            log_file.flush()

    env_vars = {**os.environ}

    if is_debug:
        env_vars['RUST_BACKTRACE'] = 'full'
        log_file.write('[plugin] 디버그 빌드 감지 → RUST_BACKTRACE=full\n')

    if env_root:
        # env 루트 자체에 python3xx.dll(pyo3 dynamic link 대상) 등 핵심 DLL이 있어
        # PATH 맨 앞에 함께 추가해야 server.exe 시작 시 OS가 찾아낼 수 있다.
        dll_dirs = [
            env_root,
            os.path.join(env_root, 'Library', 'bin'),
            os.path.join(env_root, 'DLLs'),
        ]
        env_vars['PATH'] = os.pathsep.join(dll_dirs + [env_vars.get('PATH', '')])
        log_file.write(f'[plugin] DLL 경로 추가: {env_root}\n')

    log_file.flush()

    _server_proc = subprocess.Popen(
        [exe],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
        env=env_vars,
    )
    _server = RustServer(_server_proc)
    threading.Thread(target=_pipe_reader_thread, daemon=True).start()
    threading.Thread(target=_watch_server, daemon=True).start()

def _stop_server():
    global _server_proc, _server
    _server = None
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None

def _watch_server():
    if _server_proc:
        _server_proc.wait()
    if _stopping:
        return
    try:
        adsk.core.Application.get().fireCustomEvent(SERVER_DIED_EVENT, '')
    except Exception as e:
        _plog(f'[watch_server] fireCustomEvent 실패: {e}')

def _trigger_f3z_export_if_needed(app):
    import hashlib
    if not _model_dir:
        return
    try:
        meta_path = os.path.join(_model_dir, 'metadata.json')
        with open(meta_path, 'rb') as f:
            meta_hash = hashlib.sha256(f.read()).hexdigest()[:16]
        models_root = os.path.dirname(_model_dir)
        f3z_path = os.path.join(models_root, f'{meta_hash}.f3z')
        if not os.path.exists(f3z_path):
            app.fireCustomEvent(F3Z_EXPORT_EVENT, f3z_path)
            _plog(f'[f3z] export 이벤트 발화: {f3z_path}')
    except Exception:
        _plog(f'[f3z] export trigger 실패:\n{traceback.format_exc()}')


class _F3zExportHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            f3z_path = adsk.core.CustomEventArgs.cast(args).additionalInfo
            app = adsk.core.Application.get()
            design = app.activeProduct
            if not isinstance(design, adsk.fusion.Design):
                _plog('[f3z export] activeProduct가 Design이 아님')
                return
            export_mgr = design.exportManager
            options = export_mgr.createFusionArchiveExportOptions(f3z_path)
            export_mgr.execute(options)
            _plog(f'[f3z export] 완료: {f3z_path}')
        except Exception:
            _plog(f'[f3z export] 실패:\n{traceback.format_exc()}')


class _F3zImportHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            f3z_path = adsk.core.CustomEventArgs.cast(args).additionalInfo
            app = adsk.core.Application.get()
            import_mgr = app.importManager
            options = import_mgr.createFusionArchiveImportOptions(f3z_path)
            doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType, True)
            design = doc.products.itemByProductType('DesignProductType')
            import_mgr.importToTarget(options, design.rootComponent)
            _plog(f'[f3z import] 완료: {f3z_path}')
        except Exception:
            _plog(f'[f3z import] 실패:\n{traceback.format_exc()}')


def _send_to_palette(action: str, data: dict):
    _plog(f'[py*->js] {action}')
    _send_queue.append((action, data))
    try:
        adsk.core.Application.get().fireCustomEvent(PALETTE_SEND_EVENT, '')
    except Exception as e:
        _plog(f'[send_to_palette] fireCustomEvent 실패: {e}')


class _PaletteSendHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, _):
        while _send_queue:
            action, data = _send_queue.pop(0)
            if _palette and _palette.isValid:
                _palette.sendInfoToHTML(action, json.dumps(data, ensure_ascii=False))


def run(context):
    global _stopping
    _stopping = False
    for _log in ('plugin.log', 'server.log'):
        try:
            open(os.path.join(_plugin_dir(), _log), 'w').close()
        except Exception:
            pass
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        on_send = _PaletteSendHandler()
        app.registerCustomEvent(PALETTE_SEND_EVENT).add(on_send)
        _handlers.append(on_send)

        on_died = _ServerDiedHandler()
        app.registerCustomEvent(SERVER_DIED_EVENT).add(on_died)
        _handlers.append(on_died)

        on_f3z_export = _F3zExportHandler()
        app.registerCustomEvent(F3Z_EXPORT_EVENT).add(on_f3z_export)
        _handlers.append(on_f3z_export)

        on_f3z_import = _F3zImportHandler()
        app.registerCustomEvent(F3Z_IMPORT_EVENT).add(on_f3z_import)
        _handlers.append(on_f3z_import)

        global _doc_saved_handler
        on_doc_saved = _DocumentSavedHandler()
        app.documentSaved.add(on_doc_saved)
        _handlers.append(on_doc_saved)
        _doc_saved_handler = on_doc_saved

        _init_cfg = _load_config()
        if _init_cfg and _init_cfg.get('username'):
            _set_model_dir(_init_cfg['username'])

        global _server_error
        try:
            _start_server()
            _server_error = None
        except Exception as e:
            _server_error = str(e)
            _plog(f'[run] 서버 시작 실패: {e}')

        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.isVisible = True
        else:
            palette = ui.palettes.add(
                id=PALETTE_ID,
                name='CADverse',
                htmlFileURL='palette.html',
                isVisible=True,
                showCloseButton=True,
                isResizable=True,
                width=300,
                height=500,
            )
            palette.dockingOption = adsk.core.PaletteDockingOptions.PaletteDockOptionsToVerticalOnly
            palette.dockingState  = adsk.core.PaletteDockingStates.PaletteDockStateLeft

            on_html = _HTMLEventHandler()
            palette.incomingFromHTML.add(on_html)
            _handlers.append(on_html)

            on_closed = _PaletteClosedHandler()
            palette.closed.add(on_closed)
            _handlers.append(on_closed)

        global _palette
        _palette = palette

    except Exception:
        tb = traceback.format_exc()
        _plog(f'[run] 예외:\n{tb}')
        if ui:
            ui.messageBox('CADverse 시작 오류:\n{}'.format(tb))


def stop(context):
    global _stopping, _server_proc, _server
    _plog('[stop] 진입')
    _stopping = True
    _server = None

    # 서버 프로세스 강제 종료 — 블로킹 없이 즉시 kill
    proc, _server_proc = _server_proc, None
    _plog(f'[stop] proc={proc}, poll={proc.poll() if proc else "none"}')
    if proc:
        if proc.poll() is None:
            proc.kill()   # kill 먼저 → 파이프 write 쪽 닫힘 → readline() EOF 반환
        _plog('[stop] proc.kill 완료')

    # 혹시 남아있는 프로세스 exe 이름으로 강제 종료 (별도 스레드 — 블로킹 방지)
    def _taskkill():
        try:
            subprocess.run(
                ['taskkill', '/F', '/IM', os.path.basename(_sim_server_exe())],
                timeout=3,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
    threading.Thread(target=_taskkill, daemon=True).start()

    # UI / 이벤트 정리
    _plog('[stop] UI 정리 시작')
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        global _doc_saved_handler
        if _doc_saved_handler:
            try:
                app.documentSaved.remove(_doc_saved_handler)
            except Exception as e:
                _plog(f'[stop] documentSaved.remove 실패: {e}')
            _doc_saved_handler = None

        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.deleteMe()

        try: app.unregisterCustomEvent(PALETTE_SEND_EVENT)
        except Exception: pass
        try: app.unregisterCustomEvent(SERVER_DIED_EVENT)
        except Exception: pass
        try: app.unregisterCustomEvent(F3Z_EXPORT_EVENT)
        except Exception: pass
        try: app.unregisterCustomEvent(F3Z_IMPORT_EVENT)
        except Exception: pass
        _handlers.clear()

    except Exception:
        _plog(f'[stop] UI 정리 예외:\n{traceback.format_exc()}')

    _plog('[stop] 완료')


class _PaletteClosedHandler(adsk.core.UserInterfaceGeneralEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        _plog('[PaletteClosed] 닫힘 → 애드인 종료')
        if _stopping:
            _plog('[PaletteClosed] 이미 종료 중, 스킵')
            return
        stop(None)


class _ServerDiedHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, _):
        global _server_proc
        _plog('[ServerDied] notify')
        if _server_proc is None:
            return
        _server_proc = None
        _send_to_palette('server_status', {'running': False, 'error': '서버가 예기치 않게 종료되었습니다.'})


class _HTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            ev = adsk.core.HTMLEventArgs.cast(args)
            action = ev.action
            _plog(f'[js->py*] action={action}')
            data = json.loads(ev.data) if ev.data else {}

            if action == 'get_config':
                if _server_error:
                    _send_to_palette('server_error', {'message': _server_error})
                cfg = _load_config()
                if cfg:
                    _send_to_palette('config_loaded', cfg)
                    _set_model_dir(cfg.get('username', ''))

            elif action == 'save_config':
                _save_config(data)
                _set_model_dir(data.get('username', ''))
                _send_to_palette('config_saved', data)
                _server.init(
                    username=data.get('username', ''),
                    group=data.get('group_name', ''),
                    password=data.get('group_password', ''),
                    mode=data.get('mode', 'create'),
                )

            elif action == 'resume':
                if _model_dir:
                    try:
                        product = adsk.core.Application.get().activeProduct
                        if product and product.objectType == adsk.fusion.Design.classType():
                            _plog('[resume] extract 시작')
                            _extract.run(None, _model_dir)
                            _plog('[resume] extract 완료')
                        else:
                            _plog(f'[resume] design 없음 또는 타입 불일치: {product}')
                    except Exception as e:
                        _plog(f'[HTML] resume extract 실패: {traceback.format_exc()}')
                else:
                    _plog('[resume] _model_dir 없음')
                _plog('[resume] server.resume 호출')
                _server.resume(_model_dir or '')

            elif action == 'pause':
                _server.pause()

            elif action == 'qr_show':
                threading.Thread(target=_show_qr_window, daemon=True).start()

            elif action == 'qr_show_member':
                qr_str = data.get('qr', '')
                name   = data.get('name', '')
                if qr_str:
                    rows = [r for r in qr_str.splitlines() if r]
                    threading.Thread(target=_show_qr_window,
                                     kwargs={'rows': rows, 'title': name, 'label': name},
                                     daemon=True).start()

            elif action == 'import_model':
                name = data.get('name', '')
                if name and _model_dir and _server:
                    import_root = os.path.dirname(_model_dir)
                    _server.import_model(name, import_root)

            elif action == 'export_model':
                self._handle_export_model(data)

        except Exception as e:
            tb = traceback.format_exc()
            _plog(f'[HTML] 예외: {e}\n{tb}')
            _send_to_palette('server_error', {'message': f'[plugin 오류] {e}'})

    def _handle_export_model(self, data: dict):
        app = adsk.core.Application.get()
        if app is None:
            raise RuntimeError('Fusion Application을 가져오지 못했습니다.')

        design = app.activeProduct
        if design is None:
            raise RuntimeError('활성 Fusion design이 없습니다.')
        if not isinstance(design, adsk.fusion.Design):
            raise RuntimeError('activeProduct가 Fusion Design이 아닙니다.')

        username = _get_username_from_data_or_config(data)
        _set_model_dir(username)

        importlib.reload(_extract)
        metadata = _extract.run(None, _model_dir)

        body_count    = len(metadata.get('bodies', []))    if isinstance(metadata, dict) else 0
        joint_count   = len(metadata.get('joints', []))    if isinstance(metadata, dict) else 0
        warning_count = len(metadata.get('exportWarnings', [])) if isinstance(metadata, dict) else 0
        metadata_path = os.path.join(_model_dir, 'metadata.json')

        _send_to_palette('export_done', {
            'ok':           True,
            'username':     username,
            'output_path':  _model_dir,
            'metadata_path': metadata_path,
            'sceneName':    metadata.get('sceneName', 'cad_export_scene') if isinstance(metadata, dict) else 'cad_export_scene',
            'body_count':   body_count,
            'joint_count':  joint_count,
            'warning_count': warning_count,
        })

        app.userInterface.messageBox(
            'CADverse 모델 추출 완료\n\n'
            f'bodies: {body_count}\n'
            f'joints: {joint_count}\n'
            f'warnings: {warning_count}\n\n'
            f'metadata:\n{metadata_path}'
        )
