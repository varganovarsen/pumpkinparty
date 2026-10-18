// Песочница «Бомбы»: настоящие mountBomb (web/play/bomb.js) и сцена ТВ (web/tv/scenes/bomb.js)
// на подставном сервере (engine_bomb.js). Ты — Маша, остальные четверо — боты.
// Собирается: python tools/make_sandbox.py bomb.
import { el, clear } from '/web/shared/util.js';
import { mountBomb } from '/web/play/bomb.js';
import { createBomb } from '/sandbox/engine_bomb.js';

const DATA = window.SANDBOX;
const ME = 1;
const NAMES = ['Маша', 'Аня', 'Боря', 'Вика', 'Гоша'];
const PLAYERS = NAMES.map((name, i) => ({ id: i + 1, name, avatar_url: DATA.avatars[i % DATA.avatars.length] }));
const bomb = createBomb(DATA, PLAYERS, ME, () => push());
const { B } = bomb;
const now = () => Date.now();
const snapshot = bomb.snapshot;

// ---------------------------------------------------------------- телефон и ТВ
const link = {
  serverNow: now,
  async cmd(name) {
    await new Promise((r) => setTimeout(r, 60));
    if (name === 'bomb_pass') return bomb.pass(ME);
    return { ok: false, error: `Песочница не знает команду ${name}` };
  },
};

const app = document.getElementById('app');
const topEl = el('div', { class: 'topbar' });
const phoneEl = el('div');
app.append(topEl, phoneEl);
const phone = mountBomb(phoneEl, link);

const tvWrap = el('div', { class: 'sb-tv', hidden: true });
const tvFrame = el('iframe', { class: 'sb-tv-frame', title: 'Экран ТВ', srcdoc: DATA.tvHtml });
tvWrap.append(tvFrame);
document.body.append(tvWrap);
let tv = null;
const tvCtx = { link, sfx: () => Promise.resolve(), bomb: null };
tvFrame.addEventListener('load', () => {
  const w = tvFrame.contentWindow;
  const boot = () => {
    if (!w.__mount) { setTimeout(boot, 30); return; }
    tvCtx.bomb = snapshot('tv');
    tv = w.__mount(w.document.getElementById('root'), tvCtx);
  };
  boot();
});
function fitTv() {
  const scale = Math.min(tvWrap.clientWidth / 1280, tvWrap.clientHeight / 720);
  tvFrame.style.transform = `scale(${scale})`;
}
window.addEventListener('resize', fitTv);

let view = 'phone';
function setView(v) {
  view = v;
  tvWrap.hidden = v !== 'tv';
  app.hidden = v === 'tv';
  if (v === 'tv') fitTv();
  renderBar();
}

function renderTop() {
  const sum = bomb.points(ME);
  clear(topEl).append(el('img', { class: 'avatar', src: PLAYERS[0].avatar_url, alt: '' }),
    el('div', {}, el('div', { class: 'name' }, 'Маша')), el('div', { class: 'score' }, `${sum} очк.`));
}

function push() {
  phone.update(snapshot('player'));
  if (tv) { tvCtx.bomb = snapshot('tv'); tv.onMessage({ t: 'bomb' }); }
  renderTop();
  renderBar();
  renderSheet();
}

// ---------------------------------------------------------------- пульт ведущего
const bar = el('div', { class: 'sb-bar' });
const sheet = el('div', { class: 'sb-sheet', hidden: true });
document.body.append(sheet, bar);

const PHASE = { idle: 'ждём', topic: 'тема', countdown: 'отсчёт', running: 'идёт', boom: 'взрыв', round_over: 'итоги' };

function renderBar() {
  const [label, fn] = bomb.hostAction();
  const status = B.round ? `Р${B.round} · ${PHASE[B.phase]}` : PHASE[B.phase];
  clear(bar).append(
    el('button', { class: 'sb-nav', 'aria-label': view === 'tv' ? 'Показать телефон' : 'Показать ТВ', onclick: () => setView(view === 'tv' ? 'phone' : 'tv') }, view === 'tv' ? '📱' : '📺'),
    el('button', { class: 'sb-label', onclick: () => { sheet.hidden = !sheet.hidden; renderBar(); renderSheet(); } }, status, el('span', { class: 'sb-hint' }, sheet.hidden ? 'пульт ведущего ▴' : 'скрыть ▾')),
    el('button', { class: 'sb-nav sb-act', disabled: !fn, onclick: () => fn?.() }, label || '…'),
  );
}

function seg(title, options, value, onPick) {
  return el('div', { class: 'sb-field' },
    el('div', { class: 'sb-title' }, title),
    el('div', { class: 'sb-seg' }, options.map(([v, label]) =>
      el('button', { class: v === value ? 'on' : '', onclick: () => onPick(v) }, label))));
}

const TIMINGS = [['5/1/2', '5 → 4 → 3 → 2 с'], ['8/2/3', '8 → 6 → 4 → 3 с'], ['4/1/1', '4 → 3 → 2 → 1 с']];

function renderSheet() {
  if (sheet.hidden) return;
  const t = `${B.timing.start_seconds}/${B.timing.step_seconds}/${B.timing.min_seconds}`;
  clear(sheet).append(
    seg('Время на ход', TIMINGS, t, (v) => {
      const [a, b, c] = v.split('/').map(Number);
      B.timing = { start_seconds: a, step_seconds: b, min_seconds: c };
      push();
    }),
    seg('Боты', [['slow', 'часто не успевают'], ['normal', 'иногда'], ['fast', 'почти всегда успевают']], B.skill, (v) => { B.skill = v; push(); }),
    seg('Маша (ты)', [[true, 'играет'], [false, 'смотрит раунд']], B.meOn, (v) => { if (!bomb.live()) { B.meOn = v; push(); } }),
    el('div', { class: 'sb-row' },
      el('button', { disabled: B.phase !== 'topic', onclick: bomb.pickTopic }, 'Другая тема'),
      el('button', { disabled: !bomb.live(), onclick: bomb.abort }, 'Прервать раунд'),
      el('button', { onclick: bomb.reset }, 'Всё сначала')),
    el('p', { class: 'sb-foot' }, 'Экраны — настоящие web/play/bomb.js и web/tv/scenes/bomb.js. Сервер подставной, темы из content/bomb.yaml. Звуков в песочнице нет.'),
  );
}

push();
