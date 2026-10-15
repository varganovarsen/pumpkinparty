// Экран телевизора: одна сцена за раз, модули сцен грузятся лениво (модуль 01).
import { Link } from '/web/shared/ws.js';
import { el, clear } from '/web/shared/util.js';

// Сцены с собственным модулем; остальные пока показывают заглушку.
const SCENE_MODULES = {
  ambient: './scenes/ambient.js',
  quiz: './scenes/quiz.js',
  game: './scenes/game.js',
  timer: './scenes/timer.js',
  carve_vote: './scenes/carve_vote.js',
  carve_reveal: './scenes/carve_reveal.js',
  rating_reveal: './scenes/rating_reveal.js',
  final_photo: './scenes/final_photo.js',
  slideshow: './scenes/slideshow.js',
  download: './scenes/download.js',
};
// Модули сцен с состоянием от сервера: снимок и события {t: имя, имя: {...}}.
const MODULES = ['quiz', 'game', 'vote', 'timer', 'finale'];

const stage = document.getElementById('stage');
const overlay = document.getElementById('overlay');
const ctx = { link: null, scene: null, settings: {}, players: [], joinUrl: '', stubs: [], head: null, quiz: null };
let current = null; // {name, mod, inst}
let mounting = Promise.resolve();

export function sfx(name) {
  const a = new Audio(`/assets/sfx/${name}.mp3`);
  return a.play().catch(() => {});
}

function tvToast(text, ms = 3000) {
  const t = el('div', { class: 'tv-toast' }, text);
  overlay.append(t);
  setTimeout(() => t.remove(), ms);
}

async function mountScene(force = false) {
  const name = ctx.scene.scene;
  if (current && current.name === name && !force) {
    current.inst.update?.(ctx);
    return;
  }
  current?.inst.unmount?.();
  clear(stage);
  const path = SCENE_MODULES[name] || './scenes/stub.js';
  let mod;
  try {
    mod = await import(path);
  } catch (e) {
    console.error(e);
    mod = await import('./scenes/stub.js');
  }
  if (ctx.scene.scene !== name) return; // пока грузили, сцена сменилась
  const root = el('div', { class: 'scene-root' });
  stage.append(root);
  current = { name, mod, inst: mod.mount(root, ctx) || {} };
}

function remount(force = false) {
  mounting = mounting.then(() => mountScene(force)).catch((e) => console.error(e));
}

function onMessage(m) {
  switch (m.t) {
    case 'snapshot':
      ctx.scene = m.scene; ctx.settings = m.settings; ctx.players = m.players;
      ctx.joinUrl = m.join_url; ctx.stubs = m.stubs; ctx.head = m.head;
      for (const name of MODULES) ctx[name] = m[name];
      remount(true);
      break;
    case 'scene':
      ctx.scene = m;
      if (m.scene !== 'ambient') ctx.head = null;
      remount(false);
      break;
    case 'settings':
      ctx.settings = m.settings;
      current?.inst.update?.(ctx);
      break;
    case 'players':
      ctx.players = m.players;
      current?.inst.update?.(ctx);
      break;
    case 'head':
      ctx.head = m.head;
      current?.inst.onMessage?.(m);
      break;
    case 'quiz': case 'game': case 'vote': case 'timer': case 'finale':
      ctx[m.t] = m[m.t];
      current?.inst.onMessage?.(m);
      break;
    case 'shot':
      showShot(m);
      break;
    case 'sound_test':
      sfx('correct');
      tvToast('🔊 Тест звука');
      break;
    case 'reload':
      remount(true);
      break;
    case 'error':
      clear(stage).append(el('div', { class: 'stub-scene' }, el('h1', {}, '⛔'), el('p', { class: 'meta' }, m.error)));
      break;
    default:
      current?.inst.onMessage?.(m);
  }
}

// Случайный кадр вебки: «Сейчас вылетит птичка!» 3 с → щелчок → фото 4 с с 📷 (поверх любой сцены).
let shotEl = null;
function showShot(m) {
  shotEl?.remove();
  shotEl = null;
  if (m.stage === 'countdown') {
    shotEl = el('div', { class: 'shot-overlay' }, el('div', { class: 'shot-text' }, 'Сейчас вылетит птичка! 🐦'));
  } else if (m.stage === 'taken') {
    sfx('shutter');
    shotEl = el('div', { class: 'shot-overlay flash' }, el('img', { src: m.photo.url, alt: '' }), el('div', { class: 'shot-cam' }, '📷'));
    const mine = shotEl;
    setTimeout(() => { if (shotEl === mine) { mine.remove(); shotEl = null; } }, (m.seconds || 4) * 1000);
  }
  if (shotEl) overlay.append(shotEl);
}

function startScreen() {
  const box = document.getElementById('start');
  let allowed = false;
  try { allowed = navigator.getAutoplayPolicy?.('mediaelement') === 'allowed'; } catch { /* старый браузер */ }
  if (allowed) return;
  box.classList.remove('hidden');
  document.getElementById('start-btn').addEventListener('click', () => {
    sfx('fact-notify');
    box.classList.add('hidden');
    stage.querySelectorAll('video').forEach((v) => v.play().catch(() => {}));
  });
}

ctx.link = new Link({ role: 'tv', onMessage, onStatus: (on) => document.body.classList.toggle('offline', !on) });
ctx.sfx = sfx;
ctx.link.connect();
startScreen();
