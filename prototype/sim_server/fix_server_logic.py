with open("prototype/sim_server/server_logic.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# __init__ 메서드 찾아서 수정
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]

    # __init__ 시그니처 찾기
    if "def __init__(self, server: Server, getModelState:" in line:
        # 다음 줄까지 읽기
        if i + 1 < len(lines) and '"""' in lines[i + 1]:
            # 시그니처 수정
            new_lines.append(
                '    def __init__(self, server: Server, getModelState: "Callable[[], List[PartState]]",\n'
            )
            new_lines.append("                 simulation):\n")
            i += 1
            new_lines.append(lines[i])  # """ 라인 추가
            i += 1
            # docstring 수정
            while i < len(lines) and '"""' not in lines[i]:
                new_lines.append(lines[i])
                i += 1
            # 마지막 """ 전에 simulation 설명 추가
            new_lines.append("            simulation: Simulation 객체 (힘 계산용)\n")
            new_lines.append(lines[i])  # 닫는 """ 추가
            i += 1
            continue

    # self.server_thread = None 다음에 touch_state 추가
    if "self.server_thread = None" in line:
        new_lines.append(line)
        i += 1
        # 빈 줄 건너뛰기
        while i < len(lines) and lines[i].strip() == "":
            new_lines.append(lines[i])
            i += 1
        # simulation과 touch_state 추가
        new_lines.append("        self.simulation = simulation\n")
        new_lines.append("        \n")
        new_lines.append("        # 터치 상태 추적\n")
        new_lines.append("        self.touch_state = {\n")
        new_lines.append('            "active": False,\n')
        new_lines.append('            "part_index": -1,\n')
        new_lines.append('            "action_point_local": None  # ChVector3d\n')
        new_lines.append("        }\n")
        continue

    # receiveTask 내부에서 메시지 처리 부분 찾기 (while True: 이후)
    if "data = await websocket.receive_text()" in line and i > 0:
        new_lines.append(line)
        i += 1
        # print 라인 찾기
        if 'print(f"[ws] <- 클라이언트: {data}")' in lines[i]:
            i += 1  # print 라인 건너뛰기
            # 빈 줄도 건너뛰기
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            # DTO로 파싱 라인도 건너뛰기
            if "user_input_msg = UserInputMessage.fromJson(data)" in lines[i]:
                i += 1

            # 새 코드 삽입
            new_lines.append("                        \n")
            new_lines.append("                        # JSON 파싱하여 타입 확인\n")
            new_lines.append("                        import json\n")
            new_lines.append("                        msg = json.loads(data)\n")
            new_lines.append('                        msg_type = msg.get("type")\n')
            new_lines.append("                        \n")
            new_lines.append("                        # TouchStart 메시지 처리\n")
            new_lines.append('                        if msg_type == "TouchStart":\n')
            new_lines.append(
                '                            payload = msg.get("payload", {})\n'
            )
            new_lines.append(
                '                            part_idx = payload.get("targetPartIndex", -1)\n'
            )
            new_lines.append(
                '                            action_pt = payload.get("actionPoint", {})\n'
            )
            new_lines.append("                            \n")
            new_lines.append("                            # 터치 상태 저장\n")
            new_lines.append("                            self.touch_state = {\n")
            new_lines.append('                                "active": True,\n')
            new_lines.append(
                '                                "part_index": part_idx,\n'
            )
            new_lines.append(
                '                                "action_point_local": ChVector3d(\n'
            )
            new_lines.append(
                "                                    action_pt.get('x', 0),\n"
            )
            new_lines.append(
                "                                    action_pt.get('y', 0),\n"
            )
            new_lines.append(
                "                                    action_pt.get('z', 0)\n"
            )
            new_lines.append("                                )\n")
            new_lines.append("                            }\n")
            new_lines.append("                            \n")
            new_lines.append("                            print(\n")
            new_lines.append(
                '                                f"[TouchStart] Part #{part_idx} | "\n'
            )
            new_lines.append(
                "                                f\"ActionPoint: ({action_pt.get('x', 0):.3f}, \"\n"
            )
            new_lines.append(
                "                                f\"{action_pt.get('y', 0):.3f}, \"\n"
            )
            new_lines.append(
                "                                f\"{action_pt.get('z', 0):.3f})\"\n"
            )
            new_lines.append("                            )\n")
            new_lines.append("                            continue\n")
            new_lines.append("                        \n")
            new_lines.append(
                "                        # Touching 메시지 처리 - 힘 벡터 계산\n"
            )
            new_lines.append('                        if msg_type == "Touching":\n')
            new_lines.append(
                '                            if not self.touch_state["active"]:\n'
            )
            new_lines.append("                                continue\n")
            new_lines.append("                                \n")
            new_lines.append(
                '                            payload = msg.get("payload", {})\n'
            )
            new_lines.append(
                '                            finger_pt_dict = payload.get("fingerPoint", {})\n'
            )
            new_lines.append(
                "                            finger_pt_global = ChVector3d(\n"
            )
            new_lines.append(
                "                                finger_pt_dict.get('x', 0),\n"
            )
            new_lines.append(
                "                                finger_pt_dict.get('y', 0),\n"
            )
            new_lines.append(
                "                                finger_pt_dict.get('z', 0)\n"
            )
            new_lines.append("                            )\n")
            new_lines.append("                            \n")
            new_lines.append("                            # 부품 ChBody 가져오기\n")
            new_lines.append(
                '                            part_idx = self.touch_state["part_index"]\n'
            )
            new_lines.append(
                "                            bodies = self.simulation.simHandle.bodies\n"
            )
            new_lines.append(
                "                            if part_idx < 0 or part_idx >= len(bodies):\n"
            )
            new_lines.append("                                continue\n")
            new_lines.append("                                \n")
            new_lines.append("                            body = bodies[part_idx]\n")
            new_lines.append("                            \n")
            new_lines.append("                            # 글로벌 → 로컬 변환\n")
            new_lines.append(
                "                            finger_pt_local = body.TransformPointParentToLocal(\n"
            )
            new_lines.append("                                finger_pt_global\n")
            new_lines.append("                            )\n")
            new_lines.append("                            \n")
            new_lines.append(
                "                            # 힘 벡터 = fingerPoint(로컬) - actionPoint(로컬)\n"
            )
            new_lines.append(
                '                            action_pt = self.touch_state["action_point_local"]\n'
            )
            new_lines.append(
                "                            force_vector = finger_pt_local - action_pt\n"
            )
            new_lines.append("                            \n")
            new_lines.append("                            print(\n")
            new_lines.append(
                '                                f"[Force] ({force_vector.x:.3f}, "\n'
            )
            new_lines.append(
                '                                f"{force_vector.y:.3f}, {force_vector.z:.3f})"\n'
            )
            new_lines.append("                            )\n")
            new_lines.append("                            continue\n")
            new_lines.append("                        \n")
            new_lines.append("                        # TouchEnd 메시지 처리\n")
            new_lines.append('                        if msg_type == "TouchEnd":\n')
            new_lines.append(
                '                            self.touch_state["active"] = False\n'
            )
            new_lines.append(
                '                            print("[TouchEnd] 터치 종료")\n'
            )
            new_lines.append("                            continue\n")
            new_lines.append("\n")
            continue

    new_lines.append(line)
    i += 1

with open("prototype/sim_server/server_logic.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("server_logic.py 수정 완료")
