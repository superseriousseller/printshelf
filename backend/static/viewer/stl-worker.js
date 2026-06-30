// Off-main-thread STL parser for the filament preview's ephemeral upload.
// Parses binary or ASCII STL into a flat Float32Array of triangle vertex
// positions and transfers it back. No three.js here (kept tiny). The uploaded
// geometry is never persisted — it only lives in the page until navigation.

const MAX_TRIS = 400000; // crude cap; subsample beyond this to stay smooth on mobile

function parseBinary(dv, tris) {
  const step = tris > MAX_TRIS ? Math.ceil(tris / MAX_TRIS) : 1;
  const kept = Math.ceil(tris / step);
  const pos = new Float32Array(kept * 9);
  let o = 0;
  for (let i = 0; i < tris; i += step) {
    let off = 84 + i * 50 + 12; // skip 80b header + 4b count + 12b normal
    for (let v = 0; v < 9; v++) pos[o++] = dv.getFloat32(off + v * 4, true);
  }
  return pos.subarray(0, o);
}

function parseASCII(text) {
  const verts = [];
  const re = /vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    verts.push(+m[1], +m[2], +m[3]);
    if (verts.length > MAX_TRIS * 9) break;
  }
  return new Float32Array(verts);
}

function parse(buffer) {
  const dv = new DataView(buffer);
  if (buffer.byteLength > 84) {
    const tris = dv.getUint32(80, true);
    if (buffer.byteLength === 84 + tris * 50) return parseBinary(dv, tris); // definitely binary
  }
  const head = new TextDecoder().decode(buffer.slice(0, 256)).trim().toLowerCase();
  if (head.startsWith('solid') && new TextDecoder().decode(buffer).includes('facet')) {
    return parseASCII(new TextDecoder().decode(buffer));
  }
  if (buffer.byteLength > 84) {
    const tris = dv.getUint32(80, true);
    if (tris > 0 && tris < 50000000) return parseBinary(dv, tris); // best-effort binary
  }
  throw new Error('Unrecognized STL file');
}

self.onmessage = (e) => {
  try {
    const positions = parse(e.data);
    if (!positions.length) throw new Error('No geometry found');
    self.postMessage({ ok: true, positions }, [positions.buffer]);
  } catch (err) {
    self.postMessage({ ok: false, error: String(err && err.message || err) });
  }
};
