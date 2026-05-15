// Test 5: matrix scale preservado + ty calculado como BASELINE original
// (no como bbox.top).
//
// Razon: Adobe API interpreta transform.ty como la baseline position del
// texto, NO como bbox.top. POSTMAN.psd lo confirma:
//   sent ty=6193, result bbox.bottom=6193 (la baseline cae cerca del bbox.bottom).
//
// Para que el bbox final del nuevo texto quede en la misma posicion que el
// original, hay que setear ty = baseline_original ≈ bbox.top + 0.75 * height
// (donde 0.75 es la fraccion ascent/(ascent+descent) tipica de fuentes).

const fs = require('fs');
const path = require('path');
const { readPsd, writePsdBuffer, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const argv = process.argv.slice(2);
const INPUT = path.resolve(argv[0] || '../NATURAS_MUEBLES_EXHIBIDORES.psd');
const MANIFEST = path.resolve(argv[1] || './manifest.json');
const OUTPUT = path.resolve(argv[2] || '../NATURAS_MUEBLES_EXHIBIDORES_baseline.psd');

const ASCENT_RATIO = 0.75;  // ascent / (ascent + descent) tipico

function findLayerByName(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = findLayerByName(l.children, name); if (f) return f; }
    }
    return null;
}

const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
console.log(`Manifest: ${manifest.length} layers`);

const t0 = Date.now();
console.log('Reading PSD...');
const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });

console.log('\nPatching layers (KEEP scale, ty=baseline_estimate)...');
for (const entry of manifest) {
    const layer = findLayerByName(psd.children, entry.name);
    if (!layer || !layer.text) {
        console.log(`MISS: ${entry.name}`);
        continue;
    }
    const before = layer.text.transform.slice();
    const xx = before[0], xy = before[1], yx = before[2], yy = before[3];

    // Calculo baseline usando el bbox visual del manifest
    const height = (entry.bottom !== undefined && entry.top !== undefined)
        ? (entry.bottom - entry.top)
        : 0;
    const baseline_y = entry.top + Math.round(height * ASCENT_RATIO);

    layer.text.transform = [xx, xy, yx, yy, entry.left, baseline_y];

    console.log(`  ${entry.name.slice(0, 50).padEnd(50)} bbox.top=${entry.top} height=${height} -> ty=${baseline_y}`);
}

console.log('\nWriting...');
const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`Saved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
