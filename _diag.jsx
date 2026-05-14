#target photoshop
app.displayDialogs = DialogModes.NO;

function cTID(s) { return charIDToTypeID(s); }
function sTID(s) { return stringIDToTypeID(s); }

function getTargetLayerDescriptor() {
    var ref = new ActionReference();
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    return executeActionGet(ref);
}

var log = new File(Folder.temp + "/psd_diag_log.txt");
log.open("w");

try {
    var doc = app.activeDocument;
    var origRulers = app.preferences.rulerUnits;
    var origType = app.preferences.typeUnits;
    app.preferences.rulerUnits = Units.PIXELS;

    log.writeln("Documento: " + doc.name);
    log.writeln("Resolution: " + doc.resolution + " dpi");
    log.writeln("Tamaño: " + doc.width.as("px") + " x " + doc.height.as("px") + " px");
    log.writeln("");

    function dumpLayer(layer) {
        log.writeln("=== Layer: " + layer.name + " ===");
        app.activeDocument.activeLayer = layer;
        var item = layer.textItem;
        log.writeln("DOM textItem:");
        try { log.writeln("  size = " + item.size + " (" + item.size.value + " " + item.size.type + ")"); } catch (e) { log.writeln("  size err: " + e); }
        try { log.writeln("  leading = " + item.leading + " auto=" + item.useAutoLeading); } catch (e) {}
        try { log.writeln("  position = " + item.position); } catch (e) {}
        try { log.writeln("  kind = " + item.kind); } catch (e) {}
        try { log.writeln("  contents = " + item.contents.substring(0, 40)); } catch (e) {}

        var desc = getTargetLayerDescriptor();
        if (desc.hasKey(sTID("textKey"))) {
            var textKey = desc.getObjectValue(sTID("textKey"));
            if (textKey.hasKey(sTID("textStyleRange"))) {
                var rl = textKey.getList(sTID("textStyleRange"));
                if (rl.count > 0) {
                    var range = rl.getObjectValue(0);
                    if (range.hasKey(sTID("textStyle"))) {
                        var ts = range.getObjectValue(sTID("textStyle"));
                        log.writeln("textStyle keys:");
                        for (var i = 0; i < ts.count; i++) {
                            var k = ts.getKey(i);
                            var name = "";
                            try { name = typeIDToStringID(k); } catch (e1) {}
                            if (!name) { try { name = typeIDToCharID(k); } catch (e2) {} }
                            var ttype = "";
                            try { ttype = ts.getType(k); } catch (e3) {}
                            var val = "?";
                            try {
                                if (ttype === DescValueType.DOUBLETYPE) val = ts.getDouble(k);
                                else if (ttype === DescValueType.UNITDOUBLE) {
                                    var uval = ts.getUnitDoubleValue(k);
                                    var utype = ts.getUnitDoubleType(k);
                                    var unitName = "";
                                    try { unitName = typeIDToStringID(utype); } catch(e) {}
                                    if (!unitName) { try { unitName = typeIDToCharID(utype); } catch(e) {} }
                                    val = uval + " " + unitName;
                                }
                                else if (ttype === DescValueType.INTEGERTYPE) val = ts.getInteger(k);
                                else if (ttype === DescValueType.BOOLEANTYPE) val = ts.getBoolean(k);
                                else if (ttype === DescValueType.STRINGTYPE) val = ts.getString(k);
                            } catch (eg) { val = "<err " + eg + ">"; }
                            log.writeln("  " + name + " (" + ttype + ") = " + val);
                        }
                    }
                }
            }
            // Dump textShape[0].transform values
            if (textKey.hasKey(sTID("textShape"))) {
                var sl = textKey.getList(sTID("textShape"));
                if (sl.count > 0) {
                    var shape = sl.getObjectValue(0);
                    if (shape.hasKey(sTID("transform"))) {
                        var tr = shape.getObjectValue(sTID("transform"));
                        log.writeln("textShape[0].transform:");
                        var keys = ["xx", "xy", "yx", "yy", "tx", "ty"];
                        for (var j = 0; j < keys.length; j++) {
                            try {
                                log.writeln("  " + keys[j] + " = " + tr.getDouble(sTID(keys[j])));
                            } catch (e) { log.writeln("  " + keys[j] + " err: " + e); }
                        }
                    }
                }
            }
        }
        log.writeln("");
    }

    function walk(container) {
        for (var i = 0; i < container.layers.length; i++) {
            var l = container.layers[i];
            if (l.typename === "LayerSet") { walk(l); }
            else if (l.kind === LayerKind.TEXT) { dumpLayer(l); }
        }
    }
    walk(doc);

    app.preferences.rulerUnits = origRulers;
    app.preferences.typeUnits = origType;
} catch (err) {
    log.writeln("FATAL: " + err);
}
log.close();

var done = new File(Folder.temp + "/psd_diag_done.txt");
done.open("w");
done.write("done");
done.close();
