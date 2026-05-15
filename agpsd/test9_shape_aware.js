// Test 9: SHAPE-AWARE fix. Detecta point text vs paragraph (box) text y aplica
// algoritmo apropiado para cada uno.
//
// POINT TEXT (NATURAS): Adobe resetea bounds a 0, usa transform como anchor.
//   -> Reset bounds, set tx = target - xx*bb_off_L, ty = target - yy*bb_off_T.
//
// PARAGRAPH TEXT (01_Story shapeType="box"): Adobe tiene BUG de doble offset:
//   Adobe output: tx_out = tx_in + bounds.L_out, bounds.L_out = bounds.L_in
//   Final projection = tx_in + 2*bounds.L_in
//   -> Para projection = target: input_tx = target - 2*bounds.L
//   -> KEEP bounds (no reset), set transform negative pre-compensation.

const fs = require('fs');
const path = require('path');
const { readPsd, writePsdBuffer, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const argv = process.argv.slice(2);
const INPUT = path.resolve(argv[0]);
const MANIFEST = path.resolve(argv[1]);
const OUTPUT = path.resolve(argv[2]);

function findLayerByName(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = findLayerByName(l.children, name); if (f) return f; }
    }
    return null;
}
function pt(o) { return o == null ? 0 : (typeof o === 'object' && 'value' in o) ? Number(o.value) : Number(o); }
function ptObj(v) { return { value: v, units: 'Points' }; }

const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
console.log(`Input: ${INPUT}\nManifest: ${manifest.length} layers\n`);

const t0 = Date.now();
const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });

for (const entry of manifest) {
    const layer = findLayerByName(psd.children, entry.name);
    if (!layer || !layer.text) { console.log(`MISS: ${entry.name}`); continue; }
    const t = layer.text;
    const tr = t.transform.slice();
    const xx = tr[0], xy = tr[1], yx = tr[2], yy = tr[3];

    const shapeType = t.shapeType || 'point';
    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType}`);

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);

    if (shapeType === 'box') {
        // PARAGRAPH TEXT — pre-compensar el doble offset de Adobe
        // KEEP bounds (no resetear), aplicar tx = target - 2*bounds.L
        const tx_corrected = entry.left - 2 * xx * bL;
        const ty_corrected = entry.top  - 2 * yy * bT;
        t.transform = [xx, xy, yx, yy, tx_corrected, ty_corrected];
        console.log(`    PARAGRAPH: bL=${bL.toFixed(1)} bT=${bT.toFixed(1)} ` +
            `-> tx=${tx_corrected.toFixed(1)} ty=${ty_corrected.toFixed(1)} ` +
            `(pre-comp doble offset)`);
    } else {
        // POINT TEXT — reset bounds y compensar bb_off
        const W = bR - bL, H = bB - bT;
        const bb_off_L = bbL - bL, bb_off_T = bbT - bT;
        const bb_off_R = bbR - bR, bb_off_B = bbB - bB;
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(W), bottom: ptObj(H)
        };
        t.boundingBox = {
            left: ptObj(bb_off_L), top: ptObj(bb_off_T),
            right: ptObj(W + bb_off_R), bottom: ptObj(H + bb_off_B)
        };
        const tx_corrected = entry.left - xx * bb_off_L;
        const ty_corrected = entry.top  - yy * bb_off_T;
        t.transform = [xx, xy, yx, yy, tx_corrected, ty_corrected];
        console.log(`    POINT: bbOff=(${bb_off_L.toFixed(2)},${bb_off_T.toFixed(2)}) ` +
            `-> tx=${tx_corrected.toFixed(2)} ty=${ty_corrected.toFixed(2)}`);
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
