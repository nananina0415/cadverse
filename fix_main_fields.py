import re

# main.cs 수정 - UpdateModelFromServer 메서드에서 올바른 필드명 사용
with open("prototype/ar_client/Assets/Scripts/main.cs", "r", encoding="utf-8") as f:
    content = f.read()

# UpdateModelFromServer 메서드 수정 (position, rotation → pos, rot)
content = content.replace(
    """            // 위치와 회전 업데이트
            part.transform.localPosition = new Vector3(
                state.position.x,
                state.position.y,
                state.position.z
            );
            part.transform.localRotation = new Quaternion(
                state.rotation.x,
                state.rotation.y,
                state.rotation.z,
                state.rotation.w
            );""",
    """            // 위치와 회전 업데이트
            part.transform.localPosition = new Vector3(
                state.pos.x,
                state.pos.y,
                state.pos.z
            );
            part.transform.localRotation = state.GetQuaternion();""",
)

with open("prototype/ar_client/Assets/Scripts/main.cs", "w", encoding="utf-8") as f:
    f.write(content)

print("main.cs 수정 완료 - pos, rot 필드 사용")
