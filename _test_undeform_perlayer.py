"""Test mejorado: aplica Undeform UNA CAPA A LA VEZ + move chunked + purge.

Estrategia:
  1. Abre PSD
  2. Para cada layer problema:
     a. Recorda bounds PRE (= target visual position donde se renderiza ahora)
     b. Selecciona SOLO ese layer
     c. Aplica la logica de Undeform (transform identity + warp reset)
     d. Mueve a target en chunks de 1000px
     e. Purga memoria
  3. Guarda como _fixed_undeform_v2.psd
"""
import json
import os
import sys
import tempfile
import time
import subprocess

PSD = os.path.abspath('NATURAS_MUEBLES_EXHIBIDORES.psd')
OUT_PSD = os.path.abspath('NATURAS_MUEBLES_EXHIBIDORES_fixed_undeform_v2.psd')

PROBLEM_LAYERS = [
    'TEXT_ATRIBUTO3_MUEBLES_EXHIBIDORDEPISOPALI_50CMX140CM',
    'TEXT_ATRIBUTO2_MUEBLES_EXHIBIDORDEPISOPALI_50CMX140CM',
    'TEXT_ATRIBUTO1_MUEBLES_EXHIBIDORDEPISOPALI_50CMX140CM',
    'TEXT_ATRIBUTO3_MUEBLES_EXHIBIDORDEPISOPALI_40CMX140CM',
    'TEXT_ATRIBUTO2_MUEBLES_EXHIBIDORDEPISOPALI_40CMX140CM',
    'TEXT_ATRIBUTO1_MUEBLES_EXHIBIDORDEPISOPALI_40CMX140CM',
    'TEXT_ATRIBUTO3_MUEBLES_EXHIBIDORDEPISOMETALICO_40CMX140CM',
    'TEXT_ATRIBUTO2_MUEBLES_EXHIBIDORDEPISOMETALICO_40CMX140CM',
    'TEXT_ATRIBUTO1_MUEBLES_EXHIBIDORDEPISOMETALICO_40CMX140CM',
]

