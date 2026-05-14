"""Genera el _fixed para un PSD y compara manifest contra el original.

Uso:
    python _compare_fix.py path/to/file.psd [--wait 120]
"""
import argparse
import json
import os
import sys
import tempfile
import time

from detector import analyze_psd
from fixer import fix_layers_in_psd


def build_layer_data(problems):
    layer_data = []
    for p in problems:
        bl, bt = p['bounds']
        bf = p.get('bounds_full', (bl, bt, bl + p['width'], bt + p['height']))
        layer_data.append({
            'name': p['name'],
            'layer_id': p.get('layer_id'),
            'template_layer_id': p.get('template_layer_id'),
            'template_layer_name': p.get('template_layer_name'),
            'width': p['width'],
            'height': p['height'],
            'left': bl,
            'top': bt,
            'right': bf[2],
            'bottom': bf[3],
            'style': p.get('style', {}),
            'orientation': p.get('orientation', 'horizontal'),
            'is_rotated': p.get('is_rotated', False),
            'matrix': p.get('matrix', [1, 0, 0, 1, 0, 0]),
        })
    return layer_data


def layer_index(result):
    return {L['name']: L for L in result.get('layers', [])}


def compare(original, fixed, log):
    orig_idx = layer_index(original)
    fix_idx = layer_index(fixed)

    log.append("=" * 80)
    log.append(f"COMPARACIÓN: {len(orig_idx)} layers original vs {len(fix_idx)} layers fixed")
    log.append("=" * 80)

    all_names = set(orig_idx) | set(fix_idx)
    only_orig = set(orig_idx) - set(fix_idx)
    only_fix = set(fix_idx) - set(orig_idx)
    if only_orig:
        log.append(f"\nFALTAN en fixed: {sorted(only_orig)}")
    if only_fix:
        log.append(f"\nEXTRA en fixed: {sorted(only_fix)}")

    differences = []
    fixed_problems_after = sum(1 for L in fixed.get('layers', []) if L.get('is_problem'))
    log.append(f"\nProblemas detectados en fixed: {fixed_problems_after}")
    if fixed_problems_after:
        for L in fixed.get('layers', []):
            if L.get('is_problem'):
                log.append(f"  - {L['name']}: reasons={L.get('reasons')}")

    for name in sorted(all_names & set(orig_idx) & set(fix_idx)):
        a = orig_idx[name]
        b = fix_idx[name]
        ab = a.get('bounds_full')
        bb = b.get('bounds_full')
        sa = a.get('style') or {}
        sb = b.get('style') or {}

        bounds_match = (ab == bb)
        size_a = sa.get('font_size')
        size_b = sb.get('font_size')
        ma = a.get('matrix') or []
        mb = b.get('matrix') or []
        scale_a = max(abs(ma[0]) if len(ma) > 0 else 1, abs(ma[3]) if len(ma) > 3 else 1)
        scale_b = max(abs(mb[0]) if len(mb) > 0 else 1, abs(mb[3]) if len(mb) > 3 else 1)
        # tamaño visual aproximado = font_size * scale
        eff_a = (size_a or 0) * scale_a
        eff_b = (size_b or 0) * scale_b

        was_problem = a.get('is_problem')
        marker = ""
        if was_problem:
            marker = " [WAS PROBLEM]"
            d_bounds_x = (bb[0] - ab[0]) if (ab and bb) else 0
            d_bounds_y = (bb[1] - ab[1]) if (ab and bb) else 0
            d_bounds_r = (bb[2] - ab[2]) if (ab and bb) else 0
            d_bounds_b = (bb[3] - ab[3]) if (ab and bb) else 0
            log.append(f"\n  {name}{marker}")
            log.append(f"    bounds_full orig:  {ab}")
            log.append(f"    bounds_full fixed: {bb}")
            log.append(f"    delta bounds: ({d_bounds_x:+}, {d_bounds_y:+}, {d_bounds_r:+}, {d_bounds_b:+})")
            log.append(f"    font_size orig=  {size_a}  fixed=  {size_b}")
            log.append(f"    scale orig=  {scale_a:.4f}  fixed=  {scale_b:.4f}")
            log.append(f"    effective_size orig=  {eff_a:.4f}  fixed=  {eff_b:.4f}")
            log.append(f"    status fixed: {b.get('status')}  problem={b.get('is_problem')}")
            if not bounds_match:
                # tolerancia de +-1 px por redondeo del motor de texto
                if (ab and bb and max(abs(bb[0] - ab[0]), abs(bb[1] - ab[1]),
                                       abs(bb[2] - ab[2]), abs(bb[3] - ab[3])) > 1):
                    differences.append((name, "bounds", ab, bb))

    log.append("\n" + "=" * 80)
    if differences:
        log.append(f"  DIFERENCIAS DETECTADAS: {len(differences)}")
        for d in differences:
            log.append(f"   - {d[0]} ({d[1]}): {d[2]} vs {d[3]}")
    else:
        log.append("  TODAS LAS CAPAS REPARADAS COINCIDEN.")
    log.append("=" * 80)
    return differences, fixed_problems_after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("psd_path")
    ap.add_argument("--wait", type=int, default=120)
    ap.add_argument("--skip-launch", action="store_true",
                    help="No relanza Photoshop, asume que el _fixed ya existe")
    args = ap.parse_args()

    psd_path = os.path.abspath(args.psd_path)
    if not os.path.exists(psd_path):
        print(f"NOT FOUND: {psd_path}")
        sys.exit(1)
    fixed_path = psd_path[:psd_path.rfind('.')] + "_fixed" + psd_path[psd_path.rfind('.'):]
    fixed_path_alt = fixed_path.lower()
    if fixed_path_alt != fixed_path and os.path.exists(fixed_path_alt):
        fixed_path = fixed_path_alt

    print(f"\n--- 1. Análisis original: {psd_path} ---")
    original = analyze_psd(psd_path)
    print(f"Layers: {original['total']}  Problemas: {len(original['problems'])}")
    if not original['problems'] and not args.skip_launch:
        print("Sin problemas. Nada que reparar.")
        return

    if not args.skip_launch:
        layer_data = build_layer_data(original['problems'])
        print(f"\n--- 2. Lanzando fixer con {len(layer_data)} entries ---")

        # Limpiar señalización
        temp_dir = tempfile.gettempdir()
        done_path = os.path.join(temp_dir, "psd_fix_done.txt")
        log_path = os.path.join(temp_dir, "psd_fix_log.txt")
        for stale in (done_path, log_path):
            if os.path.exists(stale):
                os.remove(stale)
        if os.path.exists(fixed_path):
            try:
                os.remove(fixed_path)
                print(f"  borrado anterior: {fixed_path}")
            except OSError as e:
                print(f"  no pude borrar {fixed_path}: {e}")

        ok = fix_layers_in_psd(psd_path, layer_data)
        if not ok:
            print("ERROR al lanzar fixer")
            sys.exit(2)
        print(f"  lanzado. esperando {args.wait}s...")

        start = time.time()
        while time.time() - start < args.wait:
            if os.path.exists(done_path):
                print(f"  done ({time.time() - start:.1f}s)")
                break
            time.sleep(2)
        else:
            print("  TIMEOUT: Photoshop no respondió")

        time.sleep(2)
        print("\n--- 3. Log de Photoshop ---")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                print(f.read())
        else:
            print("  (no se generó log)")

    print(f"\n--- 4. Análisis fixed: {fixed_path} ---")
    if not os.path.exists(fixed_path):
        print(f"  NO EXISTE el archivo fixed: {fixed_path}")
        sys.exit(3)
    fixed = analyze_psd(fixed_path)
    print(f"Layers: {fixed['total']}  Problemas: {len(fixed['problems'])}")

    log_lines = []
    diffs, leftover_problems = compare(original, fixed, log_lines)
    print("\n".join(log_lines))
    return 0 if not diffs and not leftover_problems else 4


if __name__ == "__main__":
    sys.exit(main() or 0)
