#!/usr/bin/env python3
"""
OBJ 파일의 좌표를 스케일링하는 스크립트
Fusion 360의 mm 단위를 Unity의 m 단위로 변환 (1/1000 스케일)
"""

import sys
import os

def scale_obj_file(input_path, output_path, scale_factor=0.001):
    """
    OBJ 파일의 모든 vertex 좌표를 스케일링

    Args:
        input_path: 입력 OBJ 파일 경로
        output_path: 출력 OBJ 파일 경로
        scale_factor: 스케일 팩터 (기본값: 0.001 = mm to m)
    """
    with open(input_path, 'r', encoding='utf-8') as f_in:
        with open(output_path, 'w', encoding='utf-8') as f_out:
            for line in f_in:
                # vertex 좌표 라인 (v x y z)
                if line.startswith('v '):
                    parts = line.split()
                    if len(parts) >= 4:
                        # v 명령어와 x, y, z 좌표
                        x = float(parts[1]) * scale_factor
                        y = float(parts[2]) * scale_factor
                        z = float(parts[3]) * scale_factor

                        # 추가 데이터가 있을 수 있음 (w, color 등)
                        extra = ' '.join(parts[4:])
                        if extra:
                            f_out.write(f"v {x} {y} {z} {extra}\n")
                        else:
                            f_out.write(f"v {x} {y} {z}\n")
                    else:
                        f_out.write(line)
                else:
                    # vertex가 아닌 라인은 그대로 복사
                    f_out.write(line)

    print(f"[OK] Converted: {input_path} -> {output_path} (scale: {scale_factor})")

if __name__ == "__main__":
    # model 폴더의 모든 OBJ 파일 변환
    model_dir = "model"

    if not os.path.exists(model_dir):
        print(f"Error: {model_dir} directory not found")
        sys.exit(1)

    obj_files = [f for f in os.listdir(model_dir) if f.endswith('.obj')]

    if not obj_files:
        print(f"No OBJ files found in {model_dir}")
        sys.exit(1)

    print(f"Found {len(obj_files)} OBJ file(s)")
    print("Converting mm to meters (scale: 0.001)...\n")

    for obj_file in obj_files:
        input_path = os.path.join(model_dir, obj_file)
        # 원본 백업
        backup_path = os.path.join(model_dir, obj_file.replace('.obj', '_original.obj'))

        # 백업이 없으면 원본을 백업
        if not os.path.exists(backup_path):
            os.rename(input_path, backup_path)
            print(f"[OK] Backup: {obj_file} -> {os.path.basename(backup_path)}")

            # 백업된 파일을 변환하여 원본 이름으로 저장
            scale_obj_file(backup_path, input_path, scale_factor=0.001)
        else:
            print(f"[WARN] Backup already exists: {os.path.basename(backup_path)}, skipping {obj_file}")

    print("\n[OK] Conversion complete!")
    print(f"Original files backed up as *_original.obj")
