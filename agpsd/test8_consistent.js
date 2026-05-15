// Test 8: math CONSISTENTE. Reset bounds a origen + tx,ty calculados para que
// el projection (tx + xx*boundingBox.L, ty + yy*boundingBox.T) = target exacto.
//
// Sin baseline estimate ni hardcoded ratios. Todo viene del descriptor.
//
// Math:
//   bbox.left_projection = tx + xx * boundingBox.Left
//   bbox.top_projection  = ty + yy * boundingBox.Top
// Con bounds reset a (0,0,W,H) y boundingBox shifted a (bb_off_L, bb_off_T, ...):
//   bbox.left = tx + xx * bb_off_L = target.left
//   bbox.top  = ty + yy * bb_off_T = target.top
//   => tx = target.left - xx * bb_off_L
//   => ty = target.top  - yy * bb_off_T
//
// Si Adobe respeta nuestro descriptor: bbox = target exacto.
// Si Adobe resetea bounds a su estilo baseline: caera el behavior actual de NATURAS.

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

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);

    const W = bR - bL, H = bB - bT;
    const bb_off_L = bbL - bL, bb_off_T = bbT - bT;
    const bb_off_R = bbR - bR, bb_off_B = bbB - bB;

    // Reset bounds a origen (0,0,W,H), shift boundingBox same amount
    t.bounds = {
        left: ptObj(0), top: ptObj(0), right: ptObj(W), bottom: ptObj(H)
    };
    t.boundingBox = {
        left: ptObj(bb_off_L), top: ptObj(bb_off_T),
        right: ptObj(W + bb_off_R), bottom: ptObj(H + bb_off_B)
    };

    // Transform: ambos componentes compensados por bb_off (left bearing + top bearing)
    const tx_corrected = entry.left - xx * bb_off_L;
    const ty_corrected = entry.top  - yy * bb_off_T;
    t.transform = [xx, xy, yx, yy, tx_corrected, ty_corrected];

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} ` +
        `W=${W.toFixed(1)} H=${H.toFixed(1)} bbOff=(${bb_off_L.toFixed(2)},${bb_off_T.toFixed(2)}) ` +
        `tx=${tx_corrected.toFixed(2)} ty=${ty_corrected.toFixed(2)}`);
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
