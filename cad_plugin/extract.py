import adsk.core
import importlib
import os
import json

from . import extract_mesh
from . import extract_meta


def run(context, output_path: str):
    """meshes/ 먼저 저장, metadata.json 마지막 저장."""
    importlib.reload(extract_mesh)
    importlib.reload(extract_meta)

    os.makedirs(output_path, exist_ok=True)

    transforms_data = extract_mesh.run(context, output_path)
    joints_data     = extract_meta.run(context)

    metadata = {
        "info": {
            "version": "2.0",
            "coordinate_system": "Right-Handed (Z-up)",
            "matrix_format": "Row-Major 4x4 Flattened Array (Index 0,1,2 is X-Axis Vector)",
            "units": "Translation: cm, Rotation: Degree"
        },
        "transforms": transforms_data,
        "joints":     joints_data,
    }

    with open(os.path.join(output_path, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)
