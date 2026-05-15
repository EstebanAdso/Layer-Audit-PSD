// Test 16 (v20): CW rotation con uniform scale y bounds WIDE.
//
// Original.png muestra: tops de letras apuntan a la DERECHA = 90° CW visual.
// (v19 con orientation=vertical produjo CCW — wrong direction.)
//
// Approach:
//   - orientation = 'horizontal' (rotation va en transform matrix)
//   - transform = [0, s, -s, 0, layer.right, layer.top]
//     - 90° CW: logical X → canvas Y (down), logical Y → canvas X (left)
//   - bounds WIDE (en logical): (0, 0, layer.H/s, layer.W/s)
//     - layer.H/s = bounds.W (mapea a canvas.H después de rotación)
//     - layer.W/s = bounds.H (mapea a canvas.W después de rotación)
//   - s = avg(xx_orig, yy_orig) (preserva glyph size del original)
//   - Sin orientation=vertical → glifos en orientación natural rotada por matrix.

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
    const xxOrig = tr[0], yyOrig = tr[3];
    const shapeType = t.shapeType || 'box';

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const bbL = pt(bb.left), bbT = pt(bb.top), bbR = pt(bb.right), bbB = pt(bb.bottom);
    const W = bR - bL, H = bB - bT;

    let isRotated = false;
    if (shapeType === 'box' && Array.isArray(t.boxBounds)) {
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const aspectBounds = H > 0 ? W / H : 1;
        const aspectBox = (bxB - bxT) > 0 ? (bxR - bxL) / (bxB - bxT) : 1;
        isRotated = (aspectBounds < 0.5) && (aspectBox > 2);
    }

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType} rot=${isRotated}`);

    if (isRotated) {
        const s = (Math.abs(xxOrig) + Math.abs(yyOrig)) / 2;
        const layerW = entry.right - entry.left;
        const layerH = entry.bottom - entry.top;
        // WIDE bounds en logical: W = layer.H/s, H = layer.W/s
        const Wlog = layerH / s;
        const Hlog = layerW / s;

        // orientation='horizontal' — rotation goes in transform matrix
        t.orientation = 'horizontal';
        // v22: [0, -s, s, 0] anchored at bottom-left. Pure rotation that gives
        // tops RIGHT (target original.png), with text flow bottom-to-top.
        t.transform = [0, -s, s, 0, entry.left, entry.bottom];
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boundingBox = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boxBounds = [0, 0, Wlog, Hlog];
        // Reset font scale modifications (no longer needed)
        if (t.style) {
            t.style = Object.assign({}, t.style);
            delete t.style.verticalScale;
            // Keep horizontalScale as original
        }
        console.log(`    v22: s=${s.toFixed(3)} bounds=(0,0,${Wlog.toFixed(2)},${Hlog.toFixed(2)}) ` +
            `transform=[0,-${s.toFixed(3)},${s.toFixed(3)},0,${entry.left},${entry.bottom}]`);
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
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
