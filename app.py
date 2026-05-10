"""
app.py
======
CLI de deteccion de text layers desincronizados en un PSD.

USO:
    pip install psd-tools
    python app.py ruta/al/archivo.psd
"""

import sys

from detector import analyze_psd


def _print_layer(result, indent="  "):
    name = result['name']
    status = result['status']

    if status == 'OK':
        tx, ty = result['transform']
        dx, dy = result['delta']
        print(f"{indent}[OK] '{name}'  (tx={tx:.0f}, ty={ty:.0f}, "
              f"Dx={dx:.0f}px, Dy={dy:.0f}px)")
    elif status == 'DESINCRONIZADO':
        bl, bt = result['bounds']
        tx, ty = result['transform']
        dx, dy = result['delta']
        print(f"{indent}[DESINCRONIZADO] '{name}'")
        print(f"{indent}    bounds (visual):   left={bl}, top={bt}")
        print(f"{indent}    transform interno: tx={tx:.1f},  ty={ty:.1f}")
        print(f"{indent}    delta:             Dx={dx:.0f}px, Dy={dy:.0f}px")
        print(f"{indent}    -> Layer movido/copiado incorrectamente.")
        print(f"{indent}       FALLARA al reemplazar texto con la Photoshop API.")
    else:
        err = result['error'] or ''
        print(f"{indent}[{status}] '{name}'  (error: {err})")


def main(psd_path, skip_groups=True):
    print(f"\n{'=' * 60}")
    print(f"  Analizando: {psd_path}")
    if skip_groups:
        print(f"  (ignorando layers dentro de grupos)")
    print(f"{'=' * 60}\n")

    result = analyze_psd(psd_path, skip_groups=skip_groups)

    if result['error']:
        print(f"Error al abrir el PSD: {result['error']}")
        sys.exit(1)

    print(f"Documento: {result['width']}x{result['height']}px\n")
    print("Revisando text layers...\n")

    for r in result['layers']:
        _print_layer(r)

    total = result['total']
    problemas = result['problems']
    so_total = result.get('smart_object_total', 0)
    shared_so = result.get('shared_smart_objects', [])

    print(f"\n{'=' * 60}")
    print(f"  RESUMEN")
    print(f"{'=' * 60}")
    print(f"  Text layers:             {total}  ({len(problemas)} con problemas)")
    print(f"  Smart objects:           {so_total}  ({len(shared_so)} grupos compartidos)")

    if problemas:
        print(f"\n  TEXT LAYERS QUE FALLARAN CON LA API:")
        for p in problemas:
            print(f"   -> '{p['name']}'")
        print(f"\n  SOLUCION TEXTO: en Photoshop, seleccionar el layer y "
              f"moverlo ligeramente o editar el texto para resincronizar "
              f"el transform interno con la posicion visual.")

    if shared_so:
        print(f"\n  SMART OBJECTS COMPARTIDOS (apuntan al mismo asset):")
        for g in shared_so:
            print(f"   -> {g.get('filename') or '(sin nombre)'}  "
                  f"[{g['count']} layers]")
            for L in g['layers']:
                print(f"      - {L['name']}")
        print(f"\n  SOLUCION SMART OBJECTS: en Photoshop, Layer -> Smart "
              f"Objects -> New Smart Object via Copy en cada layer "
              f"compartido para hacer instancias independientes.")

    if not problemas and not shared_so:
        print(f"\n  Todo sincronizado correctamente.")

    print(f"{'=' * 60}\n")


if __name__ == '__main__':
    args = sys.argv[1:]
    include_groups = False
    if '--include-groups' in args:
        include_groups = True
        args.remove('--include-groups')
    if len(args) < 1:
        print("Uso: python app.py [--include-groups] archivo.psd")
        print("  --include-groups: incluir layers dentro de grupos")
        print("                    (por defecto se ignoran)")
        sys.exit(1)
    main(args[0], skip_groups=not include_groups)
