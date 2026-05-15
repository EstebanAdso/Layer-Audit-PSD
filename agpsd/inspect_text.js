// Dump full structure of layer.text in ag-psd to see if bounds/boundingBox accessible
const fs = require('fs');
const path = require('path');
const { readPsd, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const INPUT = path.resolve('../NATURAS_MUEBLES_EXHIBIDORES.psd');

function findLayerByName(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = findLayerByName(l.children, name); if (f) return f; }
    }
    return null;
}

const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });
const layer = findLayerByName(psd.children, 'TEXT_ATRIBUTO1_MUEBLES_EXHIBIDORDEPISOPALI_50CMX140CM');
if (!layer) { console.log('not found'); process.exit(1); }

console.log('layer keys:', Object.keys(layer));
console.log('layer.text keys:', Object.keys(layer.text));
for (const k of Object.keys(layer.text)) {
    const v = layer.text[k];
    if (typeof v === 'object' && v !== null) {
        if (Array.isArray(v)) {
            console.log(`  ${k}: array length=${v.length}`);
            if (v.length > 0 && typeof v[0] === 'object') {
                console.log(`    [0] keys:`, Object.keys(v[0]));
            } else if (v.length > 0) {
                console.log(`    sample:`, v.slice(0, 6));
            }
        } else {
            console.log(`  ${k}: object keys=${JSON.stringify(Object.keys(v))}`);
            if (k === 'bounds' || k === 'boundingBox') {
                console.log(`    ${k} value:`, v);
            }
        }
    } else {
        console.log(`  ${k}:`, JSON.stringify(v).slice(0, 80));
    }
}