JSX = r'''
#target photoshop
app.displayDialogs = DialogModes.NO;

var log = new File(Folder.temp + "/undeform_v2_log.txt");
log.open("w");

function cTID(s) { return charIDToTypeID(s); }
function sTID(s) { return stringIDToTypeID(s); }

function findLayerByName(container, name) {
    for (var i = 0; i < container.layers.length; i++) {
        var l = container.layers[i];
        if (l.typename === "LayerSet") {
            var found = findLayerByName(l, name);
            if (found) return found;
        } else if (l.name === name) return l;
    }
    return null;
}

function selectLayer(layer) {
    app.activeDocument.activeLayer = layer;
}

function layerBoundsPx(layer) {
    var b = layer.bounds;
    return {
        left: Number(b[0].as("px")),
        top: Number(b[1].as("px")),
        right: Number(b[2].as("px")),
        bottom: Number(b[3].as("px"))
    };
}

// Undeform's exact text-layer logic, adapted for active layer:
function undeformActiveText() {
    // Read textKey of active layer
    var ref = new ActionReference();
    ref.putProperty(cTID("Prpr"), sTID("textKey"));
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    var desc = executeActionGet(ref);
    if (!desc.hasKey(sTID("textKey"))) return false;
    var textKey = desc.getObjectValue(sTID("textKey"));

    // Replace transform with identity at (0,0) — EXACT Undeform pattern
    textKey.erase(sTID("transform"));
    var tr = new ActionDescriptor();
    tr.putDouble(sTID("xx"), 1);
    tr.putDouble(sTID("xy"), 0);
    tr.putDouble(sTID("yx"), 0);
    tr.putDouble(sTID("yy"), 1);
    tr.putDouble(sTID("tx"), 0);
    tr.putDouble(sTID("ty"), 0);
    textKey.putObject(cTID("Trnf"), cTID("Trnf"), tr);

    // Reset warp to none
    textKey.erase(sTID("warp"));
    var w = new ActionDescriptor();
    w.putEnumerated(sTID("warpStyle"), sTID("warpStyle"), sTID("warpNone"));
    w.putDouble(sTID("warpValue"), 0);
    w.putDouble(sTID("warpPerspective"), 0);
    w.putDouble(sTID("warpPerspectiveOther"), 0);
    w.putEnumerated(sTID("warpRotate"), sTID("Ornt"), sTID("Hrzn"));
    textKey.putObject(sTID("warp"), sTID("warp"), w);

    // setd
    var d = new ActionDescriptor();
    var r = new ActionReference();
    r.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    d.putReference(cTID("null"), r);
    d.putObject(cTID("T   "), cTID("TxLr"), textKey);
    executeAction(cTID("setd"), d, DialogModes.NO);
    return true;
}

function moveActiveLayerByPx(dx, dy) {
    var desc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    desc.putReference(cTID("null"), ref);
    var off = new ActionDescriptor();
    off.putUnitDouble(cTID("Hrzn"), cTID("#Pxl"), dx);
    off.putUnitDouble(cTID("Vrtc"), cTID("#Pxl"), dy);
    desc.putObject(cTID("Ofst"), cTID("Ofst"), off);
    executeAction(cTID("move"), desc, DialogModes.NO);
}

// Mover en chunks <= 1000 hasta llegar al target o agotar iteraciones
function chunkedMoveToTarget(layer, targetLeft, targetTop) {
    for (var i = 0; i < 50; i++) {
        var b = layerBoundsPx(layer);
        var dx = targetLeft - b.left;
        var dy = targetTop - b.top;
        if (Math.abs(dx) <= 0.5 && Math.abs(dy) <= 0.5) {
            return { ok: true, iters: i };
        }
        var stepX = (Math.abs(dx) > 1000) ? (dx > 0 ? 1000 : -1000) : dx;
        var stepY = (Math.abs(dy) > 1000) ? (dy > 0 ? 1000 : -1000) : dy;
        try {
            moveActiveLayerByPx(stepX, stepY);
        } catch (e) {
            return { ok: false, iters: i, error: String(e) };
        }
    }
    return { ok: false, iters: 50, error: "max iters" };
}

try {
    var doc = app.activeDocument;
    var oldRulers = app.preferences.rulerUnits;
    app.preferences.rulerUnits = Units.PIXELS;

    log.writeln("Documento: " + doc.name);
    log.writeln("Canvas: " + doc.width.as("px") + " x " + doc.height.as("px"));

    var names = LAYER_NAMES_PLACEHOLDER;
    var passed = 0;
    var failed = 0;

    for (var i = 0; i < names.length; i++) {
        var lyrName = names[i];
        log.writeln("\n--- [" + (i+1) + "/" + names.length + "] " + lyrName + " ---");
        var layer = findLayerByName(doc, lyrName);
        if (!layer) { log.writeln("  NO ENCONTRADA"); failed++; continue; }

        selectLayer(layer);
        var bPre = layerBoundsPx(layer);
        var fontPre = "?";
        try { fontPre = layer.textItem.font; } catch (e) {}
        log.writeln("  PRE: bounds=(" + Math.round(bPre.left) + "," + Math.round(bPre.top) +
            "," + Math.round(bPre.right) + "," + Math.round(bPre.bottom) +
            ") font=" + fontPre);

        // 1. Undeform en ESTA capa solamente
        try {
            undeformActiveText();
            log.writeln("  setd Undeform: OK");
        } catch (eU) {
            log.writeln("  setd Undeform FALLO: " + eU);
            failed++;
            try {
                app.purge(PurgeTarget.HISTORYCACHES);
                app.purge(PurgeTarget.CLIPBOARDCACHE);
            } catch (ePurge) {}
            continue;
        }

        var bPost = layerBoundsPx(layer);
        log.writeln("  POST-setd: bounds=(" + Math.round(bPost.left) + "," + Math.round(bPost.top) +
            "," + Math.round(bPost.right) + "," + Math.round(bPost.bottom) + ")");

        // 2. Mover de vuelta al target visual (= bounds PRE)
        var moveResult = chunkedMoveToTarget(layer, bPre.left, bPre.top);
        log.writeln("  chunkedMove: ok=" + moveResult.ok + " iters=" + moveResult.iters +
            (moveResult.error ? " error=" + moveResult.error : ""));

        var bFin = layerBoundsPx(layer);
        var fontPost = "?";
        try { fontPost = layer.textItem.font; } catch (e) {}
        log.writeln("  POST-move: bounds=(" + Math.round(bFin.left) + "," + Math.round(bFin.top) +
            "," + Math.round(bFin.right) + "," + Math.round(bFin.bottom) +
            ") font=" + fontPost);

        var dxFin = bFin.left - bPre.left;
        var dyFin = bFin.top - bPre.top;
        var fontPreserved = (fontPost === fontPre);
        var positionOk = Math.abs(dxFin) <= 2 && Math.abs(dyFin) <= 2;
        log.writeln("  -> font preservado: " + fontPreserved + ", posicion OK: " + positionOk);
        if (fontPreserved && positionOk) passed++; else failed++;

        // 3. Purga entre capas
        try {
            app.purge(PurgeTarget.HISTORYCACHES);
            app.purge(PurgeTarget.CLIPBOARDCACHE);
            app.purge(PurgeTarget.UNDOCACHES);
        } catch (ePurge) {}
    }

    log.writeln("\n=== RESUMEN ===");
    log.writeln("Passed: " + passed + " / Failed: " + failed);

    var saveFile = new File("OUT_PATH_PLACEHOLDER");
    var psdOpts = new PhotoshopSaveOptions();
    psdOpts.layers = true;
    doc.saveAs(saveFile, psdOpts, true, Extension.LOWERCASE);
    log.writeln("SAVE OK: " + saveFile.fsName);

    app.preferences.rulerUnits = oldRulers;
    doc.close(SaveOptions.DONOTSAVECHANGES);
} catch (err) {
    log.writeln("FATAL: " + err);
}
log.close();

var done = new File(Folder.temp + "/undeform_v2_done.txt");
done.open("w"); done.write("done"); done.close();
'''


