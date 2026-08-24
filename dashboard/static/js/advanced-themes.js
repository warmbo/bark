import * as THREE from '/static/js/vendor/three.module.0.185.1-bark2.min.js';

/**
 * Bark Advanced Themes runtime.
 *
 * A single fixed, pointer-transparent Three.js canvas supports the Advanced
 * themes. Each theme constructs a distinct lightweight scene; CSS owns all UI
 * surfaces and typography. The renderer is capped at 1.5 DPR, pauses in hidden
 * tabs, tears down when leaving an Advanced theme, and renders one static frame
 * under prefers-reduced-motion.
 */
const ADVANCED = new Set([
  'aurora', 'neon', 'ocean', 'sunset', 'forest', 'candy', 'slate',
  'crimson', 'honey', 'deepspace', 'graffiti',
]);

const palette = {
  aurora: ['#31f5c5', '#9b7bff', '#6ae7ff'],
  neon: ['#ff4fc8', '#7c6cff', '#24e7ff'],
  ocean: ['#23d7ff', '#0d79ff', '#51ffd2'],
  sunset: ['#ffb24a', '#ff4d76', '#b56cff'],
  forest: ['#55ff91', '#16b86b', '#e9ff8a'],
  candy: ['#ff77c8', '#8c7dff', '#7ef6ff'],
  slate: ['#b9d9ff', '#7aa7e8', '#ffffff'],
  crimson: ['#ff315f', '#a60d35', '#ff9f69'],
  honey: ['#ffc83d', '#ff8f19', '#fff0a6'],
  deepspace: ['#b07cff', '#4ec9ff', '#ff67d4'],
  graffiti: ['#ffef38', '#ff3e9d', '#45f7ff'],
};

let renderer = null;
let scene = null;
let camera = null;
let canvas = null;
let activeTheme = '';
let frame = 0;
let timer = new THREE.Timer();
let updaters = [];
let pointer = new THREE.Vector2(0, 0);
let reduced = matchMedia('(prefers-reduced-motion: reduce)');
let visible = !document.hidden;
let graffitiButton = null;
let renderScale = 1;

function color(theme, index) {
  return new THREE.Color(palette[theme][index % palette[theme].length]);
}

