// /carve: резьба 3D-тыквы на iPad (модуль 06, прототип).
import * as THREE from 'three';
import { Link } from '/web/shared/ws.js';
import { el, clear, toast, api, offlineBar } from '/web/shared/util.js';
import { loadModel, PumpkinStage, Carver, orbitCamera, snapshot, DEFAULT_CAM } from '/web/shared/pumpkin3d.js';

const $ = (id) => document.getElementById(id);
const DECOR_WIDTH = { s: 0.012, m: 0.024, l: 0.045 };  // доля высоты экрана
const PHI_MIN = 0.35;
const PHI_MAX = 2.75;
const R_MIN = 2.4;
const R_MAX = 9;
const DOUBLE_TAP_MS = 350;
const CLOSE_PX = 22;
const SIDE_ANGLE = 35 * Math.PI / 180;

const S = {
  players: [],
  player: null,
  knife: 'lasso',
  decorSize: 'm',
  mode: 'cut',           // без пера: что делает один палец
  penMode: false,        // увидели Apple Pencil: перо режет, пальцы вращают
  cam: { ...DEFAULT_CAM },
  savedCam: null,
  contour: null,         // открытый контур насквозь: {pts, closed, cam}
  stroke: null,          // штрих, который рисуется сейчас
  previewing: false,
  loading: false,        // пока грузится тыква, 3D не рисуем (нет промежуточных кадров)
  dirty: true,
};

// ---------------------------------------------------------------- голосование началось: тыквы больше не меняются
function setLocked(locked) {
  S.locked = locked;
  let b = document.getElementById('locked-bar');
  if (!b) {
    b = el('div', { id: 'locked-bar', class: 'locked-bar hidden' }, '🔒 Голосование началось — тыквы больше не сохраняются');
    document.body.append(b);
  }
  b.classList.toggle('hidden', !locked);
  const save = document.getElementById('save');
  const done = document.getElementById('done');
  if (save) save.disabled = locked;
  if (done) done.disabled = locked;
}

// ---------------------------------------------------------------- выбор игрока
function renderPlayers() {
  const box = clear($('players'));
  if (!S.players.length) {
    box.append(el('p', { class: 'muted', style: { gridColumn: '1 / -1' } }, 'Пока никого нет. Гости входят по QR с экрана телевизора.'));
    return;
  }
  for (const p of S.players) {
    box.append(el('button', { class: 'pcard', onclick: () => openEditor(p) },
      el('img', { src: p.avatar_url, alt: '' }),
      el('b', {}, p.name),
      p.pumpkin_version ? el('span', { class: 'done' }, '✓ тыква есть') : null));
  }
}

const link = new Link({
  role: 'carve',
  onStatus: offlineBar,
  onMessage: (m) => {
    if (m.t === 'snapshot' || m.t === 'players') {
      S.players = m.players;
      renderPlayers();
    }
    if (m.t === 'snapshot' || m.t === 'settings') setLocked(!!m.settings?.carve_locked);
    if (m.t === 'reset' && S.player) { toast('Вечер начат заново'); closeEditor(true); }
  },
});
link.connect();

// ---------------------------------------------------------------- 3D
let renderer, stage, carver, camera;
const glCanvas = $('gl');
const drawCanvas = $('draw');

