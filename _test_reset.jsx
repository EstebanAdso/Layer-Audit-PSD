#target photoshop
app.displayDialogs = DialogModes.NO;
function cTID(s) { return charIDToTypeID(s); }
function sTID(s) { return stringIDToTypeID(s); }

var log = new File(Folder.temp + "/psd_test_log.txt");
log.open("w");

try {
    var doc = app.activeDocument;
    // Buscar primera capa de texto
    function findText(c) {
        for (var i = 0; i < c.layers.length; i++) {
            var l = c.layers[i];
            if (l.typename === "LayerSet") { var r = findText(l); if (r) return r; }
            else if (l.kind === LayerKind.TEXT) return l;
        }
        return null;
    }
    var layer = findText(doc);
    log.writeln("Layer: " + layer.name + " bounds=" + layer.bounds);

    function getActiveLayerDescriptor() {
        var ref = new ActionReference();
        ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
        return executeActionGet(ref);
    }
    function dumpTransform(label) {
        doc.activeLayer = layer;
        var d = getActiveLayerDescriptor();
        if (!d.hasKey(sTID("textKey"))) { log.writeln("[" + label + "] no textKey"); return; }
        var tk = d.getObjectValue(sTID("textKey"));
        log.writeln("[" + label + "] bounds=" + layer.bounds);
        if (tk.hasKey(sTID("textShape"))) {
            var sl = tk.getList(sTID("textShape"));
            if (sl.count > 0) {
                var sh = sl.getObjectValue(0);
                if (sh.hasKey(sTID("transform"))) {
                    var t = sh.getObjectValue(sTID("transform"));
                    var v = function(k) { try { return t.getDouble(sTID(k)).toFixed(3); } catch(e) { return "?"; } };
                    log.writeln("  textShape[0].tr: xx=" + v("xx") + " xy=" + v("xy") +
                                " yx=" + v("yx") + " yy=" + v("yy") +
                                " tx=" + v("tx") + " ty=" + v("ty"));
                }
            }
        }
    }

    dumpTransform("ORIGINAL");

    // Duplicar
    doc.activeLayer = layer;
    var dup = layer.duplicate();
    dup.name = "test_dup";
    doc.activeLayer = dup;

    layer = dup;
    dumpTransform("DUPLICATED");

    // Test 1: translate(0,0)
    log.writeln("\n=== TEST: translate(0,0) ===");
    try { dup.translate(0, 0); } catch (e) { log.writeln("  fail: " + e); }
    dumpTransform("after translate(0,0)");

    // Test 2: rotate(0)
    log.writeln("\n=== TEST: rotate(0) ===");
    try { dup.rotate(0); } catch (e) { log.writeln("  fail: " + e); }
    dumpTransform("after rotate(0)");

    // Test 3: resize(100,100)
    log.writeln("\n=== TEST: resize(100,100,TOPLEFT) ===");
    try { dup.resize(100, 100, AnchorPosition.TOPLEFT); } catch (e) { log.writeln("  fail: " + e); }
    dumpTransform("after resize");

    // Test 4: AM Trnf identity
    log.writeln("\n=== TEST: AM Trnf identity ===");
    try {
        var d = new ActionDescriptor();
        var r = new ActionReference();
        r.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
        d.putReference(cTID("null"), r);
        d.putEnumerated(cTID("FTcs"), cTID("QCSt"), cTID("Qcsa"));
        var offset = new ActionDescriptor();
        offset.putUnitDouble(cTID("Hrzn"), cTID("#Pxl"), 0);
        offset.putUnitDouble(cTID("Vrtc"), cTID("#Pxl"), 0);
        d.putObject(cTID("Ofst"), cTID("Ofst"), offset);
        executeAction(cTID("Trnf"), d, DialogModes.NO);
        log.writeln("  Trnf ok");
    } catch (e) { log.writeln("  fail: " + e); }
    dumpTransform("after Trnf identity");

    // Test 5: convert to smart object and back
    log.writeln("\n=== TEST: cmd ids disponibles ===");
    var cmds = ["rstT", "rstX", "resetBoundingBox", "resetTransform", "FrTr", "TrnS", "TrnE", "fnTb"];
    for (var ci = 0; ci < cmds.length; ci++) {
        try {
            var id = sTID(cmds[ci]);
            log.writeln("  sTID('" + cmds[ci] + "') = " + id);
        } catch (e) { log.writeln("  sTID('" + cmds[ci] + "') err"); }
    }

    // limpiar
    dup.remove();
} catch (err) {
    log.writeln("FATAL: " + err);
}
log.close();
var done = new File(Folder.temp + "/psd_test_done.txt");
done.open("w");
done.write("done");
done.close();
