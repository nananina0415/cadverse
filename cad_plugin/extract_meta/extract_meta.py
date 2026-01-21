# 구속조건 및 조인트 등을 추출하여 json 데이터로 반환
import adsk.core, adsk.fusion, traceback
import os
import json
import math

def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        design = app.activeProduct
        root = design.rootComponent

        # 1. 저장 경로 설정 (바탕화면 > AR_Project)
        user_home = os.path.expanduser("~")
        base_folder = os.path.join(user_home, "Desktop", "AR_Project")

        if not os.path.exists(base_folder):
            os.makedirs(base_folder)

        joints_list = []

        # 2. 모든 조인트 정보 추출
        for joint in root.allJoints:
            j_name = joint.name

            # 연결된 부품 이름 가져오기 (없으면 Root)
            occ_1 = joint.occurrenceOne
            occ_2 = joint.occurrenceTwo
            name_1 = occ_1.component.name.replace(' ', '_').replace(':', '_') if occ_1 else "Root"
            name_2 = occ_2.component.name.replace(' ', '_').replace(':', '_') if occ_2 else "Root"

            # 조인트 모션 및 타입 분석
            motion = joint.jointMotion
            motion_type = motion.objectType

            j_type = "Unknown"
            axis = [0, 0, 0]
            origin = [0, 0, 0]
            limits = {"min": None, "max": None}

            # [Type A] 회전 조인트 (Revolute)
            if motion_type == adsk.fusion.RevoluteJointMotion.classType():
                j_type = "Revolute"

                # 축(Axis) 및 원점(Origin)
                vec = motion.rotationAxisVector
                axis = [vec.x, vec.y, vec.z]

                if hasattr(joint.geometryOrOriginOne, 'origin'):
                    pt = joint.geometryOrOriginOne.origin
                    origin = [pt.x, pt.y, pt.z]

                # 각도 제한 (Radian -> Degree 변환)
                rot_lim = motion.rotationLimits
                if rot_lim.isMinimumValueEnabled:
                    limits["min"] = math.degrees(rot_lim.minimumValue)
                if rot_lim.isMaximumValueEnabled:
                    limits["max"] = math.degrees(rot_lim.maximumValue)

            # [Type B] 슬라이더 조인트 (Slider)
            elif motion_type == adsk.fusion.SliderJointMotion.classType():
                j_type = "Slider"

                vec = motion.slideDirectionVector
                axis = [vec.x, vec.y, vec.z]

                # 거리 제한 (cm -> mm 변환, 퓨전 기본단위는 cm)
                slide_lim = motion.slideLimits
                if slide_lim.isMinimumValueEnabled:
                    limits["min"] = slide_lim.minimumValue * 10.0
                if slide_lim.isMaximumValueEnabled:
                    limits["max"] = slide_lim.maximumValue * 10.0

            # [Type C] 고정 조인트 (Rigid)
            elif motion_type == adsk.fusion.RigidJointMotion.classType():
                j_type = "Rigid"

            # 데이터 구조화
            joint_info = {
                "name": j_name,
                "type": j_type,
                "connected_parts": {"parent": name_1, "child": name_2},
                "axis": axis,
                "origin": origin,
                "limits": limits
            }
            joints_list.append(joint_info)

        # 3. JSON 파일 저장
        json_path = os.path.join(base_folder, "joints.json")
        with open(json_path, "w") as f:
            json.dump(joints_list, f, indent=2)

        ui.messageBox(f'완료: 조인트 {len(joints_list)}개 정보 저장됨\n파일: joints.json')

    except:
        if ui:
            ui.messageBox('Error:\n{}'.format(traceback.format_exc()))