function addPoints(theme, count, spread, size = 0.035, opacity = 0.6) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    positions[i * 3] = (Math.random() - 0.5) * spread;
    positions[i * 3 + 1] = (Math.random() - 0.5) * spread * 0.62;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 4 - 2;
    const c = color(theme, i);
    colors.set([c.r, c.g, c.b], i * 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const material = new THREE.PointsMaterial({
    size, vertexColors: true, transparent: true, opacity,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const points = new THREE.Points(geometry, material);
  scene.add(points);
  return points;
}

function luminousMaterial(theme, index, opacity = 0.26, wireframe = true) {
  return new THREE.MeshBasicMaterial({
    color: color(theme, index), transparent: true, opacity, wireframe,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
}

function makeAurora() {
  const group = new THREE.Group();
  for (let band = 0; band < 5; band++) {
    const points = [];
    for (let i = 0; i < 34; i++) {
      const x = -6 + i * 0.38;
      points.push(new THREE.Vector3(x, Math.sin(i * 0.43 + band) * 0.45 + band * 0.18 - 0.5, -2 - band * 0.18));
    }
    const curve = new THREE.CatmullRomCurve3(points);
    const tube = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 96, 0.035 + band * 0.008, 6, false),
      luminousMaterial('aurora', band, 0.22, false),
    );
    group.add(tube);
  }
  group.rotation.z = -0.08;
  group.userData.baseY = 1.35;
  scene.add(group);
  const dust = addPoints('aurora', 160, 12, 0.025, 0.42);
  updaters.push((t) => {
    group.rotation.y = Math.sin(t * 0.12) * 0.08 + pointer.x * 0.06;
    group.position.y = group.userData.baseY + Math.sin(t * 0.28) * 0.16 + pointer.y * 0.1;
    dust.rotation.z = t * 0.008;
  });
}

function makeNeon() {
  const city = new THREE.Group();
  for (let i = 0; i < 28; i++) {
    const h = 0.5 + Math.random() * 2.8;
    const box = new THREE.Mesh(
      new THREE.BoxGeometry(0.28 + Math.random() * 0.35, h, 0.36),
      luminousMaterial('neon', i, 0.22, true),
    );
    box.position.set(-5.4 + i * 0.42, -2.6 + h / 2, -2.5 - Math.random() * 2);
    city.add(box);
  }
  scene.add(city);
  const bokeh = addPoints('neon', 110, 11, 0.09, 0.5);
  updaters.push((t) => {
    city.rotation.y = pointer.x * 0.07;
    city.position.x = pointer.x * -0.25;
    bokeh.rotation.z = Math.sin(t * 0.07) * 0.12;
    bokeh.position.y = Math.sin(t * 0.23) * 0.12;
  });
}

function makeOcean() {
  const geometry = new THREE.PlaneGeometry(15, 9, 54, 34);
  const base = geometry.attributes.position.array.slice();
  const material = new THREE.MeshBasicMaterial({
    color: color('ocean', 0), wireframe: true, transparent: true, opacity: 0.14,
    blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const water = new THREE.Mesh(geometry, material);
  water.rotation.x = -Math.PI * 0.58;
  water.position.set(0, -3.15, -3.8);
  scene.add(water);
  const bubbles = addPoints('ocean', 95, 10, 0.04, 0.38);
  updaters.push((t) => {
    const pos = geometry.attributes.position.array;
    for (let i = 0; i < pos.length; i += 3) {
      const x = base[i]; const y = base[i + 1];
      pos[i + 2] = Math.sin(x * 1.2 + t * 0.7) * 0.18 + Math.cos(y * 1.5 - t * 0.55) * 0.13;
    }
    geometry.attributes.position.needsUpdate = true;
    water.rotation.z = pointer.x * 0.025;
    bubbles.position.y = (t * 0.08) % 4 - 2;
  });
}

function makeSunset() {
  const sun = new THREE.Mesh(
    new THREE.SphereGeometry(1.25, 40, 24),
    new THREE.MeshBasicMaterial({ color: color('sunset', 0), transparent: true, opacity: 0.28 }),
  );
  sun.position.set(3.3, -1.2, -5);
  scene.add(sun);
  const rings = new THREE.Group();
  for (let i = 0; i < 6; i++) {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(1.55 + i * 0.42, 0.015, 8, 96),
      luminousMaterial('sunset', i, 0.22 - i * 0.018, false),
    );
    ring.position.copy(sun.position);
    rings.add(ring);
  }
  scene.add(rings);
  const embers = addPoints('sunset', 120, 11, 0.035, 0.42);
  updaters.push((t) => {
    rings.rotation.z = t * 0.035;
    rings.scale.setScalar(1 + Math.sin(t * 0.32) * 0.035);
    sun.position.y = -1.2 + Math.sin(t * 0.18) * 0.16;
    embers.position.y = Math.sin(t * 0.12) * 0.3;
  });
}

function makeForest() {
  const canopy = new THREE.Group();
  for (let i = 0; i < 48; i++) {
    const leaf = new THREE.Mesh(
      new THREE.CircleGeometry(0.12 + Math.random() * 0.22, 5),
      luminousMaterial('forest', i, 0.13, false),
    );
    leaf.position.set((Math.random() - 0.5) * 12, (Math.random() - 0.5) * 7, -2 - Math.random() * 4);
    leaf.rotation.z = Math.random() * Math.PI;
    canopy.add(leaf);
  }
  scene.add(canopy);
  const fireflies = addPoints('forest', 95, 10, 0.055, 0.65);
  updaters.push((t) => {
    canopy.rotation.z = Math.sin(t * 0.08) * 0.04;
    canopy.position.x = pointer.x * 0.22;
    fireflies.rotation.y = t * 0.025;
    fireflies.material.opacity = 0.45 + Math.sin(t * 1.6) * 0.18;
  });
}

function makeCandy() {
  const sweets = new THREE.Group();
  for (let i = 0; i < 14; i++) {
    const geometry = i % 3 === 0
      ? new THREE.TorusKnotGeometry(0.17, 0.055, 40, 7)
      : new THREE.IcosahedronGeometry(0.16 + Math.random() * 0.18, 0);
    const mesh = new THREE.Mesh(geometry, luminousMaterial('candy', i, 0.34, i % 2 === 0));
    mesh.position.set((Math.random() - 0.5) * 11, (Math.random() - 0.5) * 7, -2 - Math.random() * 4);
    mesh.userData.spin = 0.15 + Math.random() * 0.45;
    mesh.userData.baseY = mesh.position.y;
    sweets.add(mesh);
  }
  scene.add(sweets);
  updaters.push((t) => {
    sweets.children.forEach((m, i) => {
      m.rotation.x = t * m.userData.spin;
      m.rotation.y = t * m.userData.spin * 0.7;
      m.position.y = m.userData.baseY + Math.sin(t * 0.7 + i) * 0.08;
    });
    sweets.rotation.z = pointer.x * 0.03;
  });
}

function makeSlate() {
  const panes = new THREE.Group();
  for (let i = 0; i < 9; i++) {
    const pane = new THREE.Mesh(
      new THREE.PlaneGeometry(1.7 + (i % 3) * 0.35, 1 + (i % 2) * 0.4),
      new THREE.MeshBasicMaterial({
        color: color('slate', i), transparent: true, opacity: 0.055 + i * 0.008,
        side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending,
      }),
    );
    pane.position.set((i % 3 - 1) * 3.1, (Math.floor(i / 3) - 1) * 2.05, -2.5 - i * 0.22);
    pane.rotation.z = (i % 2 ? -1 : 1) * 0.035;
    pane.userData.baseZ = pane.position.z;
    panes.add(pane);
    const edge = new THREE.LineSegments(
      new THREE.EdgesGeometry(pane.geometry),
      new THREE.LineBasicMaterial({ color: color('slate', i), transparent: true, opacity: 0.17 }),
    );
    pane.add(edge);
  }
  scene.add(panes);
  updaters.push((t) => {
    panes.rotation.x = pointer.y * -0.025;
    panes.rotation.y = pointer.x * 0.045;
    panes.children.forEach((p, i) => { p.position.z = p.userData.baseZ + Math.sin(t * 0.24 + i) * 0.08; });
  });
}

function makeCrimson() {
  const knot = new THREE.Mesh(
    new THREE.TorusKnotGeometry(1.8, 0.22, 180, 14, 2, 5),
    luminousMaterial('crimson', 0, 0.14, true),
  );
  knot.position.set(4.25, -0.35, -6.2);
  scene.add(knot);
  const pulse = new THREE.Mesh(
    new THREE.TorusGeometry(2.45, 0.035, 8, 120),
    luminousMaterial('crimson', 2, 0.2, false),
  );
  pulse.position.copy(knot.position);
  scene.add(pulse);
  updaters.push((t) => {
    knot.rotation.x = t * 0.08 + pointer.y * 0.1;
    knot.rotation.y = t * 0.11 + pointer.x * 0.1;
    pulse.scale.setScalar(0.93 + Math.sin(t * 1.1) * 0.09);
  });
}

function makeHoney() {
  const hive = new THREE.Group();
  const hex = new THREE.CircleGeometry(0.26, 6);
  for (let row = -5; row <= 5; row++) {
    for (let col = -7; col <= 7; col++) {
      if ((row + col) % 3 !== 0) continue;
      const cell = new THREE.Mesh(hex, luminousMaterial('honey', row + col, 0.12, true));
      cell.position.set(col * 0.65 + (row % 2) * 0.32, row * 0.56, -3.4);
      hive.add(cell);
    }
  }
  scene.add(hive);
  const pollen = addPoints('honey', 80, 10, 0.045, 0.5);
  updaters.push((t) => {
    hive.rotation.z = Math.sin(t * 0.16) * 0.025;
    hive.position.x = pointer.x * 0.18;
    pollen.rotation.z = t * 0.018;
  });
}

function makeDeepSpace() {
  const stars = addPoints('deepspace', 520, 18, 0.026, 0.78);
  const nebula = new THREE.Group();
  for (let i = 0; i < 4; i++) {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(1.8 + i * 0.48, 0.035 + i * 0.01, 8, 128),
      luminousMaterial('deepspace', i, 0.13, false),
    );
    ring.rotation.x = 0.75 + i * 0.13;
    ring.rotation.y = -0.25 + i * 0.08;
    nebula.add(ring);
  }
  nebula.position.set(2.8, 0.2, -5.5);
  scene.add(nebula);
  updaters.push((t) => {
    stars.rotation.y = t * 0.012 + pointer.x * 0.035;
    stars.rotation.x = pointer.y * -0.025;
    nebula.rotation.z = t * 0.026;
    nebula.rotation.y = t * 0.016;
  });
}

function makeGraffiti() {
  const chaos = new THREE.Group();
  for (let i = 0; i < 24; i++) {
    const geometry = i % 2
      ? new THREE.TetrahedronGeometry(0.12 + Math.random() * 0.24)
      : new THREE.TorusGeometry(0.18 + Math.random() * 0.16, 0.045, 6, 16);
    const mesh = new THREE.Mesh(geometry, luminousMaterial('graffiti', i, 0.4, i % 3 === 0));
    mesh.position.set((Math.random() - 0.5) * 12, (Math.random() - 0.5) * 7, -2 - Math.random() * 4);
    mesh.userData.rate = 0.2 + Math.random() * 0.8;
    mesh.userData.baseY = mesh.position.y;
    chaos.add(mesh);
  }
  scene.add(chaos);
  updaters.push((t) => {
    chaos.children.forEach((m, i) => {
      m.rotation.z = t * m.userData.rate;
      m.position.y = m.userData.baseY + Math.sin(t * 1.1 + i) * 0.1;
    });
    chaos.rotation.z = Math.sin(t * 0.14) * 0.05;
  });
}

const builders = {
  aurora: makeAurora, neon: makeNeon, ocean: makeOcean, sunset: makeSunset,
  forest: makeForest, candy: makeCandy, slate: makeSlate, crimson: makeCrimson,
  honey: makeHoney, deepspace: makeDeepSpace, graffiti: makeGraffiti,
};

function ensureCanvas() {
  if (canvas) return;
  canvas = document.createElement('canvas');
  canvas.className = 'advanced-theme-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    cancelAnimationFrame(frame);
    frame = 0;
    document.documentElement.classList.add('advanced-theme-fallback');
  });
  canvas.addEventListener('webglcontextrestored', () => {
    document.documentElement.classList.remove('advanced-theme-fallback');
    initScene(activeTheme);
  });
  document.body.prepend(canvas);
}

