"""Test directo: corre Undeform.jsx tal cual sobre las capas problema de NATURAS.

No usa fixer.jsx ni nuestro normalizeTextLayerInPlace. Solo:
  1. Abre el PSD en Photoshop
  2. Selecciona las 9 capas problema por nombre
  3. Ejecuta el Undeform.jsx tal cual (algoritmo Magic Scripts, sin nuestra modificacion)
  4. Guarda como _fixed_undeform.psd

Asi sabemos si Undeform PURO alcanza, o si necesita extension para
nuestra corrupcion copy-paste-entre-artboards.
"""
import os
import sys
import tempfile
import time
import subprocess

PSD = os.path.abspath('NATURAS_MUEBLES_EXHIBIDORES.psd')
UNDEFORM = r'C:\Users\EstebanSoft\Downloads\PS_magic_scripts\[M] Undeform 1.1.jsx'
OUT_PSD = os.path.abspath('NATURAS_MUEBLES_EXHIBIDORES_fixed_undeform.psd')

# Layers problema (los 9 ATRIBUTOs)
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

# JSX wrapper: selecciona capas por nombre + corre Undeform + guarda
JSX_WRAPPER = r'''
#target photoshop
app.displayDialogs = DialogModes.NO;

var log = new File(Folder.temp + "/undeform_test_log.txt");
log.open("w");

function cTID(s) { return charIDToTypeID(s); }
function sTID(s) { return stringIDToTypeID(s); }

function findLayerByName(container, name) {
    for (var i = 0; i < container.layers.length; i++) {
        var l = container.layers[i];
        if (l.typename === "LayerSet") {
            var found = findLayerByName(l, name);
            if (found) return found;
        } else if (l.name === name) {
            return l;
        }
    }
    return null;
}

function selectLayerByName(name, addToSelection) {
    var l = findLayerByName(app.activeDocument, name);
    if (!l) { log.writeln("NO ENCONTRADA: " + name); return false; }
    var desc = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putName(cTID("Lyr "), name);
    desc.putReference(cTID("null"), ref);
    if (addToSelection) {
        desc.putEnumerated(sTID("selectionModifier"),
            sTID("selectionModifierType"), sTID("addToSelection"));
    }
    desc.putBoolean(cTID("MkVs"), false);
    executeAction(cTID("slct"), desc, DialogModes.NO);
    return true;
}

function dumpLayerState(name, prefix) {
    var l = findLayerByName(app.activeDocument, name);
    if (!l) return;
    app.activeDocument.activeLayer = l;
    var b = l.bounds;
    var info = prefix + " " + name + " bounds=(" +
        Math.round(b[0]) + "," + Math.round(b[1]) + "," +
        Math.round(b[2]) + "," + Math.round(b[3]) + ")";
    try {
        info += " font=" + l.textItem.font;
    } catch (e) { info += " font=?"; }
    log.writeln(info);
}

try {
    var doc = app.activeDocument;
    var oldRulers = app.preferences.rulerUnits;
    app.preferences.rulerUnits = Units.PIXELS;

    log.writeln("Documento: " + doc.name);
    log.writeln("Canvas: " + doc.width.as("px") + " x " + doc.height.as("px"));

    var names = LAYER_NAMES_PLACEHOLDER;

    log.writeln("\n=== ESTADO PRE ===");
    for (var i = 0; i < names.length; i++) {
        dumpLayerState(names[i], "PRE");
    }

    log.writeln("\n=== SELECCION ===");
    var selected = 0;
    for (var i = 0; i < names.length; i++) {
        if (selectLayerByName(names[i], i > 0)) selected++;
    }
    log.writeln("Seleccionadas: " + selected + "/" + names.length);

    log.writeln("\n=== CORRIENDO UNDEFORM.JSX ===");
    try {
        $.evalFile(File("UNDEFORM_PATH_PLACEHOLDER"));
        log.writeln("Undeform ejecutado OK");
    } catch (eUnd) {
        log.writeln("Undeform fallo: " + eUnd);
    }

    log.writeln("\n=== ESTADO POST ===");
    for (var i = 0; i < names.length; i++) {
        dumpLayerState(names[i], "POST");
    }

    var saveFile = new File("OUT_PATH_PLACEHOLDER");
    var psdOpts = new PhotoshopSaveOptions();
    psdOpts.layers = true;
    doc.saveAs(saveFile, psdOpts, true, Extension.LOWERCASE);
    log.writeln("\nSAVE OK: " + saveFile.fsName);

    app.preferences.rulerUnits = oldRulers;
    doc.close(SaveOptions.DONOTSAVECHANGES);
} catch (err) {
    log.writeln("FATAL: " + err);
}
log.close();

var done = new File(Folder.temp + "/undeform_test_done.txt");
done.open("w"); done.write("done"); done.close();
'''


def main():
    if not os.path.exists(PSD):
        print(f"NO existe PSD: {PSD}")
        sys.exit(1)
    if not os.path.exists(UNDEFORM):
        print(f"NO existe Undeform: {UNDEFORM}")
        sys.exit(1)

    # Render JSX
    import json
    jsx = JSX_WRAPPER.replace(
        'LAYER_NAMES_PLACEHOLDER', json.dumps(PROBLEM_LAYERS)
    ).replace(
        'UNDEFORM_PATH_PLACEHOLDER', UNDEFORM.replace('\\', '\\\\')
    ).replace(
        'OUT_PATH_PLACEHOLDER', OUT_PSD.replace('\\', '\\\\')
    )
    jsx_path = os.path.join(tempfile.gettempdir(), 'undeform_wrapper.jsx')
    with open(jsx_path, 'w', encoding='utf-8') as f:
        f.write(jsx)
    print(f"JSX wrapper: {jsx_path}")

    # Limpiar señales y borrar fixed previo
    tmpdir = tempfile.gettempdir()
    for p in ('undeform_test_done.txt', 'undeform_test_log.txt'):
        full = os.path.join(tmpdir, p)
        if os.path.exists(full):
            os.remove(full)
    if os.path.exists(OUT_PSD):
        os.remove(OUT_PSD)

    # Lanzar Photoshop via VBS
    safe_jsx = jsx_path.replace('\\', '\\\\')
    safe_psd = PSD.replace('\\', '\\\\')
    vbs = (
        'On Error Resume Next\r\n'
        'Set app = CreateObject("Photoshop.Application")\r\n'
        f'app.Open("{safe_psd}")\r\n'
        'WScript.Sleep 3000\r\n'
        f'app.DoJavaScriptFile("{safe_jsx}")\r\n'
        'Set app = Nothing\r\n'
    )
    vbs_path = os.path.join(tmpdir, 'undeform_launch.vbs')
    with open(vbs_path, 'w', encoding='utf-16') as f:
        f.write(vbs)
    subprocess.Popen(['cscript', '//Nologo', vbs_path],
                     creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)

    print("Lanzado. Esperando hasta 300s...")
    done = os.path.join(tmpdir, 'undeform_test_done.txt')
    log = os.path.join(tmpdir, 'undeform_test_log.txt')
    start = time.time()
    while time.time() - start < 300:
        if os.path.exists(done):
            print(f"DONE ({time.time() - start:.1f}s)")
            break
        time.sleep(2)
    else:
        print("TIMEOUT")

    time.sleep(1)
    if os.path.exists(log):
        with open(log, 'r', encoding='utf-8', errors='ignore') as f:
            print("\n=== UNDEFORM LOG ===")
            print(f.read())
    else:
        print("NO log generado")


if __name__ == '__main__':
    main()
