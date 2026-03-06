#!/usr/bin/env python3
"""
Analyze trends in tire properties across different widths, and compare tires.

Commands:
    python analyze_tires.py analyze <directory>
        Fit polynomial models to width-parameterized tire data and write
        tire_model.json. Used to train the resize model consumed by
        `modify_tires.py resize`.

    python analyze_tires.py compare <fileA>[:<selector>] <fileB>[:<selector>] [options]
        Compare tire properties between two tires, within or across files.
        A selector is either a tire name (string) or a 0-based index (integer).
        If omitted, defaults to index 0 (the first tire in the file).
        If the filename is omitted (e.g. `:1`), `tyres.ini` is assumed.

        Options:
            --front   Compare only FRONT / THERMAL_FRONT sections
            --rear    Compare only REAR / THERMAL_REAR sections
            (default: compare all sections)

        Examples:
            compare tyres.ini ref.ini
            compare tyres.ini ref.ini --front
            compare tyres.ini:0 ref.ini:1
            compare tyres.ini:"TCR M" ref.ini:"Valino Pergea"
            compare tyres.ini:0 tyres.ini:1
"""

import re
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# INI parsing
# ---------------------------------------------------------------------------

from tire_lib import TireConfigParser, split_base_index, tire_name as _tire_name, select_tire as _select_tire

def parse_ini(file_path: Path) -> Dict[str, Dict[str, str]]:
    """
    Parse a tire .ini file for the `analyze` command.

    Returns a dict mapping section_base -> {property: value}.
    Section bases are normalised: FRONT_1 -> FRONT, THERMAL_REAR_0 -> THERMAL_REAR.
    When multiple numbered sections exist only the first is kept (unusual for
    training files but handled gracefully).
    """
    parser = TireConfigParser(file_path)
    parser.parse()
    return parser.to_dict_for_analyze()


# ---------------------------------------------------------------------------
# Multi-tire INI parsing (for compare)
# ---------------------------------------------------------------------------

def parse_ini_tires(file_path: Path) -> List[Dict[str, Dict[str, str]]]:
    """
    Parse a tyres.ini file and return a list of tire dicts, one per tire.

    Each tire dict maps section base ('FRONT', 'REAR', 'THERMAL_FRONT',
    'THERMAL_REAR') -> {property: value}.

    Tires are ordered by their section index (FRONT / FRONT_1 / FRONT_2 ...).
    A tire is identified by any FRONT or REAR section; index 0 = no suffix.
    """
    parser = TireConfigParser(file_path)
    parser.parse()
    return parser.to_tires_list()


def _parse_file_spec(spec: str) -> Tuple[Path, Optional[str]]:
    """
    Parse a 'file.ini:selector' spec.
    The selector may be an integer index or a tire name.
    Colon is ambiguous on Windows paths (C:\\path.ini:name) so we only split
    on the LAST colon that follows a section-terminator (']' or the extension).
    Strategy: split on the last ':' only if the left part is an existing file
    or looks like a path; otherwise treat the whole thing as a path with no selector.
    """
    # If starting with a colon (e.g. ":1"), assume tyres.ini
    if spec.startswith(':'):
        return Path("tyres.ini"), spec[1:] or None

    # Try splitting on the last colon
    if ':' in spec:
        last_colon = spec.rfind(':')
        left = spec[:last_colon]
        right = spec[last_colon + 1:]
        left_path = Path(left)
        # Accept the split if the left part resolves to an actual file OR
        # if the right part is a digit (unambiguous index)
        right_is_index = right.isdigit()
        if left_path.exists() or right_is_index:
            # Confirm the left side looks like a file (not a drive letter on Windows)
            if len(left) > 2 or not left[-1].isalpha():
                return left_path, right if right else None

    return Path(spec), None


# ---------------------------------------------------------------------------
# Polynomial fitting helpers
# ---------------------------------------------------------------------------

def _try_import_numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        print("Error: numpy is required. Install it with: pip install numpy")
        sys.exit(1)


def r_squared(y_actual, y_predicted) -> float:
    np = _try_import_numpy()
    y_actual = np.asarray(y_actual, dtype=float)
    y_predicted = np.asarray(y_predicted, dtype=float)
    ss_res = float(np.sum((y_actual - y_predicted) ** 2))
    ss_tot = float(np.sum((y_actual - float(np.mean(y_actual))) ** 2))
    if ss_tot == 0.0:
        return 1.0 if ss_res == 0.0 else 0.0
    return 1.0 - ss_res / ss_tot


