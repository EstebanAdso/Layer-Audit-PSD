// Dump full descriptor for TEXT_VIGENCIA in 01_Story to understand offsets
const fs = require('fs');
const path = require('path');
const { readPsd, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const INPUT = path.resolve(process.argv[2] || '../01_Story.psd');
const TARGET = process.argv[3] || 'TEXT_VIGENCIA_01_Story';

function find(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = find(l.children, name); if (f) return f; }
    }
    return null;
}
function pt(o) { return o == null ? 0 : (typeof o === 'object' && 'value' in o) ? Number(o.value) : Number(o); }

const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });
const layer = find(psd.children, TARGET);
if (!layer) { console.log('not found'); process.exit(1); }

console.log(`Input: ${INPUT}`);
console.log(`Layer: ${layer.name}`);
console.log(`\nLayer record bounds:`);
console.log(`  left=${layer.left} top=${layer.top} right=${layer.right} bottom=${layer.bottom}`);
console.log(`  W=${layer.right - layer.left} H=${layer.bottom - layer.top}`);

const t = layer.text;
console.log(`\ntext.shapeType: ${t.shapeType}`);
console.log(`text.transform: [${t.transform.join(', ')}]`);
const xx = t.transform[0], yy = t.transform[3], tx = t.transform[4], ty = t.transform[5];

const b = t.bounds || {}, bb = t.boundingBox || {};
const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);

console.log(`\ntext.bounds:`);
console.log(`  L=${bL} T=${bT} R=${bR} B=${bB}  W=${bR-bL} H=${bB-bT}`);
console.log(`\ntext.boundingBox:`);
console.log(`  L=${bbL} T=${bbT} R=${bbR} B=${bbB}  W=${bbR-bbL} H=${bbB-bbT}`);

console.log(`\nDelta boundingBox - bounds:`);
console.log(`  dL=${bbL - bL}  dT=${bbT - bT}  dR=${bbR - bR}  dB=${bbB - bB}`);

console.log(`\n=== Projection scenarios for paragraph text ===`);
console.log(`If Adobe formula = tx + xx*bL              -> ${(tx + xx*bL).toFixed(2)}`);
console.log(`If Adobe formula = tx + xx*bbL             -> ${(tx + xx*bbL).toFixed(2)}`);
console.log(`If Adobe formula = tx + xx*(bL+bbL)        -> ${(tx + xx*(bL + bbL)).toFixed(2)}`);
console.log(`If Adobe formula = tx + xx*2*bL            -> ${(tx + xx*2*bL).toFixed(2)}`);
console.log(`If Adobe formula = tx + xx*(2*bL + dL)     -> ${(tx + xx*(2*bL + (bbL-bL))).toFixed(2)}`);
console.log(`If Adobe formula = tx + xx*(bL + bbL)*2/2  -> ${(tx + xx*(bL + bbL)).toFixed(2)}`);

console.log(`\nIf observed final.left = 8 with our v9 tx, what offset did Adobe add?`);
console.log(`(test9 used tx = -15331 for this layer if bL=7681)`);
const v9_tx = 31 - 2*xx*bL;
console.log(`  v9 tx would have been: ${v9_tx}`);
console.log(`  Observed: 8 -> Adobe added 8 - ${v9_tx} = ${8 - v9_tx}`);
console.log(`  2*bL = ${2*bL}, bL+bbL = ${bL+bbL}`);

const v9_ty = 1857 - 2*yy*bT;
console.log(`  v9 ty would have been: ${v9_ty}`);
console.log(`  Observed: 1745 -> Adobe added 1745 - ${v9_ty} = ${1745 - v9_ty}`);
console.log(`  2*bT = ${2*bT}, bT+bbT = ${bT+bbT}`);
