#target photoshop

app.displayDialogs = DialogModes.NO;

if (typeof JSON !== "object") {
    JSON = {
        parse: function (s) { return eval("(" + s + ")"); }
    };
}

function cTID(s) { return charIDToTypeID(s); }
function sTID(s) { return stringIDToTypeID(s); }

function px(value) {
    try {
        return value.as("px");
    } catch (e) {
        return Number(value);
    }
}

function layerBounds(layer) {
    var b = layer.bounds;
    return {
        left: px(b[0]),
        top: px(b[1]),
        right: px(b[2]),
        bottom: px(b[3])
    };
}

function layerId(layer) {
    try {
        return Number(layer.id);
    } catch (e) {
        return null;
    }
}

function selectLayerById(id) {
    var desc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putIdentifier(cTID("Lyr "), Number(id));
    desc.putReference(cTID("null"), ref);
    desc.putBoolean(cTID("MkVs"), false);
    executeAction(cTID("slct"), desc, DialogModes.NO);
    return app.activeDocument.activeLayer;
}

function selectLayer(layer) {
    app.activeDocument.activeLayer = layer;
    return layer;
}

function findLayerByName(container, name) {
    for (var i = 0; i < container.layers.length; i++) {
        var layer = container.layers[i];
        if (layer.typename === "LayerSet") {
            var found = findLayerByName(layer, name);
            if (found) return found;
        } else if (layer.name === name) {
            return layer;
        }
    }
    return null;
}

function findLayer(doc, entry) {
    if (entry.layer_id !== undefined && entry.layer_id !== null && entry.layer_id !== "") {
        try {
            return selectLayerById(entry.layer_id);
        } catch (e) {}
    }
    return findLayerByName(doc, entry.name);
}

function getTargetLayerDescriptor() {
    var ref = new ActionReference();
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    return executeActionGet(ref);
}

function getTextKeyDescriptor(layer) {
    selectLayer(layer);
    var desc = getTargetLayerDescriptor();
    var key = sTID("textKey");
    if (desc.hasKey(key)) {
        return desc.getObjectValue(key);
    }
    key = cTID("Txt ");
    if (desc.hasKey(key)) {
        return desc.getObjectValue(key);
    }
    throw new Error("No se encontro textKey en la capa");
}

function logDescriptorKeys(desc, label, log) {
    var names = [];
    for (var i = 0; i < desc.count; i++) {
        var key = desc.getKey(i);
        var name = "";
        try { name = typeIDToStringID(key); } catch (e1) {}
        if (!name) {
            try { name = typeIDToCharID(key); } catch (e2) {}
        }
        names.push(name || String(key));
    }
    log.writeln("    keys " + label + ": " + names.join(", "));
}

function rewriteTextKeyTransform(textKey, targetLeft, targetTop, log) {
    logDescriptorKeys(textKey, "textKey", log);
    var shapeKey = sTID("textShape");
    if (textKey.hasKey(shapeKey)) {
        try {
            var shapeList = textKey.getList(shapeKey);
            log.writeln("    textShape items: " + shapeList.count);
            var updatedShapeList = new ActionList();
            for (var si = 0; si < shapeList.count; si++) {
                var shape = shapeList.getObjectValue(si);
                logDescriptorKeys(shape, "textShape[" + si + "]", log);
                var shapeTransformKey = sTID("transform");
                if (shape.hasKey(shapeTransformKey)) {
                    var shapeTransform = shape.getObjectValue(shapeTransformKey);
                    logDescriptorKeys(shapeTransform, "textShape[" + si + "].transform", log);
                    log.writeln("    textShape[" + si + "].transform se deja para reset nativo.");
                }
                updatedShapeList.putObject(sTID("textShape"), shape);
            }
            textKey.putList(shapeKey, updatedShapeList);
        } catch (shapeErr) {
            log.writeln("    WARNING leyendo textShape: " + shapeErr);
        }
    }

    var pointKey = sTID("textClickPoint");
    if (textKey.hasKey(pointKey)) {
        var point = textKey.getObjectValue(pointKey);
        point.putUnitDouble(cTID("Hrzn"), cTID("#Pxl"), targetLeft);
        point.putUnitDouble(cTID("Vrtc"), cTID("#Pxl"), targetTop);
        textKey.putObject(pointKey, cTID("Pnt "), point);
        log.writeln("    textClickPoint corregido a (" + targetLeft + "," + targetTop + ")");
    }

    var key = sTID("transform");
    if (!textKey.hasKey(key)) {
        key = cTID("Trnf");
    }
    if (!textKey.hasKey(key)) {
        log.writeln("    textKey no tiene transform separado.");
        return;
    }

    var transform = textKey.getObjectValue(key);
    transform.putUnitDouble(sTID("tx"), cTID("#Pxl"), targetLeft);
    transform.putUnitDouble(sTID("ty"), cTID("#Pxl"), targetTop);
    textKey.putObject(key, sTID("transform"), transform);
}

function applyTextKeyToActiveLayer(textKey) {
    var desc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    desc.putReference(cTID("null"), ref);
    desc.putObject(cTID("T   "), cTID("TxLr"), textKey);
    executeAction(cTID("setd"), desc, DialogModes.NO);
}

