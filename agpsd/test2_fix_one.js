// Test 2: Modificar el transform de UNA SOLA capa problema y verificar.
//
// Capa target: TEXT_ATRIBUTO1_MUEBLES_EXHIBIDORDEPISOPALI_50CMX140CM
// Bounds visual original: (997, 6193) - donde la capa se renderiza ahora
// Matrix corrupta:        [3.77, 0, 0, 3.77, -42702, -34837]
// Matrix target:          [1, 0, 0, 1, 997, 6193]  (identity en bounds visual)

const fs = require('fs');
const path = require('path');
const { readPsd, writePsdBuffer, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const INPUT = path.resolve(__dirname, '..', 'NATURAS_MUEBLES_EXHIBIDORES.psd');
const OUTPUT = path.resolve(__dirname, '..', 'NATURAS_MUEBLES_EXHIBIDORES_fix1.psd');

const TARGET_NAME = 'TEXT_ATRIBUTO1_MUEBLES_EXHIBIDORDEPISOPALI_50CMX140CM';
const TARGET_LEFT = 997;
const TARGET_TOP = 6193;

console.log('Input :', INPUT);
console.log('Output:', OUTPUT);

function findLayerByName(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) {
            const f = findLayerByName(l.children, name);
            if (f) return f;
        }
    }
    return null;
}

const t0 = Date.now();
console.log('\n[1/4] Reading PSD...');
const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });
console.log(`     Read ${psd.children.length} top-level children in ${((Date.now()-t0)/1000).toFixed(1)}s`);

console.log('\n[2/4] Locating target layer:', TARGET_NAME);
const layer = findLayerByName(psd.children, TARGET_NAME);
if (!layer) {
    console.error('     ERROR: layer not found!');
    process.exit(1);
}

console.log('     Found layer.');
console.log('     layer.left/top/right/bottom:', layer.left, layer.top, layer.right, layer.bottom);
console.log('     layer.text exists:', !!layer.text);
if (layer.text) {
    console.log('     layer.text.text:', JSON.stringify(layer.text.text));
    console.log('     layer.text.transform (BEFORE):', layer.text.transform);
    // Inspect the style runs (font info)
    if (layer.text.style) {
        console.log('     layer.text.style.font:', JSON.stringify(layer.text.style.font));
    }
    if (layer.text.styleRuns && layer.text.styleRuns.length > 0) {
        const sr = layer.text.styleRuns[0];
        console.log('     layer.text.styleRuns[0].style.font:', JSON.stringify(sr.style && sr.style.font));
    }
}

console.log('\n[3/4] Modifying transform to identity at target position...');
if (layer.text) {
    layer.text.transform = [1, 0, 0, 1, TARGET_LEFT, TARGET_TOP];
    console.log('     layer.text.transform (AFTER):', layer.text.transform);
}

console.log('\n[4/4] Writing modified PSD with invalidateTextLayers=true...');
const t1 = Date.now();
const out = writePsdBuffer(psd, { invalidateTextLayers: true });
console.log(`     Wrote ${(out.length/1024/1024).toFixed(1)} MB in ${((Date.now()-t1)/1000).toFixed(1)}s`);
fs.writeFileSync(OUTPUT, out);
console.log(`     Saved to: ${OUTPUT}`);

console.log(`\nTotal time: ${((Date.now()-t0)/1000).toFixed(1)}s`);
console.log('Done. Open in Photoshop to confirm popup appears and text renders at correct position.');
