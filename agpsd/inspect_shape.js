const fs = require('fs');
const path = require('path');
const { readPsd, initializeCanvas } = require('ag-psd');
const { createCanvas } = require('canvas');
initializeCanvas(createCanvas);
const psd1 = readPsd(fs.readFileSync('../NATURAS_MUEBLES_EXHIBIDORES.psd'), { useImageData: false });
const psd2 = readPsd(fs.readFileSync('../01_Story.psd'), { useImageData: false });
function find(layers, name) {
    for (const l of layers || []) {
        if (l.name === name) return l;
        if (l.children) { const f = find(l.children, name); if (f) return f; }
    }
}
for (const [psd, name, label] of [
    [psd1, 'TEXT_ATRIBUTO1_MUEBLES_EXHIBIDORDEPISOPALI_50CMX140CM', 'NATURAS'],
    [psd2, 'TEXT_VIGENCIA_01_Story', '01_Story'],
]) {
    const l = find(psd.children, name);
    if (!l) continue;
    console.log(`=== ${label} ===`);
    console.log(`  text length: ${l.text.text.length} chars`);
    console.log(`  shapeType: ${l.text.shapeType}`);
    console.log(`  orientation: ${l.text.orientation}`);
    console.log(`  pointBase: ${JSON.stringify(l.text.pointBase)}`);
    console.log(`  paragraphStyle keys: ${Object.keys(l.text.paragraphStyle || {})}`);
    if (l.text.paragraphStyle) {
        const ps = l.text.paragraphStyle;
        console.log(`    justification: ${ps.justification}`);
        console.log(`    firstLineIndent: ${ps.firstLineIndent && ps.firstLineIndent.value}`);
    }
    const s = l.text.style || {};
    console.log(`  style.font: ${s.font && s.font.name}`);
    console.log(`  style.fontSize: ${s.fontSize && s.fontSize.value}`);
    console.log(`  style.fontStyle: ${JSON.stringify(s.fontStyle)}`);
    console.log(`  style.autoLeading: ${s.autoLeading}`);
    console.log(`  styleRuns count: ${l.text.styleRuns && l.text.styleRuns.length}`);
    console.log();
}