// Normaliza el transform corrupto de un text layer SIN recrear la capa.
// Tecnica del script Undeform (Jaroslav Bereza, MIT) + extensiones para
// nuestro caso de copy-paste entre artboards:
//
// Undeform original ([M] Undeform 1.1.jsx, mightyplugins.cc): para deshacer
// free transform, hace textKey.erase('transform') + put identity con tx=ty=0,
// y resetea warp. Confia en textClickPoint para el anchor.
//
// Nuestra extension: en copy-paste entre artboards, textClickPoint quedo
// apuntando al artboard ORIGINAL, no al nuevo. Por eso seteamos tx/ty al
// top-left visual ACTUAL (bounds.left/bounds.top), y tambien actualizamos
// textClickPoint y textShape.transform para que todos los anchors apunten al
// mismo lugar visual. NO compensamos impliedFontSize: el tamano visual lo
// determina impliedFontSize directamente (size POST-transform en panel
// Character) — al cambiar transform a identity, el visual se preserva
// porque impliedFontSize ya es el valor "absoluto" que Photoshop muestra.
//
//   1. Lee el textKey COMPLETO (font, color, styles, contents — intactos).
//   2. textKey.erase('transform') + put nuevo desc [1,0,0,1, targetLeft,
//      targetTop] — identidad con anchor en el bbox visual.
//   3. textKey.erase('warp') + put warpNone (limpia cualquier warp).
//   4. Update textClickPoint al top-left visual (Hrzn/Vrtc en pixeles).
//   5. Para PARAGRAPH text: resetea textShape[].transform tambien.
//   6. applyTextKeyToActiveLayer(textKey) — setd reemplaza todo el textKey.
//   7. Verifica bounds post-setd. Si drift > 50px, retorna false → fallback.
//
// Ventaja sobre recreate: NUNCA toca fontPostScriptName / Font index.
// La capa sigue siendo la misma — su font, color, fontset, todo persiste.
// Funciona incluso si la fuente no esta instalada (el name reference queda
// preservado en el textStyleRange para cuando alguien instale la fuente).
//
// Limitaciones:
//   - Solo para texto SIN rotacion (xy=yx=0). Rotado va por createRotatedTextLayer.
//   - Si drift post-setd > 50px, cae a recreate.
function normalizeTextLayerInPlace(layer, entry, log) {
    var targetLeft = Number(entry.left);
    var targetTop = Number(entry.top);

    selectLayer(layer);

    var desc;
    try {
        desc = getTargetLayerDescriptor();
    } catch (e) {
        log.writeln("    normalize: no se pudo leer descriptor: " + e);
        return false;
    }
    if (!desc.hasKey(sTID("textKey"))) {
        log.writeln("    normalize: capa sin textKey, skip");
        return false;
    }
    var textKey = desc.getObjectValue(sTID("textKey"));

    // Inspecciona el transform actual para decidir si esta corrupto o si tiene
    // rotacion/shear (que va por otro path).
    var xx = 1, yy = 1, xy = 0, yx = 0, txOrig = 0, tyOrig = 0;
    if (textKey.hasKey(sTID("transform"))) {
        var tr = textKey.getObjectValue(sTID("transform"));
        try { xx = tr.getDouble(sTID("xx")); } catch (e) {}
        try { yy = tr.getDouble(sTID("yy")); } catch (e) {}
        try { xy = tr.getDouble(sTID("xy")); } catch (e) {}
        try { yx = tr.getDouble(sTID("yx")); } catch (e) {}
        try { txOrig = tr.getDouble(sTID("tx")); } catch (e) {}
        try { tyOrig = tr.getDouble(sTID("ty")); } catch (e) {}
    }
    if (Math.abs(xy) > 0.001 || Math.abs(yx) > 0.001) {
        log.writeln("    normalize: rotacion/shear detectado (xy=" + xy +
            " yx=" + yx + "), skip -> recreate path");
        return false;
    }
    var bPre = layerBounds(layer);
    log.writeln("    normalize: bounds PRE=(" +
        Math.round(bPre.left) + "," + Math.round(bPre.top) + "," +
        Math.round(bPre.right) + "," + Math.round(bPre.bottom) +
        ") xx=" + xx.toFixed(3) + " yy=" + yy.toFixed(3) +
        " tx_inner=" + Math.round(txOrig) + " ty_inner=" + Math.round(tyOrig) +
        " target=(" + Math.round(targetLeft) + "," + Math.round(targetTop) + ")");

    // 1) Replace transform con identity en (0, 0) — patron EXACTO de Undeform.
    //    Intentar tx/ty=target en el INNER transform causa que Photoshop
    //    rechace con "resultado demasiado grande" porque inner transform.tx/ty
    //    no esta en coords de canvas. Identity en (0,0) siempre es valida —
    //    Photoshop posiciona el texto en textClickPoint (que actualizamos abajo).
    textKey.erase(sTID("transform"));
    var newTransform = new ActionDescriptor();
    newTransform.putDouble(sTID("xx"), 1.0);
    newTransform.putDouble(sTID("xy"), 0.0);
    newTransform.putDouble(sTID("yx"), 0.0);
    newTransform.putDouble(sTID("yy"), 1.0);
    newTransform.putDouble(sTID("tx"), 0.0);
    newTransform.putDouble(sTID("ty"), 0.0);
    textKey.putObject(cTID("Trnf"), cTID("Trnf"), newTransform);

    // 2) Reset warp to none (Undeform pattern — limpia cualquier deformacion).
    textKey.erase(sTID("warp"));
    var newWarp = new ActionDescriptor();
    newWarp.putEnumerated(sTID("warpStyle"), sTID("warpStyle"), sTID("warpNone"));
    newWarp.putDouble(sTID("warpValue"), 0);
    newWarp.putDouble(sTID("warpPerspective"), 0);
    newWarp.putDouble(sTID("warpPerspectiveOther"), 0);
    newWarp.putEnumerated(sTID("warpRotate"), sTID("Ornt"), sTID("Hrzn"));
    textKey.putObject(sTID("warp"), sTID("warp"), newWarp);

    // NOTA: textClickPoint NO se toca aqui. Setearlo con coords grandes
    // (target en pixels) hace fallar el setd con "resultado demasiado grande".
    // En el patron Undeform, textClickPoint queda intacto y el texto se
    // posiciona en esa coord post-setd. Si quedo en lugar incorrecto, se
    // ajusta con AM move despues.

    // 4) setd del textKey completo modificado.
    try {
        applyTextKeyToActiveLayer(textKey);
    } catch (eApply) {
        log.writeln("    normalize: setd fallo: " + eApply);
        return false;
    }

    // 5) Si la posicion no quedo exacta, ajustar via AM move repetidamente
    //    hasta llegar al target. Translate DOM se clampea (parece artboard
    //    o canvas limit), por eso iteramos con AM move en pasos chunked.
    var bAfter = layerBounds(layer);
    log.writeln("    normalize: bounds POST-setd=(" +
        Math.round(bAfter.left) + "," + Math.round(bAfter.top) + "," +
        Math.round(bAfter.right) + "," + Math.round(bAfter.bottom) + ")");

    for (var moveIter = 0; moveIter < 15; moveIter++) {
        var bCur = layerBounds(layer);
        var dxNow = targetLeft - bCur.left;
        var dyNow = targetTop - bCur.top;
        if (Math.abs(dxNow) <= 0.5 && Math.abs(dyNow) <= 0.5) break;
        // Limita el desplazamiento a 1000px por iteracion para evitar clamping
        // (las pruebas muestran que translate de >~6000px se trunca a ~400px).
        var stepX = (Math.abs(dxNow) > 1000) ? (dxNow > 0 ? 1000 : -1000) : dxNow;
        var stepY = (Math.abs(dyNow) > 1000) ? (dyNow > 0 ? 1000 : -1000) : dyNow;
        try {
            selectLayer(layer);
            moveActiveLayerBy(stepX, stepY);
            log.writeln("    normalize: AM move iter " + (moveIter + 1) +
                " step=(" + Math.round(stepX) + "," + Math.round(stepY) + ")");
        } catch (eAM) {
            log.writeln("    normalize: AM move fallo: " + eAM);
            break;
        }
    }

    var bFinal = layerBounds(layer);
    var dx = bFinal.left - targetLeft;
    var dy = bFinal.top - targetTop;
    log.writeln("    normalize: bounds FINAL=(" +
        Math.round(bFinal.left) + "," + Math.round(bFinal.top) + "," +
        Math.round(bFinal.right) + "," + Math.round(bFinal.bottom) +
        ") drift=(" + Math.round(dx) + "," + Math.round(dy) + ")");

    if (Math.abs(dx) > 50 || Math.abs(dy) > 50) {
        log.writeln("    normalize: drift fuera de tolerancia, abort -> recreate");
        return false;
    }

    return true;
}

function normalizeActiveTextTransform(targetLeft, targetTop, log) {
    var active = app.activeDocument.activeLayer;
    var textKey = getTextKeyDescriptor(active);
    var shapeKey = sTID("textShape");
    if (!textKey.hasKey(shapeKey)) {
        log.writeln("    WARNING: capa nueva sin textShape.");
        return;
    }

    var shapeList = textKey.getList(shapeKey);
    var updatedShapeList = new ActionList();
    for (var i = 0; i < shapeList.count; i++) {
        var shape = shapeList.getObjectValue(i);
        var transformKey = sTID("transform");
        if (shape.hasKey(transformKey)) {
            var transform = shape.getObjectValue(transformKey);
            var tx = transform.getUnitDoubleValue(sTID("tx"));
            var ty = transform.getUnitDoubleValue(sTID("ty"));
            transform.putUnitDouble(sTID("tx"), cTID("#Pxl"), tx + (targetLeft - tx));
            transform.putUnitDouble(sTID("ty"), cTID("#Pxl"), ty + (targetTop - ty));
            shape.putObject(transformKey, sTID("transform"), transform);
            log.writeln("    transform vivo: (" + tx + "," + ty + ") -> (" +
                targetLeft + "," + targetTop + ")");
        }
        updatedShapeList.putObject(sTID("textShape"), shape);
    }
    textKey.putList(shapeKey, updatedShapeList);

    var pointKey = sTID("textClickPoint");
    if (textKey.hasKey(pointKey)) {
        var point = textKey.getObjectValue(pointKey);
        point.putUnitDouble(cTID("Hrzn"), cTID("#Pxl"), targetLeft);
        point.putUnitDouble(cTID("Vrtc"), cTID("#Pxl"), targetTop);
        textKey.putObject(pointKey, cTID("Pnt "), point);
    }

    applyTextKeyToActiveLayer(textKey);
}

function duplicateLayerById(id) {
    selectLayerById(id);
    var idDplc = cTID("Dplc");
    var desc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    desc.putReference(cTID("null"), ref);
    executeAction(idDplc, desc, DialogModes.NO);
    return app.activeDocument.activeLayer;
}

