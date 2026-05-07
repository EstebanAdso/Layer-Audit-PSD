"""
repairer.py
===========
Wrapper Python sobre binary_repair.repair_psd, con la misma interfaz que
exponiamos antes para no tocar la GUI.

binary_repair hace cirugia binaria pura: modifica solo 16 bytes (tx + ty)
por cada layer desincronizado, sin reescribir el archivo completo. Esto:

    - Funciona con cualquier modo color (RGB, CMYK, Grayscale, Lab, etc).
    - Preserva bitmaps, smart objects, mascaras, ICC profile, alpha
      channels, layer comps, fuentes — todo, byte a byte.
    - El archivo de salida tiene el mismo tamaño que el original.
    - No requiere Node.js ni dependencias externas.
"""

from __future__ import annotations

import json
import os
import sys

import binary_repair
from detector import THRESHOLD_PX


def make_repair_path(input_path):
    base, ext = os.path.splitext(input_path)
    if not ext:
        ext = '.psd'
    return f"{base}_fixed{ext}"


def get_repair_capability():
    """
    {'available': bool, 'method': str, 'reason': str}.

    La reparacion binaria es Python puro y siempre esta disponible mientras
    psd-tools este instalado.
    """
    try:
        import psd_tools  # noqa: F401
    except ImportError:
        return {
            'available': False, 'method': 'binary',
            'reason': "psd-tools no esta instalado",
        }
    return {
        'available': True, 'method': 'binary',
        'reason': "Cirugia binaria (Python puro)",
    }


def repair_psd(input_path, output_path=None, threshold=THRESHOLD_PX):
    """
    Genera <input>_fixed.psd con tx/ty resincronizados.

    Returns dict {
        'success':     bool,
        'output_path': str | None,
        'error':       str | None,
        'method':      str | None,
        'report':      dict | None,
    }
    """
    cap = get_repair_capability()
    if not cap['available']:
        return {'success': False, 'output_path': None,
                'error': cap['reason'], 'method': cap['method'],
                'report': None}

    if not os.path.exists(input_path):
        return {'success': False, 'output_path': None,
                'error': f"No existe el archivo: {input_path}",
                'method': cap['method'], 'report': None}

    if output_path is None:
        output_path = make_repair_path(input_path)
    output_path = os.path.abspath(output_path)

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError as e:
            return {'success': False, 'output_path': None,
                    'error': f"No se pudo borrar {output_path} previo: {e}",
                    'method': cap['method'], 'report': None}

    r = binary_repair.repair_psd(input_path, output_path, threshold)
    return {
        'success':     r['success'],
        'output_path': r['output_path'],
        'error':       r['error'],
        'method':      cap['method'],
        'report':      r['report'],
    }


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("uso: python repairer.py archivo.psd")
        sys.exit(1)
    cap = get_repair_capability()
    print(f"capability: {cap}")
    if not cap['available']:
        sys.exit(2)
    r = repair_psd(sys.argv[1])
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r['success'] else 1)
