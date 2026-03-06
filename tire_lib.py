"""
Library for parsing and manipulating Assetto Corsa tyres.ini files.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Regex to match property lines: KEY=VALUE    ; comment
# Allow values with spaces and quoted strings; capture optional trailing comment
PROPERTY_PATTERN = re.compile(r'^([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*(;.*)?$', re.IGNORECASE)
# Regex to match section headers: [FRONT], [REAR], [FRONT_1], etc.
SECTION_PATTERN = re.compile(r'^\[(FRONT|REAR|THERMAL_FRONT|THERMAL_REAR)(?:_\d+)?\]', re.IGNORECASE)

BASES = ('FRONT', 'REAR', 'THERMAL_FRONT', 'THERMAL_REAR')

def split_base_index(name: str) -> Tuple[str, int]:
    """Return (base, index) from a raw section name like FRONT_2."""
    m = re.match(r'^(FRONT|REAR|THERMAL_FRONT|THERMAL_REAR)(?:_(\d+))?$', name, re.IGNORECASE)
    if not m:
        return name.upper(), 0
    base = m.group(1).upper()
    idx = int(m.group(2)) if m.group(2) else 0
    return base, idx


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
            section_match = SECTION_PATTERN.match(stripped)
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
                prop_match = PROPERTY_PATTERN.match(stripped)
                if prop_match:
                    key = prop_match.group(1).upper()
                    # Strip surrounding quotes and whitespace from value
                    value = prop_match.group(2).strip()
                    value = value.strip('"\'')
                    # Don't overwrite if we already have it (first wins)
                    if key not in current_section.properties:
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
                prop_match = PROPERTY_PATTERN.match(stripped)
                if prop_match:
                    comment = prop_match.group(3) if prop_match.group(3) else ''
                    indent = line[:len(line) - len(line.lstrip())]
                    orig_key = prop_match.group(1)
                    new_line = f"{indent}{orig_key}={value}{comment}\n"
                    output_lines.append(new_line)
                else:
                    output_lines.append(f"{key}={value}\n")
            else:
                output_lines.append(line)
            
            i += 1
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(output_lines)

    def to_dict_for_analyze(self) -> Dict[str, Dict[str, str]]:
        """
        Return a simple dict mapping base_section -> {prop: val},
        like analyze_tires.py's parse_ini() used to return.
        Only keeps the first index encountered.
        """
        sections: Dict[str, Dict[str, str]] = {}
        for sec in self.sections:
            base, idx = split_base_index(sec.section_name)
            if base not in sections:
                sections[base] = dict(sec.properties)
        return sections

    def to_tires_list(self) -> List[Dict[str, Dict[str, str]]]:
        """
        Return a list of tire dicts, one per tire index,
        ordered by index, like analyze_tires.py's parse_ini_tires().
        """
        raw: Dict[str, Dict[int, Dict[str, str]]] = {}
        indices = set()
        
        for sec in self.sections:
            base, idx = split_base_index(sec.section_name)
            raw.setdefault(base, {})[idx] = dict(sec.properties)
            if base in ('FRONT', 'REAR'):
                indices.add(idx)

        tires = []
        for idx in sorted(indices):
            tire = {}
            for base in BASES:
                props = raw.get(base, {}).get(idx)
                if props:
                    tire[base] = props
            tires.append(tire)

        return tires


def tire_name(tire: Dict[str, Dict[str, str]]) -> Optional[str]:
    """Return the NAME property from a tire's FRONT or REAR section."""
    for base in ('FRONT', 'REAR'):
        props = tire.get(base, {})
        n = props.get('NAME')
        if n:
            return n
    return None


def select_tire(tires: List[Dict], selector: Optional[str], file_label: str) -> Dict:
    """
    Select a tire from the list by name (str) or 0-based index (int-like str).
    Defaults to index 0 if selector is None.
    """
    if selector is None:
        if not tires:
            print(f"Error: no tires found in {file_label}")
            sys.exit(1)
        return tires[0]

    # Try integer index
    try:
        idx = int(selector)
        if idx < 0 or idx >= len(tires):
            print(f"Error: index {idx} out of range (0–{len(tires)-1}) in {file_label}")
            sys.exit(1)
        return tires[idx]
    except ValueError:
        pass

    # Try by name (case-insensitive)
    for tire in tires:
        n = tire_name(tire)
        if n and n.lower() == selector.lower():
            return tire

    print(f"Error: no tire named '{selector}' found in {file_label}")
    available = [tire_name(t) or f"(index {i})" for i, t in enumerate(tires)]
    print(f"  Available: {available}")
    sys.exit(1)
