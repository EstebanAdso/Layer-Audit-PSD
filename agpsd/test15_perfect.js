// Test 15 (v19): rotated text with FONT METRIC adjustments to make rendered
// dimensions match original layer bounds exactly.
//
// Approach v18 + compensación métrica:
//   - horizontalScale *= layer.H / actual_rendered_H (1.123 para textvertical)
//   - verticalScale = layer.W / actual_rendered_W (0.903 para textvertical)
//
// Como no sabemos actual_rendered_{H,W} en advance (depende del texto), usamos
// los ratios observados en v18 result para este caso. En produccion estos
// ratios podrian computarse del primer pass de prueba o derivar del descriptor
// original.

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

// Empirical compensation ratios (from observing v18 Adobe result vs target):
// Adobe renders 31x685 when bounds project to 28x769. So we compensate font
// metrics to make it render 28x769 exactly.
const H_RATIO = 769 / 685;  // 1.123: increase vertical advance
const W_RATIO = 28 / 31;    // 0.903: decrease column width

// Pass 1: detect rotation and compute max bbT
const rotInfo = [];
for (const entry of manifest) {
    const layer = findLayerByName(psd.children, entry.name);
    if (!layer || !layer.text) continue;
    const t = layer.text;
    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbT = pt(bb.top);
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
console.log(`max bbT_offset: ${maxBbtOffset.toFixed(2)}, H_ratio=${H_RATIO.toFixed(3)}, W_ratio=${W_RATIO.toFixed(3)}\n`);

// Pass 2: apply patch
for (const info of rotInfo) {
    const { entry, layer, isRotated, bbT_offset } = info;
    const t = layer.text;
    const tr = t.transform.slice();
    const xxOrig = tr[0], yyOrig = tr[3];

    const b = t.bounds || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const W = bR - bL, H = bB - bT;

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} rot=${isRotated}`);

    if (isRotated) {
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const Wbx = bxR - bxL, Hbx = bxB - bxT;
        const s = (Math.abs(xxOrig) + Math.abs(yyOrig)) / 2;
        const layerW = entry.right - entry.left;
        const layerH = entry.bottom - entry.top;
        const Wlog = layerW / s;
        const Hlog = layerH / s;
        const sy = layerW / Hbx;
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

        // Adjust font metrics to match layer dims exactly
        const origHScale = t.style.horizontalScale || 1;
        const newHScale = origHScale * H_RATIO;
        const newVScale = W_RATIO;  // verticalScale starts at 1 if not set
        t.style = Object.assign({}, t.style, {
            horizontalScale: newHScale,
            verticalScale: newVScale,
        });
        console.log(`    HScale: ${origHScale.toFixed(4)} -> ${newHScale.toFixed(4)}, VScale: 1 -> ${newVScale.toFixed(4)}`);
        console.log(`    transform=[${s.toFixed(3)},0,0,${s.toFixed(3)},${entry.left},${(entry.top - yCompensation).toFixed(2)}]`);
    } else if ((t.shapeType || 'box') === 'box') {
        const bb = t.boundingBox || {};
        const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
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
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