async function init3d() {
  if (renderer) return;
  renderer = new THREE.WebGLRenderer({ canvas: glCanvas, antialias: true, preserveDrawingBuffer: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  glCanvas.addEventListener('webglcontextlost', (e) => {
    e.preventDefault();
    busy('Графика сбросилась. Перезагрузите страницу (несохранённая резьба пропадёт).');
  });
  const model = await loadModel();
  stage = new PumpkinStage(model);
  carver = new Carver(renderer, stage);
  camera = orbitCamera(S.cam, 1);
  resize();
  requestAnimationFrame(loop);
}

function resize() {
  if (!renderer) return;
  const w = glCanvas.clientWidth;
  const h = glCanvas.clientHeight;
  renderer.setSize(w, h, false);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  drawCanvas.width = Math.round(w * dpr);
  drawCanvas.height = Math.round(h * dpr);
  S.dirty = true;
  drawOverlay();
}
window.addEventListener('resize', resize);

let frames = 0;
let fpsT = performance.now();
const showFps = new URLSearchParams(location.search).has('fps');
if (showFps) $('fps').classList.remove('hidden');

function loop(t) {
  requestAnimationFrame(loop);
  if (!S.player || S.loading) return;
  if (S.previewing) { S.cam.theta += 0.004; S.dirty = true; }
  const flick = stage.tick(t / 1000);
  if (!S.dirty && !flick && !showFps) return;
  S.dirty = false;
  orbitCamera(S.cam, glCanvas.clientWidth / glCanvas.clientHeight, camera);
  renderer.render(stage.scene, camera);
  frames++;
  if (showFps && t - fpsT > 1000) {
    $('fps').textContent = `${Math.round(frames * 1000 / (t - fpsT))} к/с`;
    frames = 0;
    fpsT = t;
  }
}

// ---------------------------------------------------------------- редактор
function busy(text) {
  $('busy').classList.toggle('hidden', !text);
  $('busy-text').textContent = text || '';
}

async function openEditor(p) {
  S.player = p;
  $('picker').classList.add('hidden');
  $('editor').classList.remove('hidden');
  $('who-avatar').src = p.avatar_url;
  $('who-name').textContent = p.name;
  busy('Загружаем тыкву…');
  S.loading = true;
  S.contour = null;
  S.stroke = null;
  drawOverlay();
  try {
    await init3d();
    resize();
    const info = await api(`/api/pumpkin/${p.id}`);
    if (info.exists) {
      await carver.loadMasks(info.masks.through, info.masks.depth);
      S.savedCam = info.camera;
      S.cam = { ...DEFAULT_CAM, theta: info.camera.theta };
    } else {
      carver.reset();
      S.savedCam = null;
      S.cam = { ...DEFAULT_CAM };
    }
  } catch (e) {
    console.error(e);
    busy('');
    toast('Не получилось загрузить тыкву');
    S.loading = false;
    closeEditor(true);
    return;
  }
  S.loading = false;
  setPreview(false);
  stage.setDark(false);
  busy('');
  updateTools();
  S.dirty = true;
}

function closeEditor(force = false) {
  if (!force && carver?.canUndo && !confirm('Выйти без сохранения? Несохранённая резьба пропадёт.')) return;
  S.player = null;
  S.contour = null;
  setPreview(false);
  $('editor').classList.add('hidden');
  $('picker').classList.remove('hidden');
}

function updateTools() {
  for (const b of document.querySelectorAll('[data-knife]')) b.classList.toggle('on', b.dataset.knife === S.knife);
  for (const b of document.querySelectorAll('[data-size]')) b.classList.toggle('on', b.dataset.size === S.decorSize);
  for (const b of document.querySelectorAll('[data-mode]')) b.classList.toggle('on', b.dataset.mode === S.mode);
  $('sizes').classList.toggle('hidden', S.knife !== 'decor');
  $('mode').classList.toggle('hidden', S.penMode);
  $('pen-note').classList.toggle('hidden', !S.penMode);
  $('undo').disabled = !carver?.canUndo;
  $('candle').classList.toggle('on', !!stage?.dark);
  const c = S.contour;
  $('contour').classList.toggle('hidden', !c);
  if (c) {
    $('cut').classList.toggle('hidden', !c.closed);
    $('close-poly').classList.toggle('hidden', c.closed || c.pts.length < 3);
    $('contour-hint').textContent = c.closed ? '' : 'Тапы ставят точки, двойной тап — замкнуть';
  }
}

for (const b of document.querySelectorAll('[data-knife]')) b.addEventListener('click', () => { S.knife = b.dataset.knife; cancelContour(); updateTools(); });
for (const b of document.querySelectorAll('[data-size]')) b.addEventListener('click', () => { S.decorSize = b.dataset.size; updateTools(); });
for (const b of document.querySelectorAll('[data-mode]')) b.addEventListener('click', () => { S.mode = b.dataset.mode; updateTools(); });
$('no-pen').addEventListener('click', () => { S.penMode = false; updateTools(); });
$('back').addEventListener('click', () => closeEditor());
$('undo').addEventListener('click', () => { if (carver.undo()) { S.dirty = true; updateTools(); } });
$('restart').addEventListener('click', () => {
  if (!confirm('Начать заново? Вся резьба этой тыквы будет стёрта.')) return;
  carver.reset();
  cancelContour();
  S.dirty = true;
  updateTools();
});
$('candle').addEventListener('click', () => { stage.setDark(!stage.dark); S.dirty = true; updateTools(); });
$('cut').addEventListener('click', () => {
  const c = S.contour;
  if (!c?.closed) return;
  apply({ knife: 'through', shape: { type: 'poly', pts: c.pts }, cam: c.cam });
  cancelContour();
});
$('close-poly').addEventListener('click', () => closeContour());
$('cancel-contour').addEventListener('click', () => cancelContour());
document.addEventListener('gesturestart', (e) => e.preventDefault());

function apply(op) {
  carver.apply(op);
  S.dirty = true;
  updateTools();
}

function cancelContour() {
  S.contour = null;
  drawOverlay();
  updateTools();
}

function closeContour() {
  const c = S.contour;
  if (!c || c.pts.length < 3) return;
  c.closed = true;
  drawOverlay();
  updateTools();
}

function camSnapshot() {
  return { ...S.cam, aspect: glCanvas.clientWidth / glCanvas.clientHeight };
}

// ---------------------------------------------------------------- рисование поверх
function drawOverlay() {
  const W = drawCanvas.width;
  const H = drawCanvas.height;
  drawCanvas.width = W; // полный сброс холста и его состояния
  const g = drawCanvas.getContext('2d');
  const c = S.contour;
  if (c && c.pts.length) {
    g.beginPath();
    c.pts.forEach(([x, y], i) => (i ? g.lineTo(x * W, y * H) : g.moveTo(x * W, y * H)));
    if (c.closed) {
      g.closePath();
      g.fillStyle = 'rgba(255, 220, 120, 0.28)';
      g.fill();
    }
    g.lineWidth = 3 * (W / glCanvas.clientWidth);
    g.setLineDash(c.closed ? [10, 8] : []);
    g.strokeStyle = '#ffd27a';
    g.stroke();
    g.setLineDash([]);
    if (!c.closed && c.poly) {
      for (const [x, y] of c.pts) { g.beginPath(); g.arc(x * W, y * H, 6, 0, Math.PI * 2); g.fillStyle = '#ffd27a'; g.fill(); }
    }
  }
  const s = S.stroke;
  if (s && s.pts.length) {
    g.beginPath();
    s.pts.forEach(([x, y], i) => (i ? g.lineTo(x * W, y * H) : g.moveTo(x * W, y * H)));
    g.lineCap = g.lineJoin = 'round';
    g.lineWidth = s.width * H;
    g.strokeStyle = 'rgba(255, 210, 130, 0.65)';
    g.stroke();
  }
}

// ---------------------------------------------------------------- ввод
const pointers = new Map(); // id -> {x, y, role, type, sx, sy}
let lastTap = null;

function norm(e) {
  const r = glCanvas.getBoundingClientRect();
  return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
}

function cameraLocked() {
  return !!S.contour || S.previewing === 'saving';
}

function roleFor(e) {
  if (e.pointerType === 'pen') return 'tool';
  if (S.penMode) return 'camera';
  if (e.pointerType === 'mouse') return e.button === 2 || S.mode === 'rotate' ? 'camera' : 'tool';
  // палец: второй палец всегда камера, а начатый штрих отменяется
  if ([...pointers.values()].some((p) => p.role === 'tool' && p.type !== 'pen')) return 'camera';
  if (pointers.size) return 'camera';
  return S.mode === 'cut' ? 'tool' : 'camera';
}

glCanvas.addEventListener('contextmenu', (e) => e.preventDefault());

glCanvas.addEventListener('pointerdown', (e) => {
  if (!S.player || S.previewing) return;
  if (e.pointerType === 'pen' && !S.penMode) { S.penMode = true; updateTools(); }
  // перо на экране: касания ладонью игнорируем
  if (S.penMode && e.pointerType === 'touch' && [...pointers.values()].some((p) => p.type === 'pen')) return;
  const role = roleFor(e);
  if (role === 'camera' && e.pointerType !== 'pen') {
    // второй палец во время штриха: штрих отменяется, жест уходит камере
    for (const p of pointers.values()) {
      if (p.role === 'tool' && p.type !== 'pen') { p.role = 'camera'; abortToolStroke(); }
    }
  }
  try { glCanvas.setPointerCapture(e.pointerId); } catch { /* синтетическое событие */ }
  const [x, y] = norm(e);
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, role, type: e.pointerType, sx: e.clientX, sy: e.clientY, t: performance.now() });
  if (role === 'tool') toolDown(x, y);
});

