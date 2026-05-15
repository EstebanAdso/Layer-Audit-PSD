// Detect all text layers in a PSD and emit manifest with layer record bounds
// (which is the canvas-target position when the descriptor is fixed).
const fs = require('fs');
const path = require('path');
const { readPsd, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);
// Monkey-patch CMYK support (mode 4) — we only modify text, not image data
const psdReader = require('ag-psd/dist/psdReader');
if (!psdReader.supportedColorModes.includes(4)) psdReader.supportedColorModes.push(4);

const INPUT = path.resolve(process.argv[2]);
const OUTPUT = path.resolve(process.argv[3]);

const out = [];
function walk(layers) {
    if (!layers) return;
    for (const l of layers) {
        if (l.text) {
            out.push({
                name: l.name,
                left: l.left, top: l.top, right: l.right, bottom: l.bottom,
                shapeType: l.text.shapeType || 'point',
            });
        }
        if (l.children) walk(l.children);
    }
}

const psd = readPsd(fs.readFileSync(INPUT), { useImageData: false });
walk(psd.children);

console.log(`Text layers found in ${path.basename(INPUT)}: ${out.length}`);
for (const e of out) {
    console.log(`  [${e.shapeType.padEnd(5)}] ${e.name.slice(0,55).padEnd(55)} ` +
        `(${e.left},${e.top})-(${e.right},${e.bottom}) ${e.right-e.left}x${e.bottom-e.top}`);
}

fs.writeFileSync(OUTPUT, JSON.stringify(out.map(({shapeType, ...rest}) => rest), null, 2));
console.log(`\nManifest written: ${OUTPUT}`);
