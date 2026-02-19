#!/usr/bin/env python3
"""
Modify tire properties in Assetto Corsa tyres.ini file.

Usage:
    ./modify_tires.py set name="Tire Name" PROPERTY=value PROPERTY2=value2
    ./modify_tires.py set name="Tire Name" --front DX_REF=1.4 --rear DX_REF=1.3
    ./modify_tires.py merge other_tyres.ini   # Append and reindex sections from another file

Find tires by name and modify properties. Use --front and --rear to set
different values for front and rear sections separately. The `merge` command
appends sections from another tyres.ini and reindexes imported sections so
their numeric suffixes continue after the current file. If a tire NAME
already exists locally, it will be skipped and printed.
"""

import re
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class TireSection:
    """Represents a tire section [FRONT] or [REAR] with its properties."""
    
    def __init__(self, section_name: str, start_line: int, end_line: int):
        self.section_name = section_name  # e.g., "FRONT", "REAR", "FRONT_1"
        self.start_line = start_line
        self.end_line = end_line
        self.properties: Dict[str, str] = {}
        self.original_properties: Dict[str, str] = {}  # Store original values
        self.property_lines: Dict[str, int] = {}  # Map property name to line number
        self.raw_lines: List[str] = []
        self.is_front = section_name.startswith('FRONT')
        self.is_rear = section_name.startswith('REAR')
        self.modified = False  # Track if section was modified
    
    def get_name(self) -> Optional[str]:
        """Get the NAME property value."""
        return self.properties.get('NAME')
    
    def set_property(self, key: str, value: str):
        """Set a property value (will update when written)."""
        key_upper = key.upper()
        self.properties[key_upper] = value
        self.modified = True
        # If this property didn't exist before, we'll need to add it
        # (for now, we only update existing properties)
    
    def get_property(self, key: str) -> Optional[str]:
        """Get a property value."""
        return self.properties.get(key)


class TireConfigParser:
    """Parser for tyres.ini file."""
    
    # Regex to match property lines: KEY=VALUE    ; comment
    # Allow values with spaces and quoted strings; capture optional trailing comment
    PROPERTY_PATTERN = re.compile(r'^([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*(;.*)?$', re.IGNORECASE)
    # Regex to match section headers: [FRONT], [REAR], [FRONT_1], etc.
    SECTION_PATTERN = re.compile(r'^\[(FRONT|REAR|THERMAL_FRONT|THERMAL_REAR)(?:_\d+)?\]', re.IGNORECASE)
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.sections: List[TireSection] = []
        self.header_lines: List[str] = []
        self.lines: List[str] = []
    
    def parse(self):
        """Parse the tyres.ini file."""
        with open(self.file_path, 'r', encoding='utf-8') as f:
            self.lines = f.readlines()
        
        current_section: Optional[TireSection] = None
        i = 0
        
        while i < len(self.lines):
            line = self.lines[i]
            stripped = line.strip()
            
            # Check for section header
            section_match = self.SECTION_PATTERN.match(stripped)
            if section_match:
                # Save previous section if exists
                if current_section:
                    current_section.end_line = i - 1
                    self.sections.append(current_section)
                
                # Start new section
                # Get full section name if it has a number
                full_match = re.match(r'\[((?:FRONT|REAR|THERMAL_FRONT|THERMAL_REAR)(?:_\d+)?)\]', stripped, re.IGNORECASE)
                if full_match:
                    section_name = full_match.group(1).upper()
                else:
                    section_name = section_match.group(1).upper()
                
                current_section = TireSection(section_name, i, i)
                current_section.raw_lines.append(line)
                i += 1
                continue
            
            # If we're in a section, parse properties
            if current_section:
                current_section.raw_lines.append(line)
                prop_match = self.PROPERTY_PATTERN.match(stripped)
                if prop_match:
                    key = prop_match.group(1).upper()
                    # Strip surrounding quotes and whitespace from value
                    value = prop_match.group(2).strip()
                    value = value.strip('"\'')
                    current_section.properties[key] = value
                    current_section.original_properties[key] = value
                    current_section.property_lines[key] = i
            else:
                # Header lines before any section - store as list of (line_num, line) tuples
                if not hasattr(self, 'header_line_numbers'):
                    self.header_line_numbers = []
                self.header_line_numbers.append(i)
            
            i += 1
        
        # Save last section
        if current_section:
            current_section.end_line = i - 1
            self.sections.append(current_section)
    
    def find_by_name(self, name: str, section_type: Optional[str] = None) -> List[TireSection]:
        """
        Find tire sections by NAME property.
        
        Args:
            name: Tire name to search for
            section_type: Optional filter: 'front', 'rear', or None for both
        """
        results = []
        for section in self.sections:
            section_name = section.get_name()
            if section_name and section_name.lower() == name.lower():
                if section_type is None:
                    results.append(section)
                elif section_type.lower() == 'front' and section.is_front:
                    results.append(section)
                elif section_type.lower() == 'rear' and section.is_rear:
                    results.append(section)
        return results
    
    def write(self, output_path: Optional[Path] = None):
        """Write the modified configuration back to file."""
        if output_path is None:
            output_path = self.file_path
        
        # Build a map of line numbers to modified properties (only for modified sections)
        modified_lines = {}
        for section in self.sections:
            if not section.modified:
                continue
            
            # For each property in the section, check if it was modified
            for key, value in section.properties.items():
                # Only modify if it exists in property_lines (was in original file)
                # and the value changed
                if key in section.property_lines:
                    original_value = section.original_properties.get(key)
                    if value != original_value:
                        line_num = section.property_lines[key]
                        modified_lines[line_num] = (key, value, section)
        
        # Build output lines
        output_lines = []
        i = 0
        
        while i < len(self.lines):
            line = self.lines[i]
            stripped = line.strip()
            
            # Check if this line should be modified
            if i in modified_lines:
                key, value, section = modified_lines[i]
                # Try to preserve original formatting and comments
                prop_match = self.PROPERTY_PATTERN.match(stripped)
                if prop_match:
                    comment = prop_match.group(3) if prop_match.group(3) else ''
                    # Preserve original indentation if any
                    indent = line[:len(line) - len(line.lstrip())]
                    # Use original key casing
                    orig_key = prop_match.group(1)
                    new_line = f"{indent}{orig_key}={value}{comment}\n"
                    output_lines.append(new_line)
                else:
                    # Fallback: just replace with key=value
                    output_lines.append(f"{key}={value}\n")
            else:
                # Keep original line
                output_lines.append(line)
            
            i += 1
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(output_lines)


