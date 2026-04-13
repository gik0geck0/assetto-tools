#!/usr/bin/env python3
"""
Modify suspension geometry properties in Assetto Corsa suspensions.ini files.

Usage:
    python3 modify_suspension.py [options] <command> <value> [<command> <value> ...]

Options:
    --file <path>   Specify path to suspensions.ini (default: suspensions.ini)

Commands:
    rack <offset>     Moves the steering rack forward (Z-axis of WBCAR_STEER) by offset in mm.
                      Example: 'rack +10' moves the rack 10mm forward.
    ackerman <offset> Adjusts lateral position (X-axis of WBTYRE_STEER) by offset in mm.
                      Example: 'ackerman +1' moves the outer tie rod 1mm further away from car.
"""

import sys
import os
import re

def parse_args():
    args = sys.argv[1:]
    if not args or '-h' in args or '--help' in args:
        print(__doc__)
        sys.exit(0)

    file_path = "suspensions.ini"
    commands = {}

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--file':
            if i + 1 >= len(args):
                print("Error: --file requires a path.")
                sys.exit(1)
            file_path = args[i+1]
            i += 2
        elif arg.lower() in ['rack', 'ackerman']:
            if i + 1 >= len(args):
                print(f"Error: command '{arg}' requires an offset value.")
                sys.exit(1)
            try:
                val = float(args[i+1])
                commands[arg.lower()] = val
            except ValueError:
                print(f"Error: invalid offset for '{arg}': {args[i+1]}")
                sys.exit(1)
            i += 2
        else:
            print(f"Unknown argument or command: {arg}")
            sys.exit(1)

    return file_path, commands

def parse_vector3(line_val):
    # Parses strings like '0.55, 0.0, 0.12' into a list of floats
    parts = [p.strip() for p in line_val.split(',')]
    if len(parts) != 3:
        raise ValueError("Not a valid Vector3: " + line_val)
    return [float(parts[0]), float(parts[1]), float(parts[2])]

def format_vector3(vec):
    # Formats a list of floats back into a string, maintaining standard precision
    return f"{vec[0]:.4f}, {vec[1]:.4f}, {vec[2]:.4f}"

def main():
    file_path, commands = parse_args()

    if not os.path.exists(file_path):
        print(f"Error: Cannot find file {file_path}")
        sys.exit(1)

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    current_section = None
    modified = False

    # Regex for a key-value property line, capturing optional inline comments
    prop_re = re.compile(r'^(\s*)([a-zA-Z0-9_]+)\s*=\s*([^;]+)(;.*)?$')
    
    out_lines = []

    for line in lines:
        stripped = line.strip()
        
        # Track section
        if stripped.startswith('[') and stripped.endswith(']'):
            current_section = stripped[1:-1]
            out_lines.append(line)
            continue

        if current_section == 'FRONT':
            match = prop_re.match(line)
            if match:
                indent = match.group(1)
                key = match.group(2)
                val_str = match.group(3).strip()
                comment = match.group(4) or ""

                if key == 'WBCAR_STEER' and 'rack' in commands:
                    # Move inner tie rod (rack) forward/backward
                    # Assumption: Positive Z is Forward. So 'rack +10' means Z += 0.010
                    try:
                        vec = parse_vector3(val_str)
                        offset_m = commands['rack'] / 1000.0
                        vec[2] += offset_m
                        new_val_str = format_vector3(vec)
                        out_lines.append(f"{indent}{key}={new_val_str}\t\t{comment}\n")
                        print(f"rack: Updated WBCAR_STEER Z from {val_str}' to {new_val_str}")
                        modified = True
                        continue
                    except ValueError as e:
                        print(f"Warning: Failed to parse WBCAR_STEER: {e}")

                elif key == 'WBTYRE_STEER' and 'ackerman' in commands:
                    # Move outer tie rod laterally
                    # Assumption: Inner is relatively 0 to wheel center (WBTYRE coords)
                    # +X is inboard. 'ackerman +1' (further away from car) => more outboard => decreasing X
                    try:
                        vec = parse_vector3(val_str)
                        offset_m = commands['ackerman'] / 1000.0
                        vec[0] -= offset_m
                        new_val_str = format_vector3(vec)
                        out_lines.append(f"{indent}{key}={new_val_str}\t\t{comment}\n")
                        print(f"ackerman: Updated WBTYRE_STEER X from '{val_str}' to {new_val_str}")
                        modified = True
                        continue
                    except ValueError as e:
                        print(f"Warning: Failed to parse WBTYRE_STEER: {e}")

        # Preserve line if not modified
        out_lines.append(line)

    if modified:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.writelines(out_lines)
        print("Changes saved to", file_path)
    else:
        print("No changes made. Either commands were missing or targets not found.")

if __name__ == "__main__":
    main()
