import adsk.core, adsk.fusion, traceback
import os, re, shutil, json

from . import extract as _extract

# ── 전역 상태 ──────────────────────────────────────────────────────────────────

_handlers = []   # Fusion 360 핸들러 참조 유지 (GC 방지)
_palette  = None

PALETTE_ID = 'cadverse_palette'

# ── 경로 헬퍼 ──────────────────────────────────────────────────────────────────

def _plugin_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))

def _config_path() -> str:
    return os.path.join(_plugin_dir(), 'config.json')

def _model_path(username: str) -> str:
    sim_server_dir = os.path.join(_plugin_dir(), '..', 'sim_server')
    return os.path.normpath(os.path.join(sim_server_dir, 'models', username))

def _load_config() -> dict:
    try:
        with open(_config_path()) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_config(cfg: dict):
    with open(_config_path(), 'w') as f:
        json.dump(cfg, f, indent=2)

# ── Addin 진입점 ───────────────────────────────────────────────────────────────

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

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

        global _palette
        _palette = palette

    except:
        if ui:
            ui.messageBox('CADverse 시작 오류:\n{}'.format(traceback.format_exc()))


def stop(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.deleteMe()

        _handlers.clear()

    except:
        if ui:
            ui.messageBox('CADverse 종료 오류:\n{}'.format(traceback.format_exc()))

# ── Palette → Python 명령 처리 ─────────────────────────────────────────────────

class _HTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            ev     = adsk.core.HTMLEventArgs.cast(args)
            action = ev.action
            data   = json.loads(ev.data) if ev.data else {}

            if action == 'get_config':
                cfg = _load_config()
                if cfg:
                    _send_to_palette('config_saved', cfg)

            elif action == 'save_config':
                _save_config(data)
                _send_to_palette('config_saved', data)

            # Phase 4: pause / resume / qr_show / qr_hide 처리 예정

        except:
            pass


def _send_to_palette(action: str, data: dict):
    if _palette and _palette.isValid:
        _palette.sendInfoToHTML(action, json.dumps(data, ensure_ascii=False))

# ── DocumentSaved / DocumentClosed 이벤트 (Phase 5에서 구현) ──────────────────
# 이벤트 핸들러 등록은 Phase 5에서 추가
