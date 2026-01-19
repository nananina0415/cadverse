# 모든 부품의 형상정보를 obj 데이터로 반환
import adsk.core, adsk.fusion, traceback
import os
import json

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        design = app.activeProduct
        exportMgr = design.exportManager

        # 1. 저장 경로 설정 (바탕화면 > AR_Project)
        user_home = os.path.expanduser("~")
        base_folder = os.path.join(user_home, "Desktop", "AR_Project")
        mesh_folder = os.path.join(base_folder, "meshes")

        if not os.path.exists(mesh_folder):
            os.makedirs(mesh_folder)

        root = design.rootComponent
        transform_map = {}
        count = 0

        # 2. 모든 부품 순회 및 데이터 추출
        for occ in root.allOccurrences:
            # 이름 정리 (공백/특수문자 제거)
            comp_name = occ.component.name.replace(':', '_').replace(' ', '_')

            # [A] OBJ 파일 내보내기
            filename = os.path.join(mesh_folder, f"{comp_name}.obj")
            objOpt = exportMgr.createOBJExportOptions(occ, filename)
            exportMgr.execute(objOpt)

            # [B] 위치 행렬(Matrix) 추출
            transform_map[comp_name] = occ.transform.asArray()
            count += 1

        # 3. 위치 정보 JSON 저장
        json_path = os.path.join(base_folder, "transforms.json")
        with open(json_path, "w") as f:
            json.dump(transform_map, f, indent=2)

        ui.messageBox(f'완료: 총 {count}개 부품 저장됨')

    except:
        if ui:
            ui.messageBox('Error:\n{}'.format(traceback.format_exc()))
