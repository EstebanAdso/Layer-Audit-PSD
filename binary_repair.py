"""
binary_repair.py
================
Reparador de PSDs basado en cirugia binaria: modifica IN-PLACE 16 bytes
por cada layer desincronizado -- los componentes tx y ty del transform
en el chunk `TySh`. NO reescribe el archivo entero, evitando los problemas
que tienen los parsers completos de PSD (perdida de modo CMYK, fallo con
artboards, edge cases con smart objects).

Estructura del chunk Tagged Block "TySh" (TypeToolObjectSetting):
    bytes 0-1   version (uint16)
    bytes 2-49  transform: 6 doubles big-endian (xx, xy, yx, yy, tx, ty)
                * tx esta en bytes 34-41
                * ty esta en bytes 42-49
    ...

Estrategia: para cada TypeLayer desincronizado:
    1. Reconstruimos el patron exacto de 48 bytes del transform con
       struct.pack('>6d', xx, xy, yx, yy, tx, ty) — los doubles tienen
       precision unica, asi que el patron es practicamente unico en el PSD.
    2. Buscamos ese patron en el archivo. Si hay varias ocurrencias, las
       asignamos a layers en orden de aparicion (los chunks TySh estan en
       el archivo en el mismo orden que los TypeLayer).
    3. Sobrescribimos los 16 bytes de tx/ty con los nuevos valores
       (visualLeft, visualTop) usando struct.pack('>d', value).

Ventajas:
    - Funciona con cualquier modo color: RGB, CMYK, Grayscale, Lab, etc.
    - El archivo de salida tiene el mismo tamaño que el original.
    - No toca color mode, channels, image data, smart objects, mascaras,
      ICC profile, alpha channels, layer comps, fuentes, ajustes — nada
      excepto los 16 bytes especificos.
    - Preserva escala/rotacion legitimas (xx, xy, yx, yy intactos).
"""

from __future__ import annotations

import struct
from psd_tools import PSDImage
from psd_tools.api.layers import TypeLayer

from detector import THRESHOLD_PX


def _collect_type_layers(layer, out=None):
    if out is None:
        out = []
    if isinstance(layer, TypeLayer):
        out.append(layer)
    if hasattr(layer, '__iter__'):
        for c in layer:
            _collect_type_layers(c, out)
    return out


