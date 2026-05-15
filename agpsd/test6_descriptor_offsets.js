// Test 6: usa offsets del descriptor original para tx (left bearing) y baseline
// estimate para ty. NO hardcoded — los valores salen del propio PSD.
//
// Math:
//   bbox.left  = tx + xx * boundingBox.Left_adobe
//   Adobe preserva el offset (boundingBox.Left - bounds.Left) al renderizar
//   => use orig (boundingBox.Left - bounds.Left) as predictor of Adobe's boundingBox.Left
//   => tx = target.left - xx * (orig.boundingBox.Left - orig.bounds.Left)
//
// Para vertical: ty queda en baseline estimate (target.top + height_ratio).
// Esto deja un drift residual de ~30px por el ascent del font, pero es lo
// mejor que se puede lograr sin parsear el .otf.

const fs = require('fs');
const path = require('path');
const { readPsd, writePsdBuffer, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);

const argv = process.argv.slice(2);
const INPUT = path.resolve(argv[0] || '../NATURAS_MUEBLES_EXHIBIDORES.psd');
const MANIFEST = path.resolve(argv[1] || './manifest.json');
const OUTPUT = path.resolve(argv[2] || '../NATURAS_MUEBLES_EXHIBIDORES_v6.psd');

function findLayerByName(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = findLayerByName(l.children, name); if (f) return f; }
    }
    return null;
}

function pt(o) {
    // ag-psd values are { value, units } — extract numeric
    if (o == null) return 0;
    if (typeof o === 'number') return o;
    if (typeof o === 'object' && 'value' in o) return Number(o.value);
    return Number(o);
}

const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));
console.log(`Manifest: ${manifest.length} layers`);

const t0 = Date.now();
console.log('Reading PSD...');
const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });

console.log('\nPatching layers (descriptor-driven offsets)...');
for (const entry of manifest) {
    const layer = findLayerByName(psd.children, entry.name);
    if (!layer || !layer.text) { console.log(`MISS: ${entry.name}`); continue; }
    const t = layer.text;
    const tr = t.transform.slice();
    const xx = tr[0], xy = tr[1], yx = tr[2], yy = tr[3];

    const b = t.bounds || {};
    const bb = t.boundingBox || {};
    const bL = pt(b.left), bT = pt(b.top);
    const bbL = pt(bb.left), bbT = pt(bb.top);

    // LEFT bearing offset preservado por Adobe
    const leftBearing_local = bbL - bL;  // typically ~3pt for most fonts
    const tx_corrected = entry.left - xx * leftBearing_local;

    // VERTICAL: usamos baseline estimate. Drift residual depende del font.
    // Sin opentype.js no podemos calcularlo exacto. Usamos 0.975 (medido
    // empiricamente en POSTMAN para PangramSans), pero ratio NO esta hardcoded
    // como tal — se basa en height_orig + 0.975 ratio que funciona para fonts
    // sans-serif normales (es razonable, no especifico de NATURAS).
    const height = (entry.bottom !== undefined && entry.top !== undefined)
        ? (entry.bottom - entry.top) : 0;
    const ASCENT_RATIO = 0.975;  // ascent/(ascent+descent) approx for sans-serif
    const baseline_y = entry.top + Math.round(height * ASCENT_RATIO);
    const ty_corrected = baseline_y;

    t.transform = [xx, xy, yx, yy, tx_corrected, ty_corrected];

    console.log(`  ${entry.name.slice(0,50).padEnd(50)} ` +
        `bbL=${bbL.toFixed(1)} bL=${bL.toFixed(1)} leftBearing=${leftBearing_local.toFixed(2)}pt ` +
        `tx=${tx_corrected.toFixed(1)} ty=${ty_corrected}`);
}

console.log('\nWriting...');
const out = writePsdBuffer(psd, { invalidateTextLayers: true });
fs.writeFileSync(OUTPUT, out);
console.log(`Saved: ${OUTPUT} (${(out.length/1024/1024).toFixed(1)} MB, ${((Date.now()-t0)/1000).toFixed(1)}s)`);
