// Compare text descriptors of the SAME layer across two PSDs.
const fs = require('fs');
const path = require('path');
const { readPsd, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);
const psdReader = require('ag-psd/dist/psdReader');
if (!psdReader.supportedColorModes.includes(4)) psdReader.supportedColorModes.push(4);

const A = path.resolve(process.argv[2]);
const B = path.resolve(process.argv[3]);
const NAME = process.argv[4];

function find(layers, name) {
    if (!layers) return null;
    for (const l of layers) {
        if (l.name === name) return l;
        if (l.children) { const f = find(l.children, name); if (f) return f; }
    }
    return null;
}
function pt(o) { return o == null ? 0 : (typeof o === 'object' && 'value' in o) ? Number(o.value) : Number(o); }

const psdA = readPsd(fs.readFileSync(A), { useImageData: false });
const psdB = readPsd(fs.readFileSync(B), { useImageData: false });
const lA = find(psdA.children, NAME);
const lB = find(psdB.children, NAME);
if (!lA || !lB) { console.log('layer not found in one or both files'); process.exit(1); }

function describe(label, l) {
    const t = l.text;
    console.log(`\n=== ${label} ===`);
    console.log(`Layer record: (${l.left},${l.top})-(${l.right},${l.bottom}) ${l.right-l.left}x${l.bottom-l.top}`);
    console.log(`orientation: ${t.orientation}  shapeType: ${t.shapeType}`);
    console.log(`transform: [${t.transform.map(v => typeof v === 'number' ? v.toFixed(3) : v).join(', ')}]`);
    const b = t.bounds, bb = t.boundingBox;
    console.log(`bounds:      L=${pt(b.left).toFixed(2)} T=${pt(b.top).toFixed(2)} R=${pt(b.right).toFixed(2)} B=${pt(b.bottom).toFixed(2)} -> ${(pt(b.right)-pt(b.left)).toFixed(2)} x ${(pt(b.bottom)-pt(b.top)).toFixed(2)}`);
    console.log(`boundingBox: L=${pt(bb.left).toFixed(2)} T=${pt(bb.top).toFixed(2)} R=${pt(bb.right).toFixed(2)} B=${pt(bb.bottom).toFixed(2)} -> ${(pt(bb.right)-pt(bb.left)).toFixed(2)} x ${(pt(bb.bottom)-pt(bb.top)).toFixed(2)}`);
    if (t.boxBounds) console.log(`boxBounds:   [${t.boxBounds.map(v => v.toFixed(2)).join(', ')}] -> ${(t.boxBounds[2]-t.boxBounds[0]).toFixed(2)} x ${(t.boxBounds[3]-t.boxBounds[1]).toFixed(2)}`);
    console.log(`warp: ${JSON.stringify(t.warp)}`);
    console.log(`text: "${t.text.slice(0, 60)}${t.text.length > 60 ? '...' : ''}"`);
}

describe(`A: ${path.basename(A)}`, lA);
describe(`B: ${path.basename(B)}`, lB);
