import adsk.core, adsk.fusion, traceback
import math

# 폴더 경로가 필요 없으므로 context만 받음
def run(context):
    app = adsk.core.Application.get()
    design = app.activeProduct
    root = design.rootComponent

    joints_list = []

    # 설계 내 모든 조인트 순회
    for joint in root.allJoints:
        j_name = joint.name

        # 연결된 부품 이름 가져오기
        occ_1 = joint.occurrenceOne
        occ_2 = joint.occurrenceTwo
        name_1 = occ_1.component.name.replace(' ', '_').replace(':', '_') if occ_1 else "Root"
        name_2 = occ_2.component.name.replace(' ', '_').replace(':', '_') if occ_2 else "Root"

        # 운동 정보 분석
        motion = joint.jointMotion
        motion_type = motion.objectType

        # 기본값 설정
        j_type = "Unknown"
        axis = [0, 0, 0]
        origin = [0, 0, 0]
        limits = {"min": None, "max": None}

        # 1. 회전 조인트 (Revolute)
        if motion_type == adsk.fusion.RevoluteJointMotion.classType():
            j_type = "Revolute"
            vec = motion.rotationAxisVector
            axis = [vec.x, vec.y, vec.z]

            if hasattr(joint.geometryOrOriginOne, 'origin'):
                pt = joint.geometryOrOriginOne.origin
                origin = [pt.x, pt.y, pt.z]

            # 각도 변환 (Radian -> Degree)
            rot_lim = motion.rotationLimits
            if rot_lim.isMinimumValueEnabled:
                limits["min"] = math.degrees(rot_lim.minimumValue)
            if rot_lim.isMaximumValueEnabled:
                limits["max"] = math.degrees(rot_lim.maximumValue)

        # 2. 슬라이더 조인트 (Slider)
        elif motion_type == adsk.fusion.SliderJointMotion.classType():
            j_type = "Slider"
            vec = motion.slideDirectionVector
            axis = [vec.x, vec.y, vec.z]

            # 거리 변환 (cm -> mm)
            slide_lim = motion.slideLimits
            if slide_lim.isMinimumValueEnabled:
                limits["min"] = slide_lim.minimumValue * 10.0
            if slide_lim.isMaximumValueEnabled:
                limits["max"] = slide_lim.maximumValue * 10.0

        # 3. 고정 조인트 (Rigid)
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

    # 수집한 리스트를 main.py에게 반환(Return)
    return joints_list
