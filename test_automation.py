"""
Smoke test del ciclo detect -> fix con el motor ag-psd (Node).
Requiere Node.js en PATH y el directorio agpsd/ con node_modules.
"""

import os

from detector import analyze_psd
from fixer import fix_layers_in_psd, fixed_path_for


def test_full_cycle():
    psd_path = os.path.abspath("01_Story.psd")
    print(f"--- 1. Analizando {psd_path} ---")
    res = analyze_psd(psd_path)

    if not res['problems']:
        print("No se encontraron problemas iniciales.")
        return

    print(f"Detectadas {len(res['problems'])} capas con problemas.")
    layer_data = []
    for p in res['problems']:
        bl, bt = p['bounds']
        layer_data.append({
            'name': p['name'],
            'width': p['width'],
            'height': p['height'],
            'left': bl,
            'top': bt,
            'right': p.get('bounds_full',
                           (bl, bt, bl + p['width'], bt + p['height']))[2],
            'bottom': p.get('bounds_full',
                            (bl, bt, bl + p['width'], bt + p['height']))[3],
        })

    print("\n--- 2. Ejecutando fix_layers_in_psd ---")
    ok = fix_layers_in_psd(psd_path, layer_data)
    out = fixed_path_for(psd_path)
    print(f"  ok = {ok}")
    print(f"  output = {out} ({os.path.getsize(out) if os.path.exists(out) else 0} bytes)")

    if not ok or not os.path.exists(out):
        print("[X] La reparacion fallo.")
        return

    print("\n--- 3. Re-analizando archivo reparado ---")
    res2 = analyze_psd(out)
    remaining = len(res2['problems'])
    print(f"  problemas restantes: {remaining}")
    for L in res2['layers']:
        print(f"    [{L['status']}] {L['name']}  bounds={L['bounds']}  "
              f"transform={L['transform']}")


if __name__ == "__main__":
    test_full_cycle()
