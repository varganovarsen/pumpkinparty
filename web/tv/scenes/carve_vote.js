// Аллея тыкв на ТВ (модуль 06, сцена carve_vote): живое 3D в темноте, анонимные номера.
// Если средняя частота кадров ниже 24 к/с в течение 5 секунд — показ снимков слайдами.
import * as THREE from 'three';
import { el, clear } from '/web/shared/util.js';
import { loadModel, buildPumpkin, pumpkinUniforms, applyCandle, flickerAt, MaskBank } from '/web/shared/pumpkin3d.js';

const FPS_MIN = 24;          // по умолчанию; берётся из config.yaml (carve.fps_fallback_threshold)
const FPS_WARMUP = 5000;     // первые секунды не меряем: грузятся маски и компилируются шейдеры
const FPS_WINDOW = 5000;
const SLIDE_SECONDS = 4;

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene alley-tv' });
  const canvas = el('canvas', { class: 'alley-canvas' });
  const labels = el('div', { class: 'alley-labels' });
  const head = el('div', { class: 'alley-head' });
  const slides = el('div', { class: 'alley-slides hidden' });
  box.append(canvas, slides, labels, head);
  root.append(box);

  let renderer = null;
  let raf = 0;
  let alive = true;
  let mode = '3d';
  let pumpkins = [];        // {n, parts, mask, label}
  let slideTimer = null;
  let bank = null;
  const camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.1, 100);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x050302);
  // «лунный» свет: тыквы видны в темноте, но главное — свечи внутри
  scene.add(new THREE.HemisphereLight(0xbfd0ff, 0x1a0f08, 0.35));
  const moon = new THREE.DirectionalLight(0x9fb4ff, 0.6);
  moon.position.set(-3, 5, 6);
  scene.add(moon);
  let builtFor = '';

  function header() {
    const v = ctx.vote || {};
    clear(head).append(
      el('div', { class: 'qt-big small' }, v.phase === 'closed' ? 'Голосование закрыто' : 'Аллея тыкв'),
      el('div', { class: 'qt-sub' }, v.phase === 'open'
        ? `Голосуйте на телефоне! Проголосовали ${v.voted_count} из ${v.voters_total}`
        : v.phase === 'closed' ? 'Смотрим итоги…' : 'Скоро голосование'));
  }

  // ---------------------------------------------------------------- слайды (запасной вариант)
  function startSlides() {
    if (mode === 'slides') return;
    mode = 'slides';
    cancelAnimationFrame(raf);
    canvas.classList.add('hidden');
    labels.classList.add('hidden');
    slides.classList.remove('hidden');
    const entries = ctx.vote?.entries || [];
    let i = 0;
    const show = () => {
      if (!entries.length) return;
      const e = entries[i % entries.length];
      clear(slides).append(el('img', { src: e.shots.dark, alt: '' }), el('div', { class: 'alley-num big' }, `№${e.n}`));
      i++;
      slideTimer = setTimeout(show, SLIDE_SECONDS * 1000);
    };
    show();
  }

  // ---------------------------------------------------------------- 3D
  async function build() {
    const entries = ctx.vote?.entries || [];
    const sig = entries.map((e) => `${e.n}:${e.masks.through}`).join('|');
    if (sig === builtFor) return;
    builtFor = sig;
    for (const p of pumpkins) { scene.remove(p.parts.group); p.mask?.dispose(); }
    pumpkins = [];
    clear(labels);
    if (!entries.length) return;
    if (!renderer) {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    }
    const model = await loadModel();
    bank?.dispose();
    bank = new MaskBank(renderer, model, 1024);
    const n = entries.length;
    const spread = Math.min(Math.PI * 0.9, 0.42 * n);
    for (let i = 0; i < n; i++) {
      const e = entries[i];
      const uniforms = pumpkinUniforms();
      const parts = buildPumpkin(model, uniforms);
      const a = n === 1 ? 0 : -spread / 2 + (spread * i) / (n - 1);
      const R = 6;
      parts.group.position.set(Math.sin(a) * R, 0, -Math.cos(a) * R + R);
      parts.group.rotation.y = Math.random() * Math.PI * 2;
      scene.add(parts.group);
      const label = el('div', { class: 'alley-num' }, `№${e.n}`);
      labels.append(label);
      const p = { n: e.n, parts, label, mask: null, phase: Math.random() * 10, spin: 0.15 + Math.random() * 0.1 };
      pumpkins.push(p);
      bank.load(e.masks.through, e.masks.depth).then((rt) => {
        if (!alive) { rt.dispose(); return; }
        p.mask = rt;
        uniforms.carveMask.value = rt.texture;
      }).catch(() => { /* маска не загрузилась — тыква без резьбы */ });
    }
    // кадр по ширине ряда: крайние тыквы с запасом в радиус тыквы
    const halfW = Math.max(1.6, Math.sin(spread / 2) * 6 + 1.4);
    const aspect = (canvas.clientWidth || 16) / (canvas.clientHeight || 9);
    const dist = halfW / (Math.tan((camera.fov * Math.PI) / 360) * aspect);
    const zMid = n === 1 ? 0 : (6 - Math.cos(spread / 2) * 6) / 2;
    camera.position.set(0, 1.4, zMid + dist + 1.2);
    camera.lookAt(0, -0.15, zMid);
  }

  function startLive() {
    if (mode === '3d') return;
    mode = '3d';
    clearTimeout(slideTimer);
    slides.classList.add('hidden');
    canvas.classList.remove('hidden');
    labels.classList.remove('hidden');
    fpsStart = 0;
    frames = 0;
    builtAt = performance.now();
    raf = requestAnimationFrame(loop);
  }

  function applyMode() {
    if (ctx.settings.alley_slides) startSlides();
    else if (mode === 'slides' && forced) startLive();
    forced = !!ctx.settings.alley_slides;
  }
  let forced = false;
  let builtAt = performance.now();
  let fpsStart = 0;
  let frames = 0;
  let last = performance.now();
  function loop(t) {
    if (!alive || mode !== '3d') return;
    raf = requestAnimationFrame(loop);
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (renderer && (canvas.width !== Math.round(w * renderer.getPixelRatio()))) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    const dt = Math.min(0.1, (t - last) / 1000);
    last = t;
    const v = new THREE.Vector3();
    for (const p of pumpkins) {
      p.parts.group.rotation.y += p.spin * dt;
      applyCandle(p.parts, flickerAt(t / 1000, p.phase));
      p.parts.flame.scale.set(1, 1.8 + 0.25 * Math.sin(t / 1000 * 11 + p.phase), 1);
      v.set(0, -1.1, 0).applyMatrix4(p.parts.group.matrixWorld).project(camera);
      p.label.style.left = `${(v.x * 0.5 + 0.5) * 100}%`;
      p.label.style.top = `${(-v.y * 0.5 + 0.5) * 100}%`;
    }
    if (renderer) renderer.render(scene, camera);
    // запасной режим по частоте кадров (после прогрева)
    if (t - builtAt < FPS_WARMUP || !pumpkins.length) return;
    if (!fpsStart) fpsStart = t;
    frames++;
    if (t - fpsStart >= FPS_WINDOW) {
      const fps = (frames * 1000) / (t - fpsStart);
      if (fps < (ctx.config?.fps_fallback_threshold || FPS_MIN)) { console.warn(`Аллея: ${fps.toFixed(1)} к/с, переход на снимки`); startSlides(); return; }
      fpsStart = t;
      frames = 0;
    }
  }

  header();
  build().then(() => {
    builtAt = performance.now();
    if (ctx.settings.alley_slides) { forced = true; startSlides(); } else raf = requestAnimationFrame(loop);
  }).catch((e) => { console.error(e); startSlides(); });

  return {
    update() { header(); applyMode(); },
    onMessage(m) {
      if (m.t !== 'vote') return;
      header();
      if (mode === '3d') build();
    },
    unmount() {
      alive = false;
      cancelAnimationFrame(raf);
      clearTimeout(slideTimer);
      for (const p of pumpkins) {
        p.mask?.dispose();
        p.parts.group.traverse((o) => { if (o.isMesh) { o.material.dispose?.(); if (o.geometry !== p.model?.body) o.geometry.dispose?.(); } });
      }
      bank?.dispose();
      renderer?.dispose();
      renderer?.forceContextLoss(); // освободить WebGL-контекст сразу, а не при сборке мусора
    },
  };
}