def fit_property(widths_mm: List[float], values: List[float], degree: int = 2):
    np = _try_import_numpy()
    x = np.asarray(widths_mm, dtype=float)
    y = np.asarray(values, dtype=float)
    coeffs = np.polyfit(x, y, degree).tolist()
    y_pred = np.polyval(np.asarray(coeffs), x).tolist()
    r2 = r_squared(y, y_pred)
    return coeffs, r2


# ---------------------------------------------------------------------------
# Section-type constants
# ---------------------------------------------------------------------------

SECTION_TRAINING_MAP = {
    'FRONT': 'FRONT',
    'REAR': 'FRONT',
    'THERMAL_FRONT': 'THERMAL_FRONT',
    'THERMAL_REAR': 'THERMAL_FRONT',
}

TRAINING_SECTIONS = ('FRONT', 'THERMAL_FRONT')

SKIP_PROPERTIES = {
    'NAME', 'SHORT_NAME', 'WEAR_CURVE', 'PERFORMANCE_CURVE',
    'RADIUS', 'RIM_RADIUS', 'DAMP',
    'ROLLING_RESISTANCE_0',
    'DCAMBER_0', 'DCAMBER_1',
    'XMU',
    'PRESSURE_FLEX_GAIN', 'PRESSURE_RR_GAIN', 'PRESSURE_D_GAIN',
    'FALLOFF_LEVEL', 'FALLOFF_SPEED',
    'CX_MULT', 'BRAKE_DX_MOD',
    'PATCH_TRANSFER', 'GRAIN_GAMMA', 'GRAIN_GAIN', 'BLISTER_GAMMA',
}

VARIATION_THRESHOLD = 0.001  # 0.1%


# ---------------------------------------------------------------------------
# analyze command
# ---------------------------------------------------------------------------

def _mode_value(records, section_base, prop) -> str:
    from collections import Counter
    vals = []
    for _, secs in records:
        if section_base in secs and prop in secs[section_base]:
            vals.append(secs[section_base][prop])
    if not vals:
        return ''
    return Counter(vals).most_common(1)[0][0]


def analyze(directory: Path, output_path: Path, poly_degree: int = 2, verbose: bool = True):
    """Read all *.ini files in `directory`, fit polynomial models, write JSON."""
    np = _try_import_numpy()

    ini_files = sorted(directory.glob('*.ini'))
    if not ini_files:
        print(f"No *.ini files found in {directory}")
        sys.exit(1)

    records: List[Tuple[float, Dict[str, Dict[str, str]]]] = []

    for f in ini_files:
        sections = parse_ini(f)
        width_str = None
        for sec_name in ('FRONT', 'REAR'):
            if sec_name in sections and 'WIDTH' in sections[sec_name]:
                width_str = sections[sec_name]['WIDTH']
                break
        if width_str is None:
            print(f"  Warning: {f.name} has no WIDTH property, skipping.")
            continue
        try:
            width_m = float(width_str)
        except ValueError:
            print(f"  Warning: {f.name} has invalid WIDTH '{width_str}', skipping.")
            continue
        width_mm = round(width_m * 1000, 3)
        records.append((width_mm, sections))
        if verbose:
            print(f"  Loaded {f.name}  (WIDTH={width_mm:.1f} mm)")

    if len(records) < 3:
        print("Error: need at least 3 data points to fit a polynomial.")
        sys.exit(1)

    records.sort(key=lambda r: r[0])
    widths_mm = [r[0] for r in records]

    if verbose:
        print(f"\nFitting degree-{poly_degree} polynomials across "
              f"{len(records)} widths: {widths_mm}\n")

    section_models: Dict[str, Dict] = {}
    constant_props: Dict[str, Dict[str, str]] = {}

    col_w = 28

    for section_base in TRAINING_SECTIONS:
        models: Dict[str, dict] = {}
        consts: Dict[str, str] = {}

        all_props: set = set()
        for _, secs in records:
            if section_base in secs:
                all_props.update(secs[section_base].keys())

        if verbose:
            print('-' * 70)
            print(f"  Section: [{section_base}]")
            print('-' * 70)
            print(f"  {'Property':<{col_w}} {'R2':>6}  Polynomial (high->low degree)")
            print(f"  {'-'*col_w} {'-'*6}  {'-'*32}")

        for prop in sorted(all_props):
            if prop in SKIP_PROPERTIES:
                consts[prop] = _mode_value(records, section_base, prop)
                continue

            values: List[float] = []
            ws: List[float] = []
            for w, secs in records:
                if section_base in secs and prop in secs[section_base]:
                    try:
                        values.append(float(secs[section_base][prop]))
                        ws.append(w)
                    except ValueError:
                        pass

            if len(values) < 3:
                consts[prop] = _mode_value(records, section_base, prop)
                continue

            mean_v = sum(values) / len(values)
            if mean_v == 0:
                cv = max(abs(v) for v in values)
            else:
                cv = (sum((v - mean_v) ** 2 for v in values) / len(values)) ** 0.5 / abs(mean_v)

            if cv < VARIATION_THRESHOLD:
                consts[prop] = _mode_value(records, section_base, prop)
                continue

            coeffs, r2 = fit_property(ws, values, degree=poly_degree)
            models[prop] = {'poly': coeffs, 'r2': round(r2, 6)}

            if verbose:
                coeffs_str = ', '.join(f'{c:.6g}' for c in coeffs)
                print(f"  {prop:<{col_w}} {r2:>6.4f}  [{coeffs_str}]")

        if verbose:
            print()

        section_models[section_base] = models
        constant_props[section_base] = consts

    model = {
        'widths_mm': widths_mm,
        'poly_degree': poly_degree,
        'sections': section_models,
        'constant_properties': constant_props,
    }

    with open(output_path, 'w', encoding='utf-8') as fh:
        json.dump(model, fh, indent=2)

    print(f"Model saved to: {output_path}")
    print(f"  Modeled properties: "
          f"{sum(len(v) for v in section_models.values())}")
    print(f"  Constant properties: "
          f"{sum(len(v) for v in constant_props.values())}")
    print(f"  Training widths (mm): {widths_mm}")


