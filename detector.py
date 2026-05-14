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

# Margen separado para validar contra el artboard/grupo padre. En piezas
# multiplaforma con texto centrado o justificado, Photoshop puede guardar el
# punto de texto un poco fuera del artboard aunque la capa sea sana.
OUT_OF_PARENT_MARGIN = 250


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


def _extract_type_style(layer):
    style = {}
    try:
        ed = layer.engine_dict
        run_array = ed['StyleRun']['RunArray']
        if not run_array:
            return style
        data = run_array[0]['StyleSheet']['StyleSheetData']
        for src, dst in (
                ('FontSize', 'font_size'),
                ('Leading', 'leading'),
                ('Tracking', 'tracking')):
            value = data.get(src)
            if value is not None:
                try:
                    value = float(value)
                except Exception:
                    pass
                style[dst] = value
        faux_bold = data.get('FauxBold')
        if faux_bold is not None:
            style['faux_bold'] = bool(faux_bold)
        # Fuente: leer el indice de Font del run y resolverlo contra el
        # FontSet del resource_dict de la capa. Los bytes crudos del PSD
        # son la unica fuente confiable — Photoshop en runtime puede
        # sustituir la fuente cuando la capa tiene herencia/transform
        # corruptos, y entonces textItem.font / fontPostScriptName del
        # descriptor en vivo devuelven la fuente sustituta (ej. Myriad
        # Pro Regular) en vez de la original.
        font_idx = data.get('Font')
        if font_idx is not None:
            try:
                rd = layer.resource_dict
                font_set = rd.get('FontSet', []) if hasattr(rd, 'get') else []
                if 0 <= int(font_idx) < len(font_set):
                    font_name = font_set[int(font_idx)].get('Name')
                    if font_name:
                        # psd_tools devuelve el nombre con las comillas
                        # simples literales del formato TyShO crudo
                        # ("'PPPangramSansRounded-...'"). Hay que limpiarlas
                        # para que sea un PostScript name valido para PS.
                        clean = str(font_name).strip()
                        if len(clean) >= 2 and clean[0] == "'" and clean[-1] == "'":
                            clean = clean[1:-1]
                        if clean:
                            style['font_name'] = clean
            except Exception:
                pass
    except Exception:
        pass
    return style


