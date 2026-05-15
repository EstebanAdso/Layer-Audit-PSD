// Test 3: arregla TODAS las capas problema en un solo pase.
//
// Input: PSD + JSON manifest con capas problema (name, targetLeft, targetTop)
// Output: PSD reparado donde cada capa problema tiene transform=identity at target
//
// Uso: node test3_fix_all.js <input.psd> <manifest.json> <output.psd>

const fs = require('fs');
const path = require('path');
const { readPsd, writePsdBuffer, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const argv = process.argv.slice(2);
const INPUT = path.resolve(argv[0] || '../NATURAS_MUEBLES_EXHIBIDORES.psd');
const MANIFEST = path.resolve(argv[1] || './manifest.json');
const OUTPUT = path.resolve(argv[2] || '../NATURAS_MUEBLES_EXHIBIDORES_fixed_agpsd.psd');

console.log('Input    :', INPUT);
console.log('Manifest :', MANIFEST);
console.log('Output   :', OUTPUT);

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

const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
console.log(`\nManifest: ${manifest.length} layers to fix`);

const t0 = Date.now();
console.log('\n[1/3] Reading PSD...');
const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });
console.log(`     Read in ${((Date.now()-t0)/1000).toFixed(1)}s`);

console.log('\n[2/3] Patching layers...');
let okCount = 0;
let missCount = 0;
for (const entry of manifest) {
    const layer = findLayerByName(psd.children, entry.name);
    if (!layer || !layer.text) {
        console.log(`     MISS: ${entry.name}`);
        missCount++;
        continue;
    }
    const before = layer.text.transform.slice();
    layer.text.transform = [1, 0, 0, 1, entry.left, entry.top];
    okCount++;
    console.log(`     ${entry.name.slice(0, 55).padEnd(55)} ` +
        `tx ${Math.round(before[4])} -> ${entry.left}, ty ${Math.round(before[5])} -> ${entry.top}`);
}
console.log(`     Patched: ${okCount}, missing: ${missCount}`);

console.log('\n[3/3] Writing PSD with invalidateTextLayers=true...');
const t1 = Date.now();
const out = writePsdBuffer(psd, { invalidateTextLayers: true });
console.log(`     Wrote ${(out.length/1024/1024).toFixed(1)} MB in ${((Date.now()-t1)/1000).toFixed(1)}s`);
fs.writeFileSync(OUTPUT, out);
console.log(`     Saved: ${OUTPUT}`);

console.log(`\nTotal time: ${((Date.now()-t0)/1000).toFixed(1)}s`);
console.log('Done.');
