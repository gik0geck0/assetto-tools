import argparse
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tire_lib

FZ_ASSUMED = 3335.7

def _parse_file_spec(spec: str) -> Tuple[Path, Optional[int|str]]:
    if not spec:
        return Path('tyres.ini'), 0
    parts = spec.rsplit(':', 1)
    if len(parts) == 2 and Path(parts[0]).exists():
        file_path = Path(parts[0])
        selector_str = parts[1]
        try:
            return file_path, int(selector_str)
        except ValueError:
            return file_path, selector_str.strip('"\'')
            
    # If no colon but file doesn't exist, maybe it's a selector for tyres.ini
    if not Path(spec).exists() and Path('tyres.ini').exists():
        try:
            return Path('tyres.ini'), int(spec)
        except ValueError:
            return Path('tyres.ini'), spec.strip('"\'')

    return Path(spec), None

def calc_grip(props: Dict[str, str], gamma_deg: float) -> Tuple[float, float, float, float, float, float]:
    """Calculate (Dy, Dx, G_lat, G_long, G_mag, target_slip_pct) for a given slip angle gamma_deg."""
    FZ0 = float(props.get('FZ0', '1.0'))
    if FZ0 <= 0: FZ0 = 1.0
    
    DY_REF = float(props.get('DY_REF', '1.0'))
    DX_REF = float(props.get('DX_REF', '1.0'))
    LS_EXPY = float(props.get('LS_EXPY', '1.0'))
    LS_EXPX = float(props.get('LS_EXPX', '1.0'))
    FALLOFF_LEVEL = float(props.get('FALLOFF_LEVEL', '1.0'))
    FALLOFF_SPEED = float(props.get('FALLOFF_SPEED', '1.0'))
    FRICTION_LIMIT_ANGLE = float(props.get('FRICTION_LIMIT_ANGLE', '8.0'))
    CX_MULT = float(props.get('CX_MULT', '1.0'))
    
    FLEX = float(props.get('FLEX', '0.0007'))
    RADIUS = float(props.get('RADIUS', '0.3'))
    SPEED_SENSITIVITY = float(props.get('SPEED_SENSITIVITY', '0.003'))
    
    # Target Slip Ratio Calculation (at ~40mph = 17.8 m/s)
    V_mps = 17.8
    R_eff = RADIUS + (SPEED_SENSITIVITY * V_mps)
    base_slip = (FLEX * 10000.0) * (FALLOFF_SPEED / 2.0)
    target_slip_pct = base_slip * (1.0 + (gamma_deg / 90.0)**2) * (RADIUS / R_eff) * 10.0
    
    Dy = DY_REF * ((FZ_ASSUMED / FZ0) ** (LS_EXPY - 1.0))
    Dx_base = DX_REF * ((FZ_ASSUMED / FZ0) ** (LS_EXPX - 1.0))
    Dx = Dx_base * CX_MULT
    
    if gamma_deg <= FRICTION_LIMIT_ANGLE:
        M = 1.0
    else:
        gamma_diff_rad = math.radians(gamma_deg - FRICTION_LIMIT_ANGLE)
        M = FALLOFF_LEVEL + (1.0 - FALLOFF_LEVEL) * math.exp(-FALLOFF_SPEED * gamma_diff_rad)
        
    gamma_rad = math.radians(gamma_deg)
    
    G_lat = Dy * M * math.cos(gamma_rad)
    G_long = Dx * M * math.sin(gamma_rad)
    G_mag = math.sqrt(G_lat**2 + G_long**2)
    
    return Dy, Dx, G_lat, G_long, G_mag, target_slip_pct

def print_separator(width: int = 85):
    print("-" * width)

def print_row(cols: List[str], widths: List[int]):
    padded = [cols[i].ljust(widths[i]) for i in range(len(cols))]
    print(" | ".join(padded))

def process_tires(tires: List[Dict[str, Dict[str, str]]], show_front: bool, show_rear: bool):
    widths = [20, 10, 5, 10, 10, 10, 10]
    headers = ["Tire Name", "Section", "Dir", "Peak G", "PeakYaw G", "35deg G", "60deg G"]
    
    print_separator(sum(widths) + len(widths) * 3 - 1)
    print_row(headers, widths)
    print_separator(sum(widths) + len(widths) * 3 - 1)
    
    bases_to_show = []
    if show_front: bases_to_show.extend(['FRONT', 'THERMAL_FRONT'])
    if show_rear: bases_to_show.extend(['REAR', 'THERMAL_REAR'])
    if not bases_to_show:
        bases_to_show = ['FRONT', 'REAR', 'THERMAL_FRONT', 'THERMAL_REAR']
        
    for tire in tires:
        for base in ['FRONT', 'REAR']:
            if base not in tire or base not in bases_to_show:
                continue
                
            props = tire[base]
            name = props.get('NAME', 'Unknown')
            limit_angle = float(props.get('FRICTION_LIMIT_ANGLE', '8.0'))
            
            Dy, Dx, lat_pk, lon_pk, mag_pk, slip_pk = calc_grip(props, limit_angle)
            _, _, lat_35, lon_35, mag_35, slip_35 = calc_grip(props, 35.0)
            _, _, lat_60, lon_60, mag_60, slip_60 = calc_grip(props, 60.0)
            
            row_lat = [
                name[:20],
                base,
                "Lat",
                f"{Dy:.3f}",
                f"{lat_pk:.3f}",
                f"{lat_35:.3f}",
                f"{lat_60:.3f}"
            ]
            
            row_lon = [
                "",
                "",
                "Lon",
                f"{Dx:.3f}",
                f"{lon_pk:.3f}",
                f"{lon_35:.3f}",
                f"{lon_60:.3f}"
            ]
            
            row_mag = [
                "",
                "",
                "Mag",
                "",
                f"{mag_pk:.3f}",
                f"{mag_35:.3f}",
                f"{mag_60:.3f}"
            ]
            
            row_slip = [
                "",
                "",
                "Slip%",
                "",
                f"{slip_pk:.1f}",
                f"{slip_35:.1f}",
                f"{slip_60:.1f}"
            ]
            
            print_row(row_lat, widths)
            print_row(row_lon, widths)
            print_row(row_mag, widths)
            print_row(row_slip, widths)
            print_separator(sum(widths) + len(widths) * 3 - 1)

def main():
    parser = argparse.ArgumentParser(description='Predict tire G-forces at various slip angles.')
    parser.add_argument(
        'file',
        nargs='?',
        default='tyres.ini',
        metavar='file.ini[:selector]',
        help='Tire file path with optional :name or :index selector'
    )
    parser.add_argument(
        '--front', '-f',
        action='store_true',
        help='Only process FRONT sections'
    )
    parser.add_argument(
        '--rear', '-r',
        action='store_true',
        help='Only process REAR sections'
    )
    args = parser.parse_args()

    file_path, selector = _parse_file_spec(args.file)
    
    if not file_path.exists():
        print(f"Error: Could not find file {file_path}")
        sys.exit(1)
        
    print(f"Loading {file_path.resolve()}...")
    
    parser_obj = tire_lib.TireConfigParser(file_path)
    parser_obj.parse()
    
    tires_list = parser_obj.to_tires_list()
    
    if selector is not None:
        selected_tire = tire_lib.select_tire(tires_list, selector)
        if not selected_tire:
            print(f"Error: Tire specified by '{selector}' not found in {file_path}.")
            sys.exit(1)
        tires_list = [selected_tire]
        
    print(f"\nPredicted G-Forces")
    process_tires(tires_list, args.front, args.rear)

if __name__ == '__main__':
    main()
