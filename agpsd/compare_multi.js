// Compare layer record bounds across multiple PSDs for given layer names.
require('./patch_ag_psd');
const fs = require('fs');
const path = require('path');
const { readPsd, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const PSDS = process.argv[2].split(',');
const NAMES = process.argv[3].split(',');

function find(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = find(l.children, name); if (f) return f; }
    }
    return null;
}

const data = {};
for (const p of PSDS) {
    const psd = readPsd(fs.readFileSync(p), { useImageData: false });
    data[path.basename(p)] = psd;
}

for (const name of NAMES) {
    console.log(`\n=== ${name} ===`);
    console.log('PSD'.padEnd(40) + '  bbox'.padEnd(28) + 'W x H');
    for (const fname of Object.keys(data)) {
        const l = find(data[fname].children, name);
        if (!l) { console.log(`  ${fname.padEnd(38)}  NOT FOUND`); continue; }
        const W = l.right - l.left, H = l.bottom - l.top;
        const bbox = `(${l.left},${l.top})-(${l.right},${l.bottom})`;
        console.log(`  ${fname.padEnd(38)}  ${bbox.padEnd(26)}  ${W}x${H}`);
    }
}