glCanvas.addEventListener('pointermove', (e) => {
  const p = pointers.get(e.pointerId);
  if (!p) return;
  const dx = e.clientX - p.x;
  const dy = e.clientY - p.y;
  p.x = e.clientX;
  p.y = e.clientY;
  if (p.role === 'tool') {
    const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ce of evs.length ? evs : [e]) toolMove(...norm(ce));
    return;
  }
  if (cameraLocked()) return;
  const cams = [...pointers.values()].filter((q) => q.role === 'camera');
  if (cams.length >= 2) {
    const [a, b] = cams;
    const d = Math.hypot(a.x - b.x, a.y - b.y);
    if (a.pd) S.cam.radius = Math.min(R_MAX, Math.max(R_MIN, S.cam.radius * a.pd / d));
    a.pd = d;
    S.cam.theta -= dx * 0.004;
    S.cam.phi = Math.min(PHI_MAX, Math.max(PHI_MIN, S.cam.phi - dy * 0.004));
  } else {
    S.cam.theta -= dx * 0.008;
    S.cam.phi = Math.min(PHI_MAX, Math.max(PHI_MIN, S.cam.phi - dy * 0.008));
  }
  S.dirty = true;
});

function pointerEnd(e) {
  const p = pointers.get(e.pointerId);
  if (!p) return;
  pointers.delete(e.pointerId);
  for (const q of pointers.values()) q.pd = null;
  if (p.role === 'tool') toolUp(norm(e), p, e.type === 'pointercancel');
  else if (cameraLocked() && Math.hypot(p.x - p.sx, p.y - p.sy) > 20) toast('Сначала вырежьте контур или отмените его');
}
glCanvas.addEventListener('pointerup', pointerEnd);
glCanvas.addEventListener('pointercancel', pointerEnd);

glCanvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (cameraLocked()) return;
  S.cam.radius = Math.min(R_MAX, Math.max(R_MIN, S.cam.radius * Math.exp(e.deltaY * 0.001)));
  S.dirty = true;
}, { passive: false });

// ---------------------------------------------------------------- ножи
function toolDown(x, y) {
  if (S.knife === 'lasso') {
    if (S.contour?.closed) S.contour = null;
    S.contour = { pts: [[x, y]], closed: false, poly: false, cam: camSnapshot(), drawing: true };
  } else if (S.knife === 'decor') {
    S.stroke = { pts: [[x, y]], width: DECOR_WIDTH[S.decorSize], cam: camSnapshot() };
  }
  drawOverlay();
  updateTools();
}

function toolMove(x, y) {
  const minStep = 2 / glCanvas.clientHeight;
  if (S.knife === 'lasso' && S.contour?.drawing) {
    const last = S.contour.pts[S.contour.pts.length - 1];
    if (Math.hypot(x - last[0], y - last[1]) > minStep) S.contour.pts.push([x, y]);
  } else if (S.knife === 'decor' && S.stroke) {
    const last = S.stroke.pts[S.stroke.pts.length - 1];
    if (Math.hypot(x - last[0], y - last[1]) > minStep) S.stroke.pts.push([x, y]);
  } else {
    return;
  }
  drawOverlay();
}

