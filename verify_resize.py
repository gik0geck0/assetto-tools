import json
from pathlib import Path

# Mock tire_model.json
model = {
    "widths_mm": [200, 210, 220],
    "poly_degree": 1,
    "sections": {
        "FRONT": {
            "DX_REF": {"poly": [0.01, 1.0], "r2": 1.0}  # DX_REF = 0.01 * width_mm + 1.0
        }
    },
    "constant_properties": {"FRONT": {}}
}

with open('tire_model.json', 'w') as f:
    json.dump(model, f)

# Mock tyres.ini
# Original width: 0.200m (200mm)
# DX_REF: 1.5
# poly at 200: 0.01*200 + 1.0 = 3.0
# poly at 210: 0.01*210 + 1.0 = 3.1
# Delta: 3.1 - 3.0 = 0.1
# Expected DX_REF: 1.5 + 0.1 = 1.6
ini_content = """[FRONT]
NAME="Test Tire"
WIDTH=0.200
DX_REF=1.500
"""

with open('tyres.ini', 'w') as f:
    f.write(ini_content)

print("Test setup complete.")