function makeBlankTextLayer(parent, entry, source, log) {
    var doc = app.activeDocument;

    // PRIMERA ruta: AM action "Mk TxLr" en doc raiz.
    try {
        var desc = new ActionDescriptor();
        var ref = new ActionReference();
        ref.putClass(cTID("TxLr"));
        desc.putReference(cTID("null"), ref);

        var textDesc = new ActionDescriptor();
        var pointDesc = new ActionDescriptor();
        pointDesc.putUnitDouble(cTID("Hrzn"), cTID("#Pxl"), 0);
        pointDesc.putUnitDouble(cTID("Vrtc"), cTID("#Pxl"), 0);
        textDesc.putObject(cTID("TxtC"), cTID("Pnt "), pointDesc);
        textDesc.putString(cTID("Txt "), " ");

        desc.putObject(cTID("Usng"), cTID("TxLr"), textDesc);
        executeAction(cTID("Mk  "), desc, DialogModes.NO);
        return doc.activeLayer;
    } catch (e1) {
        log.writeln("    WARNING crear texto AM fallo: " + e1);
    }

    // Fallback A: duplicar TEMPLATE (capa sana del mismo parent). Hereda
    // transform LIMPIO y no toca parent.artLayers (evita bug TÍTULOS).
    if (entry.template_layer_id !== undefined && entry.template_layer_id !== null && entry.template_layer_id !== "") {
        try {
            var tdup = duplicateLayerById(entry.template_layer_id);
            log.writeln("    fallback: duplicando template id=" + entry.template_layer_id);
            return tdup;
        } catch (e2) {
            log.writeln("    WARNING duplicate template fallo: " + e2);
        }
    }

    // Fallback B: doc.artLayers.add() en raiz + asignar kind=TEXT. En algunas
    // versiones de PS esto falla con "La capa no puede contener texto".
    try {
        var domLayer = doc.artLayers.add();
        domLayer.kind = LayerKind.TEXT;
        domLayer.textItem.contents = " ";
        log.writeln("    fallback DOM doc.artLayers.add()");
        return domLayer;
    } catch (e3) {
        log.writeln("    WARNING crear texto DOM (raiz) fallo: " + e3);
    }

    // Fallback C: parent.artLayers.add() (riesgo de bug TÍTULOS).
    try {
        if (parent && parent.artLayers) {
            var dom2 = parent.artLayers.add();
            dom2.kind = LayerKind.TEXT;
            dom2.textItem.contents = " ";
            log.writeln("    fallback DOM parent.artLayers.add() (RIESGO TÍTULOS)");
            return dom2;
        }
    } catch (e4) {
        log.writeln("    WARNING crear texto DOM (parent) fallo: " + e4);
    }

    throw new Error("No se pudo crear una capa de texto nueva y no hay plantilla limpia.");
}

function resetTextTransform(log) {
    try {
        executeAction(cTID("rstT"), undefined, DialogModes.NO);
        log.writeln("    reset transform nativo aplicado.");
    } catch (e) {
        log.writeln("    WARNING reset transform fallo: " + e);
    }
}

function copyLayerPresentation(source, target) {
    try { target.opacity = source.opacity; } catch (e) {}
    try { target.blendMode = source.blendMode; } catch (e) {}
    try { target.visible = source.visible; } catch (e) {}
    try { target.grouped = source.grouped; } catch (e) {}
}

function copyTextItemBasics(sourceItem, targetItem, entry, log) {
    var style = entry.style || {};
    var matrix = entry.matrix || [1, 0, 0, 1, 0, 0];
    var mx = Math.abs(Number(matrix[0] || 1));
    var my = Math.abs(Number(matrix[3] || 1));
    var textScale = (entry.orientation === "vertical") ? 1.0 : Math.max(mx, my);
    if (!isFinite(textScale) || textScale <= 0) {
        textScale = 1.0;
    }
    try { targetItem.kind = sourceItem.kind; } catch (e) {}
    try { targetItem.contents = sourceItem.contents; } catch (e) {}
    // Fuente: priorizar el nombre PostScript leido desde engine_dict (bytes
    // crudos del PSD via psd_tools, en el manifest). El DOM textItem.font de
    // la capa original puede devolver el nombre stored (correcto) pero la
    // capa renderizar con un sustituto si la fuente no esta instalada — al
    // copiar via DOM la asignacion tambien se substituye. Logueamos el
    // resultado real para detectar fuentes faltantes en el sistema.
    try {
        var requested = style.font_name || (function(){ try { return sourceItem.font; } catch (e) { return ""; } })();
        if (requested) {
            targetItem.font = requested;
            var applied = "";
            try { applied = targetItem.font; } catch (e) {}
            if (applied !== requested) {
                log.writeln("    AVISO: fuente '" + requested +
                    "' NO INSTALADA -> Photoshop sustituyo por '" + applied + "'");
            }
        }
    } catch (e) {
        log.writeln("    WARNING aplicando fuente: " + e);
    }
    try {
        if (style.font_size !== undefined) targetItem.size = UnitValue(Number(style.font_size) * textScale, "pt");
        else targetItem.size = sourceItem.size;
    } catch (e) {}
    try {
        if (style.leading !== undefined) targetItem.leading = UnitValue(Number(style.leading) * textScale, "pt");
        else targetItem.leading = sourceItem.leading;
    } catch (e) {}
    try {
        if (style.leading !== undefined) {
            targetItem.useAutoLeading = false;
            targetItem.leading = UnitValue(Number(style.leading) * textScale, "pt");
        }
    } catch (e) {}
    try {
        if (style.tracking !== undefined) targetItem.tracking = Number(style.tracking);
        else targetItem.tracking = sourceItem.tracking;
    } catch (e) {}
    try { targetItem.color = sourceItem.color; } catch (e) {}
    try { targetItem.justification = sourceItem.justification; } catch (e) {}
    try { targetItem.antiAliasMethod = sourceItem.antiAliasMethod; } catch (e) {}
    try { targetItem.capitalization = sourceItem.capitalization; } catch (e) {}
    try { targetItem.direction = sourceItem.direction; } catch (e) {}
    try {
        if (entry.orientation === "vertical") {
            targetItem.direction = Direction.VERTICAL;
        }
    } catch (e) {}
    try { targetItem.horizontalScale = sourceItem.horizontalScale; } catch (e) {}
    try { targetItem.verticalScale = sourceItem.verticalScale; } catch (e) {}
    try { targetItem.baselineShift = sourceItem.baselineShift; } catch (e) {}
    try { targetItem.width = UnitValue(Number(entry.width), "px"); } catch (e) {}
    try { targetItem.height = UnitValue(Number(entry.height), "px"); } catch (e) {}
    try { targetItem.position = [Number(entry.left), Number(entry.top)]; } catch (e) {}
    log.writeln("    propiedades basicas de textItem copiadas.");
}

function tuneLeadingToTargetHeight(layer, entry, log) {
    var style = entry.style || {};
    if (style.leading === undefined || entry.bottom === undefined || entry.top === undefined) {
        return;
    }

    var targetHeight = Number(entry.bottom) - Number(entry.top);
    var leading = Number(style.leading);
    for (var i = 0; i < 8; i++) {
        var b = layerBounds(layer);
        var currentHeight = b.bottom - b.top;
        if (Math.abs(currentHeight - targetHeight) <= 0.5) {
            if (i > 0) {
                log.writeln("    leading ajustado a " + leading + " para igualar alto visual.");
            }
            return;
        }
        if (currentHeight > targetHeight) {
            leading -= 0.5;
        } else {
            leading += 0.5;
        }
        try {
            layer.textItem.useAutoLeading = false;
            layer.textItem.leading = UnitValue(leading, "pt");
        } catch (e) {
            log.writeln("    WARNING ajuste de leading fallo: " + e);
            return;
        }
    }
}

function scaleLayerToTargetBounds(layer, entry, log) {
    if (entry.right === undefined || entry.bottom === undefined) {
        return;
    }
    var targetWidth = Number(entry.right) - Number(entry.left);
    var targetHeight = Number(entry.bottom) - Number(entry.top);
    if (targetWidth <= 0 || targetHeight <= 0) {
        return;
    }

    for (var i = 0; i < 6; i++) {
        var b = layerBounds(layer);
        var currentWidth = b.right - b.left;
        var currentHeight = b.bottom - b.top;
        if (currentWidth <= 0 || currentHeight <= 0) {
            return;
        }

        var scaleX = 100.0 * targetWidth / currentWidth;
        var scaleY = 100.0 * targetHeight / currentHeight;
        if (Math.abs(scaleX - 100.0) <= 0.5 && Math.abs(scaleY - 100.0) <= 0.5) {
            return;
        }

        try {
            layer.resize(scaleX, scaleY, AnchorPosition.TOPLEFT);
            log.writeln("    escala visual aplicada (iter " + (i+1) + "): " +
                Math.round(scaleX * 100) / 100 + "% x " +
                Math.round(scaleY * 100) / 100 + "%.");
        } catch (e) {
            log.writeln("    WARNING escala visual fallo: " + e);
            return;
        }
    }
}