def parse_command_line_args(args):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Modify tire properties in tyres.ini',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ./modify_tires.py set name="Valino Matsuri 400TW" DX_REF=1.4 DY_REF=1.4
  ./modify_tires.py set name="Tire Name" --front DX_REF=1.4 DY_REF=1.4 --rear DX_REF=1.3 DY_REF=1.3
  ./modify_tires.py set name="Tire Name" DX_REF=1.4 --front DY_REF=1.4 --rear DY_REF=1.3
        """
    )
    
    parser.add_argument('command', choices=['set', 'merge', 'copy', 'shift', 'resize'], help='Command to execute')
    parser.add_argument('name', nargs='?', help='For `set`: Tire name (can also use name="..."). For `merge`: path to source tyres.ini')
    parser.add_argument('properties', nargs='*', help='For `set`: Properties to set (KEY=value)')
    
    # If command is 'merge', the next positional arg should be the source file
    if len(args) >= 2 and args[1] == 'merge':
        if len(args) < 3:
            print('Error: merge requires a source tyres.ini path')
            parser.print_help()
            sys.exit(1)
        return {'command': 'merge', 'source': args[2]}

    # If command is 'shift', parse two integers (source and destination), preserve order
    if len(args) >= 2 and args[1] == 'shift':
        if len(args) < 4:
            print('Error: shift requires two integer indices: source dest (e.g. shift 32 7)')
            parser.print_help()
            sys.exit(1)
        try:
            a = int(args[2])
            b = int(args[3])
        except ValueError:
            print('Error: shift indices must be integers')
            sys.exit(1)
        return {'command': 'shift', 'src': a, 'dst': b}

    # If command is 'resize', parse mm values (global or per-axle) and optional name
    if len(args) >= 2 and args[1] == 'resize':
        parsed_name = None
        global_width = None
        front_width = None
        rear_width = None
        i = 2

        while i < len(args):
            arg = args[i]
            if arg.startswith('name='):
                parsed_name = re.match(r'name=(.+)', arg).group(1).strip('"\'')
                i += 1
                continue

            # --front 225 or --front=225
            if arg == '--front':
                if i + 1 < len(args):
                    try:
                        front_width = float(args[i+1])
                    except ValueError:
                        print('Error: front width must be a number')
                        sys.exit(1)
                    i += 2
                    continue
                else:
                    print('Error: --front requires a width value')
                    sys.exit(1)
            if arg.startswith('--front='):
                try:
                    front_width = float(arg.split('=',1)[1])
                except ValueError:
                    print('Error: front width must be a number')
                    sys.exit(1)
                i += 1
                continue

            if arg == '--rear':
                if i + 1 < len(args):
                    try:
                        rear_width = float(args[i+1])
                    except ValueError:
                        print('Error: rear width must be a number')
                        sys.exit(1)
                    i += 2
                    continue
                else:
                    print('Error: --rear requires a width value')
                    sys.exit(1)
            if arg.startswith('--rear='):
                try:
                    rear_width = float(arg.split('=',1)[1])
                except ValueError:
                    print('Error: rear width must be a number')
                    sys.exit(1)
                i += 1
                continue

            # standalone numeric: global width
            try:
                v = float(arg)
                if global_width is None:
                    global_width = v
                i += 1
                continue
            except ValueError:
                # unknown token
                i += 1
                continue

        return {
            'command': 'resize',
            'name': parsed_name,
            'global_width': global_width,
            'front_width': front_width,
            'rear_width': rear_width
        }

    # If command is 'copy', parse name and new_name and optional properties
    if len(args) >= 2 and args[1] == 'copy':
        if len(args) < 3:
            print('Error: copy requires a source tire name and new name')
            parser.print_help()
            sys.exit(1)

        parsed_name = None
        new_name = None
        global_props = {}
        front_props = {}
        rear_props = {}
        i = 2
        current_target = 'global'

        while i < len(args):
            arg = args[i]
            if arg == '--front':
                current_target = 'front'
                i += 1
                continue
            elif arg == '--rear':
                current_target = 'rear'
                i += 1
                continue

            if arg.startswith('name='):
                parsed_name = re.match(r'name=(.+)', arg).group(1).strip('"\'')
                i += 1
                continue
            if arg.startswith('new_name='):
                new_name = re.match(r'new_name=(.+)', arg).group(1).strip('"\'')
                i += 1
                continue

            if '=' in arg:
                key, value = arg.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                if current_target == 'global':
                    global_props[key] = value
                elif current_target == 'front':
                    front_props[key] = value
                elif current_target == 'rear':
                    rear_props[key] = value
                i += 1
                continue

            # positional: first is name, second is new_name
            if parsed_name is None:
                parsed_name = arg.strip('"\'')
            elif new_name is None:
                new_name = arg.strip('"\'')
            i += 1

        if not parsed_name or not new_name:
            print('Error: copy requires both existing name and new_name')
            parser.print_help()
            sys.exit(1)

        return {
            'command': 'copy',
            'name': parsed_name,
            'new_name': new_name,
            'global_props': global_props,
            'front_props': front_props,
            'rear_props': rear_props
        }

    # Default: command is 'set' - parse name and properties (supporting --front/--rear)
    if len(args) < 2:
        parser.print_help()
        sys.exit(1)

    # Extract name and parse properties
    parsed_name = None
    global_props = {}
    front_props = {}
    rear_props = {}

    i = 2  # Skip script name and command
    current_target = 'global'  # 'global', 'front', or 'rear'

    while i < len(args):
        arg = args[i]

        if arg == '--front':
            current_target = 'front'
            i += 1
            continue
        elif arg == '--rear':
            current_target = 'rear'
            i += 1
            continue
        elif arg.startswith('name='):
            name_match = re.match(r'name=(.+)', arg)
            if name_match:
                parsed_name = name_match.group(1).strip('"\'')
            i += 1
            continue
        elif '=' in arg:
            key, value = arg.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"\'')

            if current_target == 'global':
                global_props[key] = value
            elif current_target == 'front':
                front_props[key] = value
            elif current_target == 'rear':
                rear_props[key] = value
            i += 1
        else:
            if parsed_name is None and not any(c in arg for c in '='):
                parsed_name = arg.strip('"\'')
            i += 1

    if parsed_name is None:
        print("Error: Tire name is required")
        parser.print_help()
        sys.exit(1)

    return {
        'command': 'set',
        'name': parsed_name,
        'global_props': global_props,
        'front_props': front_props,
        'rear_props': rear_props
    }


def main():
    """Main function."""
    if len(sys.argv) < 2 or '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
        parser = argparse.ArgumentParser(description='Modify tire properties in tyres.ini')
        parser.print_help()
        sys.exit(0)

    # Parse arguments
    config = parse_command_line_args(sys.argv)

    # Find tyres.ini file
    # script_dir = Path(__file__).parent
    tyres_file = Path('tyres.ini')

    if not tyres_file.exists():
        print(f"Error: tyres.ini not found at {tyres_file}")
        sys.exit(1)

    # If merge command, handle merging and exit
    if config.get('command') == 'merge':
        source_path = Path(config['source'])
        if not source_path.exists():
            print(f"Error: source file not found: {source_path}")
            sys.exit(1)

        # Parse both files
        target_parser = TireConfigParser(tyres_file)
        target_parser.parse()
        source_parser = TireConfigParser(source_path)
        source_parser.parse()

        # Helper: extract base and index from section name
        def split_base_index(name: str) -> Tuple[str, int]:
            m = re.match(r'^(FRONT|REAR|THERMAL_FRONT|THERMAL_REAR)(?:_(\d+))?$', name, re.IGNORECASE)
            if not m:
                return name, 0
            base = m.group(1).upper()
            idx = int(m.group(2)) if m.group(2) else 0
            return base, idx

        # Compute current max index per base in target
        max_index = {}
        print("Target sections: " + ", ".join(sec.section_name for sec in target_parser.sections))
        for sec in target_parser.sections:
            base, idx = split_base_index(sec.section_name)
            cur = max_index.get(base, -1)
            if idx > cur:
                max_index[base] = idx

        # Build set of existing tire names (case-insensitive), normalize by stripping quotes
        existing_names = set()
        for sec in target_parser.sections:
            n = sec.get_name()
            if n:
                existing_names.add(n.strip('"\'').lower())

        # Group source sections by tire NAME property (normalized)
        # If a THERMAL_* section has no NAME, try to find the NAME from the
        # matching-index FRONT/REAR section and attach it to that tire group.
        source_groups = {}
        print("Source sections: " + ", ".join(sec.section_name for sec in source_parser.sections))
        for sec in source_parser.sections:
            name = sec.get_name()
            clean = None

            if name:
                clean = name.strip('"\'')
            else:
                # Try to resolve from counterpart section (e.g., THERMAL_FRONT -> FRONT)
                base, idx = split_base_index(sec.section_name)
                if base.startswith('THERMAL_'):
                    # Map THERMAL_FRONT -> FRONT, THERMAL_REAR -> REAR
                    if base == 'THERMAL_FRONT':
                        search_base = 'FRONT'
                    elif base == 'THERMAL_REAR':
                        search_base = 'REAR'
                    else:
                        search_base = base

                    for s2 in source_parser.sections:
                        b2, idx2 = split_base_index(s2.section_name)
                        if b2 == search_base and idx2 == idx:
                            n2 = s2.get_name()
                            if n2:
                                clean = n2.strip('"\'')
                                break

            if not clean:
                print(f"Warning: Source section {sec.section_name} has no NAME property and no matching counterpart, skipping")
                continue

            source_groups.setdefault(clean, []).append(sec)

        # For each tire in source, append if not existing
        skipped = []
        appended_count = 0
        for name, sections in source_groups.items():
            if name.lower() in existing_names:
                print(f"Skipping existing tire: {name}")
                skipped.append(name)
                continue

            # Import all sections for this tire
            for sec in sections:
                base, src_idx = split_base_index(sec.section_name)
                cur_max = max_index.get(base, -1)

                # Decide new index: if no existing base and source index == 0, keep unnumbered
                if cur_max == -1 and src_idx == 0:
                    new_idx = 0
                else:
                    new_idx = cur_max + 1

                # Build new section name
                if new_idx == 0:
                    new_section_name = base
                else:
                    new_section_name = f"{base}_{new_idx}"

                # Update max index for base
                max_index[base] = new_idx

                # Prepare lines to append: replace header line with new section name
                new_lines = list(sec.raw_lines)
                if new_lines:
                    # Replace header (first line) with updated header
                    new_lines[0] = f'[{new_section_name}]\n'
                else:
                    new_lines = [f'[{new_section_name}]\n']

                # Ensure there's a blank line before appended section for readability
                if target_parser.lines and not target_parser.lines[-1].endswith('\n'):
                    target_parser.lines[-1] = target_parser.lines[-1] + '\n'
                target_parser.lines.append('\n')
                target_parser.lines.extend(new_lines)
                appended_count += 1

        # Write merged file
        target_parser.write()
        print(f"Merge complete. Appended {appended_count} sections. Skipped {len(skipped)} tires.")
        sys.exit(0)

    # If shift command, move section from src index to dst index, shifting intervening indices
    if config.get('command') == 'shift':
        src = config['src']
        dst = config['dst']

        parser_local = TireConfigParser(tyres_file)
        parser_local.parse()

        def split_base_index(name: str) -> Tuple[str, int]:
            m = re.match(r'^(FRONT|REAR|THERMAL_FRONT|THERMAL_REAR)(?:_(\d+))?$', name, re.IGNORECASE)
            if not m:
                return name, 0
            base = m.group(1).upper()
            idx = int(m.group(2)) if m.group(2) else 0
            return base, idx

        bases = ['FRONT', 'REAR', 'THERMAL_FRONT', 'THERMAL_REAR']
        total_changes = 0

        for base in bases:
            # Map current indices to sections
            idx_map = {}
            for sec in parser_local.sections:
                b, idx = split_base_index(sec.section_name)
                if b == base:
                    idx_map[idx] = sec

            updates = []  # list of tuples (section, new_idx)

            if src == dst:
                continue

            if src > dst:
                # moving from higher index down to lower: shift dst..src-1 up by +1, src -> dst
                for idx in range(dst, src):
                    sec = idx_map.get(idx)
                    if sec:
                        updates.append((sec, idx + 1))
                # source moves to dst
                sec_src = idx_map.get(src)
                if sec_src:
                    updates.append((sec_src, dst))
            else:
                # src < dst: moving from lower index up to higher: shift src+1..dst down by -1, src -> dst
                for idx in range(src + 1, dst + 1):
                    sec = idx_map.get(idx)
                    if sec:
                        updates.append((sec, idx - 1))
                sec_src = idx_map.get(src)
                if sec_src:
                    updates.append((sec_src, dst))

            # Apply updates: rename sections accordingly
            for sec, new_idx in updates:
                if new_idx == 0:
                    new_name = base
                else:
                    new_name = f"{base}_{new_idx}"

                sec.section_name = new_name
                if sec.raw_lines:
                    sec.raw_lines[0] = f'[{new_name}]\n'
                else:
                    sec.raw_lines = [f'[{new_name}]\n']

                if 0 <= sec.start_line < len(parser_local.lines):
                    parser_local.lines[sec.start_line] = sec.raw_lines[0]

                total_changes += 1

        parser_local.write()
        print(f"Shift complete (src={src} -> dst={dst}). Renamed/updated {total_changes} sections.")
        sys.exit(0)

    # If resize command, adjust WIDTH and derived properties
    if config.get('command') == 'resize':
        # widths in config are in mm; convert to meters (file uses meters)
        name_filter = config.get('name')
        gw = config.get('global_width')
        fw = config.get('front_width')
        rw = config.get('rear_width')

        def mm_to_m(mm_val: float) -> float:
            return mm_val / 1000.0

        target_parser = TireConfigParser(tyres_file)
        target_parser.parse()

        # Determine which sections to process
        sections_to_modify: List[TireSection] = []
        if name_filter:
            # restrict to sections with matching NAME
            for sec in target_parser.sections:
                n = sec.get_name()
                if n and n.strip('"\'').lower() == name_filter.strip('"\'').lower():
                    sections_to_modify.append(sec)
        else:
            sections_to_modify = list(target_parser.sections)

        modified_count = 0
        for sec in sections_to_modify:
            # determine which width to apply for this section (front/rear/global)
            base = 'FRONT' if sec.is_front else 'REAR' if sec.is_rear else None
            desired_mm = None
            if base == 'FRONT' and fw is not None:
                desired_mm = fw
            elif base == 'REAR' and rw is not None:
                desired_mm = rw
            elif gw is not None:
                desired_mm = gw

            if desired_mm is None:
                continue  # no width target for this section

            # get old width in meters
            old_w_s = sec.get_property('WIDTH')
            if not old_w_s:
                print(f"Skipping section {sec.section_name}: no WIDTH property")
                continue
            try:
                old_w = float(old_w_s)
            except Exception:
                print(f"Skipping section {sec.section_name}: invalid WIDTH value '{old_w_s}'")
                continue

            new_w = mm_to_m(float(desired_mm))

            # Get old derived properties
            ai_s = sec.get_property('ANGULAR_INERTIA')
            rate_s = sec.get_property('RATE')
            damp_s = sec.get_property('DAMP')

            # Update WIDTH (meters) with 3 decimals
            sec.set_property('WIDTH', f"{new_w:.3f}")

            # Update ANGULAR_INERTIA if present (2 decimals)
            if ai_s:
                try:
                    ai_old = float(ai_s)
                    ai_new = ai_old * (new_w / old_w)
                    sec.set_property('ANGULAR_INERTIA', f"{ai_new:.2f}")
                except Exception:
                    print(f"Warning: could not parse ANGULAR_INERTIA '{ai_s}' for {sec.section_name}")

            # Update RATE if present (integer)
            if rate_s:
                try:
                    rate_old = float(rate_s)
                    rate_new = rate_old * (old_w / new_w) ** 0.25
                    sec.set_property('RATE', str(int(round(rate_new))))
                except Exception:
                    print(f"Warning: could not parse RATE '{rate_s}' for {sec.section_name}")

            # Update DAMP if present (integer)
            if damp_s:
                try:
                    damp_old = float(damp_s)
                    damp_new = damp_old * (new_w / old_w)
                    sec.set_property('DAMP', str(int(round(damp_new))))
                except Exception:
                    print(f"Warning: could not parse DAMP '{damp_s}' for {sec.section_name}")

            modified_count += 1

        if modified_count == 0:
            print("No sections modified by resize")
            sys.exit(0)

        target_parser.write()
        print(f"Resized {modified_count} sections (widths in mm applied: global={gw}, front={fw}, rear={rw})")
        sys.exit(0)

    # If copy command, duplicate a tire within the local tyres.ini
    if config.get('command') == 'copy':
        tire_name = config['name']
        new_name = config['new_name']
        global_props = config['global_props']
        front_props = config['front_props']
        rear_props = config['rear_props']

        parser_local = TireConfigParser(tyres_file)
        parser_local.parse()

        # Helper: extract base and index from section name
        def split_base_index(name: str) -> Tuple[str, int]:
            m = re.match(r'^(FRONT|REAR|THERMAL_FRONT|THERMAL_REAR)(?:_(\d+))?$', name, re.IGNORECASE)
            if not m:
                return name, 0
            base = m.group(1).upper()
            idx = int(m.group(2)) if m.group(2) else 0
            return base, idx

        # Build set of existing names
        existing_names = set()
        for sec in parser_local.sections:
            n = sec.get_name()
            if n:
                existing_names.add(n.strip('"\'').lower())

        if new_name.strip('"\'').lower() in existing_names:
            print(f"Error: target name already exists: {new_name}")
            sys.exit(1)

        # Compute current max index per base in target
        max_index = {}
        for sec in parser_local.sections:
            base, idx = split_base_index(sec.section_name)
            cur = max_index.get(base, -1)
            if idx > cur:
                max_index[base] = idx

        # Collect sections that belong to the tire to copy
        to_copy = []  # list of TireSection
        for sec in parser_local.sections:
            n = sec.get_name()
            if n and n.strip('"\'').lower() == tire_name.strip('"\'').lower():
                to_copy.append(sec)

        # also attach thermal counterparts by matching index
        for sec in parser_local.sections:
            if sec.section_name.startswith('THERMAL_'):
                b, idx = split_base_index(sec.section_name)
                # find FRONT/REAR counterpart of same index whose name matches
                counterpart = None
                search_base = 'FRONT' if b == 'THERMAL_FRONT' else 'REAR' if b == 'THERMAL_REAR' else None
                if search_base:
                    for s2 in parser_local.sections:
                        b2, idx2 = split_base_index(s2.section_name)
                        if b2 == search_base and idx2 == idx:
                            n2 = s2.get_name()
                            if n2 and n2.strip('"\'').lower() == tire_name.strip('"\'').lower():
                                to_copy.append(sec)
                                break

        if not to_copy:
            print(f"Error: No tire found with name '{tire_name}'")
            sys.exit(1)

        # Helper to apply property overrides to raw lines
        def apply_props_to_lines(raw_lines: List[str], props: Dict[str, str]):
            # props keys are expected upper-case or mixed; treat case-insensitively
            found_keys = set()
            out_lines = []
            for i, line in enumerate(raw_lines):
                stripped = line.strip()
                pm = TireConfigParser.PROPERTY_PATTERN.match(stripped)
                if pm:
                    key = pm.group(1)
                    key_u = key.upper()
                    comment = pm.group(3) or ''
                    indent = line[:len(line) - len(line.lstrip())]
                    if key_u in props:
                        val = props[key_u]
                        out_lines.append(f"{indent}{key}={val}{comment}\n")
                        found_keys.add(key_u)
                        continue
                out_lines.append(line)

            # If NAME override provided and not found, insert after header
            if 'NAME' in props and not any(k.upper() == 'NAME' for k in found_keys):
                # insert after header line (index 0)
                insert_line = f"NAME={props['NAME']}\n"
                if len(out_lines) > 0:
                    out_lines.insert(1, insert_line)
                else:
                    out_lines.append(insert_line)

            return out_lines

        appended = 0
        # Duplicate each section block and append to lines
        for sec in to_copy:
            base, src_idx = split_base_index(sec.section_name)
            cur_max = max_index.get(base, -1)
            if cur_max == -1 and src_idx == 0:
                new_idx = 0
            else:
                new_idx = cur_max + 1

            if new_idx == 0:
                new_section_name = base
            else:
                new_section_name = f"{base}_{new_idx}"

            max_index[base] = new_idx

            # Build new raw lines and apply NAME + overrides
            new_lines = list(sec.raw_lines)
            if new_lines:
                new_lines[0] = f'[{new_section_name}]\n'
            else:
                new_lines = [f'[{new_section_name}]\n']

            # Determine which overrides to apply
            # Start with global props, then specific front/rear overrides
            overrides = {k.upper(): v for k, v in config['global_props'].items()}
            if base == 'FRONT':
                overrides.update({k.upper(): v for k, v in config['front_props'].items()})
            if base == 'REAR':
                overrides.update({k.upper(): v for k, v in config['rear_props'].items()})

            # Ensure NAME is set on non-thermal sections
            if base in ('FRONT', 'REAR'):
                overrides['NAME'] = new_name

            new_lines = apply_props_to_lines(new_lines, overrides)

            # Append a blank line then the new lines
            if parser_local.lines and not parser_local.lines[-1].endswith('\n'):
                parser_local.lines[-1] = parser_local.lines[-1] + '\n'
            parser_local.lines.append('\n')
            parser_local.lines.extend(new_lines)
            appended += 1

        parser_local.write()
        print(f"Copied tire '{tire_name}' -> '{new_name}', appended {appended} sections")
        sys.exit(0)

    # Else it's a 'set' command
    tire_name = config['name']
    global_props = config['global_props']
    front_props = config['front_props']
    rear_props = config['rear_props']
    
    # Parse the file
    parser = TireConfigParser(tyres_file)
    parser.parse()
    
    # Find matching tire sections
    front_sections = parser.find_by_name(tire_name, 'front')
    rear_sections = parser.find_by_name(tire_name, 'rear')
    
    if not front_sections and not rear_sections:
        print(f"Error: No tire found with name '{tire_name}'")
        sys.exit(1)
    
    # Apply properties
    modified = False
    
    # Apply global properties to all sections
    all_sections = front_sections + rear_sections
    for section in all_sections:
        for key, value in global_props.items():
            section.set_property(key, value)
            modified = True
    
    # Apply front-specific properties
    for section in front_sections:
        for key, value in front_props.items():
            section.set_property(key, value)
            modified = True
    
    # Apply rear-specific properties
    for section in rear_sections:
        for key, value in rear_props.items():
            section.set_property(key, value)
            modified = True
    
    if not modified:
        print("No properties to modify")
        sys.exit(0)
    
    # Write back to file
    parser.write()
    
    # Print summary
    print(f"Modified tire: {tire_name}")
    if front_sections:
        print(f"  Front sections: {len(front_sections)}")
    if rear_sections:
        print(f"  Rear sections: {len(rear_sections)}")
    
    if global_props:
        print(f"  Global properties: {list(global_props.keys())}")
    if front_props:
        print(f"  Front properties: {list(front_props.keys())}")
    if rear_props:
        print(f"  Rear properties: {list(rear_props.keys())}")


if __name__ == '__main__':
    main()
