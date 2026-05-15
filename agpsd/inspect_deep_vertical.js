// Deep inspection: dump ALL fields of layer.text to find where Adobe keeps the
// hidden bL/bT copy. We need to find any field with values ~7681 or ~9087.
const fs = require('fs');
const path = require('path');
const { readPsd, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const INPUT = path.resolve(process.argv[2] || '../01_Story_v10.psd');
const TARGET = process.argv[3] || 'TEXT_VIGENCIA_01_Story';

function find(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = find(l.children, name); if (f) return f; }
    }
    return null;
}

const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });
const layer = find(psd.children, TARGET);
const t = layer.text;

console.log(`Looking for values close to 7681 or 9087 anywhere in layer.text...\n`);
function walk(obj, pathStr) {
    if (obj == null) return;
    if (typeof obj === 'number') {
        if ((obj > 7600 && obj < 7800) || (obj > 9000 && obj < 9200) ||
            (obj > 8200 && obj < 8500) || (obj > 9000 && obj < 9200)) {
            console.log(`  HIT: ${pathStr} = ${obj}`);
        }
        return;
    }
    if (typeof obj === 'object') {
        if (Array.isArray(obj)) {
            obj.forEach((v, i) => walk(v, `${pathStr}[${i}]`));
        } else {
            for (const k of Object.keys(obj)) {
                walk(obj[k], pathStr ? `${pathStr}.${k}` : k);
            }
        }
    }
}
walk(t, '');

console.log(`\n--- All top-level keys in layer.text ---`);
console.log(Object.keys(t).join(', '));

console.log(`\n--- Full JSON dump (truncated values) ---`);
function summarize(obj, depth) {
    if (depth > 4) return '...';
    if (obj == null) return obj;
    if (typeof obj !== 'object') {
        if (typeof obj === 'string' && obj.length > 100) return obj.slice(0, 100) + '...';
        return obj;
    }
    if (Array.isArray(obj)) {
        if (obj.length > 5) return `[${obj.length} items]`;
        return obj.map(v => summarize(v, depth + 1));
    }
    const out = {};
    for (const k of Object.keys(obj)) {
        out[k] = summarize(obj[k], depth + 1);
    }
    return out;
}
console.log(JSON.stringify(summarize(t, 0), null, 2));