// Para texto horizontal de una linea: primero escala uniforme para hacer
// match de altura (preserva metricas del glifo), despues escala SOLO
// horizontal hasta que el ancho coincida (acomoda la HorizontalScale del
// style original que se pierde al recrear la capa).
function scaleLayerUniformToHeight(layer, entry, log) {
    if (entry.bottom === undefined || entry.top === undefined) return;
    var targetHeight = Number(entry.bottom) - Number(entry.top);
    if (targetHeight <= 0) return;

    for (var i = 0; i < 6; i++) {
        var b = layerBounds(layer);
        var currentHeight = b.bottom - b.top;
        if (currentHeight <= 0) return;
        var ratio = targetHeight / currentHeight;
        if (Math.abs(ratio - 1.0) <= 0.005) break;
        var scale = 100.0 * ratio;
        try {
            layer.resize(scale, scale, AnchorPosition.TOPLEFT);
            log.writeln("    escala uniforme (iter " + (i+1) + "): " +
                (Math.round(scale * 100) / 100) + "%, ratio=" +
                ratio.toFixed(4));
        } catch (e) {
            log.writeln("    WARNING escala uniforme fallo: " + e);
            return;
        }
    }

    if (entry.right === undefined || entry.left === undefined) return;
    var targetWidth = Number(entry.right) - Number(entry.left);
    if (targetWidth <= 0) return;

    for (var j = 0; j < 6; j++) {
        var b2 = layerBounds(layer);
        var currentWidth = b2.right - b2.left;
        if (currentWidth <= 0) return;
        var wratio = targetWidth / currentWidth;
        if (Math.abs(wratio - 1.0) <= 0.005) return;
        try {
            layer.resize(100.0 * wratio, 100.0, AnchorPosition.TOPLEFT);
            log.writeln("    escala horizontal (iter " + (j+1) + "): " +
                (Math.round(wratio * 10000) / 100) + "%, ratio=" +
                wratio.toFixed(4));
        } catch (e) {
            log.writeln("    WARNING escala horizontal fallo: " + e);
            return;
        }
    }
}

function moveActiveLayerBy(dx, dy) {
    var desc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    desc.putReference(cTID("null"), ref);
    var offset = new ActionDescriptor();
    offset.putUnitDouble(cTID("Hrzn"), cTID("#Pxl"), dx);
    offset.putUnitDouble(cTID("Vrtc"), cTID("#Pxl"), dy);
    desc.putObject(cTID("Ofst"), cTID("Ofst"), offset);
    executeAction(cTID("move"), desc, DialogModes.NO);
}

function moveLayerToTarget(layer, targetLeft, targetTop, log) {
    var b = layerBounds(layer);
    var dx = targetLeft - b.left;
    var dy = targetTop - b.top;
    if (Math.abs(dx) <= 0.5 && Math.abs(dy) <= 0.5) {
        return layerBounds(layer);
    }

    selectLayer(layer);
    var moved = false;
    try {
        layer.translate(dx, dy);
        moved = true;
    } catch (e) {
        log.writeln("    WARNING translate DOM fallo: " + e);
    }

    if (!moved) {
        try {
            moveActiveLayerBy(dx, dy);
            log.writeln("    move via AM aplicado: dx=" + dx + " dy=" + dy);
            moved = true;
        } catch (e2) {
            log.writeln("    WARNING move AM fallo: " + e2);
        }
    }

    if (!moved) {
        try {
            // Ultimo recurso: textItem.position ajusta el clickPoint.
            // No es exacto en bounds porque el clickPoint suele estar en
            // el baseline (no en bounds.top), pero al menos arrima.
            layer.textItem.position = [targetLeft, targetTop];
            log.writeln("    fallback textItem.position aplicado.");
        } catch (posErr) {
            log.writeln("    ERROR textItem.position fallo: " + posErr);
        }
    }

    return layerBounds(layer);
}

// Copy minimo para texto rotado: fuerza POINTTEXT, no setea width/height/
// position (esas las maneja el flujo de rotacion+escala+move posterior).
//
// size/leading se copian DIRECTAMENTE del sourceItem (no multiplicamos por
// matrix scale). Photoshop ya reporta el tamano efectivo en pt que ve el
// usuario en el panel Character — usar style.font_size * matrix_scale daria
// un tamano ~3% mayor al original porque la escala efectiva en pantalla no
// es exactamente la componente xx/yy del transform crudo del TyShO.
function copyRotatedTextItemBasics(sourceItem, targetItem, entry, metrics, log) {
    var style = entry.style || {};
    metrics = metrics || {};

    try { targetItem.kind = TextType.POINTTEXT; } catch (e) {
        log.writeln("    WARNING forzar POINTTEXT fallo: " + e);
    }
    try { targetItem.font = sourceItem.font; } catch (e) {}
    try { targetItem.contents = sourceItem.contents; } catch (e) {}

    // size efectivo (visual) leido del descriptor del textKey original.
    // Fallback al sourceItem.size (nominal) si no se pudo leer.
    var appliedSize = null;
    try {
        if (metrics.size !== null && metrics.size !== undefined &&
                isFinite(metrics.size) && metrics.size > 0) {
            targetItem.size = UnitValue(Number(metrics.size), "pt");
            appliedSize = Number(metrics.size);
        } else {
            targetItem.size = sourceItem.size;
            appliedSize = px(sourceItem.size);
        }
    } catch (e) {
        if (style.font_size !== undefined) {
            try { targetItem.size = UnitValue(Number(style.font_size), "pt"); } catch (e2) {}
        }
    }

    var appliedLeading = null;
    try {
        var hasExplicitLeading = (metrics.leading !== null && metrics.leading !== undefined &&
                                  isFinite(metrics.leading) && metrics.leading > 0);
        var autoLead = (metrics.autoLeading === true);
        if (hasExplicitLeading && !autoLead) {
            targetItem.useAutoLeading = false;
            targetItem.leading = UnitValue(Number(metrics.leading), "pt");
            appliedLeading = Number(metrics.leading);
        } else if (autoLead) {
            targetItem.useAutoLeading = true;
        } else {
            // Sin info del descriptor: copiar del DOM.
            targetItem.useAutoLeading = sourceItem.useAutoLeading;
            if (!sourceItem.useAutoLeading) {
                targetItem.leading = sourceItem.leading;
                appliedLeading = px(sourceItem.leading);
            }
        }
    } catch (e) {
        if (style.leading !== undefined) {
            try {
                targetItem.useAutoLeading = false;
                targetItem.leading = UnitValue(Number(style.leading), "pt");
            } catch (e2) {}
        }
    }

    try {
        if (metrics.tracking !== null && metrics.tracking !== undefined) {
            targetItem.tracking = Number(metrics.tracking);
        } else {
            targetItem.tracking = sourceItem.tracking;
        }
    } catch (e) {}
    try { targetItem.color = sourceItem.color; } catch (e) {}
    try { targetItem.justification = sourceItem.justification; } catch (e) {}
    try { targetItem.antiAliasMethod = sourceItem.antiAliasMethod; } catch (e) {}
    try { targetItem.capitalization = sourceItem.capitalization; } catch (e) {}
    try {
        if (metrics.horizontalScale !== null && metrics.horizontalScale !== undefined) {
            targetItem.horizontalScale = Number(metrics.horizontalScale);
        } else {
            targetItem.horizontalScale = sourceItem.horizontalScale;
        }
    } catch (e) {}
    try {
        if (metrics.verticalScale !== null && metrics.verticalScale !== undefined) {
            targetItem.verticalScale = Number(metrics.verticalScale);
        } else {
            targetItem.verticalScale = sourceItem.verticalScale;
        }
    } catch (e) {}
    try {
        if (metrics.baselineShift !== null && metrics.baselineShift !== undefined) {
            targetItem.baselineShift = UnitValue(Number(metrics.baselineShift), "pt");
        } else {
            targetItem.baselineShift = sourceItem.baselineShift;
        }
    } catch (e) {}
    log.writeln("    propiedades rotadas de textItem copiadas (size=" +
        (appliedSize !== null ? appliedSize.toFixed(2) : "?") +
        "pt, leading=" +
        (appliedLeading !== null ? appliedLeading.toFixed(2) : "auto") + ").");
}