def _read_text_orientation_descriptor(layer):
    """Lee el campo `Ornt` (orientation) del descriptor TyShO de la capa.

    Devuelve 'vertical' si el texto fue creado como texto vertical real
    (escritura columnar al estilo CJK), 'horizontal' si es horizontal
    standard, o None si no se pudo leer.

    El bbox visual puede ser alto y delgado incluso con Ornt='Hrzn'
    cuando la capa fue rotada 90 grados — el campo Ornt solo refleja
    la direccion natural de escritura del texto, no rotaciones de capa.
    """
    try:
        for blk in layer._record.tagged_blocks.values():
            data = getattr(blk, 'data', None)
            if data is None or not hasattr(data, 'text_data'):
                continue
            ornt = data.text_data.get(b'Ornt')
            if ornt is None:
                continue
            enum = getattr(ornt, 'enum', None)
            if enum == b'Vrtc':
                return 'vertical'
            if enum == b'Hrzn':
                return 'horizontal'
            return None
    except Exception:
        return None
    return None


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
    bounds_right = layer.right
    bounds_bottom = layer.bottom
    layer_id = _safe_attr(layer, 'layer_id')
    parent = _safe_attr(layer, 'parent')
    parent_id = _safe_attr(parent, 'layer_id')
    parent_name = _safe_attr(parent, 'name')
    parent_bounds = None
    try:
        parent_bounds = tuple(parent.bbox) if parent is not None else None
    except Exception:
        parent_bounds = None

    try:
        # transform = (xx, xy, yx, yy, tx, ty)
        xx, xy, yx, yy, tx, ty = layer.transform
        delta_x = abs(tx - bounds_left)
        delta_y = abs(ty - bounds_top)

        # Regla 1: threshold fijo. En capas de texto alineadas al centro o
        # a la derecha, tx puede alejarse bastante de bounds.left sin estar
        # corrupto; por eso el delta solo es problema si el transform queda
        # fuera del contenedor natural de la capa.
        delta_exceeded = delta_x > threshold_px or delta_y > threshold_px
        transform_out_of_parent = False
        if parent_bounds is not None:
            pl, pt, pr, pb = parent_bounds
            m = OUT_OF_PARENT_MARGIN
            if (tx < pl - m or tx > pr + m or
                    ty < pt - m or ty > pb + m):
                transform_out_of_parent = True

        # Regla 2: coordenadas claramente fuera del canvas.
        out_of_canvas = False
        if doc_width is not None and doc_height is not None:
            m = OUT_OF_CANVAS_MARGIN
            if (tx < -m or ty < -m or
                    tx > doc_width + m or ty > doc_height + m):
                out_of_canvas = True

        # Orientacion + rotacion. Distinguimos dos cosas:
        #   - orientation: direccion natural del texto (horizontal vs vertical
        #     real / escritura columnar CJK). La fija el campo `Ornt` del TyShO.
        #   - is_rotated: True si la CAPA fue rotada visualmente (la rotacion
        #     no aparece en el TyShO transform que lee psd_tools, pero queda
        #     evidente como un bbox alto y estrecho en un texto horizontal).
        orientation = 'horizontal'
        is_rotated = False
        ornt_field = _read_text_orientation_descriptor(layer)
        if ornt_field == 'vertical':
            orientation = 'vertical'
        else:
            # Fallback al engine_dict si no pudimos leer el campo Ornt.
            if ornt_field is None:
                try:
                    ed = layer.engine_dict
                    if ed and 'Editor' in ed:
                        if ed['Editor'].get('TextOrientation') == 1:
                            orientation = 'vertical'
                except Exception:
                    pass
            # Texto horizontal con bbox vertical -> capa rotada 90 grados.
            if orientation == 'horizontal' and layer.width > 0:
                try:
                    ratio = layer.height / layer.width
                except Exception:
                    ratio = 0
                if ratio > 5.0 and len(layer.text.strip()) > 2:
                    is_rotated = True

        is_problem = (delta_exceeded and transform_out_of_parent) or out_of_canvas
        reasons = []
        if delta_exceeded and transform_out_of_parent:
            reasons.append('delta-exceeded')
        if transform_out_of_parent:
            reasons.append('out-of-parent')
        if out_of_canvas:
            reasons.append('out-of-canvas')

        # En texto vertical Photoshop guarda la linea base en ty; puede estar
        # fuera del canvas en capas sanas. El indicador estable de herencia
        # corrupta para vertical es el eje X.
        if orientation == 'vertical':
            vertical_delta_exceeded = delta_x > threshold_px
            vertical_out_of_canvas = False
            vertical_out_of_parent = False
            if parent_bounds is not None:
                pl, pt, pr, pb = parent_bounds
                m = OUT_OF_PARENT_MARGIN
                vertical_out_of_parent = tx < pl - m or tx > pr + m
            if doc_width is not None:
                m = OUT_OF_CANVAS_MARGIN
                vertical_out_of_canvas = tx < -m or tx > doc_width + m
            is_problem = (
                vertical_delta_exceeded and vertical_out_of_parent
            ) or vertical_out_of_canvas
            reasons = []
            if vertical_delta_exceeded and vertical_out_of_parent:
                reasons.append('delta-x-exceeded')
            if vertical_out_of_parent:
                reasons.append('x-out-of-parent')
            if vertical_out_of_canvas:
                reasons.append('x-out-of-canvas')

        matrix = (1, 0, 0, 1, tx, ty)
        try:
            matrix = list(layer.transform)
        except:
            pass

        return {
            'name': layer.name,
            'layer_id': layer_id,
            'parent_id': parent_id,
            'parent_name': parent_name,
            'parent_bounds': parent_bounds,
            'style': _extract_type_style(layer),
            'status': 'DESINCRONIZADO' if is_problem else 'OK',
            'is_problem': is_problem,
            'bounds': (bounds_left, bounds_top),
            'bounds_full': (bounds_left, bounds_top, bounds_right, bounds_bottom),
            'width': layer.width,
            'height': layer.height,
            'orientation': orientation,
            'is_rotated': is_rotated,
            'matrix': matrix,
            'transform': (tx, ty),
            'delta': (delta_x, delta_y),
            'threshold': threshold_px,
            'reasons': reasons,
            'error': None,
        }
    except Exception as e:
        return {
            'name': layer.name,
            'layer_id': layer_id,
            'parent_id': parent_id,
            'parent_name': parent_name,
            'parent_bounds': parent_bounds,
            'style': _extract_type_style(layer),
            'status': 'NO PUDO LEER TRANSFORM',
            'is_problem': False,
            'bounds': (bounds_left, bounds_top),
            'bounds_full': (bounds_left, bounds_top, bounds_right, bounds_bottom),
            'width': layer.width,
            'height': layer.height,
            'orientation': 'horizontal',
            'is_rotated': False,
            'matrix': (1, 0, 0, 1, 0, 0),
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

    templates_by_parent = {}
    fallback_template = None
    for r in layers_results:
        if r['is_problem']:
            continue
        template = {
            'layer_id': r.get('layer_id'),
            'name': r.get('name'),
        }
        if template['layer_id'] is None:
            continue
        if fallback_template is None:
            fallback_template = template
        parent_id = r.get('parent_id')
        if parent_id is not None and parent_id not in templates_by_parent:
            templates_by_parent[parent_id] = template

    for r in layers_results:
        if not r['is_problem']:
            continue
        template = templates_by_parent.get(r.get('parent_id')) or fallback_template
        if template:
            r['template_layer_id'] = template['layer_id']
            r['template_layer_name'] = template['name']

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
