# 각 추출 코드를 불러 사용하여 지정된 폴더에 저장
import adsk.core, adsk.fusion, traceback
import importlib

# 같은 폴더에 있는 추출 모듈 가져오기
# 주의: 반드시 extract_mesh.py, extract_meta.py가 main.py와 같은 폴더에 있어야 함
from . import extract_mesh
from . import extract_meta

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        # ---------------------------------------------------
        # 1. 모듈 새로고침 (Hot Reload)
        # ---------------------------------------------------
        # 코드를 수정하고 Fusion 360을 껐다 켜지 않아도 반영되도록 함
        importlib.reload(extract_mesh)
        importlib.reload(extract_meta)

        # ---------------------------------------------------
        # 2. 형상 추출 (Mesh Extraction)
        # ---------------------------------------------------
        # extract_mesh.py의 run 함수 실행
        extract_mesh.run(context)

        # ---------------------------------------------------
        # 3. 메타 데이터 추출 (Meta/Joint Extraction)
        # ---------------------------------------------------
        # extract_meta.py의 run 함수 실행
        extract_meta.run(context)

        # ---------------------------------------------------
        # 4. 완료 메시지
        # ---------------------------------------------------
        ui.messageBox('All Tasks Completed Successfully!\n\n1. Meshes (.obj)\n2. Transforms (.json)\n3. Joints (.json)')

    except:
        if ui:
            ui.messageBox('Main Execution Failed:\n{}'.format(traceback.format_exc()))
