import os

def rescale_obj(obj_str:str, scale=0.001)->str:
    """
    OBJ 문자열을 받아 모든 'v ' 정점 좌표를 scale 배로 줄임 (기본: 0.001 → mm→m)
    """
    rescaled_lines = []
    for line in obj_str.splitlines(keepends=True):
        if line.startswith('v '):  # 정점 좌표 라인만 변환
            parts = line.strip().split()
            if len(parts) >= 4:
                try:
                    x, y, z = [float(p) * scale for p in parts[1:4]]
                    rescaled_lines.append(f"v {x:.6f} {y:.6f} {z:.6f}\n")
                except ValueError:
                    rescaled_lines.append(line)  # 숫자 파싱 실패 시 원본 유지
            else:
                rescaled_lines.append(line)
        else:
            rescaled_lines.append(line)

    return ''.join(rescaled_lines)

# 사실 위에 것만 있어도 되는데 명확한 이름이 필요한 경우 사용할 수 있음
def rescale_obj_mm_to_m(obj_str:str)->str:
    """
    OBJ 문자열을 받아 모든 'v ' 정점 좌표를 1/1000 배로 줄임(mm→m)
    """
    return rescale_obj(obj_str, scale=0.001)