// Lee size, leading y tracking EFECTIVOS de la primera run de estilo, tal
// como Photoshop los muestra en el panel Character (post-escala visual).
// sourceItem.size devuelve el size NOMINAL del style sheet (9.2pt en una
// capa rotada/escalada con matriz 3.84x), no el efectivo (34.41pt) — por
// eso vamos a leerlo via descriptor.
function readEffectiveTextMetrics(source, log) {
    var result = {
        size: null, leading: null, autoLeading: null, tracking: null,
        horizontalScale: null, verticalScale: null, baselineShift: null
    };
    try {
        selectLayer(source);
        var desc = getTargetLayerDescriptor();
        if (!desc.hasKey(sTID("textKey"))) return result;
        var textKey = desc.getObjectValue(sTID("textKey"));
        if (!textKey.hasKey(sTID("textStyleRange"))) return result;
        var rangeList = textKey.getList(sTID("textStyleRange"));
        if (rangeList.count === 0) return result;
        var range = rangeList.getObjectValue(0);
        if (!range.hasKey(sTID("textStyle"))) return result;
        var ts = range.getObjectValue(sTID("textStyle"));
        // impliedFontSize / impliedLeading son los valores POST-transform que
        // Photoshop muestra en el panel Character. "size" / "leading" son el
        // valor NOMINAL del style sheet, pre-transform — preferimos implied.
        try {
            if (ts.hasKey(sTID("impliedFontSize"))) {
                result.size = ts.getUnitDoubleValue(sTID("impliedFontSize"));
            } else if (ts.hasKey(sTID("size"))) {
                result.size = ts.getUnitDoubleValue(sTID("size"));
            }
        } catch (e) {}
        try {
            if (ts.hasKey(sTID("autoLeading"))) {
                result.autoLeading = ts.getBoolean(sTID("autoLeading"));
            }
        } catch (e) {}
        try {
            if (ts.hasKey(sTID("impliedLeading"))) {
                result.leading = ts.getUnitDoubleValue(sTID("impliedLeading"));
            } else if (ts.hasKey(sTID("leading"))) {
                result.leading = ts.getUnitDoubleValue(sTID("leading"));
            }
        } catch (e) {}
        try {
            if (ts.hasKey(sTID("tracking"))) {
                result.tracking = ts.getInteger(sTID("tracking"));
            }
        } catch (e) {}
        try {
            if (ts.hasKey(sTID("horizontalScale"))) {
                result.horizontalScale = ts.getDouble(sTID("horizontalScale"));
            }
        } catch (e) {}
        try {
            if (ts.hasKey(sTID("verticalScale"))) {
                result.verticalScale = ts.getDouble(sTID("verticalScale"));
            }
        } catch (e) {}
        try {
            if (ts.hasKey(sTID("impliedBaselineShift"))) {
                result.baselineShift = ts.getUnitDoubleValue(sTID("impliedBaselineShift"));
            } else if (ts.hasKey(sTID("baselineShift"))) {
                result.baselineShift = ts.getUnitDoubleValue(sTID("baselineShift"));
            }
        } catch (e) {}
    } catch (e) {
        log.writeln("    WARNING leyendo metrics efectivas: " + e);
    }
    log.writeln("    metrics efectivas: size=" +
        (result.size !== null ? result.size.toFixed(3) : "?") +
        "pt, leading=" +
        (result.leading !== null ? result.leading.toFixed(3) : "?") +
        "pt, hScale=" +
        (result.horizontalScale !== null ? result.horizontalScale.toFixed(2) + "%" : "?") +
        ", vScale=" +
        (result.verticalScale !== null ? result.verticalScale.toFixed(2) + "%" : "?") +
        ", autoLeading=" + result.autoLeading);
    return result;
}

// Lee el angulo de rotacion (en grados) de un text layer leyendo la matriz
// del descriptor en vivo. La rotacion no aparece en el TyShO transform que
// lee psd_tools, pero Photoshop si la conserva en textKey/textShape.
function getLayerRotationDegrees(source, log) {
    try {
        selectLayer(source);
        var desc = getTargetLayerDescriptor();
        if (!desc.hasKey(sTID("textKey"))) return 0;
        var textKey = desc.getObjectValue(sTID("textKey"));

        function readAngle(transform, label) {
            try {
                var xx = transform.getDouble(sTID("xx"));
                var xy = transform.getDouble(sTID("xy"));
                if (Math.abs(xy) < 1e-6 && Math.abs(xx - 1) < 1e-6) {
                    return null;
                }
                var deg = Math.atan2(xy, xx) * 180 / Math.PI;
                log.writeln("    rotation " + label + ": xx=" + xx +
                    " xy=" + xy + " -> " + deg.toFixed(2) + " deg");
                return deg;
            } catch (e) {
                return null;
            }
        }

        if (textKey.hasKey(sTID("textShape"))) {
            var shapeList = textKey.getList(sTID("textShape"));
            if (shapeList.count > 0) {
                var shape = shapeList.getObjectValue(0);
                if (shape.hasKey(sTID("transform"))) {
                    var ang = readAngle(shape.getObjectValue(sTID("transform")),
                                        "textShape[0]");
                    if (ang !== null) return ang;
                }
            }
        }
        if (textKey.hasKey(sTID("transform"))) {
            var ang2 = readAngle(textKey.getObjectValue(sTID("transform")),
                                 "textKey");
            if (ang2 !== null) return ang2;
        }
    } catch (e) {
        log.writeln("    rotation read error: " + e);
    }
    return 0;
}

// Lee el textStyle COMPLETO (descriptor entero) de la primera run de estilo
// del texto original. Devuelve null si no se pudo leer.
function readSourceTextStyleDescriptor(source) {
    try {
        selectLayer(source);
        var d = getTargetLayerDescriptor();
        if (!d.hasKey(sTID("textKey"))) return null;
        var tk = d.getObjectValue(sTID("textKey"));
        if (!tk.hasKey(sTID("textStyleRange"))) return null;
        var rl = tk.getList(sTID("textStyleRange"));
        if (rl.count === 0) return null;
        var range = rl.getObjectValue(0);
        if (!range.hasKey(sTID("textStyle"))) return null;
        return range.getObjectValue(sTID("textStyle"));
    } catch (e) {
        return null;
    }
}

// Lee el paragraphStyle COMPLETO de la primera run del texto original.
function readSourceParagraphStyleDescriptor(source) {
    try {
        selectLayer(source);
        var d = getTargetLayerDescriptor();
        if (!d.hasKey(sTID("textKey"))) return null;
        var tk = d.getObjectValue(sTID("textKey"));
        if (!tk.hasKey(sTID("paragraphStyleRange"))) return null;
        var rl = tk.getList(sTID("paragraphStyleRange"));
        if (rl.count === 0) return null;
        var range = rl.getObjectValue(0);
        if (!range.hasKey(sTID("paragraphStyle"))) return null;
        return range.getObjectValue(sTID("paragraphStyle"));
    } catch (e) {
        return null;
    }
}

// Aplica un textStyle (descriptor completo) a TODO el rango de texto de la
// capa de texto activa. Esto se hace con executeAction("setd") en la capa,
// pasandole un nuevo textKey con un textStyleRange que cubre todo el texto
// y referencia el textStyle clonado del original.
function applyTextStyleToActiveLayer(textStyle, paragraphStyle, contents, log) {
    try {
        var textKey = new ActionDescriptor();
        textKey.putString(cTID("Txt "), contents);

        var range = new ActionDescriptor();
        range.putInteger(sTID("from"), 0);
        range.putInteger(sTID("to"), contents.length);
        range.putObject(sTID("textStyle"), sTID("textStyle"), textStyle);

        var rangeList = new ActionList();
        rangeList.putObject(sTID("textStyleRange"), range);
        textKey.putList(sTID("textStyleRange"), rangeList);

        if (paragraphStyle) {
            var prange = new ActionDescriptor();
            prange.putInteger(sTID("from"), 0);
            prange.putInteger(sTID("to"), contents.length);
            prange.putObject(sTID("paragraphStyle"), sTID("paragraphStyle"), paragraphStyle);
            var prangeList = new ActionList();
            prangeList.putObject(sTID("paragraphStyleRange"), prange);
            textKey.putList(sTID("paragraphStyleRange"), prangeList);
        }

        applyTextKeyToActiveLayer(textKey);
        log.writeln("    textStyle completo aplicado al rango entero.");
    } catch (e) {
        log.writeln("    WARNING aplicando textStyle: " + e);
    }
}

