// Test 10: SHAPE-AWARE v2. Para PARAGRAPH (box), en lugar de pre-compensar el
// doble offset (v9), RESETEAMOS el descriptor a coords locales pequeñas
// alineadas con el LAYER RECORD bounds, que ya esta intacto en el PSD.
//
// El layer record (layer.left/top/right/bottom) NO esta corrupto — solo el
// text descriptor lo esta. Si rehacemos descriptor.bounds y descriptor.transform
// para que sean internamente consistentes con el layer record, Adobe rendereara
// en la posicion correcta.
//
// Math:
//   Para "limpiar" el descriptor:
//     new bounds   = (0, 0, layer.W, layer.H)
//     new bbox     = (bb_off_L, bb_off_T, bb_off_L + bbW_orig, bb_off_T + bbH_orig)
//     new tx, ty   = (layer.left, layer.top)   <- target en canvas
//
//   Asi el descriptor cumple: tx + bounds.L = layer.left (proyeccion consistente)
//   y Adobe puede rerenderear sin re-aplicar el offset corrupto.
//
// POINT TEXT (NATURAS) sigue igual que v9 (ya funciona).

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

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
    const W = bR - bL, H = bB - bT;
    const bb_off_L = bbL - bL, bb_off_T = bbT - bT;
    const bb_off_R = bbR - bR, bb_off_B = bbB - bB;

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType}`);

    if (shapeType === 'box') {
        // PARAGRAPH TEXT — clean descriptor: bounds en local (0,0,W,H),
        // tx/ty en canvas absoluto (target.left, target.top).
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(W), bottom: ptObj(H)
        };
        t.boundingBox = {
            left: ptObj(bb_off_L), top: ptObj(bb_off_T),
            right: ptObj(W + bb_off_R), bottom: ptObj(H + bb_off_B)
        };
        t.transform = [xx, xy, yx, yy, entry.left, entry.top];
        console.log(`    PARAGRAPH: bounds reset to (0,0,${W.toFixed(1)},${H.toFixed(1)}) ` +
            `tx=${entry.left} ty=${entry.top}`);
    } else {
        // POINT TEXT — como v9 (NATURAS funciona)
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
            `tx=${tx_corrected.toFixed(2)} ty=${ty_corrected.toFixed(2)}`);
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
