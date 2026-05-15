// Test 7: ademas de tx/ty, resetea bounds y boundingBox del descriptor a coords
// LOCALES con origen en (0,0). Asi:
//   - Sin importar lo que Adobe haga (resetear bounds o no), el proyectado
//     bbox = tx + xx*0 = tx queda en posicion correcta.
//   - Preserva el offset bounds-vs-boundingBox del original (left bearing).
//
// Caso NATURAS: Adobe ya reseteaba bounds, no afectaba.
// Caso 01_Story: Adobe NO reseteaba, mantenia bounds grandes -> bbox off-canvas.
//                Con esta correccion, bounds=0 garantiza posicionamiento correcto.

const fs = require('fs');
const path = require('path');
const { readPsd, writePsdBuffer, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const argv = process.argv.slice(2);
const INPUT = path.resolve(argv[0] || '../NATURAS_MUEBLES_EXHIBIDORES.psd');
const MANIFEST = path.resolve(argv[1] || './manifest.json');
const OUTPUT = path.resolve(argv[2] || '../NATURAS_v7.psd');

function findLayerByName(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = findLayerByName(l.children, name); if (f) return f; }
    }
    return null;
}

function pt(o) {
    if (o == null) return 0;
    if (typeof o === 'number') return o;
    if (typeof o === 'object' && 'value' in o) return Number(o.value);
    return Number(o);
}
function ptObj(v) {
    return { value: v, units: 'Points' };
}

const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
console.log(`Manifest: ${manifest.length} layers`);

const t0 = Date.now();
console.log('Reading PSD...');
const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });

console.log('\nPatching layers (reset bounds + tx/ty with leftBearing)...');
for (const entry of manifest) {
    const layer = findLayerByName(psd.children, entry.name);
    if (!layer || !layer.text) { console.log(`MISS: ${entry.name}`); continue; }
    const t = layer.text;
    const tr = t.transform.slice();
    const xx = tr[0], xy = tr[1], yx = tr[2], yy = tr[3];

    const b = t.bounds || {};
    const bb = t.boundingBox || {};
    const bL = pt(b.left),  bT = pt(b.top),  bR = pt(b.right),  bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);

    // Width/height del bounds local original
    const W = bR - bL;
    const H = bB - bT;

    // Offsets relativos boundingBox-vs-bounds (left bearing, ascent, etc)
    const bb_off_L = bbL - bL;
    const bb_off_T = bbT - bT;
    const bb_off_R = bbR - bR;
    const bb_off_B = bbB - bB;

    // Reset bounds a (0, 0, W, H)
    t.bounds = {
        left:   ptObj(0),
        top:    ptObj(0),
        right:  ptObj(W),
        bottom: ptObj(H)
    };
    // Shift boundingBox por -bL, -bT (mismo shift que aplicamos a bounds)
    t.boundingBox = {
        left:   ptObj(bb_off_L),
        top:    ptObj(bb_off_T),
        right:  ptObj(W + bb_off_R),
        bottom: ptObj(H + bb_off_B)
    };

    // Compute tx para que bbox.left = target.left con bounds.Left ahora en 0
    // Y compensar el left bearing (boundingBox.Left tras shift)
    const tx_corrected = entry.left - xx * bb_off_L;

    // Compute ty con baseline estimate
    const height = (entry.bottom !== undefined && entry.top !== undefined)
        ? (entry.bottom - entry.top) : 0;
    const ASCENT_RATIO = 0.975;
    const baseline_y = entry.top + Math.round(height * ASCENT_RATIO);
    const ty_corrected = baseline_y;

    t.transform = [xx, xy, yx, yy, tx_corrected, ty_corrected];

    console.log(`  ${entry.name.slice(0,50).padEnd(50)} W=${W.toFixed(1)} H=${H.toFixed(1)} ` +
        `bbOff=(${bb_off_L.toFixed(2)},${bb_off_T.toFixed(2)}) ` +
        `tx=${tx_corrected.toFixed(1)} ty=${ty_corrected}`);
}

console.log('\nWriting...');
const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`Saved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
