import os

def rescale_obj_mm_to_m(input_path, output_path, scale=0.001):
    """
    OBJ 파일을 읽어서 모든 'v ' 정점 좌표를 scale 배로 줄임 (기본: 0.001 → mm→m)
    """
    with open(input_path, 'r', encoding='utf-8') as fin, \
         open(output_path, 'w', encoding='utf-8') as fout:
        for line in fin:
            if line.startswith('v '):  # 정점 좌표 라인만 변환
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        x, y, z = [float(p) * scale for p in parts[1:4]]
                        fout.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
                    except ValueError:
                        fout.write(line)  # 숫자 파싱 실패 시 원본 유지
                else:
                    fout.write(line)
            else:
                fout.write(line)

if __name__ == "__main__":
    # 변환할 파일 목록
    input_files = [
        "shaft.obj",
        "base.obj",
    ]
    for fn in input_files:
        output_fn = fn.replace(".obj", "_scaled.obj")
        rescale_obj_mm_to_m(fn, output_fn, scale=0.001)
        print(f"[완료] {fn} → {output_fn}")
