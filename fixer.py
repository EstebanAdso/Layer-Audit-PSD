"""
fixer.py
========
Repara text layers desincronizados reescribiendo el PSD via ag-psd
(Node.js + agpsd/test11_boxbounds.js). Genera siempre una copia con
sufijo `_fixed.psd` al lado del archivo original — el PSD de entrada
nunca se modifica.

Reemplaza el antiguo flujo basado en Photoshop + JSX. Requiere Node.js
instalado en PATH y el directorio `agpsd/` con sus node_modules.
"""

import json
import os
import platform
import subprocess
import sys
import tempfile


def _find_agpsd_dir():
    """Localiza el directorio `agpsd/` (con test11_boxbounds.js + node_modules).

    En desarrollo es un sibling de este script; bajo PyInstaller esta
    en sys._MEIPASS.
    """
    if hasattr(sys, '_MEIPASS'):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'agpsd')


def _build_manifest(layer_data):
    """Convierte la lista interna de problem layers al formato que
    espera test11_boxbounds.js: [{name, left, top, right, bottom}, ...].
    """
    manifest = []
    for entry in layer_data:
        left = entry.get('left')
        top = entry.get('top')
        if left is None or top is None:
            continue
        right = entry.get('right')
        bottom = entry.get('bottom')
        if right is None:
            right = left + entry.get('width', 0)
        if bottom is None:
            bottom = top + entry.get('height', 0)
        manifest.append({
            'name': entry['name'],
            'left': int(round(left)),
            'top': int(round(top)),
            'right': int(round(right)),
            'bottom': int(round(bottom)),
        })
    return manifest


def fixed_path_for(psd_path):
    """Ruta de salida convencional: `<basename>_fixed<ext>` junto al original."""
    base, ext = os.path.splitext(psd_path)
    return f"{base}_fixed{ext}"


def fix_layers_in_psd(psd_path, layer_data):
    """Repara las capas indicadas y escribe `<base>_fixed.psd` al lado.

    Retorna True si la reparacion termino OK y el archivo de salida existe.
    El log/stderr de Node se vuelca a `psd_fix_log.txt` en temp.
    """
    if not layer_data:
        return False

    manifest = _build_manifest(layer_data)
    if not manifest:
        return False

    agpsd_dir = _find_agpsd_dir()
    jsx_path = os.path.join(agpsd_dir, 'test11_boxbounds.js')
    if not os.path.exists(jsx_path):
        print(f"No existe test11_boxbounds.js en {jsx_path}")
        return False

    temp_dir = tempfile.gettempdir()
    manifest_path = os.path.join(temp_dir, 'psd_layers_to_fix.json')
    log_path = os.path.join(temp_dir, 'psd_fix_log.txt')

    # Node corre con cwd=agpsd_dir; pasamos paths absolutos para que
    # path.resolve() en test11_boxbounds.js no los relativice al cwd.
    psd_path_abs = os.path.abspath(psd_path)
    output_path = fixed_path_for(psd_path_abs)
    manifest_path_abs = os.path.abspath(manifest_path)

    try:
        with open(manifest_path_abs, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error al escribir manifest: {e}")
        return False

    kwargs = {
        'cwd': agpsd_dir,
        'capture_output': True,
        'text': True,
        'encoding': 'utf-8',
        'errors': 'replace',
        # Sin timeout duro: PSDs muy grandes pueden tardar minutos.
        'timeout': 600,
    }
    if platform.system() == 'Windows' and hasattr(subprocess, 'CREATE_NO_WINDOW'):
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

    try:
        res = subprocess.run(
            ['node', 'test11_boxbounds.js',
             psd_path_abs, manifest_path_abs, output_path],
            **kwargs,
        )
    except FileNotFoundError:
        print("Node.js no esta instalado o no esta en PATH.")
        return False
    except subprocess.TimeoutExpired:
        print("La reparacion excedio el timeout de 10 minutos.")
        return False
    except Exception as e:
        print(f"Error lanzando Node: {e}")
        return False

    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f"$ node test11_boxbounds.js \"{psd_path}\" \"{manifest_path}\" \"{output_path}\"\n")
            f.write(f"exit code: {res.returncode}\n\n")
            f.write("--- stdout ---\n")
            f.write(res.stdout or '')
            f.write("\n--- stderr ---\n")
            f.write(res.stderr or '')
    except Exception:
        pass

    if res.returncode != 0:
        return False
    return os.path.exists(output_path)
