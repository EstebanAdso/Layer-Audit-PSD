// Test 14 (v18): rotated text via orientation=vertical, with per-layer Y
// pre-compensation for Adobe's "free space redistribution" behavior.
//
// Adobe respeta orientation=vertical y bounds, pero distribuye el espacio vacío
// (bounds.H - rendered_text_H) según la posición Y del layer en canvas:
//   - Layer más abajo → free space al bottom (texto top-aligned)
//   - Layer más arriba → free space al top (texto bottom-aligned)
//   - Medios → centered
//
// La magnitud del shift sigue: shift = sy * (max_bbT - this_bbT)
//   donde sy = layer.W / boxBounds.H y bbT_offset = bbT_orig - bT_orig
//
// Para compensar, ajustamos ty per-layer:
//   ty = layer.top - sy * (max_bbT - this_bbT)

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

// Primera pasada: detectar rotated y calcular max_bbT_offset entre todos
const rotInfo = [];
for (const entry of manifest) {
    const layer = findLayerByName(psd.children, entry.name);
    if (!layer || !layer.text) continue;
    const t = layer.text;
    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
    const W = bR - bL, H = bB - bT;
    let isRotated = false;
    if ((t.shapeType || 'box') === 'box' && Array.isArray(t.boxBounds)) {
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const aspectBounds = H > 0 ? W / H : 1;
        const aspectBox = (bxB - bxT) > 0 ? (bxR - bxL) / (bxB - bxT) : 1;
        isRotated = (aspectBounds < 0.5) && (aspectBox > 2);
    }
    rotInfo.push({ entry, layer, isRotated, bbT_offset: bbT - bT });
}
const maxBbtOffset = Math.max(...rotInfo.filter(r => r.isRotated).map(r => r.bbT_offset), 0);
console.log(`max bbT_offset across rotated layers: ${maxBbtOffset.toFixed(2)}\n`);

// Segunda pasada: aplicar patch
for (const info of rotInfo) {
    const { entry, layer, isRotated, bbT_offset } = info;
    const t = layer.text;
    const tr = t.transform.slice();
    const xxOrig = tr[0], yyOrig = tr[3];
    const shapeType = t.shapeType || 'box';

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
    const W = bR - bL, H = bB - bT;

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType} rot=${isRotated}`);

    if (isRotated) {
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const Wbx = bxR - bxL, Hbx = bxB - bxT;
        const s = (Math.abs(xxOrig) + Math.abs(yyOrig)) / 2;
        const layerW = entry.right - entry.left;
        const layerH = entry.bottom - entry.top;
        const Wlog = layerW / s;
        const Hlog = layerH / s;
        // Per-layer sy = layer.W / boxBounds.H — controls horizontal scale of rotated chars
        const sy = layerW / Hbx;
        // Compensation: Adobe shifts the text down by sy * (max_bbT - this_bbT)
        const yCompensation = sy * (maxBbtOffset - bbT_offset);
        t.orientation = 'vertical';
        t.transform = [s, 0, 0, s, entry.left, entry.top - yCompensation];
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boundingBox = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boxBounds = [0, 0, Wlog, Hlog];
        console.log(`    VERTICAL: s=${s.toFixed(3)} bbT_off=${bbT_offset.toFixed(2)} yComp=${yCompensation.toFixed(2)} ` +
            `tx=${entry.left} ty=${(entry.top - yCompensation).toFixed(2)}`);
    } else if (shapeType === 'box') {
        const bb_off_L = bbL - bL, bb_off_T = bbT - bT;
        const bb_off_R = bbR - bR, bb_off_B = bbB - bB;
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(W), bottom: ptObj(H)
        };
        t.boundingBox = {
            left: ptObj(bb_off_L), top: ptObj(bb_off_T),
            right: ptObj(W + bb_off_R), bottom: ptObj(H + bb_off_B)
        };
        if (Array.isArray(t.boxBounds) && t.boxBounds.length === 4) {
            const [bxL, bxT, bxR, bxB] = t.boxBounds;
            t.boxBounds = [0, 0, bxR - bxL, bxB - bxT];
        }
        t.transform = [xxOrig, tr[1], tr[2], yyOrig, entry.left, entry.top];
        console.log(`    PARAGRAPH: tx=${entry.left} ty=${entry.top}`);
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