function disposeScene() {
  cancelAnimationFrame(frame);
  frame = 0;
  updaters = [];
  if (scene) {
    scene.traverse((object) => {
      object.geometry?.dispose?.();
      if (Array.isArray(object.material)) object.material.forEach((m) => m.dispose?.());
      else object.material?.dispose?.();
    });
  }
  scene = null;
  renderer?.dispose?.();
  renderer = null;
  renderScale = 1;
  delete document.documentElement.dataset.advancedQuality;
  canvas?.remove();
  canvas = null;
}

function resize() {
  if (!renderer || !camera) return;
  renderer.setSize(
    Math.max(1, Math.round(innerWidth * renderScale)),
    Math.max(1, Math.round(innerHeight * renderScale)),
    false,
  );
  camera.aspect = innerWidth / Math.max(innerHeight, 1);
  camera.updateProjectionMatrix();
}

function animate() {
  frame = 0;
  if (!renderer || !scene || !camera) return;
  if (!visible) return;
  timer.update();
  const t = timer.getElapsed();
  updaters.forEach((update) => update(t));
  camera.position.x += (pointer.x * 0.18 - camera.position.x) * 0.025;
  camera.position.y += (pointer.y * 0.12 - camera.position.y) * 0.025;
  camera.lookAt(0, 0, -3);
  renderer.render(scene, camera);
  frame = requestAnimationFrame(animate);
}

