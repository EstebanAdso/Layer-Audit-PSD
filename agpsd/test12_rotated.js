// Test 12: SHAPE-AWARE v4 — detecta texto rotado por aspect ratio mismatch entre
// bounds (post-rotation) y boxBounds (logical text frame). Cuando bounds.H > bounds.W
// pero boxBounds.W > boxBounds.H significa rotación 90° del frame logico.
//
// El descriptor original NO tiene rotation en transform (es scale puro) ni en
// TransformPoints (identidad). La rotacion debe estar baked en raster, en un
// chunk no expuesto, o implicita en la relacion bounds<->boxBounds.
//
// Estrategia: si detectamos rotacion 90° CW (caso comun para texto vertical),
// reconstruimos el transform matrix con rotacion baked:
//   xx=0, xy=sx, yx=-sy, yy=0
//   donde sx = layer.H / boxBounds.W, sy = layer.W / boxBounds.H
//   tx = layer.right, ty = layer.top
//
// Si Adobe respeta el transform matrix con rotacion, esto deberia preservar la
// rotacion. Si Adobe no lo respeta para texto, no hay manera de fixearlo via
// API (limite fundamental).

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

    const shapeType = t.shapeType || 'point';

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
    const W = bR - bL, H = bB - bT;
    const bb_off_L = bbL - bL, bb_off_T = bbT - bT;
    const bb_off_R = bbR - bR, bb_off_B = bbB - bB;

    // Detectar rotacion 90°: bounds tall (H>>W) pero boxBounds wide (W>>H)
    let isRotated = false;
    if (shapeType === 'box' && Array.isArray(t.boxBounds)) {
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const Wbx = bxR - bxL, Hbx = bxB - bxT;
        const aspectBounds = H > 0 ? W / H : 1;
        const aspectBox = Hbx > 0 ? Wbx / Hbx : 1;
        // bounds tall (aspectBounds < 0.5) AND box wide (aspectBox > 2)
        isRotated = (aspectBounds < 0.5) && (aspectBox > 2);
    }

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType} rot=${isRotated}`);

    if (isRotated) {
        // ROTATED PARAGRAPH — bake 90° CCW rotation into transform matrix
        // SCALE UNIFORME = original scale (preserva tamaño de glifos del PSD original).
        // NORMALIZAR boundingBox para eliminar offset per-layer del PSD original
        // (en el original ese offset controlaba el Y rotado; con nuestra rotation
        // explicita en transform, el offset estorba).
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const Wbx = bxR - bxL, Hbx = bxB - bxT;
        const s = (Math.abs(xxOrig) + Math.abs(yyOrig)) / 2;
        const tx = entry.left;
        const ty = entry.bottom;
        t.transform = [0, -s, s, 0, tx, ty];

        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wbx), bottom: ptObj(Hbx)
        };
        // boundingBox NORMALIZADO: igual para todos los layers (sin offset per-layer)
        t.boundingBox = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wbx), bottom: ptObj(Hbx)
        };
        t.boxBounds = [0, 0, Wbx, Hbx];
        console.log(`    ROTATED 90°CCW uniform: s=${s.toFixed(3)} ` +
            `transform=[0,-${s.toFixed(3)},${s.toFixed(3)},0,${tx},${ty}] bbox normalized`);
    } else if (shapeType === 'box') {
        // PARAGRAPH normal (horizontal)
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
        }
        t.transform = [xxOrig, xyOrig, yxOrig, yyOrig, entry.left, entry.top];
        console.log(`    PARAGRAPH: tx=${entry.left} ty=${entry.top}`);
    } else {
        // POINT TEXT
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
        console.log(`    POINT: tx=${tx_corrected.toFixed(2)} ty=${ty_corrected.toFixed(2)}`);
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
