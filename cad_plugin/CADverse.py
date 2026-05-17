import adsk.core, adsk.fusion, traceback
import os, json, subprocess, threading
import tkinter as tk

from . import extract as _extract
from .server import RustServer

_handlers          = []
_palette           = None
_server_proc       = None
_server             = None
_server_error      = None
_send_queue        = []
_stopping          = False
_model_dir         = None
_doc_saved_handler = None

SERVER_DIED_EVENT  = 'cadverse_server_died'
PALETTE_SEND_EVENT = 'cadverse_palette_send'
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
    override = _debug_config().get('server_exe')
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
    with open(_config_path(), 'w') as f:
        json.dump(cfg, f, indent=2)

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
        except Exception as e:
            _plog(f'[DocSaved] extract 실패: {e}')


def _show_qr_window():
    path = os.path.join(os.path.dirname(_sim_server_exe()), 'local_sim_qr.txt')
    try:
        rows = [r for r in open(path, encoding='utf-8').read().splitlines() if r]
    except Exception:
        return
    if not rows:
        return

    username = _load_config().get('username', '')

    root = tk.Tk()
    root.title('CADverse QR')
    root.resizable(False, False)
    root.attributes('-topmost', True)

    dpi      = root.winfo_fpixels('1i')
    target_px = int((5.0 / 2.54) * dpi)   # 5cm → pixels
    n_cols   = max(len(r) for r in rows)
    cell     = max(1, target_px // n_cols)
    margin   = cell * 4

    w = n_cols * cell + margin * 2
    h = len(rows) * cell + margin * 2

    canvas = tk.Canvas(root, width=w, height=h, bg='white', highlightthickness=0)
    canvas.pack()

    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == '1':
                x0, y0 = margin + x * cell, margin + y * cell
                canvas.create_rectangle(x0, y0, x0 + cell, y0 + cell, fill='black', outline='')

    if username:
        tk.Label(root, text=username, font=('Segoe UI', 11), bg='white').pack(pady=(0, margin // 2))

    root.bind('<Escape>', lambda _: root.destroy())
    root.mainloop()


def _pipe_reader_thread():
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
            except json.JSONDecodeError:
                pass
        except Exception as e:
            _plog(f'[reader] 예외: {e}')
            break
    if not _stopping:
        _send_to_palette('server_status', {'running': False, 'error': '서버 연결이 끊어졌습니다.'})

def _start_server():
    global _server_proc, _server
    exe = _sim_server_exe()
    if not os.path.exists(exe):
        raise FileNotFoundError(f'sim_server.exe 없음: {exe}')
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
    _server_proc = subprocess.Popen(
        [exe],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_file,
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
    global _stopping, _server_proc
    _stopping = True
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        proc, _server_proc = _server_proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.terminate()

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

        app.unregisterCustomEvent(PALETTE_SEND_EVENT)
        app.unregisterCustomEvent(SERVER_DIED_EVENT)
        _handlers.clear()

    except Exception:
        tb = traceback.format_exc()
        _plog(f'[stop] 예외:\n{tb}')
        if ui:
            ui.messageBox('CADverse 종료 오류:\n{}'.format(tb))


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
                            _extract.run(None, _model_dir)
                    except Exception as e:
                        _plog(f'[HTML] resume extract 실패: {e}')
                _server.resume(_model_dir or '')

            elif action == 'pause':
                _server.pause()

            elif action == 'qr_show':
                threading.Thread(target=_show_qr_window, daemon=True).start()

        except Exception as e:
            tb = traceback.format_exc()
            _plog(f'[HTML] 예외: {e}\n{tb}')
            _send_to_palette('server_error', {'message': f'[plugin 오류] {e}'})
