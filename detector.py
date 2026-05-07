"""
detector.py
===========
Logica compartida de deteccion de problemas en archivos PSD:

1. Text layers desincronizados:
   bounds visual difiere del transform interno (cuando se copia/pega un
   text layer entre artboards, Photoshop actualiza bounds pero NO el
   transform). La Photoshop API al reemplazar texto lo posiciona en el
   transform (lugar incorrecto).

2. Smart objects compartidos (linked instances):
   cuando se copia/pega un smart object con Ctrl+C/V, Photoshop crea un
   nuevo layer pero apunta al MISMO asset embebido (mismo UUID interno).
   Editar uno actualiza ambos -> la Photoshop API no puede reemplazar la
   imagen de uno sin afectar al otro.
"""

from collections import defaultdict

from psd_tools import PSDImage
from psd_tools.api.layers import (
    Artboard, Group, SmartObjectLayer, TypeLayer,
)


def _is_regular_group(layer):
    """True si el layer es un Group normal (no un Artboard)."""
    return isinstance(layer, Group) and not isinstance(layer, Artboard)

# Threshold para considerar un layer como desincronizado.
#
# Si |tx - bounds.left| > THRESHOLD_PX o |ty - bounds.top| > THRESHOLD_PX,
# se marca como problema. El padding "natural" del motor de texto
# (metricas de fuente, leading, alineacion) raramente supera 150 px;
# 200 px deja margen para casos legitimos sin ocultar movimientos reales
# de copy-paste (que tipicamente generan deltas de cientos a miles de px).
THRESHOLD_PX = 200

# Margen de tolerancia para considerar un transform como "fuera del canvas".
# Si tx o ty caen mas alla del canvas en mas de OUT_OF_CANVAS_MARGIN px en
# cualquier direccion, es problema sin importar el delta. Esto pesca casos
# donde el delta seria pequeño pero la coordenada interna ya es invalida
# (ej. transform en (-50, -100) con un canvas que arranca en 0,0).
OUT_OF_CANVAS_MARGIN = 100


def collect_type_layers(layer, layers=None, skip_groups=False):
    """Recorre recursivamente el arbol y devuelve los TypeLayer.

    Si skip_groups=True, no desciende dentro de Groups regulares (los
    Artboards SI se recorren porque son el contenedor "natural" de cada
    pieza). Esto permite ignorar carpetas que normalmente contienen
    elementos compartidos entre plataformas (logos, legales fijos, etc).
    """
    if layers is None:
        layers = []
    if isinstance(layer, TypeLayer):
        layers.append(layer)
    if hasattr(layer, '__iter__'):
        for child in layer:
            if skip_groups and _is_regular_group(child):
                continue
            collect_type_layers(child, layers, skip_groups=skip_groups)
    return layers


def collect_smart_object_layers(layer, layers=None, skip_groups=False):
    """Recorre recursivamente el arbol y devuelve los SmartObjectLayer.

    Mismo comportamiento de skip_groups que collect_type_layers.
    """
    if layers is None:
        layers = []
    if isinstance(layer, SmartObjectLayer):
        layers.append(layer)
    if hasattr(layer, '__iter__'):
        for child in layer:
            if skip_groups and _is_regular_group(child):
                continue
            collect_smart_object_layers(child, layers, skip_groups=skip_groups)
    return layers


def _safe_attr(obj, name, default=None):
    try:
        v = getattr(obj, name, default)
        return v
    except Exception:
        return default


def analyze_smart_objects(smart_objects):
    """
    Identifica grupos de SmartObjectLayer que comparten el mismo
    UUID interno -- al copiarse con Ctrl+C/V apuntan al mismo asset
    embebido y editar uno actualiza todos.

    Retorna lista de dicts:
        {
            'unique_id': str,
            'filename':  str,
            'count':     int,
            'layers':    [{'name': str, 'bounds': (l, t, r, b)}, ...],
            'is_problem': True,
        }
    Solo se incluyen grupos con count >= 2.
    """
    by_uid = defaultdict(list)
    for layer in smart_objects:
        try:
            so = layer.smart_object
        except Exception:
            continue
        uid = _safe_attr(so, 'unique_id') or _safe_attr(so, 'uuid')
        if not uid:
            continue
        uid_str = uid.decode('ascii') if isinstance(uid, bytes) else str(uid)
        by_uid[uid_str].append((layer, so))

    groups = []
    for uid, items in by_uid.items():
        if len(items) < 2:
            continue
        layer_descs = []
        filename = None
        for layer, so in items:
            if filename is None:
                filename = _safe_attr(so, 'filename')
            try:
                bounds = (layer.left, layer.top, layer.right, layer.bottom)
            except Exception:
                bounds = (0, 0, 0, 0)
            layer_descs.append({
                'name': _safe_attr(layer, 'name') or '(sin nombre)',
                'bounds': bounds,
            })
        groups.append({
            'unique_id': uid,
            'filename': filename,
            'count': len(items),
            'layers': layer_descs,
            'is_problem': True,
        })
    return groups