function initScene(theme) {
  disposeScene();
  if (!ADVANCED.has(theme) || reduced.matches) {
    document.documentElement.classList.remove('advanced-theme-live');
    return;
  }
  ensureCanvas();
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: 'low-power' });
  } catch (error) {
    document.documentElement.classList.add('advanced-theme-fallback');
    canvas?.remove();
    canvas = null;
    renderer = null;
    return;
  }
  document.documentElement.classList.remove('advanced-theme-fallback');
  const gl = renderer.getContext();
  const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
  const rendererName = debugInfo
    ? String(gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL))
    : String(gl.getParameter(gl.RENDERER) || '');
  const software = /swiftshader|llvmpipe|software/i.test(rendererName);
  if (software) {
    // Software WebGL can block the main thread for 60–120ms per frame. Keep
    // Bark responsive and use the theme's layered CSS artwork instead.
    renderer.dispose();
    renderer = null;
    canvas?.remove();
    canvas = null;
    document.documentElement.classList.add('advanced-theme-fallback');
    document.documentElement.dataset.advancedQuality = 'static';
    return;
  }
  renderScale = innerWidth <= 768 ? 0.82 : 1;
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, innerWidth <= 768 ? 1.25 : 1.5));
  document.documentElement.dataset.advancedQuality = 'full';
  renderer.setClearColor(0x000000, 0);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(48, innerWidth / Math.max(innerHeight, 1), 0.1, 50);
  camera.position.set(0, 0, 7.5);
  timer = new THREE.Timer();
  builders[theme]?.();
  resize();
  document.documentElement.classList.add('advanced-theme-live');
  renderer.render(scene, camera);
  if (visible) frame = requestAnimationFrame(animate);
}

