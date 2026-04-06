import adsk.core, adsk.fusion, traceback
import importlib
import os
import json

# 같은 폴더에 있는 모듈 불러오기
from . import extract_mesh
from . import extract_meta

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        # 1. 코드 수정 사항 반영 (Hot Reload)
        importlib.reload(extract_mesh)
        importlib.reload(extract_meta)

        # 2. [UI] 저장할 폴더 선택 창 띄우기
        folderDlg = ui.createFolderDialog()
        folderDlg.title = "AR 데이터 저장 경로 선택"

        # 취소 버튼 누르면 스크립트 종료
        if folderDlg.showDialog() != adsk.core.DialogResults.DialogOK:
            return

        save_folder = folderDlg.folder # 사용자가 선택한 경로

        # 3. 데이터 추출 실행 (각 파일의 run 함수 호출)

        # (A) 형상 추출: 폴더 경로를 넘겨줘서 OBJ를 저장하게 하고, 위치 정보는 받아옴
        transforms_data = extract_mesh.run(context, save_folder)

        # (B) 조인트 추출: 조인트 리스트 데이터를 받아옴
        joints_data = extract_meta.run(context)

        # 4. 데이터 병합 (하나의 JSON 구조로 만들기)
        final_metadata = {
            "info": {
                "version": "2.0",
                "description": "Fusion 360 to AR/Unity Exporter",
                "coordinate_system": "Right-Handed (Z-up)",
                "matrix_format": "Row-Major 4x4 Flattened Array (Index 0,1,2 is X-Axis Vector)",                "units": "Translation: cm (Fusion Default), Rotation: Degree"
            },
            "transforms": transforms_data, # 부품 위치 정보
            "joints": joints_data          # 조인트/관절 정보
        }

        # 5. 통합된 JSON 파일 저장
        json_path = os.path.join(save_folder, "metadata.json")
        with open(json_path, "w") as f:
            json.dump(final_metadata, f, indent=2)

        # 6. 최종 완료 메시지
        ui.messageBox(f'추출 완료!\n\n[저장 위치]\n{save_folder}\n\n[생성 파일]\n1. meshes/ (OBJ 파일들)\n2. metadata.json (위치+조인트 통합본)')

    except:
        if ui:
            ui.messageBox('Main Error:\n{}'.format(traceback.format_exc()))