function createRotatedTextLayer(source, entry, log) {
    var doc = app.activeDocument;
    var originalName = source.name;
    var targetLeft = Number(entry.left);
    var targetTop = Number(entry.top);
    var targetRight = Number(entry.right);
    var targetBottom = Number(entry.bottom);
    var targetWidth = targetRight - targetLeft;
    var targetHeight = targetBottom - targetTop;
    var centerX = (targetLeft + targetRight) / 2;
    var centerY = (targetTop + targetBottom) / 2;

    // 1. Leer info del original ANTES de borrarlo:
    //    - angulo de rotacion (vive en textShape.transform)
    //    - textStyle COMPLETO (descriptor con TODAS las propiedades, no solo
    //      las que expone el DOM textItem)
    //    - paragraphStyle completo
    //    - contents
    var angle = getLayerRotationDegrees(source, log);
    if (Math.abs(angle) < 0.5) {
        angle = -90;
        log.writeln("    rotation fallback: -90 deg (no detectada en textKey)");
    } else {
        log.writeln("    rotation detectada: " + angle.toFixed(2) + " deg");
    }
    var sourceContents = "";
    try { sourceContents = source.textItem.contents; } catch (e) {}
    var sourceTextStyle = readSourceTextStyleDescriptor(source);
    var sourceParaStyle = readSourceParagraphStyleDescriptor(source);
    log.writeln("    textStyle leido: " + (sourceTextStyle ? "OK" : "NULL"));
    log.writeln("    paragraphStyle leido: " + (sourceParaStyle ? "OK" : "NULL"));

    // 2. Crear capa de texto nueva (transform interno LIMPIO).
    log.writeln("    creando capa de texto nueva...");
    var newLayer = makeBlankTextLayer(source.parent, entry, source, log);
    newLayer = doc.activeLayer;
    newLayer.name = originalName + "__rebuild";

    // 3. Forzar POINT TEXT y aplicar el textStyle COMPLETO del original. Esto
    // copia EXACTAMENTE font, size, leading, hScale, vScale, tracking,
    // autoKern, ligature, baselineShift, color, fontCaps, miterLimit, etc.
    try { newLayer.textItem.kind = TextType.POINTTEXT; } catch (e) {}
    if (sourceTextStyle && sourceContents.length > 0) {
        applyTextStyleToActiveLayer(sourceTextStyle, sourceParaStyle, sourceContents, log);
    } else {
        // Fallback minimo si no se pudo leer el descriptor.
        try { newLayer.textItem.font = source.textItem.font; } catch (e) {}
        try { newLayer.textItem.size = source.textItem.size; } catch (e) {}
        try { newLayer.textItem.contents = sourceContents || " "; } catch (e) {}
        log.writeln("    fallback DOM copy aplicado.");
    }
    // Re-forzar fuente desde manifest: el descriptor del original puede traer
    // una fuente sustituta cuando Photoshop la cambia al abrir la capa rota.
    try {
        if ((entry.style || {}).font_name) {
            newLayer.textItem.font = entry.style.font_name;
            log.writeln("    fuente forzada desde manifest: " + entry.style.font_name);
        }
    } catch (e) {
        log.writeln("    WARNING aplicando fuente del manifest: " + e);
    }

    // 4. Centrar y rotar.
    var b0 = layerBounds(newLayer);
    var dx0 = centerX - (b0.left + b0.right) / 2;
    var dy0 = centerY - (b0.top + b0.bottom) / 2;
    if (Math.abs(dx0) > 0.5 || Math.abs(dy0) > 0.5) {
        try { newLayer.translate(dx0, dy0); } catch (e) {
            log.writeln("    WARNING translate pre-rotate: " + e);
        }
    }
    try {
        newLayer.rotate(angle, AnchorPosition.MIDDLECENTER);
        log.writeln("    rotacion aplicada: " + angle.toFixed(2) + " deg");
    } catch (e) {
        log.writeln("    WARNING rotate fallo: " + e);
    }

    // 5. Reporte de drift. Si pasamos el textStyle entero y la fuente es la
    // misma, los bounds post-rotacion deberian coincidir con target dentro
    // de 1-2 px (subpixel rounding del rasterizador).
    var bPre = layerBounds(newLayer);
    var driftW = (bPre.right - bPre.left) - targetWidth;
    var driftH = (bPre.bottom - bPre.top) - targetHeight;
    var relW = (targetWidth > 0) ? Math.abs(driftW / targetWidth) : 0;
    var relH = (targetHeight > 0) ? Math.abs(driftH / targetHeight) : 0;
    log.writeln("    drift bbox post-rotate: dW=" + driftW.toFixed(1) +
        " dH=" + driftH.toFixed(1) +
        " (" + (relW * 100).toFixed(2) + "% x " + (relH * 100).toFixed(2) + "%)");

    // 6. Pre-posicionar al top-left antes de escalar (resize con TOPLEFT
    // anchor preserva la posicion del top-left).
    moveLayerToTarget(newLayer, targetLeft, targetTop, log);

    // 7. Si el bbox no coincide al pixel con el target, aplicar un resize
    // correctivo fino. Llamamos resize() directamente (no usamos
    // scaleLayerToTargetBounds que ignora ajustes < 0.5%) porque queremos
    // que incluso drifts subpixel queden corregidos. Para drifts de 1-2 px
    // el escalado es < 4% en el eje chico y < 1% en el grande, imperceptible
    // en panel Character.
    var bMeasure = layerBounds(newLayer);
    var curW = bMeasure.right - bMeasure.left;
    var curH = bMeasure.bottom - bMeasure.top;
    if (curW > 0 && curH > 0 &&
            (Math.abs(curW - targetWidth) >= 0.5 || Math.abs(curH - targetHeight) >= 0.5)) {
        var sX = 100.0 * targetWidth / curW;
        var sY = 100.0 * targetHeight / curH;
        try {
            newLayer.resize(sX, sY, AnchorPosition.TOPLEFT);
            log.writeln("    resize correctivo: " + sX.toFixed(3) + "% x " +
                sY.toFixed(3) + "%");
        } catch (e) {
            log.writeln("    WARNING resize correctivo fallo: " + e);
        }
    }

    // 8. Re-posicionar exacto al top-left del target (resize puede dejar
    // micro-drift).
    var b1 = moveLayerToTarget(newLayer, targetLeft, targetTop, log);
    var dx1 = targetLeft - b1.left;
    var dy1 = targetTop - b1.top;
    if (Math.abs(dx1) > 0.5 || Math.abs(dy1) > 0.5) {
        b1 = moveLayerToTarget(newLayer, targetLeft, targetTop, log);
    }

    log.writeln("    copiando presentacion...");
    copyLayerPresentation(source, newLayer);

    log.writeln("    moviendo junto a la capa original y eliminando original...");
    newLayer.move(source, ElementPlacement.PLACEBEFORE);
    newLayer.name = originalName;
    source.remove();

    log.writeln("    nuevo bounds=(" +
        Math.round(b1.left) + "," + Math.round(b1.top) + "," +
        Math.round(b1.right) + "," + Math.round(b1.bottom) + ")");
}