function setupGraffitiMenu(theme) {
  const enabled = theme === 'graffiti';
  document.body.classList.toggle('graffiti-theme', enabled);
  if (!enabled) {
    graffitiButton?.remove();
    graffitiButton = null;
    document.body.classList.remove('graffiti-menu-open');
    document.querySelectorAll('.main-content, .context-bar').forEach((element) => {
      element.inert = false;
    });
    const sidebar = document.querySelector('#sidebar');
    if (sidebar) {
      sidebar.toggleAttribute('inert', innerWidth <= 768 && !sidebar.classList.contains('open'));
    }
    return;
  }
  if (!graffitiButton) {
    graffitiButton = document.createElement('button');
    graffitiButton.type = 'button';
    graffitiButton.className = 'graffiti-pause-button';
    graffitiButton.setAttribute('aria-controls', 'sidebar');
    graffitiButton.setAttribute('aria-expanded', 'false');
    graffitiButton.innerHTML = '<span aria-hidden="true">Ⅱ</span> PAUSE';
    graffitiButton.addEventListener('click', () => toggleGraffitiMenu());
    document.body.append(graffitiButton);
  }
  document.querySelector('#sidebar')?.setAttribute('inert', '');
}

function toggleGraffitiMenu(force) {
  if (!document.body.classList.contains('graffiti-theme')) return;
  const open = force ?? !document.body.classList.contains('graffiti-menu-open');
  document.body.classList.toggle('graffiti-menu-open', open);
  graffitiButton?.setAttribute('aria-expanded', String(open));
  if (graffitiButton) {
    graffitiButton.innerHTML = open
      ? '<span aria-hidden="true">▶</span> RESUME'
      : '<span aria-hidden="true">Ⅱ</span> PAUSE';
    graffitiButton.setAttribute('aria-label', open ? 'Resume dashboard' : 'Pause and open navigation');
  }
  document.querySelectorAll('.main-content, .context-bar').forEach((element) => {
    element.inert = open;
  });
  document.querySelector('#sidebar')?.toggleAttribute('inert', !open);
  if (open) {
    window.setTimeout(() => {
      document.querySelector('#sidebar .nav-item, #sidebar a, #sidebar button')?.focus({ preventScroll: true });
    }, 50);
  } else {
    graffitiButton?.focus({ preventScroll: true });
  }
}

function applyTheme() {
  const theme = document.documentElement.getAttribute('data-theme') || 'steel';
  if (theme === activeTheme) return;
  activeTheme = theme;
  document.documentElement.toggleAttribute('data-advanced-theme', ADVANCED.has(theme));
  document.documentElement.setAttribute('data-advanced-name', theme);
  setupGraffitiMenu(theme);
  initScene(theme);
}

let pointerFrame = 0;
let nextPointerX = 0;
let nextPointerY = 0;
document.addEventListener('pointermove', (event) => {
  if (!ADVANCED.has(activeTheme)) return;
  nextPointerX = event.clientX;
  nextPointerY = event.clientY;
  if (pointerFrame) return;
  pointerFrame = requestAnimationFrame(() => {
    pointerFrame = 0;
    pointer.x = (nextPointerX / Math.max(innerWidth, 1)) * 2 - 1;
    pointer.y = -((nextPointerY / Math.max(innerHeight, 1)) * 2 - 1);
    document.documentElement.style.setProperty('--advanced-pointer-x', `${nextPointerX}px`);
    document.documentElement.style.setProperty('--advanced-pointer-y', `${nextPointerY}px`);
  });
}, { passive: true });
window.addEventListener('resize', resize, { passive: true });
document.addEventListener('visibilitychange', () => {
  visible = !document.hidden;
  if (!visible) {
    cancelAnimationFrame(frame);
    frame = 0;
    return;
  }
  timer = new THREE.Timer();
  if (renderer && !frame) frame = requestAnimationFrame(animate);
});
document.addEventListener('keydown', (event) => {
  if (activeTheme !== 'graffiti' || event.key !== 'Escape') return;
  if (!document.body.classList.contains('graffiti-menu-open')) return;
  const modalOpen = document.querySelector(
    '.palette-overlay[aria-hidden="false"], .dialog-overlay:not([hidden]), [aria-modal="true"]:focus-within',
  );
  if (modalOpen) return;
  event.preventDefault();
  toggleGraffitiMenu(false);
});
reduced.addEventListener('change', () => initScene(activeTheme));
new MutationObserver(applyTheme).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ['data-theme'],
});

applyTheme();