def _find_all(data: bytes, pattern: bytes) -> list:
    """Devuelve todas las posiciones donde aparece `pattern` en `data`."""
    positions = []
    start = 0
    n = len(data)
    while start <= n:
        idx = data.find(pattern, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def repair_psd(input_path: str, output_path: str,
               threshold: int = THRESHOLD_PX) -> dict:
    """
    Repara un PSD modificando solo los componentes tx/ty del transform
    de los TypeLayers desincronizados.

    Returns dict {
        'success': bool,
        'output_path': str | None,
        'error': str | None,
        'report': {
            'text_layers': int, 'fixed': int, 'in_sync': int,
            'skipped': int, 'errors': list[str], 'details': list[dict]
        }
    }
    """
    report = {
        'text_layers': 0, 'fixed': 0, 'in_sync': 0,
        'skipped': 0, 'errors': [], 'details': [],
    }

    # Leer PSD entero a memoria
    try:
        with open(input_path, 'rb') as f:
            data = bytearray(f.read())
    except OSError as e:
        return {'success': False, 'output_path': None,
                'error': f"No se pudo leer {input_path}: {e}",
                'report': report}

    # Parsear con psd-tools (soporta CMYK perfectamente)
    try:
        psd = PSDImage.open(input_path)
    except Exception as e:
        return {'success': False, 'output_path': None,
                'error': f"psd-tools fallo al abrir: {e}",
                'report': report}

    type_layers = _collect_type_layers(psd)
    report['text_layers'] = len(type_layers)

    # Ordenar layers por orden documental: los chunks TySh aparecen en el
    # archivo en orden de creacion del layer. psd-tools los enumera en
    # orden DFS (parent -> children). Lo importante es que el orden sea
    # consistente entre nuestro parsing y el archivo binario.

    # Para cada layer, calcular el patron de transform original y el
    # transform reparado.
    plan = []
    for layer in type_layers:
        try:
            xx, xy, yx, yy, tx, ty = layer.transform
        except Exception as e:
            report['skipped'] += 1
            report['errors'].append(f"{layer.name}: no transform ({e})")
            continue

        bl, bt = layer.left, layer.top

        detail = {
            'name': layer.name,
            'visual': [bl, bt],
            'transform_before': [tx, ty],
            'xx': xx, 'xy': xy, 'yx': yx, 'yy': yy,
        }

        if abs(tx - bl) <= threshold and abs(ty - bt) <= threshold:
            detail['action'] = 'in-sync'
            report['in_sync'] += 1
            report['details'].append(detail)
            continue

        # Patron a buscar: 48 bytes de los 6 doubles big-endian
        try:
            pattern = struct.pack('>6d', xx, xy, yx, yy, tx, ty)
        except struct.error as e:
            report['skipped'] += 1
            report['errors'].append(f"{layer.name}: pack fallo {e}")
            continue

        plan.append({
            'layer': layer,
            'pattern': pattern,
            'new_tx': float(bl),
            'new_ty': float(bt),
            'detail': detail,
        })

    if not plan:
        # Nada que reparar — copiar tal cual
        try:
            with open(output_path, 'wb') as f:
                f.write(bytes(data))
        except OSError as e:
            return {'success': False, 'output_path': None,
                    'error': f"No se pudo escribir {output_path}: {e}",
                    'report': report}
        return {'success': True, 'output_path': output_path,
                'error': None, 'report': report}

    # Buscar todos los matches de cada patron y asignarlos a layers en
    # orden de aparicion en el archivo (chunks TySh siguen el orden DFS
    # documental).
    bytes_data = bytes(data)
    consumed_offsets = set()

    for item in plan:
        positions = _find_all(bytes_data, item['pattern'])
        # Filtrar offsets ya usados por otro layer con el mismo transform
        available = [p for p in positions if p not in consumed_offsets]

        if not available:
            item['detail']['action'] = 'pattern-not-found'
            report['skipped'] += 1
            report['errors'].append(
                f"{item['layer'].name}: patron de transform no encontrado en binario"
            )
            report['details'].append(item['detail'])
            continue

        # Tomar la primera posicion disponible
        offset = available[0]
        consumed_offsets.add(offset)

        # tx esta en [offset + 32, offset + 40)
        # ty esta en [offset + 40, offset + 48)
        new_tx_bytes = struct.pack('>d', item['new_tx'])
        new_ty_bytes = struct.pack('>d', item['new_ty'])
        data[offset + 32:offset + 40] = new_tx_bytes
        data[offset + 40:offset + 48] = new_ty_bytes

        item['detail']['action'] = 'fixed'
        item['detail']['offset'] = offset
        item['detail']['transform_after'] = [item['new_tx'], item['new_ty']]
        report['fixed'] += 1
        report['details'].append(item['detail'])

    try:
        with open(output_path, 'wb') as f:
            f.write(bytes(data))
    except OSError as e:
        return {'success': False, 'output_path': None,
                'error': f"No se pudo escribir {output_path}: {e}",
                'report': report}

    return {'success': True, 'output_path': output_path,
            'error': None, 'report': report}


if __name__ == '__main__':
    import json
    import os
    import sys

    if len(sys.argv) < 2:
        print("uso: python binary_repair.py archivo.psd [output.psd]")
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) >= 3 else (
        os.path.splitext(src)[0] + '_fixed.psd'
    )
    r = repair_psd(src, out)
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    sys.exit(0 if r['success'] else 1)
