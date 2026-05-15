// Test 13 (v17): usar orientation='vertical' en lugar de rotation matrix.
// PSD soporta texto vertical nativo (CJK-style) via WritingDirection=2 y
// Procession=1 en engineData. Adobe debería renderizar el texto en columna
// vertical sin necesidad de rotar la transform matrix.
//
// Caso ROTATED: orientation='vertical' + transform scale (no rotation) +
//   bounds en dimensiones LOGICAS rotadas (W=layer.W/s, H=layer.H/s).

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
    const W = bR - bL, H = bB - bT;

    // Detect rotated
    let isRotated = false;
    if (shapeType === 'box' && Array.isArray(t.boxBounds)) {
        const [bxL, bxT, bxR, bxB] = t.boxBounds;
        const Wbx = bxR - bxL, Hbx = bxB - bxT;
        const aspectBounds = H > 0 ? W / H : 1;
        const aspectBox = Hbx > 0 ? Wbx / Hbx : 1;
        isRotated = (aspectBounds < 0.5) && (aspectBox > 2);
    }

    console.log(`  ${entry.name.slice(0,55).padEnd(55)} shape=${shapeType} rot=${isRotated}`);

    if (isRotated) {
        // VERTICAL ORIENTATION — usar WritingDirection=2 via orientation
        const s = (Math.abs(xxOrig) + Math.abs(yyOrig)) / 2;
        const layerW = entry.right - entry.left;
        const layerH = entry.bottom - entry.top;
        // En coords lógicas (antes del scale):
        // - Column width = layer.W / s (espacio para cada caracter rotado)
        // - Column height = layer.H / s (largo del texto vertical)
        const Wlog = layerW / s;
        const Hlog = layerH / s;

        t.orientation = 'vertical';
        t.transform = [s, 0, 0, s, entry.left, entry.top];
        t.bounds = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boundingBox = {
            left: ptObj(0), top: ptObj(0), right: ptObj(Wlog), bottom: ptObj(Hlog)
        };
        t.boxBounds = [0, 0, Wlog, Hlog];
        console.log(`    VERTICAL: s=${s.toFixed(3)} bounds=(0,0,${Wlog.toFixed(2)},${Hlog.toFixed(2)}) ` +
            `tx=${entry.left} ty=${entry.top}`);
    } else if (shapeType === 'box') {
        // PARAGRAPH horizontal — algoritmo de test11/test12
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
        console.log(`    PARAGRAPH: tx=${entry.left} ty=${entry.top}`);
    }
}

const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`\nSaved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