function createCleanTextLayer(source, entry, log) {
    var doc = app.activeDocument;
    var originalName = source.name;
    var targetLeft = Number(entry.left);
    var targetTop = Number(entry.top);
    var targetRight = (entry.right !== undefined) ? Number(entry.right) :
                      (targetLeft + Number(entry.width || 0));
    var targetBottom = (entry.bottom !== undefined) ? Number(entry.bottom) :
                       (targetTop + Number(entry.height || 0));
    var targetWidth = targetRight - targetLeft;
    var targetHeight = targetBottom - targetTop;

    try {
        log.writeln("    parent=" + source.parent.typename + " / " + source.parent.name);
    } catch (pe) {}

    // Leer metricas EFECTIVAS del descriptor original (lo que Photoshop
    // muestra en panel Character). NO calcular size como font_size *
    // matrix_scale: el transform del TyShO puede estar "corrupto" (escala
    // 3.77) pero la escala VISUAL real del texto suele ser muy distinta
    // (ej. 1.8) porque Photoshop la compensa internamente. Leer
    // impliedFontSize evita calcular mal el size de la capa nueva y
    // produce resize correctivo gigante (45%) que distorsiona.
    var sourceTextStyleDesc = readSourceTextStyleDescriptor(source);
    var explicitSize = null;
    var explicitLeading = null;
    var explicitAutoLeading = null;
    var explicitHScale = null;
    var explicitVScale = null;
    if (sourceTextStyleDesc) {
        try {
            if (sourceTextStyleDesc.hasKey(sTID("impliedFontSize"))) {
                explicitSize = sourceTextStyleDesc.getUnitDoubleValue(sTID("impliedFontSize"));
            } else if (sourceTextStyleDesc.hasKey(sTID("size"))) {
                explicitSize = sourceTextStyleDesc.getUnitDoubleValue(sTID("size"));
            }
        } catch (e) {}
        try {
            if (sourceTextStyleDesc.hasKey(sTID("autoLeading"))) {
                explicitAutoLeading = sourceTextStyleDesc.getBoolean(sTID("autoLeading"));
            }
        } catch (e) {}
        try {
            if (sourceTextStyleDesc.hasKey(sTID("impliedLeading"))) {
                explicitLeading = sourceTextStyleDesc.getUnitDoubleValue(sTID("impliedLeading"));
            } else if (sourceTextStyleDesc.hasKey(sTID("leading"))) {
                explicitLeading = sourceTextStyleDesc.getUnitDoubleValue(sTID("leading"));
            }
        } catch (e) {}
        try {
            if (sourceTextStyleDesc.hasKey(sTID("horizontalScale"))) {
                explicitHScale = sourceTextStyleDesc.getDouble(sTID("horizontalScale"));
            }
        } catch (e) {}
        try {
            if (sourceTextStyleDesc.hasKey(sTID("verticalScale"))) {
                explicitVScale = sourceTextStyleDesc.getDouble(sTID("verticalScale"));
            }
        } catch (e) {}
    }
    log.writeln("    metrics descriptor: size=" +
        (explicitSize !== null ? explicitSize.toFixed(3) + "pt" : "?") +
        " leading=" + (explicitLeading !== null ? explicitLeading.toFixed(3) + "pt" : "auto") +
        " hScale=" + (explicitHScale !== null ? explicitHScale.toFixed(2) + "%" : "?") +
        " autoLeading=" + explicitAutoLeading);

    // Leer paragraphStyle y contents del original ANTES de crear la capa
    // nueva. Junto con sourceTextStyleDesc, esto permite aplicar el style
    // COMPLETO via Action Manager (font, color, fontCaps, baseline, ligature,
    // tracking, etc.). DOM textItem.font NO es confiable en capas con
    // herencia corrupta — devuelve la fuente default de Photoshop (Myriad
    // Pro) y el try/catch de copyTextItemBasics lo traga silenciosamente,
    // perdiendo la fuente original.
    var sourceParaStyleDesc = readSourceParagraphStyleDescriptor(source);
    var sourceContents = "";
    try { sourceContents = source.textItem.contents; } catch (e) {}
    log.writeln("    textStyle leido: " + (sourceTextStyleDesc ? "OK" : "NULL"));
    log.writeln("    paragraphStyle leido: " + (sourceParaStyleDesc ? "OK" : "NULL"));

    log.writeln("    creando capa de texto nueva...");
    var newLayer = makeBlankTextLayer(source.parent, entry, source, log);
    newLayer = doc.activeLayer;
    newLayer.name = originalName + "__rebuild";

    // 1) copyTextItemBasics setea kind, bounds, justification, etc. Si la
    //    fuente se logra copiar via DOM, perfecto; si no, el paso 2 la repara.
    copyTextItemBasics(source.textItem, newLayer.textItem, entry, log);

    // 2) Aplicar el textStyle COMPLETO del descriptor del original via Action
    //    Manager. Esto sobrescribe la fuente con el valor REAL del original
    //    (fontPostScriptName del descriptor), ignorando lo que el DOM haya
    //    devuelto. Tambien preserva color, fontCaps, ligature, baselineShift,
    //    syntheticBold, etc. — propiedades que el DOM no expone todas.
    if (sourceTextStyleDesc && sourceContents.length > 0) {
        applyTextStyleToActiveLayer(sourceTextStyleDesc, sourceParaStyleDesc, sourceContents, log);
        // Re-establecer width/height/position post-setd: aplicar textStyle via
        // "setd" puede resetear el textShape (bounding box). Para POINTTEXT
        // width/height son read-only; para PARAGRAPH se reaplican.
        try { newLayer.textItem.width = UnitValue(Number(entry.width), "px"); } catch (e) {}
        try { newLayer.textItem.height = UnitValue(Number(entry.height), "px"); } catch (e) {}
        try { newLayer.textItem.position = [Number(entry.left), Number(entry.top)]; } catch (e) {}
        // Re-forzar fuente desde el manifest. El nombre del manifest viene de
        // los bytes crudos del PSD (engine_dict.FontSet) — la unica fuente
        // confiable. Photoshop verifica al setear: si la fuente NO esta
        // instalada, sustituye silenciosamente por la default (Myriad Pro).
        // En ese caso textItem.font tras el set devuelve el nombre sustituto
        // y queda evidencia en el log para que el operador sepa que tiene
        // que instalar la fuente.
        try {
            if ((entry.style || {}).font_name) {
                newLayer.textItem.font = entry.style.font_name;
                var applied = "";
                try { applied = newLayer.textItem.font; } catch (e) {}
                if (applied === entry.style.font_name) {
                    log.writeln("    fuente re-forzada: " + entry.style.font_name + " OK");
                } else {
                    log.writeln("    AVISO: fuente '" + entry.style.font_name +
                        "' NO INSTALADA -> Photoshop sustituyo por '" + applied + "'");
                }
            }
        } catch (e) {
            log.writeln("    WARNING re-aplicando fuente: " + e);
        }
    }

    // Sobrescribir size/leading/hScale/vScale con valores EFECTIVOS del
    // descriptor (los que Photoshop muestra). Asi el texto queda con las
    // metricas exactas del original, sin depender de heuristicas con la
    // matrix del TyShO que puede estar corrupta.
    try {
        if (explicitSize !== null && isFinite(explicitSize) && explicitSize > 0) {
            newLayer.textItem.size = UnitValue(explicitSize, "pt");
            log.writeln("    size forzado a " + explicitSize.toFixed(3) + "pt.");
        }
    } catch (e) {
        log.writeln("    WARNING aplicando size: " + e);
    }
    try {
        if (explicitAutoLeading === true) {
            newLayer.textItem.useAutoLeading = true;
        } else if (explicitLeading !== null && isFinite(explicitLeading) && explicitLeading > 0) {
            newLayer.textItem.useAutoLeading = false;
            newLayer.textItem.leading = UnitValue(explicitLeading, "pt");
            log.writeln("    leading forzado a " + explicitLeading.toFixed(3) + "pt.");
        }
    } catch (e) {
        log.writeln("    WARNING aplicando leading: " + e);
    }
    try {
        if (explicitHScale !== null && isFinite(explicitHScale) && explicitHScale > 0) {
            newLayer.textItem.horizontalScale = explicitHScale;
        }
    } catch (e) {}
    try {
        if (explicitVScale !== null && isFinite(explicitVScale) && explicitVScale > 0) {
            newLayer.textItem.verticalScale = explicitVScale;
        }
    } catch (e) {}

    // Mover ANTES de escalar: para texto chico que sera muy pequeno post-escala,
    // translate() falla con "Transformar no disponible". Posicionando primero
    // (mientras la capa aun esta grande) evitamos ese error; luego el resize
    // con anchor TOPLEFT preserva la posicion.
    log.writeln("    posicionamiento previo a escala...");
    moveLayerToTarget(newLayer, targetLeft, targetTop, log);

    // Resize correctivo fino al bbox exacto. Con el textStyle completo aplicado
    // el drift es subpixel; resize() corrige sin alterar leading/size internos
    // (solo redimensiona visualmente).
    // Resize correctivo: SOLO si el drift relativo en algun eje es > 1%
    // del target. Sin esto, drifts de 4-6% (que afectan el impliedFontSize
    // visible en panel Character) se aplican y distorsionan el tamano del
    // texto. Para drifts < 1% el ojo no nota la diferencia en bounds, pero
    // SI nota un texto que cambio de 75pt a 80pt.
    //
    // Tambien tope absoluto de 1.5 px: drifts subpixel no requieren resize.
    var bMeasure = layerBounds(newLayer);
    var curW = bMeasure.right - bMeasure.left;
    var curH = bMeasure.bottom - bMeasure.top;
    if (curW > 0 && curH > 0 && targetWidth > 0 && targetHeight > 0) {
        var driftX = Math.abs(curW - targetWidth);
        var driftY = Math.abs(curH - targetHeight);
        var relX = driftX / targetWidth;
        var relY = driftY / targetHeight;
        // Aplicar resize en un eje SOLO si: drift >= 1.5 px Y drift >= 1% del lado.
        var needX = (driftX >= 1.5) && (relX >= 0.01);
        var needY = (driftY >= 1.5) && (relY >= 0.01);
        if (needX || needY) {
            var sX = needX ? (100.0 * targetWidth / curW) : 100.0;
            var sY = needY ? (100.0 * targetHeight / curH) : 100.0;
            try {
                newLayer.resize(sX, sY, AnchorPosition.TOPLEFT);
                log.writeln("    resize correctivo: " + sX.toFixed(3) + "% x " +
                    sY.toFixed(3) + "% (drift " + driftX.toFixed(1) + "px / " +
                    driftY.toFixed(1) + "px, " + (relX * 100).toFixed(2) + "% x " +
                    (relY * 100).toFixed(2) + "%)");
            } catch (e) {
                log.writeln("    WARNING resize correctivo fallo: " + e);
            }
        } else {
            log.writeln("    drift " + driftX.toFixed(1) + "/" + driftY.toFixed(1) +
                "px (" + (relX * 100).toFixed(2) + "% x " + (relY * 100).toFixed(2) +
                "%) bajo threshold; no resize.");
        }
    }

    // Re-ajuste fino post-escala (resize puede causar pequeno drift).
    log.writeln("    re-ajuste post-escala...");
    var b = moveLayerToTarget(newLayer, targetLeft, targetTop, log);
    var dx = targetLeft - b.left;
    var dy = targetTop - b.top;
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
        b = moveLayerToTarget(newLayer, targetLeft, targetTop, log);
    }

    // RE-APLICAR size/leading/hScale al final: el resize correctivo (cuando
    // se aplico) distorsiona el style sheet (ej. size 75.612 -> 78.87 tras
    // resize 104%). Reaplicar despues del resize garantiza que el panel
    // Character muestre los valores exactos del original.
    try {
        if (explicitSize !== null && isFinite(explicitSize) && explicitSize > 0) {
            newLayer.textItem.size = UnitValue(explicitSize, "pt");
            log.writeln("    size re-forzado a " + explicitSize.toFixed(3) + "pt (post-resize).");
        }
    } catch (e) {}
    try {
        if (explicitAutoLeading === true) {
            newLayer.textItem.useAutoLeading = true;
        } else if (explicitLeading !== null && isFinite(explicitLeading) && explicitLeading > 0) {
            newLayer.textItem.useAutoLeading = false;
            newLayer.textItem.leading = UnitValue(explicitLeading, "pt");
        }
    } catch (e) {}
    try {
        if (explicitHScale !== null && isFinite(explicitHScale) && explicitHScale > 0) {
            newLayer.textItem.horizontalScale = explicitHScale;
        }
    } catch (e) {}
    try {
        if (explicitVScale !== null && isFinite(explicitVScale) && explicitVScale > 0) {
            newLayer.textItem.verticalScale = explicitVScale;
        }
    } catch (e) {}

    log.writeln("    copiando presentacion...");
    copyLayerPresentation(source, newLayer);

    log.writeln("    moviendo junto a la capa original...");
    newLayer.move(source, ElementPlacement.PLACEBEFORE);
    newLayer.name = originalName;
    log.writeln("    eliminando capa original...");
    source.remove();

    log.writeln("    nuevo bounds=(" +
        Math.round(b.left) + "," + Math.round(b.top) + "," +
        Math.round(b.right) + "," + Math.round(b.bottom) + ")");
}