def check_type_layer(layer, threshold_px=THRESHOLD_PX,
                     doc_width=None, doc_height=None):
    """Verifica un TypeLayer y devuelve un dict con su estado.

    Compara bounds visuales contra el transform interno con dos reglas
    independientes:

    1. Threshold de delta: si |tx - left| o |ty - top| supera
       THRESHOLD_PX (200 px), es problema. Layers sanos tienen delta
       <150 px (padding del motor de texto); deltas mayores indican
       copy-paste real.

    2. Out-of-canvas: si tx/ty caen mas alla del canvas (con
       OUT_OF_CANVAS_MARGIN px de tolerancia), es problema sin importar
       el delta. Esto pesca casos donde el delta seria pequeño pero la
       coordenada interna ya es invalida (transforms negativos o que
       superan width/height del documento).
    """
    bounds_left = layer.left
    bounds_top = layer.top

    try:
        # transform = (xx, xy, yx, yy, tx, ty)
        xx, xy, yx, yy, tx, ty = layer.transform
        delta_x = abs(tx - bounds_left)
        delta_y = abs(ty - bounds_top)

        # Regla 1: threshold fijo
        delta_exceeded = delta_x > threshold_px or delta_y > threshold_px

        # Regla 2: coordenadas claramente fuera del canvas
        out_of_canvas = False
        if doc_width is not None and doc_height is not None:
            m = OUT_OF_CANVAS_MARGIN
            if (tx < -m or ty < -m or
                    tx > doc_width + m or ty > doc_height + m):
                out_of_canvas = True

        is_problem = delta_exceeded or out_of_canvas
        reasons = []
        if delta_exceeded:
            reasons.append('delta-exceeded')
        if out_of_canvas:
            reasons.append('out-of-canvas')

        return {
            'name': layer.name,
            'status': 'DESINCRONIZADO' if is_problem else 'OK',
            'is_problem': is_problem,
            'bounds': (bounds_left, bounds_top),
            'transform': (tx, ty),
            'delta': (delta_x, delta_y),
            'threshold': threshold_px,
            'reasons': reasons,
            'error': None,
        }
    except Exception as e:
        return {
            'name': layer.name,
            'status': 'NO PUDO LEER TRANSFORM',
            'is_problem': False,
            'bounds': (bounds_left, bounds_top),
            'transform': None,
            'delta': None,
            'threshold': None,
            'reasons': [],
            'error': str(e),
        }


def analyze_psd(psd_path, threshold_px=THRESHOLD_PX,
                progress_callback=None, skip_groups=True):
    """Analiza un archivo PSD y devuelve sus resultados.

    skip_groups: si es True (default), ignora layers dentro de Groups
                 normales (no Artboards). Util cuando los grupos contienen
                 assets compartidos entre plataformas (logos, legales fijos)
                 que el equipo no piensa modificar via API.

    Retorna dict con:
        - path:     ruta de entrada
        - width, height: dimensiones del documento
        - skip_groups: el valor usado en este analisis
        - layers:   lista de resultados por text layer
        - problems: subset de text layers con is_problem == True
        - total:    cantidad de text layers encontrados
        - smart_object_groups:    lista de grupos de SmartObject por uuid
                                  (todos los grupos, len>=1)
        - shared_smart_objects:   solo grupos compartidos (len>=2) — son problema
        - smart_object_total:     cantidad total de SmartObjectLayer encontrados
        - error:    str con el error de carga, o None
    """
    if progress_callback:
        progress_callback(5.0, "Abriendo PSD...")

    try:
        psd = PSDImage.open(psd_path)
    except Exception as e:
        return {
            'path': psd_path,
            'width': 0, 'height': 0,
            'skip_groups': skip_groups,
            'layers': [], 'problems': [], 'total': 0,
            'smart_object_groups': [],
            'shared_smart_objects': [],
            'smart_object_total': 0,
            'error': f"No se pudo abrir el PSD: {e}",
        }

    if progress_callback:
        progress_callback(25.0, "Recopilando layers...")

    type_layers = []
    smart_object_layers = []
    for layer in psd:
        # En el primer nivel del documento, si skip_groups y es Group regular,
        # saltarlo. Si es Artboard u otro tipo de layer, recorrer normal.
        if skip_groups and _is_regular_group(layer):
            continue
        collect_type_layers(layer, type_layers, skip_groups=skip_groups)
        collect_smart_object_layers(
            layer, smart_object_layers, skip_groups=skip_groups
        )

    total = len(type_layers)
    layers_results = []

    if progress_callback:
        progress_callback(35.0, f"Analizando {total} text layer(s)...")

    if total > 0:
        doc_w, doc_h = psd.width, psd.height
        for i, tl in enumerate(type_layers):
            layers_results.append(
                check_type_layer(tl, threshold_px,
                                 doc_width=doc_w, doc_height=doc_h)
            )
            if progress_callback:
                pct = 35.0 + (50.0 * (i + 1) / total)
                progress_callback(pct, f"Text layers {i + 1}/{total}")

    if progress_callback:
        progress_callback(85.0,
            f"Analizando {len(smart_object_layers)} smart object(s)...")

    so_groups = analyze_smart_objects(smart_object_layers)
    shared = [g for g in so_groups if g['is_problem']]

    if progress_callback:
        progress_callback(100.0, "Listo")

    return {
        'path': psd_path,
        'width': psd.width,
        'height': psd.height,
        'skip_groups': skip_groups,
        'layers': layers_results,
        'problems': [r for r in layers_results if r['is_problem']],
        'total': total,
        'smart_object_groups': so_groups,
        'shared_smart_objects': shared,
        'smart_object_total': len(smart_object_layers),
        'error': None,
    }
