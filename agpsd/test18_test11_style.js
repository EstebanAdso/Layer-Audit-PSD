// Test 18 (v25): aplicar la MISMA lógica de test11 (que funcionó perfectamente
// para horizontal en 01_Story y TEST_TEXTOS) para texto rotado.
//
// La clave de test11:
//   - bounds reset a (0, 0, bounds.W, bounds.H) — preservando dimensiones LOCALES del descriptor
//   - boxBounds reset a [0, 0, boxBounds.W, boxBounds.H] — preservando dimensiones LOCALES
//   - transform usa scale original [xx, xy, yx, yy] con NEW tx, ty = layer.left, layer.top
//
// Para el caso rotado, la "discordancia" entre bounds (tall: W<H) y boxBounds (wide: W>H)
// del descriptor original ES el indicador de rotación. Si LO PRESERVAMOS, Adobe debería
// detectar la rotación implícita y renderear correctamente — igual que hizo para horizontal.

require('./patch_ag_psd');
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
    const xxOrig = tr[0], xyOrig = tr[1], yxOrig = tr[2], yyOrig = tr[3];

    const shapeType = t.shapeType || 'box';

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
    const W = bR - bL, H = bB - bT;
    const bb_off_L = bbL - bL, bb_off_T = bbT - bT;
    const bb_off_R = bbR - bR, bb_off_B = bbB - bB;

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType}`);

    if (shapeType === 'box') {
        // EXACTAMENTE test11 logic — sin distinguir rotated vs horizontal.
        // Reset bounds y boxBounds preservando sus dimensiones LOCALES.
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
            // Preservar W, H del boxBounds tal cual (sin tocar aspect ratio mismatch con bounds)
            t.boxBounds = [0, 0, Wbx, Hbx];
        }
        // Transform = original con NEW tx, ty para apuntar a target.left, target.top
        t.transform = [xxOrig, xyOrig, yxOrig, yyOrig, entry.left, entry.top];
        console.log(`    test11 logic: bounds=(0,0,${W.toFixed(2)},${H.toFixed(2)}) ` +
            `boxBounds=[0,0,${(t.boxBounds[2]).toFixed(2)},${(t.boxBounds[3]).toFixed(2)}] ` +
            `tx=${entry.left} ty=${entry.top}`);
    } else {
        // POINT TEXT - test11 algorithm
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(W), bottom: ptObj(H)
        };
        t.boundingBox = {
            left: ptObj(bb_off_L), top: ptObj(bb_off_T),
            right: ptObj(W + bb_off_R), bottom: ptObj(H + bb_off_B)
        };
        const tx_corrected = entry.left - xxOrig * bb_off_L;
        const ty_corrected = entry.top  - yyOrig * bb_off_T;
        t.transform = [xxOrig, xyOrig, yxOrig, yyOrig, tx_corrected, ty_corrected];
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