function fixedPathFor(doc) {
    var originalPath = doc.fullName.fsName;
    return originalPath.replace(/\.[^\.]+$/, "_fixed$&");
}

function main() {
    var logFile = new File(Folder.temp + "/psd_fix_log.txt");
    logFile.open("w");
    logFile.writeln("Rebuild text layers from manifest");

    try {
        if (app.documents.length === 0) {
            logFile.writeln("ERROR: No hay documentos.");
            return;
        }

        var doc = app.activeDocument;
        var originalRulers = app.preferences.rulerUnits;
        app.preferences.rulerUnits = Units.PIXELS;

        try {
            logFile.writeln("Documento: " + doc.name);

            var tempFile = new File(Folder.temp + "/psd_layers_to_fix.json");
            if (!tempFile.exists) {
                logFile.writeln("ERROR: No existe el manifest JSON.");
                return;
            }

            tempFile.open("r");
            var jsonString = tempFile.read();
            tempFile.close();

            var layerEntries = JSON.parse(jsonString);
            logFile.writeln("Layers en manifest: " + layerEntries.length);

            for (var i = 0; i < layerEntries.length; i++) {
                var entry = layerEntries[i];
                logFile.writeln("Layer: " + entry.name + " id=" + entry.layer_id);
                var layer = findLayer(doc, entry);
                if (!layer) {
                    logFile.writeln("    ERROR: no se encontro la capa.");
                    continue;
                }
                if (layer.kind !== LayerKind.TEXT) {
                    logFile.writeln("    ERROR: la capa encontrada no es texto.");
                    continue;
                }
                // Estrategia: PRIMERO intentar normalize in-place (preserva
                // font 100%, no recrea la capa, no depende de que la fuente
                // este instalada). Solo aplica para texto no rotado — para
                // rotado, recreate sigue siendo el path correcto.
                //
                // Si normalize falla (drift muy grande, capa con rotacion,
                // descriptor sin transform, error de setd), cae al recreate
                // existente (createCleanTextLayer / createRotatedTextLayer).
                var handled = false;
                if (entry.is_rotated !== true) {
                    try {
                        if (normalizeTextLayerInPlace(layer, entry, logFile)) {
                            logFile.writeln("    OK: normalizado in-place (font preservado).");
                            handled = true;
                        }
                    } catch (normErr) {
                        logFile.writeln("    WARNING normalize fallo: " + normErr);
                    }
                }
                if (!handled) {
                    if (entry.is_rotated === true) {
                        createRotatedTextLayer(layer, entry, logFile);
                        logFile.writeln("    OK: reconstruida (rotada) desde capa nueva (fallback).");
                    } else {
                        createCleanTextLayer(layer, entry, logFile);
                        logFile.writeln("    OK: reconstruida desde capa nueva (fallback).");
                    }
                }
                // Liberar memoria entre capas. PSDs grandes (8K x 8K)
                // pueden llenar scratch space rapido con duplicates +
                // resizes. purge libera historial deshacer + clipboard.
                try {
                    app.purge(PurgeTarget.HISTORYCACHES);
                    app.purge(PurgeTarget.CLIPBOARDCACHE);
                } catch (purgeErr) {}
            }

            var saveFile = new File(fixedPathFor(doc));
            var psdOptions = new PhotoshopSaveOptions();
            psdOptions.layers = true;
            psdOptions.embedColorConfiguration = true;
            doc.saveAs(saveFile, psdOptions, true, Extension.LOWERCASE);
            logFile.writeln("SAVE OK: " + saveFile.fsName);
            try {
                doc.close(SaveOptions.DONOTSAVECHANGES);
                logFile.writeln("Documento original cerrado sin sobrescribir.");
            } catch (closeErr) {
                logFile.writeln("WARNING close fallo: " + closeErr);
            }
        } finally {
            app.preferences.rulerUnits = originalRulers;
        }
    } catch (err) {
        logFile.writeln("FATAL ERROR: " + err);
    } finally {
        logFile.close();
        var doneFile = new File(Folder.temp + "/psd_fix_done.txt");
        doneFile.open("w");
        doneFile.write("done");
        doneFile.close();
    }
}

main();
