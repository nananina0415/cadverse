import adsk.core, adsk.fusion, traceback
import os

# [핵심 수정] main에서 넘겨준 save_folder를 받을 수 있도록 인자 추가
def run(context, save_folder):
    app = adsk.core.Application.get()
    design = app.activeProduct
    exportMgr = design.exportManager
    root = design.rootComponent

    # 1. meshes 폴더 생성 (OBJ 파일 저장용)
    mesh_folder = os.path.join(save_folder, "meshes")
    if not os.path.exists(mesh_folder):
        os.makedirs(mesh_folder)

    transform_data = {}

    # 2. 모든 부품 순회 및 데이터 추출
    for occ in root.allOccurrences:
        # 파일명 및 ID로 쓸 이름 정리
        comp_name = occ.component.name.replace(':', '_').replace(' ', '_')

        # (A) OBJ 파일은 여기서 즉시 저장
        filename = os.path.join(mesh_folder, f"{comp_name}.obj")
        objOpt = exportMgr.createOBJExportOptions(occ, filename)
        exportMgr.execute(objOpt)

        # (B) 위치 정보(Matrix)는 딕셔너리에 담기 (저장 X)
        # 4x4 행렬을 리스트 형태로 변환하여 저장
        transform_data[comp_name] = occ.transform.asArray()

    # 3. 수집한 위치 데이터를 main.py에게 반환(Return)
    return transform_data
