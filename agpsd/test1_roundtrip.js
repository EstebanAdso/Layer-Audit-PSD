// Test 1: Roundtrip puro de ag-psd.
// Lee PSD original sin modificar nada, escribe a archivo nuevo.
// Validar que el output sea valido y abrible sin warnings extranos.

const fs = require('fs');
const path = require('path');
const { readPsd, writePsdBuffer, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
// initializeCanvas con SOLO createCanvas (sin pasar Image como segundo arg).
// Si pasamos Image como createImageDataMethod, ag-psd intentaria new Image(w,h)
// que falla con "Class constructors cannot be invoked without new".
// Sin segundo arg, ag-psd usa fallback: tempCanvas.getContext('2d').createImageData(w,h)
// que node-canvas SI soporta.
initializeCanvas(createCanvas);

const INPUT = path.resolve(__dirname, '..', 'NATURAS_MUEBLES_EXHIBIDORES.psd');
const OUTPUT = path.resolve(__dirname, '..', 'NATURAS_MUEBLES_EXHIBIDORES_roundtrip.psd');

console.log('Input :', INPUT);
console.log('Output:', OUTPUT);
console.log('Input size :', (fs.statSync(INPUT).size / 1024 / 1024).toFixed(1), 'MB');

const t0 = Date.now();
console.log('\n[1/3] Reading PSD with ag-psd...');
const buffer = fs.readFileSync(INPUT);
// Lee TODO incluyendo pixel data para que el roundtrip preserve la apariencia.
// Para 1.85 GB necesitamos --max-old-space-size grande (16-20 GB).
const psd = readPsd(buffer, { useImageData: false, skipThumbnail: false });
console.log(`     Read in ${((Date.now() - t0)/1000).toFixed(1)}s`);
console.log(`     Doc dimensions: ${psd.width} x ${psd.height}`);
console.log(`     Top-level children: ${psd.children ? psd.children.length : 0}`);

function countNested(layers) {
    let total = 0;
    let textLayers = 0;
    if (!layers) return {total, textLayers};
    for (const l of layers) {
        total++;
        if (l.text) textLayers++;
        if (l.children) {
            const sub = countNested(l.children);
            total += sub.total;
            textLayers += sub.textLayers;
        }
    }
    return {total, textLayers};
}
const counts = countNested(psd.children);
console.log(`     Total layers (recursive): ${counts.total}`);
console.log(`     Text layers: ${counts.textLayers}`);

const t1 = Date.now();
console.log('\n[2/3] Writing PSD (no modifications)...');
const out = writePsdBuffer(psd);
console.log(`     Wrote ${(out.length/1024/1024).toFixed(1)} MB in ${((Date.now()-t1)/1000).toFixed(1)}s`);

console.log('\n[3/3] Saving to disk...');
fs.writeFileSync(OUTPUT, out);
const outSize = fs.statSync(OUTPUT).size;
console.log(`     Saved: ${(outSize/1024/1024).toFixed(1)} MB`);
console.log(`     Original: ${(fs.statSync(INPUT).size/1024/1024).toFixed(1)} MB`);
console.log(`     Size diff: ${((outSize - fs.statSync(INPUT).size)/1024/1024).toFixed(1)} MB`);
console.log(`\nTotal time: ${((Date.now()-t0)/1000).toFixed(1)}s`);
console.log('OK roundtrip complete.');