# ---------------------------------------------------------------------------
# compare command
# ---------------------------------------------------------------------------

# Properties never shown in the diff table
COMPARE_SKIP = {'WEAR_CURVE', 'PERFORMANCE_CURVE'}

# Section display order
SECTION_ORDER = ('FRONT', 'THERMAL_FRONT', 'REAR', 'THERMAL_REAR')


def compare(
    file_a: Path, selector_a: Optional[str],
    file_b: Path, selector_b: Optional[str],
    show_front: bool,
    show_rear: bool,
    threshold: float = 5.0,
):
    """Compare two tires (optionally from the same file) property by property."""
    if not file_a.exists():
        print(f"Error: file not found: {file_a}")
        sys.exit(1)
    if not file_b.exists():
        print(f"Error: file not found: {file_b}")
        sys.exit(1)

    # Parse both files (may be the same file)
    tires_a = parse_ini_tires(file_a)
    # Avoid double-reading if comparing within the same file
    if file_a.resolve() == file_b.resolve():
        tires_b = tires_a
    else:
        tires_b = parse_ini_tires(file_b)

    tire_a = _select_tire(tires_a, selector_a, str(file_a))
    tire_b = _select_tire(tires_b, selector_b, str(file_b))

    # Determine which section types to show
    if not show_front and not show_rear:
        show_front = show_rear = True

    sections_to_show = []
    if show_front:
        sections_to_show += ['FRONT', 'THERMAL_FRONT']
    if show_rear:
        sections_to_show += ['REAR', 'THERMAL_REAR']

    # Build labels (e.g. "tyres.ini:0 (TCR M)")
    def _label(path: Path, selector: Optional[str], tire: Dict) -> str:
        name = _tire_name(tire)
        sel_str = selector if selector is not None else '0'
        label = f"{path.name}:{sel_str}"
        if name:
            label += f" ({name})"
        return label

    label_a = _label(file_a, selector_a, tire_a)
    label_b = _label(file_b, selector_b, tire_b)

    col_prop = 34
    col_val = 18
    header_width = col_prop + col_val * 2 + 10

    print(f"\n  A: {label_a}")
    print(f"  B: {label_b}\n")
    print(f"  {'Property':<{col_prop}} {'A':>{col_val}} {'B':>{col_val}} {'Diff%':>8}")
    print('  ' + '-' * (header_width - 2))

    any_large = False
    found_any = False

    for sec in SECTION_ORDER:
        if sec not in sections_to_show:
            continue

        props_a = tire_a.get(sec, {})
        props_b = tire_b.get(sec, {})

        if not props_a and not props_b:
            continue

        all_props = sorted(set(props_a) | set(props_b))
        section_rows = []

        for prop in all_props:
            if prop in COMPARE_SKIP:
                continue

            va = props_a.get(prop, '—')
            vb = props_b.get(prop, '—')

            try:
                fa, fb = float(va), float(vb)
                denom = max(abs(fa), 1e-12)
                err = (fb - fa) / denom * 100
                flag = ' <<<' if abs(err) > threshold else ''
                if abs(err) > threshold:
                    any_large = True
                row = (f"{sec+'.'+prop:<{col_prop}} "
                       f"{va:>{col_val}} {vb:>{col_val}} "
                       f"{err:>+7.2f}%{flag}")
            except (ValueError, TypeError):
                match = '' if va == vb else ' DIFF'
                row = (f"{sec+'.'+prop:<{col_prop}} "
                       f"{va:>{col_val}} {vb:>{col_val}}{match}")

            section_rows.append(row)

        if section_rows:
            found_any = True
            print(f"\n  [{sec}]")
            for row in section_rows:
                print(f"  {row}")

    if not found_any:
        print("  (no sections matched)")

    print()
    if any_large:
        print(f"  WARN: Some properties differ by >{threshold:.0f}%.")
    else:
        print(f"  PASS: All properties within {threshold:.0f}%.")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h'):
        print(__doc__)
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description='Tire analysis utilities.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest='command')

    # ---- analyze -------------------------------------------------------
    analyze_p = sub.add_parser(
        'analyze',
        help='Fit polynomial models to width-parameterized tire data'
    )
    analyze_p.add_argument(
        'directory',
        help='Directory containing width-parameterized *.ini files'
    )
    analyze_p.add_argument(
        '--output', '-o',
        default=None,
        help='Output JSON model file (default: tire_model.json next to this script)'
    )
    analyze_p.add_argument(
        '--degree', '-d',
        type=int,
        default=2,
        help='Polynomial degree to fit (default: 2)'
    )
    analyze_p.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Suppress per-property output table'
    )

    # ---- compare -------------------------------------------------------
    compare_p = sub.add_parser(
        'compare',
        help='Compare tire properties between two tires (by name or index)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""Compare two tires property-by-property.

Each tire is specified as: file.ini[:selector]
where selector is a 0-based index (integer) or a tire name (string).
Omit the selector to use the first tire (index 0).
Omit the filename (e.g. ":1") to assume tyres.ini.

To compare within the same file, pass the same file twice with different selectors.

Examples:
  compare tyres.ini ref.ini
  compare tyres.ini ref.ini --front
  compare tyres.ini:0 ref.ini:1
  compare tyres.ini:"TCR M" ref.ini:"Valino Pergea"
  compare :0 :1
  compare tyres.ini:0 tyres.ini:1 --rear
""",
    )
    compare_p.add_argument(
        'tire_a',
        metavar='fileA[:selector]',
        help='First tire: file path with optional :name or :index'
    )
    compare_p.add_argument(
        'tire_b',
        metavar='fileB[:selector]',
        help='Second tire: file path with optional :name or :index'
    )
    compare_p.add_argument(
        '--front', '-f',
        action='store_true',
        help='Compare only FRONT / THERMAL_FRONT sections'
    )
    compare_p.add_argument(
        '--rear', '-r',
        action='store_true',
        help='Compare only REAR / THERMAL_REAR sections'
    )
    compare_p.add_argument(
        '--threshold', '-t',
        type=float,
        default=5.0,
        help='Percentage difference threshold for warnings (default: 5.0)'
    )

    args = parser.parse_args()

    if args.command == 'analyze':
        directory = Path(args.directory)
        if not directory.is_dir():
            print(f"Error: directory not found: {directory}")
            sys.exit(1)

        output_path = Path(args.output) if args.output else Path(__file__).parent / 'tire_model.json'

        print(f"Analyzing tire data in: {directory.resolve()}")
        print(f"Output model:           {output_path.resolve()}")
        print()

        analyze(
            directory=directory,
            output_path=output_path,
            poly_degree=args.degree,
            verbose=not args.quiet,
        )

    elif args.command == 'compare':
        file_a, sel_a = _parse_file_spec(args.tire_a)
        file_b, sel_b = _parse_file_spec(args.tire_b)

        compare(
            file_a=file_a, selector_a=sel_a,
            file_b=file_b, selector_b=sel_b,
            show_front=args.front,
            show_rear=args.rear,
            threshold=args.threshold,
        )

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