function toolUp([x, y], p, cancelled) {
  if (S.knife === 'lasso') {
    const c = S.contour;
    if (!c?.drawing) return;
    c.drawing = false;
    if (cancelled || c.pts.length < 3 || polyArea(c.pts) < 0.0004) { cancelContour(); return; }
    c.closed = true;
  } else if (S.knife === 'decor') {
    const s = S.stroke;
    S.stroke = null;
    if (s && !cancelled) apply({ knife: 'decor', shape: { type: 'stroke', pts: s.pts, width: s.width }, cam: s.cam });
  } else if (S.knife === 'poly') {
    if (cancelled || Math.hypot(p.x - p.sx, p.y - p.sy) > 12) return; // не тап
    const now = performance.now();
    const px = [x, y];
    if (!S.contour) S.contour = { pts: [], closed: false, poly: true, cam: camSnapshot() };
    const c = S.contour;
    if (c.closed) return;
    const W = glCanvas.clientWidth;
    const H = glCanvas.clientHeight;
    const near = (a, b) => Math.hypot((a[0] - b[0]) * W, (a[1] - b[1]) * H) < CLOSE_PX;
    const dbl = lastTap && now - lastTap.t < DOUBLE_TAP_MS && near(lastTap.px, px);
    if ((dbl || (c.pts.length >= 3 && near(c.pts[0], px))) && c.pts.length >= 3) {
      closeContour();
      lastTap = null;
      return;
    }
    if (!dbl) c.pts.push(px);
    lastTap = { t: now, px };
  }
  drawOverlay();
  updateTools();
}

function abortToolStroke() {
  if (S.knife === 'lasso' && S.contour?.drawing) S.contour = null;
  S.stroke = null;
  drawOverlay();
  updateTools();
}

function polyArea(pts) {
  let a = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % pts.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a / 2);
}

// ---------------------------------------------------------------- «Готово»: предпросмотр и сохранение
function frontTheta() {
  // «спереди» — откуда в основном резали (круговое среднее углов камеры)
  const angles = carver.ops.map((o) => o.cam.theta);
  if (!angles.length) return S.savedCam ? S.savedCam.theta : S.cam.theta;
  const sx = angles.reduce((s, a) => s + Math.sin(a), 0);
  const cx = angles.reduce((s, a) => s + Math.cos(a), 0);
  return Math.atan2(sx, cx);
}

function setPreview(on) {
  S.previewing = on;
  $('preview').classList.toggle('hidden', !on);
  $('done').classList.toggle('hidden', !!on);
  document.querySelector('.tools').classList.toggle('hidden', !!on);
  if (stage) stage.setDark(!!on);
  S.dirty = true;
  updateTools();
}

$('done').addEventListener('click', () => {
  if (S.contour) cancelContour();
  S.cam = { ...DEFAULT_CAM, theta: frontTheta() };
  setPreview(true);
});
$('preview-back').addEventListener('click', () => setPreview(false));

$('save').addEventListener('click', async () => {
  const front = { ...DEFAULT_CAM, theta: frontTheta() };
  S.previewing = 'saving';
  busy('Сохраняем тыкву…');
  try {
    const masks = await carver.exportMasks();
    const lit = await snapshot(renderer, stage, front, { dark: false });
    const dark = await snapshot(renderer, stage, front, { dark: true });
    const side = await snapshot(renderer, stage, { ...front, theta: front.theta + SIDE_ANGLE }, { dark: true });
    const fd = new FormData();
    fd.append('through.png', masks.through, 'through.png');
    fd.append('depth.png', masks.depth, 'depth.png');
    fd.append('lit.jpg', lit, 'lit.jpg');
    fd.append('dark.jpg', dark, 'dark.jpg');
    fd.append('side.jpg', side, 'side.jpg');
    fd.append('camera', JSON.stringify(front));
    const r = await api(`/api/pumpkin/${S.player.id}`, fd);
    busy('');
    if (!r.ok) { S.previewing = true; toast(r.error || 'Не сохранилось', 4000); return; }
    toast(`Тыква ${S.player.name} сохранена!`, 3000);
    closeEditor(true);
  } catch (e) {
    console.error(e);
    busy('');
    S.previewing = true;
    toast('Не сохранилось, попробуйте ещё раз', 4000);
  }
});

// для автотестов и отладки на iPad
window.__carve = { S, apply: (op) => apply(op), get carver() { return carver; }, get stage() { return stage; }, openEditor };
