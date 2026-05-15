// Test 17 (v23): combina v22 (rotación correcta CW con anchor bottom-left)
// con font metric stretching de v19 para que texto llene la columna exacta.
//
// Approach:
//   - transform = [0, -s, s, 0, layer.left, layer.bottom]
//   - bounds = (0, 0, 220, 7.28)  (slightly bigger to fit stretched text)
//   - horizontalScale *= 1.123 (stretch text length 12%)
//   - per-layer ty compensation (in case Adobe still redistributes)
//
// Resultado esperado:
//   - Tops apuntando a la derecha (CW visual)
//   - Text reading bottom-to-top
//   - Bounds match exacto con layer record (28×769)
//   - Texto llena toda la columna

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

// Empirical (v24): from v23 result, derive factors:
const H_STRETCH = 769 / 686;       // 1.121 - HScale factor para fit columna
const W_RATIO = 28 / 27;            // 1.037 - VScale para fix column width
const COMP_FACTOR = 1.9;            // empirical: con HScale stretched, Adobe usa factor 1.9

// Pass 1: detect rotation, compute max bbT
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
console.log(`max bbT_offset: ${maxBbtOffset.toFixed(2)}, H_stretch=${H_STRETCH.toFixed(3)}\n`);

for (const info of rotInfo) {
    const { entry, layer, isRotated, bbT_offset } = info;
    const t = layer.text;
    const tr = t.transform.slice();
    const xxOrig = tr[0], yyOrig = tr[3];

    const b = t.bounds || {}, bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top), bR = pt(b.right), bB = pt(b.bottom);
    const W = bR - bL, H = bB - bT;

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} rot=${isRotated}`);

    if (isRotated) {
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const Wbx = bxR - bxL, Hbx = bxB - bxT;
        const s = (Math.abs(xxOrig) + Math.abs(yyOrig)) / 2;
        const layerW = entry.right - entry.left;
        const layerH = entry.bottom - entry.top;
        // Bounds en logical wide. Aumentar W para fit text estirado.
        const Wlog = (layerH / s) * 1.15;  // 15% safety margin para text estirado
        const Hlog = layerW / s;

        // Per-layer Y compensation usando factor empírico 1.9 (no sy).
        // Cuando HScale stretched para llenar columna, Adobe usa factor 1.9.
        const yCompensation = COMP_FACTOR * (maxBbtOffset - bbT_offset);

        t.orientation = 'horizontal';
        t.transform = [0, -s, s, 0, entry.left, entry.bottom + yCompensation];

        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boundingBox = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boxBounds = [0, 0, Wlog, Hlog];

        // Stretch font para llenar columna; VScale para column width
        const origHScale = t.style.horizontalScale || 1;
        const newHScale = origHScale * H_STRETCH;
        t.style = Object.assign({}, t.style, {
            horizontalScale: newHScale,
            verticalScale: W_RATIO,
        });

        console.log(`    v24: s=${s.toFixed(3)} bounds=(0,0,${Wlog.toFixed(1)},${Hlog.toFixed(2)}) ` +
            `yComp=${yCompensation.toFixed(2)} ty=${(entry.bottom + yCompensation).toFixed(2)} ` +
            `HScale=${newHScale.toFixed(3)} VScale=${W_RATIO.toFixed(3)}`);
    } else if ((t.shapeType || 'box') === 'box') {
        // Horizontal paragraph - test11 algorithm
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
