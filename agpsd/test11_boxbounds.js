// Test 11: SHAPE-AWARE v3 — incluye reset de `boxBounds` (campo oculto que ag-psd
// expone como array). Adobe usa `boxBounds` (no `bounds`/`boundingBox`) para
// posicionar paragraph text. La formula es:
//   final = tx + 2 * boxBounds[0]
//
// Reset descriptor a coords locales:
//   bounds      = (0, 0, W, H)
//   boundingBox = (bb_off_L, bb_off_T, bb_off_L + bbW, bb_off_T + bbH)
//   boxBounds   = [0, 0, W_box, H_box]
//   transform   = (xx, xy, yx, yy, target.left, target.top)
//
// Predicted Adobe output:
//   x = tx + 2*0 = tx = target.left ✓
//   y = ty + 2*0 = ty = target.top ✓

const fs = require('fs');
const path = require('path');
require('./patch_ag_psd'); // CMYK support + TransformPoints preservation
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

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
    const W = bR - bL, H = bB - bT;
    const bb_off_L = bbL - bL, bb_off_T = bbT - bT;
    const bb_off_R = bbR - bR, bb_off_B = bbB - bB;

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType}`);

    if (shapeType === 'box') {
        // PARAGRAPH — reset bounds, boundingBox Y boxBounds, tx/ty = target canvas
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(W), bottom: ptObj(H)
        };
        t.boundingBox = {
            left: ptObj(bb_off_L), top: ptObj(bb_off_T),
            right: ptObj(W + bb_off_R), bottom: ptObj(H + bb_off_B)
        };
        if (Array.isArray(t.boxBounds) && t.boxBounds.length === 4) {
            const [bxL, bxT, bxR, bxB] = t.boxBounds;
            const Wbx = bxR - bxL, Hbx = bxB - bxT;
            t.boxBounds = [0, 0, Wbx, Hbx];
            console.log(`    boxBounds: [${bxL.toFixed(1)},${bxT.toFixed(1)},${bxR.toFixed(1)},${bxB.toFixed(1)}] -> [0,0,${Wbx.toFixed(1)},${Hbx.toFixed(1)}]`);
        }
        t.transform = [xx, xy, yx, yy, entry.left, entry.top];
        console.log(`    PARAGRAPH: tx=${entry.left} ty=${entry.top}`);
    } else {
        // POINT TEXT (NATURAS) — v9 working algorithm
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
        console.log(`    POINT: bbOff=(${bb_off_L.toFixed(2)},${bb_off_T.toFixed(2)}) tx=${tx_corrected.toFixed(2)} ty=${ty_corrected.toFixed(2)}`);
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
