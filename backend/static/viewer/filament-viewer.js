// Preview in Real Filament — client-side WebGL viewer (Phase 1 MVP).
// 100% on the visitor's GPU. No server render, no slicing, no re-hosting models.
// Renders curated CC0/PrintShelf-original SAMPLE shapes (see sample_licenses.json)
// in a chosen filament's true color + material finish, with shader-faked layer lines.
//
// three.js is vendored (../three.module.js) and dynamic-import()ed only on the
// viewer route. Bare "three" specifier resolves via the page's <script type=importmap>.

import * as THREE from 'three';
import { OrbitControls } from './OrbitControls.js';
import { STLLoader } from './STLLoader.js';
import { RoomEnvironment } from './RoomEnvironment.js';
import { mergeVertices } from './BufferGeometryUtils.js';

const NORM_H = 1.0;            // every model is normalized to this object-space height
const STATIC = '/static';

// ---- Sample geometry (procedural = PrintShelf-original; up axis = +Y) -------
// realHeightMm drives layer-line density (bands = realHeightMm / layerHeightMm).
function buildSwatch() {
  // a standing tile — shows true color + a clean run of layer lines across the face
  return new THREE.BoxGeometry(0.9, 1.4, 0.14, 1, 1, 1);
}
function buildDome() {
  // smooth sphere — best canvas for a silk sheen sweep + anisotropy
  return new THREE.SphereGeometry(0.62, 96, 64);
}
function buildVase() {
  // thin-walled lathe vase/lampshade — shows translucency / transmission
  const pts = [];
  const profile = [
    [0.34, 0.00], [0.40, 0.10], [0.30, 0.34], [0.22, 0.58],
    [0.30, 0.80], [0.40, 0.96], [0.38, 1.00],
  ];
  for (const [x, y] of profile) pts.push(new THREE.Vector2(x, y - 0.5));
  const g = new THREE.LatheGeometry(pts, 80);
  g.computeVertexNormals();
  return g;
}
function buildCoin() {
  // relief coin — fine detail + how layer lines read on matte detail
  const parts = [new THREE.CylinderGeometry(0.7, 0.7, 0.16, 96)];
  // concentric raised rings = procedural "relief" detail
  for (let i = 0; i < 3; i++) {
    const r = 0.30 + i * 0.16;
    const ring = new THREE.TorusGeometry(r, 0.022, 16, 96);
    ring.rotateX(Math.PI / 2);
    ring.translate(0, 0.085, 0);
    parts.push(ring);
  }
  const merged = mergeGeoms(parts);
  return merged;
}
function mergeGeoms(list) {
  // tiny local merge (avoids needing mergeGeometries import differences across versions)
  const geos = list.map((g) => g.toNonIndexed());
  let total = 0;
  for (const g of geos) total += g.attributes.position.count;
  const pos = new Float32Array(total * 3);
  let o = 0;
  for (const g of geos) {
    pos.set(g.attributes.position.array, o);
    o += g.attributes.position.array.length;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  out.computeVertexNormals();
  return out;
}

const SAMPLES = [
  { id: 'swatch', label: 'Color swatch', realHeightMm: 50, upAxis: 'y', build: buildSwatch },
  { id: 'dome',   label: 'Sheen dome',   realHeightMm: 45, upAxis: 'y', build: buildDome },
  { id: 'vase',   label: 'Vase',         realHeightMm: 80, upAxis: 'y', build: buildVase },
  { id: 'coin',   label: 'Relief coin',  realHeightMm: 10, upAxis: 'y', build: buildCoin },
  // 3DBenchy (CC0) — listed only if the STL is actually present (HEAD check at boot).
  { id: 'benchy', label: '3DBenchy', realHeightMm: 48, upAxis: 'z', stl: STATIC + '/viewer/samples/3dbenchy.stl' },
];

// Normalize any geometry to up=+Y, centered, height = NORM_H.
function normalizeGeometry(geo, upAxis) {
  let g = geo.index ? geo : mergeVertices(geo);
  if (upAxis === 'z') g.rotateX(-Math.PI / 2);
  else if (upAxis === 'x') g.rotateZ(Math.PI / 2);
  g.computeBoundingBox();
  const bb = g.boundingBox;
  const size = new THREE.Vector3(); bb.getSize(size);
  const center = new THREE.Vector3(); bb.getCenter(center);
  g.translate(-center.x, -center.y, -center.z);
  // Scale by the LARGEST dimension so flat shapes (coin) don't blow up the frame;
  // stash the resulting Y extent for the layer-band math (bands run along Y).
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  const s = NORM_H / maxDim;
  g.scale(s, s, s);
  g.computeVertexNormals();
  g.computeBoundingBox();
  g.userData.normHeight = (g.boundingBox.max.y - g.boundingBox.min.y) || NORM_H;
  return g;
}

// ---- Material builder (data-driven; layer-line shader injected) -------------
function aliasedFinish(presets, finish) {
  const f = (finish || '').toLowerCase().trim();
  return (presets.finishAliases && presets.finishAliases[f]) || f;
}
function resolvePreset(presets, material, finish) {
  const M = (material || '').toUpperCase().trim();
  const fin = aliasedFinish(presets, finish);
  const p = presets.presets;
  if (fin === 'transparent') return p['transparent'];
  return p[`${M}|${fin}`] || p[M] || p['_default'];
}

// Named-color fallback for filaments with no stored color_hex — otherwise a
// "Matte Black" with a null hex washes out to neutral grey (reads as white).
const COLOR_WORDS = {
  black: '#1a1a1a', white: '#f0f0f0', gray: '#9aa0aa', grey: '#9aa0aa', silver: '#c4c4c8',
  red: '#c0392b', orange: '#e67e22', yellow: '#f1c40f', gold: '#d4af37', green: '#27ae60',
  blue: '#2563eb', navy: '#1e3a8a', teal: '#14b8a6', cyan: '#22d3ee', purple: '#8e44ad',
  violet: '#7c3aed', pink: '#ff6fae', magenta: '#d6249f', brown: '#7a5230', tan: '#d2b48c',
  beige: '#e8e2d0', natural: '#e8e2d0', clear: '#dfeaf0', transparent: '#dfeaf0',
};
function resolveBaseColor(filament) {
  const hex = (filament.color_hex || '').trim();
  if (/^#?[0-9a-fA-F]{6}$/.test(hex)) return new THREE.Color(hex.startsWith('#') ? hex : '#' + hex);
  const name = (filament.color_name || '').toLowerCase();
  for (const word in COLOR_WORDS) if (name.includes(word)) return new THREE.Color(COLOR_WORDS[word]);
  return new THREE.Color('#9aa0aa');
}

function buildMaterial(presets, filament, layerUniforms) {
  const preset = resolvePreset(presets, filament.material, filament.finish);
  const base = resolveBaseColor(filament);
  // Marble/speckle/granite: view-independent color flecks in the albedo.
  const speck = (presets.specks && presets.specks[aliasedFinish(presets, filament.finish)]) || null;
  let speckColor = new THREE.Color('#1e1e1e');
  if (speck) {
    if (speck.colorHex) speckColor = new THREE.Color(speck.colorHex);
    else {
      const lum = base.r * 0.299 + base.g * 0.587 + base.b * 0.114;  // dark base → light flecks & vice-versa
      speckColor = new THREE.Color(lum > 0.5 ? '#1c1c1c' : '#e8e8e8');
    }
  }
  const mat = new THREE.MeshPhysicalMaterial({
    color: base,
    roughness: preset.roughness,
    metalness: preset.metalness,
    ior: preset.ior,
    transmission: preset.transmission,
    thickness: preset.thickness,
    sheen: preset.sheen,
    sheenColor: new THREE.Color(preset.sheenColorHex || '#ffffff'),
    sheenRoughness: preset.sheenRoughness,
    clearcoat: preset.clearcoat || 0,
    clearcoatRoughness: 0.3,
  });
  if ('anisotropy' in mat) { mat.anisotropy = preset.anisotropy || 0; mat.anisotropyRotation = preset.anisotropyRotation || 0; }
  if (preset.emissiveFromBase && preset.emissiveIntensity > 0) {
    mat.emissive = base.clone();
    mat.emissiveIntensity = preset.emissiveIntensity;
    mat.userData.glow = true;
  }
  // Inject the layer-line banding (shared uniforms so the slider updates live)
  // + per-material sparkle/flake glints for glitter filaments.
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uLayerHeight = layerUniforms.uLayerHeight;
    shader.uniforms.uBandStrength = layerUniforms.uBandStrength;
    shader.uniforms.uSparkle = { value: preset.sparkleIntensity || 0 };
    shader.uniforms.uSpeckI = { value: speck ? speck.intensity : 0 };
    shader.uniforms.uSpeckColor = { value: speckColor };
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying float vLayerY;\nvarying vec3 vSpk;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvLayerY = position.y;\nvSpk = position;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying float vLayerY;\nvarying vec3 vSpk;\nuniform float uLayerHeight;\nuniform float uBandStrength;\nuniform float uSparkle;\nuniform float uSpeckI;\nuniform vec3 uSpeckColor;')
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
      {
        float _p = fract(vLayerY / max(uLayerHeight, 1e-4));
        float _g = abs(_p - 0.5) * 2.0;            // 0 at band center .. 1 at boundary
        float _groove = smoothstep(0.55, 1.0, _g); // darken near the groove
        float _ridge  = smoothstep(0.28, 0.0, _g); // shinier ridge catches light
        diffuseColor.rgb *= (1.0 - 0.22 * uBandStrength * _groove);
        roughnessFactor *= mix(1.0, 0.5, _ridge * uBandStrength);
      }
      // Marble/speckle: view-INDEPENDENT color flecks baked into the albedo.
      if (uSpeckI > 0.0) {
        vec3 _sp = vSpk * 52.0;
        vec3 _c = floor(_sp);
        float _r  = fract(sin(dot(_c, vec3(41.3, 289.1, 97.7))) * 43758.5453);
        float _r2 = fract(sin(dot(_c, vec3(11.9, 78.2, 151.3))) * 24634.6345);
        float _chosen = step(1.0 - 0.42 * uSpeckI, _r);
        vec3 _j = (vec3(_r, _r2, fract(_r * 7.0)) - 0.5) * 0.7;
        float _fd = length(fract(_sp) - 0.5 - _j);
        float _fleck = _chosen * smoothstep(0.26, 0.10, _fd);
        diffuseColor.rgb = mix(diffuseColor.rgb, uSpeckColor, _fleck);
      }`)
      // Sparkle: sparse object-space flake cells. Each flake has a faint always-on
      // shimmer (so flakes read on EVERY face, not just camera-facing ones) plus a
      // view-dependent glint on top that twinkles as the model/lights move.
      .replace('#include <opaque_fragment>', `#include <opaque_fragment>
      if (uSparkle > 0.0) {
        vec3 _cell = floor(vSpk * 190.0);
        float _h  = fract(sin(dot(_cell, vec3(127.1, 311.7, 74.7))) * 43758.5453);
        float _h2 = fract(sin(dot(_cell, vec3(269.5, 183.3, 246.1))) * 43758.5453);
        float _flake = step(0.985 - 0.012 * uSparkle, _h);
        gl_FragColor.rgb += _flake * uSparkle * (0.25 + 0.35 * _h);   // base shimmer, all faces
        vec3 _fn = normalize(vNormal + (vec3(_h, _h2, fract(_h * 7.3)) - 0.5) * 1.6);
        float _glint = pow(max(dot(_fn, normalize(vViewPosition)), 0.0), 28.0);
        gl_FragColor.rgb += _flake * _glint * uSparkle * 2.6;                 // twinkle on top
      }`);
  };
  // Cache key varies by sparkle so glitter vs non-glitter materials get their own program.
  mat.customProgramCacheKey = () => 'fp-layerlines-' + (preset.sparkleIntensity > 0 ? 'spk' : 'plain');
  return mat;
}

// ---- Boot ------------------------------------------------------------------
export async function boot(container, config) {
  const presets = await fetch(`${STATIC}/data/filament_presets.json?v=8`).then((r) => r.json());

  // Which samples are available (drop benchy if its STL isn't deployed).
  const samples = [];
  for (const s of SAMPLES) {
    if (!s.stl) { samples.push(s); continue; }
    try {
      const head = await fetch(s.stl, { method: 'HEAD' });
      if (head.ok) samples.push(s);
    } catch (e) { /* skip benchy */ }
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  const isMobile = matchMedia('(max-width: 700px)').matches;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, isMobile ? 1.5 : 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const camera = new THREE.PerspectiveCamera(40, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.set(0, 0.4, 3.2);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.minDistance = 1.5; controls.maxDistance = 8;

  // 3-point studio lighting
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(2, 3, 2);
  const fill = new THREE.DirectionalLight(0xffffff, 0.8); fill.position.set(-3, 1, 1);
  const rim = new THREE.DirectionalLight(0xffffff, 1.2); rim.position.set(0, 2, -3);
  const amb = new THREE.AmbientLight(0xffffff, 0.25);
  scene.add(key, fill, rim, amb);

  const layerUniforms = {
    uLayerHeight: { value: 0.2 / 50 },   // object-space period (set per sample/slider)
    uBandStrength: { value: 1.0 },
  };

  const state = {
    sampleId: samples[0].id,
    filament: config.filaments[0] || (config.catalog || [])[0] || { material: 'PLA', finish: '', color_hex: '#ff6a3d' },
    layerHeightMm: 0.2,
    turntable: true,
    lightsOff: false,
    geomCache: {},
    uploadRaw: null,     // raw BufferGeometry of an uploaded STL (ephemeral, never persisted)
    uploadAxis: 'z',     // assumed print-up axis for uploads (slicer STLs are usually Z-up)
    compare: false,      // side-by-side: same model in two filaments
    filamentB: config.filaments[1] || config.filaments[0] || (config.catalog || [])[1] || (config.catalog || [])[0] || { material: 'PLA', finish: '', color_hex: '#2563eb' },
    matB: null,          // material for the right (compare) pane
  };

  let mesh = null;
  const stlLoader = new STLLoader();

  function rebuildMatB() {
    if (state.matB) state.matB.dispose();
    state.matB = buildMaterial(presets, state.filamentB, layerUniforms);
  }

  async function loadSample(id) {
    const s = samples.find((x) => x.id === id);
    setLoading(true);
    let geo = state.geomCache[id];
    if (!geo) {
      if (s.stl) {
        const raw = await stlLoader.loadAsync(s.stl);
        geo = normalizeGeometry(raw, s.upAxis);
      } else {
        geo = normalizeGeometry(s.build(), s.upAxis);
      }
      state.geomCache[id] = geo;
    }
    if (mesh) { scene.remove(mesh); mesh.material.dispose(); }
    mesh = new THREE.Mesh(geo, buildMaterial(presets, state.filament, layerUniforms));
    mesh.rotation.y = 0;
    scene.add(mesh);
    state.sampleId = id;
    fitCamera();
    applyLayerHeight();
    setLoading(false);
  }

  // Frame any model to its bounding sphere so flat (coin) and tall (swatch) shapes
  // all sit nicely in view — fixes the coin zooming in too close.
  function fitCamera() {
    if (!mesh) return;
    mesh.geometry.computeBoundingSphere();
    const r = mesh.geometry.boundingSphere.radius || 1;
    const fov = camera.fov * Math.PI / 180;
    const dist = (r / Math.sin(fov / 2)) * 1.3;
    const dir = new THREE.Vector3(0, 0.22, 1).normalize();
    camera.position.copy(dir.multiplyScalar(dist));
    camera.near = Math.max(dist / 100, 0.01);
    camera.far = dist * 12;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.minDistance = dist * 0.45;
    controls.maxDistance = dist * 3.5;
    controls.update();
  }

  function refreshMaterial() {
    if (!mesh) return;
    mesh.material.dispose();
    mesh.material = buildMaterial(presets, state.filament, layerUniforms);
  }

  function applyLayerHeight() {
    const s = samples.find((x) => x.id === state.sampleId);
    const bands = Math.max(1, s.realHeightMm / state.layerHeightMm);
    const yExtent = (mesh && mesh.geometry.userData.normHeight) || NORM_H;
    layerUniforms.uLayerHeight.value = yExtent / bands;
  }

  function applyLights() {
    const off = state.lightsOff;
    key.intensity = off ? 0.04 : 2.2;
    fill.intensity = off ? 0.02 : 0.8;
    rim.intensity = off ? 0.06 : 1.2;
    amb.intensity = off ? 0.02 : 0.25;
    renderer.toneMappingExposure = off ? 1.6 : 1.1;
    scene.environmentIntensity = off ? 0.04 : 1.0;
  }

  // ---- UI wiring (elements provided by the template) ----
  const ui = config.ui;
  function setLoading(v) { if (ui.loading) ui.loading.style.display = v ? 'flex' : 'none'; }

  if (ui.sample) {
    ui.sample.innerHTML = samples.map((s) => `<option value="${s.id}">${s.label}</option>`).join('');
    ui.sample.value = state.sampleId;
    ui.sample.addEventListener('change', () => loadSample(ui.sample.value));
  }
  // Picker options: "My filaments" (owned) + "Browse & buy" (community catalog).
  const catalog = config.catalog || [];
  function filLabel(f) { return `${f.brand} ${f.material}${f.finish ? ' ' + f.finish : ''}${f.color_name ? ' · ' + f.color_name : ''}`; }
  function filamentOptionsHTML() {
    let html = '';
    if (config.filaments.length) html += '<optgroup label="My filaments">' + config.filaments.map((f, i) => `<option value="own:${i}">${filLabel(f)}</option>`).join('') + '</optgroup>';
    if (catalog.length) html += '<optgroup label="Browse &amp; buy">' + catalog.map((f, i) => `<option value="cat:${i}">${filLabel(f)}</option>`).join('') + '</optgroup>';
    return html || '<option>No filaments yet</option>';
  }
  function filFromValue(v) {
    const [src, idx] = String(v).split(':');
    return (src === 'cat' ? catalog : config.filaments)[Number(idx)] || null;
  }
  if (ui.filament) {
    ui.filament.innerHTML = filamentOptionsHTML();
    ui.filament.addEventListener('change', () => {
      state.filament = filFromValue(ui.filament.value) || state.filament;
      refreshMaterial();
      updateBuyLinks();
    });
  }

  // Affiliate Buy — owned filaments hit the tracked /buy redirector; catalog
  // (non-owned) filaments carry a buyUrl to the tracked store-search redirector.
  // In compare mode BOTH filaments are buyable (you're weighing the two).
  function buyHref(f) { return f ? (f.buyUrl || (f.id ? `/dashboard/filaments/${f.id}/buy` : null)) : null; }
  function setBuy(el, f, show) {
    if (!el) return;
    const href = buyHref(f);
    if (show && href) {
      el.href = href;
      el.textContent = `Buy ${f.brand} ${f.material} →`;
      el.style.display = '';
    } else {
      el.style.display = 'none';
    }
  }
  function updateBuyLinks() {
    setBuy(ui.buy, state.filament, true);
    setBuy(ui.buyB, state.filamentB, state.compare);
  }

  // Share: composite the canvas + a caption/watermark into a downloadable PNG.
  function shareImage() {
    renderer.render(scene, camera);
    const src = renderer.domElement;
    const W = src.width, H = src.height, pad = Math.round(H * 0.09);
    const out = document.createElement('canvas');
    out.width = W; out.height = H + pad;
    const ctx = out.getContext('2d');
    ctx.fillStyle = '#0f1115'; ctx.fillRect(0, 0, W, H + pad);
    ctx.drawImage(src, 0, 0);
    const f = state.filament;
    const label = f ? `${f.brand} ${f.material}${f.finish ? ' ' + f.finish : ''}${f.color_name ? ' · ' + f.color_name : ''}` : '';
    ctx.font = `${Math.round(pad * 0.42)}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#e8e9ed'; ctx.textAlign = 'left'; ctx.fillText(label, pad * 0.5, H + pad / 2);
    ctx.fillStyle = '#ff6a3d'; ctx.textAlign = 'right'; ctx.fillText('printshelf.app', W - pad * 0.5, H + pad / 2);
    const a = document.createElement('a');
    a.download = 'printshelf-filament-preview.png';
    a.href = out.toDataURL('image/png');
    a.click();
  }
  if (ui.share) ui.share.addEventListener('click', shareImage);

  // Ephemeral STL upload — parsed in a Worker, rendered, never persisted/uploaded.
  const stlWorker = new Worker('/static/viewer/stl-worker.js');
  let uploadResolve = null;
  stlWorker.onmessage = (e) => { if (uploadResolve) { uploadResolve(e.data); uploadResolve = null; } };

  function rebuildUpload() {
    if (!state.uploadRaw) return;
    const s = samples.find((x) => x.id === 'upload');
    s.upAxis = state.uploadAxis;
    state.geomCache['upload'] = normalizeGeometry(state.uploadRaw.clone(), state.uploadAxis);
    if (ui.sample) ui.sample.value = 'upload';
    loadSample('upload');
  }

  async function handleFile(file) {
    if (!file) return;
    if (ui.uploadErr) ui.uploadErr.style.display = 'none';
    if (!/\.stl$/i.test(file.name)) {
      if (ui.uploadErr) { ui.uploadErr.textContent = 'STL files only for now (3MF coming).'; ui.uploadErr.style.display = ''; }
      return;
    }
    setLoading(true);
    try {
      const buf = await file.arrayBuffer();
      const res = await new Promise((resolve) => { uploadResolve = resolve; stlWorker.postMessage(buf, [buf]); });
      if (!res.ok) throw new Error(res.error || 'parse failed');
      const raw = new THREE.BufferGeometry();
      raw.setAttribute('position', new THREE.BufferAttribute(res.positions, 3));
      raw.computeVertexNormals();
      state.uploadRaw = raw;
      if (!samples.find((s) => s.id === 'upload')) {
        samples.push({ id: 'upload', label: 'Your model', realHeightMm: 50, upAxis: state.uploadAxis });
        if (ui.sample) ui.sample.innerHTML = samples.map((s) => `<option value="${s.id}">${s.label}</option>`).join('');
      }
      rebuildUpload();
    } catch (err) {
      setLoading(false);
      console.error('STL upload failed', err);
      if (ui.uploadErr) { ui.uploadErr.textContent = 'Could not read that STL.'; ui.uploadErr.style.display = ''; }
    }
  }
  if (ui.upload) ui.upload.addEventListener('change', () => handleFile(ui.upload.files[0]));
  if (ui.upAxis) ui.upAxis.addEventListener('change', () => { state.uploadAxis = ui.upAxis.value; rebuildUpload(); });
  container.addEventListener('dragover', (e) => { e.preventDefault(); container.classList.add('fp-dragover'); });
  container.addEventListener('dragleave', () => container.classList.remove('fp-dragover'));
  container.addEventListener('drop', (e) => {
    e.preventDefault(); container.classList.remove('fp-dragover');
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
  if (ui.layer) {
    ui.layer.addEventListener('input', () => {
      state.layerHeightMm = Number(ui.layer.value);
      if (ui.layerLabel) ui.layerLabel.textContent = state.layerHeightMm.toFixed(2) + ' mm';
      applyLayerHeight();
    });
  }
  if (ui.turntable) ui.turntable.addEventListener('change', () => { state.turntable = ui.turntable.checked; });
  if (ui.lightsOff) ui.lightsOff.addEventListener('change', () => { state.lightsOff = ui.lightsOff.checked; applyLights(); });

  // Side-by-side compare: same model, two filaments.
  function updateCompareLabels() {
    const f = state.filament, g = state.filamentB;
    if (ui.labelA) ui.labelA.textContent = f ? `${f.brand} ${f.material}${f.color_name ? ' · ' + f.color_name : ''}` : '';
    if (ui.labelB) ui.labelB.textContent = g ? `${g.brand} ${g.material}${g.color_name ? ' · ' + g.color_name : ''}` : '';
    const show = state.compare ? '' : 'none';
    if (ui.labelA) ui.labelA.style.display = show;
    if (ui.labelB) ui.labelB.style.display = show;
  }
  if (ui.filamentB) {
    ui.filamentB.innerHTML = filamentOptionsHTML();   // same list → compare owned vs a filament you'd buy
    ui.filamentB.addEventListener('change', () => {
      state.filamentB = filFromValue(ui.filamentB.value) || state.filamentB;
      rebuildMatB(); updateCompareLabels(); updateBuyLinks();
    });
  }
  if (ui.compare) {
    ui.compare.addEventListener('change', () => {
      state.compare = ui.compare.checked;
      if (ui.compareRow) ui.compareRow.style.display = state.compare ? '' : 'none';
      updateCompareLabels(); updateBuyLinks();
    });
  }

  window.addEventListener('resize', () => {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  });

  applyLights();
  updateBuyLinks();
  await loadSample(state.sampleId);
  rebuildMatB();
  updateCompareLabels();

  const clock = new THREE.Clock();
  (function animate() {
    requestAnimationFrame(animate);
    const dt = clock.getDelta();
    if (state.turntable && mesh) mesh.rotation.y += dt * 0.5;
    controls.update();
    if (state.compare && mesh && state.matB) {
      const W = container.clientWidth, H = container.clientHeight, half = Math.floor(W / 2);
      camera.aspect = half / H; camera.updateProjectionMatrix();
      renderer.setScissorTest(true);
      renderer.setViewport(0, 0, half, H); renderer.setScissor(0, 0, half, H);
      renderer.render(scene, camera);                 // left = filament A (mesh.material)
      const a = mesh.material; mesh.material = state.matB;
      renderer.setViewport(half, 0, W - half, H); renderer.setScissor(half, 0, W - half, H);
      renderer.render(scene, camera);                 // right = filament B
      mesh.material = a;
      renderer.setScissorTest(false);
    } else {
      const W = container.clientWidth, H = container.clientHeight;
      renderer.setViewport(0, 0, W, H);
      if (Math.abs(camera.aspect - W / H) > 0.001) { camera.aspect = W / H; camera.updateProjectionMatrix(); }
      renderer.render(scene, camera);
    }
  })();
}
