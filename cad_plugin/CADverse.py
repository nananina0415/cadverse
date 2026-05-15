# CADverse.py

import adsk.core
import adsk.fusion
import traceback
import os
import re
import json
import importlib

from . import extract as _extract

# ── 전역 상태 ──────────────────────────────────────────────────────────────────

_handlers = []   # Fusion 360 핸들러 참조 유지 (GC 방지)
_palette = None

PALETTE_ID = 'cadverse_palette'

# ── 경로 헬퍼 ──────────────────────────────────────────────────────────────────

def _plugin_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _config_path() -> str:
    return os.path.join(_plugin_dir(), 'config.json')


def _model_path(username: str) -> str:
    sim_server_dir = os.path.join(_plugin_dir(), '..', 'sim_server')
    return os.path.normpath(os.path.join(sim_server_dir, 'models', username))


def _sanitize_username(username: str) -> str:
    s = str(username or "default_user")
    s = s.replace(" ", "_").replace(":", "_")
    s = re.sub(r"[^A-Za-z0-9가-힣_\-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "default_user"


def _load_config() -> dict:
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg: dict):
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _get_username_from_data_or_config(data: dict) -> str:
    """
    HTML에서 username을 직접 넘기면 그 값을 사용하고,
    없으면 config.json의 username / user / name 후보를 사용한다.
    그래도 없으면 default_user.
    """
    candidates = [
        data.get("username"),
        data.get("user"),
        data.get("name"),
    ]

    cfg = _load_config()
    candidates.extend([
        cfg.get("username"),
        cfg.get("user"),
        cfg.get("name"),
    ])

    for c in candidates:
        if c is not None and str(c).strip():
            return _sanitize_username(str(c))

    return "default_user"


# ── Addin 진입점 ───────────────────────────────────────────────────────────────

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

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
            palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateLeft

            on_html = _HTMLEventHandler()
            palette.incomingFromHTML.add(on_html)
            _handlers.append(on_html)

        global _palette
        _palette = palette

    except Exception:
        if ui:
            ui.messageBox('CADverse 시작 오류:\n{}'.format(traceback.format_exc()))


def stop(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.deleteMe()

        _handlers.clear()

    except Exception:
        if ui:
            ui.messageBox('CADverse 종료 오류:\n{}'.format(traceback.format_exc()))


# ── Palette → Python 명령 처리 ─────────────────────────────────────────────────

class _HTMLEventHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            ev = adsk.core.HTMLEventArgs.cast(args)
            action = ev.action
            data = json.loads(ev.data) if ev.data else {}

            if action == 'get_config':
                cfg = _load_config()
                _send_to_palette('config_saved', cfg)

            elif action == 'save_config':
                _save_config(data)
                _send_to_palette('config_saved', data)

            elif action == 'export_model':
                self._handle_export_model(data)

            # Phase 4: pause / resume / qr_show / qr_hide 처리 예정

            else:
                _send_to_palette('unknown_action', {
                    'ok': False,
                    'action': action,
                    'message': f"Unknown action: {action}"
                })

        except Exception:
            msg = traceback.format_exc()

            _send_to_palette('export_error', {
                'ok': False,
                'message': msg
            })

            try:
                app = adsk.core.Application.get()
                if app:
                    app.userInterface.messageBox("CADverse 오류:\n\n" + msg)
            except Exception:
                pass

    def _handle_export_model(self, data: dict):
        """
        CAD 모델을 sim_server/models/<username>/ 아래로 export한다.

        결과:
        sim_server/models/<username>/
          ├─ metadata.json
          └─ meshes/
              ├─ ...
        """
        app = adsk.core.Application.get()
        if app is None:
            raise RuntimeError("Fusion Application을 가져오지 못했습니다.")

        design = app.activeProduct
        if design is None:
            raise RuntimeError("활성 Fusion design이 없습니다.")

        if not isinstance(design, adsk.fusion.Design):
            raise RuntimeError("activeProduct가 Fusion Design이 아닙니다.")

        username = _get_username_from_data_or_config(data)
        output_path = _model_path(username)

        os.makedirs(output_path, exist_ok=True)

        # 개발 중 reload해서 파일 수정 후 Fusion 재시작 없이 반영되게 함
        importlib.reload(_extract)

        metadata = _extract.run(None, output_path)

        body_count = len(metadata.get("bodies", [])) if isinstance(metadata, dict) else 0
        joint_count = len(metadata.get("joints", [])) if isinstance(metadata, dict) else 0
        warning_count = len(metadata.get("exportWarnings", [])) if isinstance(metadata, dict) else 0
        metadata_path = os.path.join(output_path, "metadata.json")

        _send_to_palette('export_done', {
            'ok': True,
            'username': username,
            'output_path': output_path,
            'metadata_path': metadata_path,
            'sceneName': metadata.get("sceneName", "cad_export_scene") if isinstance(metadata, dict) else "cad_export_scene",
            'body_count': body_count,
            'joint_count': joint_count,
            'warning_count': warning_count,
        })

        # Fusion → HTML 콜백이 안 보이는 경우를 대비한 확실한 완료 알림
        app.userInterface.messageBox(
            "CADverse 모델 추출 완료\n\n"
            f"bodies: {body_count}\n"
            f"joints: {joint_count}\n"
            f"warnings: {warning_count}\n\n"
            f"metadata:\n{metadata_path}"
        )


def _send_to_palette(action: str, data: dict):
    try:
        if _palette and _palette.isValid:
            _palette.sendInfoToHTML(action, json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


# ── DocumentSaved / DocumentClosed 이벤트 (Phase 5에서 구현) ──────────────────
# 이벤트 핸들러 등록은 Phase 5에서 추가