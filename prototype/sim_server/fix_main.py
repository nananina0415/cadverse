import re

# main.py 수정
with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# ServerRunner 호출에 sim 추가
content = re.sub(
    r"ServerRunner\(server, sim\.modelState\.getReadAccess\(doDeepCopy=False\)\)",
    r"ServerRunner(server, sim.modelState.getReadAccess(doDeepCopy=False), sim)",
    content,
)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)

print("main.py 수정 완료")
