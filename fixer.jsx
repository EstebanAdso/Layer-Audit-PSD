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

function makeBlankTextLayer(parent, entry, log) {
    try {
        if (parent && parent.artLayers) {
            var domLayer = parent.artLayers.add();
            domLayer.kind = LayerKind.TEXT;
            domLayer.textItem.contents = " ";
            return domLayer;
        }
    } catch (e) {
        log.writeln("    WARNING crear texto DOM fallo: " + e);
    }

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
        return app.activeDocument.activeLayer;
    } catch (e2) {
        log.writeln("    WARNING crear texto AM fallo: " + e2);
    }

    if (entry.template_layer_id !== undefined && entry.template_layer_id !== null && entry.template_layer_id !== "") {
        log.writeln("    fallback: duplicando plantilla limpia id=" + entry.template_layer_id);
        return duplicateLayerById(entry.template_layer_id);
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
    try { targetItem.font = sourceItem.font; } catch (e) {}
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

function createCleanTextLayer(source, entry, log) {
    var doc = app.activeDocument;
    var originalName = source.name;
    var targetLeft = Number(entry.left);
    var targetTop = Number(entry.top);

    try {
        log.writeln("    parent=" + source.parent.typename + " / " + source.parent.name);
    } catch (pe) {}
    log.writeln("    creando capa de texto nueva...");
    var newLayer = makeBlankTextLayer(source.parent, entry, log);

    newLayer = doc.activeLayer;
    newLayer.name = originalName + "__rebuild";
    copyTextItemBasics(source.textItem, newLayer.textItem, entry, log);
    tuneLeadingToTargetHeight(newLayer, entry, log);

    // Mover ANTES de escalar: para texto chico que sera muy pequeno post-escala,
    // translate() falla con "Transformar no disponible". Posicionando primero
    // (mientras la capa aun esta grande) evitamos ese error; luego el resize
    // con anchor TOPLEFT preserva la posicion.
    log.writeln("    posicionamiento previo a escala...");
    moveLayerToTarget(newLayer, targetLeft, targetTop, log);

    // Reescalar para igualar bounds. Vertical: scale eje-por-eje (forzamos
    // ancho de columna). Horizontal: uniforme por altura + ajuste horizontal
    // para compensar HorizontalScale/VerticalScale del style original que
    // se pierden al recrear.
    if (entry.orientation === "vertical") {
        scaleLayerToTargetBounds(newLayer, entry, log);
    } else {
        scaleLayerUniformToHeight(newLayer, entry, log);
    }

    // Re-ajuste fino post-escala (resize puede causar pequeno drift).
    log.writeln("    re-ajuste post-escala...");
    var b = moveLayerToTarget(newLayer, targetLeft, targetTop, log);
    var dx = targetLeft - b.left;
    var dy = targetTop - b.top;
    if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
        b = moveLayerToTarget(newLayer, targetLeft, targetTop, log);
    }

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
                createCleanTextLayer(layer, entry, logFile);
                logFile.writeln("    OK: reconstruida desde capa nueva.");
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
