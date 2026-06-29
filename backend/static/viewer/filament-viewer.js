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
  { id: 'coin',   label: 'Relief coin',  realHeightMm: 30, upAxis: 'y', build: buildCoin },
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
  const h = size.y || 1;
  g.scale(NORM_H / h, NORM_H / h, NORM_H / h);
  g.computeVertexNormals();
  g.computeBoundingBox();
  return g;
}

// ---- Material builder (data-driven; layer-line shader injected) -------------
function resolvePreset(presets, material, finish) {
  const M = (material || '').toUpperCase().trim();
  const fRaw = (finish || '').toLowerCase().trim();
  const fin = presets.finishAliases[fRaw] || fRaw;
  const p = presets.presets;
  if (fin === 'transparent') return p['transparent'];
  return p[`${M}|${fin}`] || p[M] || p['_default'];
}

function buildMaterial(presets, filament, layerUniforms) {
  const preset = resolvePreset(presets, filament.material, filament.finish);
  const base = new THREE.Color(filament.color_hex || '#9aa0aa');
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
  // Inject the layer-line banding (shared uniforms so the slider updates live).
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uLayerHeight = layerUniforms.uLayerHeight;
    shader.uniforms.uBandStrength = layerUniforms.uBandStrength;
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying float vLayerY;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvLayerY = position.y;');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying float vLayerY;\nuniform float uLayerHeight;\nuniform float uBandStrength;')
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
      {
        float _p = fract(vLayerY / max(uLayerHeight, 1e-4));
        float _g = abs(_p - 0.5) * 2.0;            // 0 at band center .. 1 at boundary
        float _groove = smoothstep(0.55, 1.0, _g); // darken near the groove
        float _ridge  = smoothstep(0.28, 0.0, _g); // shinier ridge catches light
        diffuseColor.rgb *= (1.0 - 0.22 * uBandStrength * _groove);
        roughnessFactor *= mix(1.0, 0.5, _ridge * uBandStrength);
      }`);
  };
  mat.customProgramCacheKey = () => 'layerlines';
  return mat;
}

// ---- Boot ------------------------------------------------------------------
export async function boot(container, config) {
  const presets = await fetch(`${STATIC}/data/filament_presets.json`).then((r) => r.json());

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
    filament: config.filaments[0] || { material: 'PLA', finish: '', color_hex: '#ff6a3d' },
    layerHeightMm: 0.2,
    turntable: true,
    lightsOff: false,
    geomCache: {},
  };

  let mesh = null;
  const stlLoader = new STLLoader();

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
    applyLayerHeight();
    setLoading(false);
  }

  function refreshMaterial() {
    if (!mesh) return;
    mesh.material.dispose();
    mesh.material = buildMaterial(presets, state.filament, layerUniforms);
  }

  function applyLayerHeight() {
    const s = samples.find((x) => x.id === state.sampleId);
    const bands = Math.max(1, s.realHeightMm / state.layerHeightMm);
    layerUniforms.uLayerHeight.value = NORM_H / bands;
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
  if (ui.filament) {
    ui.filament.innerHTML = config.filaments.map((f, i) =>
      `<option value="${i}">${f.brand} ${f.material}${f.finish ? ' ' + f.finish : ''}${f.color_name ? ' · ' + f.color_name : ''}</option>`).join('')
      || '<option>No filaments yet</option>';
    ui.filament.addEventListener('change', () => {
      state.filament = config.filaments[Number(ui.filament.value)] || state.filament;
      refreshMaterial();
    });
  }
  if (ui.layer) {
    ui.layer.addEventListener('input', () => {
      state.layerHeightMm = Number(ui.layer.value);
      if (ui.layerLabel) ui.layerLabel.textContent = state.layerHeightMm.toFixed(2) + ' mm';
      applyLayerHeight();
    });
  }
  if (ui.turntable) ui.turntable.addEventListener('change', () => { state.turntable = ui.turntable.checked; });
  if (ui.lightsOff) ui.lightsOff.addEventListener('change', () => { state.lightsOff = ui.lightsOff.checked; applyLights(); });

  window.addEventListener('resize', () => {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  });

  applyLights();
  await loadSample(state.sampleId);

  const clock = new THREE.Clock();
  (function animate() {
    requestAnimationFrame(animate);
    const dt = clock.getDelta();
    if (state.turntable && mesh) mesh.rotation.y += dt * 0.5;
    controls.update();
    renderer.render(scene, camera);
  })();
}
