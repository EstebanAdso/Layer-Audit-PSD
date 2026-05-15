// Monkey-patch ag-psd to preserve text descriptor TransformPoints (rotation
// matrix). Without this, ag-psd hardcodes them to identity on write, which
// loses 90° rotation for vertical text layers.
//
// Also enables CMYK color mode (mode 4) since we only modify text descriptors,
// not image data.

const text = require('ag-psd/dist/text');
const psdReader = require('ag-psd/dist/psdReader');
const psdWriter = require('ag-psd/dist/psdWriter');
const imageResources = require('ag-psd/dist/imageResources');

if (!psdReader.supportedColorModes.includes(4)) psdReader.supportedColorModes.push(4);

// ag-psd has read/write handlers for resources like ICC_PROFILE (1039), EXIF
// (1058), color halftoning (1013) and color transfer (1016) but they are
// gated behind MOCK_HANDLERS=false, so they never get registered. Without
// these the round-trip drops the embedded ICC profile, which makes the
// re-saved PSD render with different (more dull / wrong) colors when opened
// in Photoshop (no profile -> assumed working space).
//
// We register byte-passthrough handlers for these resources manually: read
// stores raw bytes under target._ir<id>, write emits them back unchanged.
function registerPassthrough(id) {
    if (imageResources.resourceHandlersMap[id]) return; // already registered
    const has = (target) => target['_ir' + id] !== undefined;
    const read = (reader, target, left) => {
        target['_ir' + id] = psdReader.readBytes(reader, left());
    };
    const write = (writer, target) => {
        psdWriter.writeBytes(writer, target['_ir' + id]);
    };
    const handler = { key: id, has, read, write };
    imageResources.resourceHandlers.push(handler);
    imageResources.resourceHandlersMap[id] = handler;
}

// Resources that survive round-trip as opaque bytes. The list mirrors the
// MOCK_HANDLERS-gated registrations in ag-psd's imageResources.js — i.e.
// every resource ag-psd knows how to skip but not parse. Critical ones for
// color fidelity: 1039 (ICC profile), 1013/1016 (halftoning/transfer),
// 1058 (EXIF). The others (IPTC, print style, Windows DEVMODE, ...) get
// preserved too at zero extra cost.
[1013, 1016, 1025, 1028, 1039, 1058, 1077, 1083, 1085, 1092, 10000].forEach(registerPassthrough);

const origDecode = text.decodeEngineData;
text.decodeEngineData = function(engineData) {
    const result = origDecode(engineData);
    try {
        const base = engineData
            && engineData.EngineDict
            && engineData.EngineDict.Rendered
            && engineData.EngineDict.Rendered.Shapes
            && engineData.EngineDict.Rendered.Shapes.Children
            && engineData.EngineDict.Rendered.Shapes.Children[0]
            && engineData.EngineDict.Rendered.Shapes.Children[0].Cookie
            && engineData.EngineDict.Rendered.Shapes.Children[0].Cookie.Photoshop
            && engineData.EngineDict.Rendered.Shapes.Children[0].Cookie.Photoshop.Base;
        if (base) {
            result.transformPoints = {
                tp0: Array.isArray(base.TransformPoint0) ? base.TransformPoint0.slice() : [1, 0],
                tp1: Array.isArray(base.TransformPoint1) ? base.TransformPoint1.slice() : [0, 1],
                tp2: Array.isArray(base.TransformPoint2) ? base.TransformPoint2.slice() : [0, 0],
            };
        }
    } catch (e) {}
    return result;
};

const origEncode = text.encodeEngineData;
text.encodeEngineData = function(data) {
    const engineData = origEncode(data);
    try {
        if (data.transformPoints) {
            const base = engineData
                && engineData.EngineDict
                && engineData.EngineDict.Rendered
                && engineData.EngineDict.Rendered.Shapes
                && engineData.EngineDict.Rendered.Shapes.Children
                && engineData.EngineDict.Rendered.Shapes.Children[0]
                && engineData.EngineDict.Rendered.Shapes.Children[0].Cookie
                && engineData.EngineDict.Rendered.Shapes.Children[0].Cookie.Photoshop
                && engineData.EngineDict.Rendered.Shapes.Children[0].Cookie.Photoshop.Base;
            if (base) {
                base.TransformPoint0 = data.transformPoints.tp0;
                base.TransformPoint1 = data.transformPoints.tp1;
                base.TransformPoint2 = data.transformPoints.tp2;
            }
        }
    } catch (e) {}
    return engineData;
};