def main():
    jsx = JSX.replace(
        'LAYER_NAMES_PLACEHOLDER', json.dumps(PROBLEM_LAYERS)
    ).replace(
        'OUT_PATH_PLACEHOLDER', OUT_PSD.replace('\\', '\\\\')
    )
    jsx_path = os.path.join(tempfile.gettempdir(), 'undeform_v2.jsx')
    with open(jsx_path, 'w', encoding='utf-8') as f:
        f.write(jsx)

    tmpdir = tempfile.gettempdir()
    for p in ('undeform_v2_done.txt', 'undeform_v2_log.txt'):
        full = os.path.join(tmpdir, p)
        if os.path.exists(full): os.remove(full)
    if os.path.exists(OUT_PSD): os.remove(OUT_PSD)

    safe_jsx = jsx_path.replace('\\', '\\\\')
    safe_psd = PSD.replace('\\', '\\\\')
    vbs = (
        'On Error Resume Next\r\n'
        'Set app = CreateObject("Photoshop.Application")\r\n'
        f'app.Open("{safe_psd}")\r\n'
        'WScript.Sleep 4000\r\n'
        f'app.DoJavaScriptFile("{safe_jsx}")\r\n'
        'Set app = Nothing\r\n'
    )
    vbs_path = os.path.join(tmpdir, 'undeform_v2.vbs')
    with open(vbs_path, 'w', encoding='utf-16') as f:
        f.write(vbs)

    subprocess.Popen(['cscript', '//Nologo', vbs_path],
                     creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)

    print("Lanzado. Esperando hasta 600s...")
    done = os.path.join(tmpdir, 'undeform_v2_done.txt')
    log = os.path.join(tmpdir, 'undeform_v2_log.txt')
    start = time.time()
    while time.time() - start < 600:
        if os.path.exists(done):
            print(f"DONE ({time.time() - start:.1f}s)")
            break
        time.sleep(3)
    else:
        print("TIMEOUT")

    time.sleep(1)
    if os.path.exists(log):
        with open(log, 'r', encoding='utf-8', errors='ignore') as f:
            print("\n=== LOG ===")
            print(f.read())


if __name__ == '__main__':
    main()
