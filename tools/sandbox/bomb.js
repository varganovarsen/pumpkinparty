// Песочница «Бомбы»: настоящие mountBomb (web/play/bomb.js) и сцена ТВ (web/tv/scenes/bomb.js)
// на подставном сервере. Ты — Маша, остальные четверо — боты: передают бомбу сами, иногда не успевают.
// Логика раунда повторяет server/bomb.py. Собирается: python tools/make_sandbox.py bomb.
const DATA = window.SANDBOX;
const ME = 1;
const NAMES = ['Маша', 'Аня', 'Боря', 'Вика', 'Гоша'];
const PLAYERS = NAMES.map((name, i) => ({ id: i + 1, name, avatar_url: DATA.avatars[i % DATA.avatars.length] }));
const COUNTDOWN = 3500;
const ROULETTE = 4000;
const BOOM_PAUSE = 3000;
const SKILL = { slow: 0.35, normal: 0.18, fast: 0.06 }; // доля ходов, на которых бот не успевает

const B = {
  phase: 'idle', round: 0, topic: null, revealAt: 0, used: [], order: PLAYERS.map((p) => p.id),
  alive: [], out: [], holder: null, next: null, startAt: 0, turnStarted: 0, deadline: 0, turnSec: 0,
  lap: 0, lapPasses: 0, passes: 0, boom: null, resumeAt: 0, results: {},
  timing: { ...DATA.timing }, skill: 'normal', meOn: true,
};
let botTimer = 0;

const now = () => Date.now();
const who = (id) => {
  const p = PLAYERS.find((x) => x.id === id);
  return p ? { player_id: p.id, name: p.name, avatar_url: p.avatar_url, in_scoring: true } : null;
};
const lineup = () => B.order.filter((id) => id !== ME || B.meOn);
const turnSeconds = () => Math.max(B.timing.min_seconds, B.timing.start_seconds - B.lap * B.timing.step_seconds);
const after = (id, list) => list[(list.indexOf(id) + 1) % list.length];
const live = () => ['countdown', 'running', 'boom'].includes(B.phase);
const done = () => B.phase === 'round_over' && B.round >= DATA.rounds;

// ---------------------------------------------------------------- ход раунда (как server/bomb.py)
function pickTopic() {
  if (live()) return;
  if (B.phase !== 'topic') {
    if (B.round >= DATA.rounds) return;
    B.round += 1;
  }
  const pool = DATA.topics.filter((t) => !B.used.includes(t) && t !== B.topic);
  const list = pool.length ? pool : DATA.topics.filter((t) => t !== B.topic);
  B.topic = list[Math.floor(Math.random() * list.length)];
  Object.assign(B, { phase: 'topic', revealAt: now() + ROULETTE, alive: [], out: [], holder: null, boom: null });
  push();
}

function start() {
  if (B.phase !== 'topic') return;
  let alive = lineup();
  const shift = (B.round - 1) % alive.length;
  alive = alive.slice(shift).concat(alive.slice(0, shift));
  B.used.push(B.topic);
  Object.assign(B, { phase: 'countdown', alive, out: [], startAt: now() + COUNTDOWN, holder: null, next: alive[0],
    lap: 0, lapPasses: 0, passes: 0, boom: null, revealAt: Math.min(B.revealAt, now()) });
  push();
}

function turn(id) {
  const sec = turnSeconds();
  Object.assign(B, { phase: 'running', holder: id, next: null, turnStarted: now(), deadline: now() + sec * 1000, turnSec: sec, boom: null });
  clearTimeout(botTimer);
  if (id !== ME) {
    // бот: думает и передаёт, иногда не успевает
    const miss = Math.random() < SKILL[B.skill];
    const think = miss ? sec * 1000 + 500 : 400 + Math.random() * Math.min(sec * 850, 2600);
    botTimer = setTimeout(() => { if (B.holder === id && B.phase === 'running') pass(id); }, think);
  }
}

function pass(id) {
  if (B.phase !== 'running') return { ok: false, code: 'closed', error: 'Бомба сейчас не ходит' };
  if (B.holder !== id) return { ok: false, code: 'not_holder', error: 'Бомба не у тебя' };
  if (now() >= B.deadline) return { ok: false, code: 'late', error: 'Не успел — бомба взорвалась!' };
  const nxt = after(id, B.alive);
  B.passes += 1;
  B.lapPasses += 1;
  if (B.lapPasses >= B.alive.length) { B.lap += 1; B.lapPasses = 0; }
  turn(nxt);
  push();
  return { ok: true, to: nxt };
}

function explode() {
  if (B.phase !== 'running') return;
  clearTimeout(botTimer);
  const id = B.holder;
  const nxt = after(id, B.alive);
  B.alive = B.alive.filter((x) => x !== id);
  B.out.push(id);
  B.boom = { player_id: id, place: B.alive.length + 1 };
  if (B.lapPasses >= B.alive.length) { B.lap += 1; B.lapPasses = 0; }
  if (B.alive.length <= 1) { finishRound(); return; }
  Object.assign(B, { phase: 'boom', holder: null, next: nxt, deadline: 0, resumeAt: now() + BOOM_PAUSE });
  push();
}

function finishRound() {
  const finishers = B.alive.concat([...B.out].reverse());
  B.results[B.round] = finishers.map((id, i) => ({ player_id: id, place: i + 1, points: DATA.points[i] || 0 }));
  Object.assign(B, { phase: 'round_over', holder: null, next: null, deadline: 0 });
  push();
}

function abort() {
  if (!live()) return;
  clearTimeout(botTimer);
  B.used = B.used.filter((t) => t !== B.topic);
  Object.assign(B, { phase: 'topic', alive: [], out: [], holder: null, next: null, boom: null, deadline: 0 });
  push();
}

function resetAll() {
  clearTimeout(botTimer);
  Object.assign(B, { phase: 'idle', round: 0, topic: null, used: [], alive: [], out: [], holder: null, next: null,
    boom: null, results: {}, lap: 0, lapPasses: 0 });
  push();
}

setInterval(() => {
  const t = now();
  if (B.phase === 'countdown' && t >= B.startAt) { turn(B.next); push(); }
  else if (B.phase === 'running' && t >= B.deadline) explode();
  else if (B.phase === 'boom' && t >= B.resumeAt) { turn(B.next); push(); }
}, 40);

// ---------------------------------------------------------------- состояние для экранов (как Bomb.public)
function places() {
  const n = B.alive.length + B.out.length;
  const out = {};
  B.out.forEach((id, i) => { out[id] = n - i; });
  if (B.phase === 'round_over' && B.alive.length) out[B.alive[0]] = 1;
  return out;
}

function snapshot(role) {
  const pl = places();
  const ids = ['idle', 'topic'].includes(B.phase) ? lineup() : B.order.filter((id) => B.alive.includes(id) || B.out.includes(id));
  const last = B.results[B.round] || [];
  const sums = {};
  for (const rows of Object.values(B.results)) for (const r of rows) sums[r.player_id] = (sums[r.player_id] || 0) + r.points;
  const s = {
    phase: B.phase, round: B.round, rounds: DATA.rounds, done: done(), topic: B.topic,
    topic_reveal_at_ms: B.revealAt, start_at_ms: B.startAt, deadline_ms: B.deadline || null, turn_started_ms: B.turnStarted,
    turn_seconds: B.phase === 'idle' ? null : B.turnSec || null, resume_at_ms: B.resumeAt, lap: B.lap + 1, passes: B.passes,
    holder: who(B.holder), next_holder: who(B.next),
    boom: B.boom ? { ...who(B.boom.player_id), place: B.boom.place } : null,
    players: ids.map((id) => ({ ...who(id), alive: !B.out.includes(id), place: pl[id] ?? null, connected: true })),
    alive_count: B.alive.length,
    results: B.phase === 'round_over' ? last.map((r) => ({ ...who(r.player_id), ...r })) : [],
    totals: Object.entries(sums).map(([id, points]) => ({ ...who(Number(id)), points })).sort((a, b) => b.points - a.points),
    timing: { ...B.timing }, points: DATA.points,
  };
  if (role === 'tv' && B.phase === 'topic') {
    s.reel = DATA.topics.filter((t) => t !== B.topic).sort(() => Math.random() - 0.5).slice(0, 12);
  }
  if (role === 'player') {
    const inRound = ['idle', 'topic'].includes(B.phase) ? lineup().includes(ME) : B.alive.includes(ME) || B.out.includes(ME);
    s.my = { player_id: ME, can_play: true, in_round: inRound, alive: B.alive.includes(ME), holder: B.holder === ME,
      place: pl[ME] ?? null, points: sums[ME] || 0 };
  }
  return s;
}

// ---------------------------------------------------------------- телефон и ТВ
const link = {
  serverNow: now,
  async cmd(name) {
    await new Promise((r) => setTimeout(r, 60));
    if (name === 'bomb_pass') return pass(ME);
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
  const sum = Object.values(B.results).flat().filter((r) => r.player_id === ME).reduce((a, r) => a + r.points, 0);
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

function hostAction() {
  if (B.phase === 'idle' || (B.phase === 'round_over' && !done())) return ['Тема', pickTopic];
  if (B.phase === 'topic') return ['Старт', start];
  if (B.phase === 'running') return ['💥', explode];
  if (done()) return ['Заново', resetAll];
  return [null, null];
}

const PHASE = { idle: 'ждём', topic: 'тема', countdown: 'отсчёт', running: 'идёт', boom: 'взрыв', round_over: 'итоги' };

function renderBar() {
  const [label, fn] = hostAction();
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
    seg('Маша (ты)', [[true, 'играет'], [false, 'смотрит раунд']], B.meOn, (v) => { if (!live()) { B.meOn = v; push(); } }),
    el('div', { class: 'sb-row' },
      el('button', { disabled: B.phase !== 'topic', onclick: pickTopic }, 'Другая тема'),
      el('button', { disabled: !live(), onclick: abort }, 'Прервать раунд'),
      el('button', { onclick: resetAll }, 'Всё сначала')),
    el('p', { class: 'sb-foot' }, 'Экраны — настоящие web/play/bomb.js и web/tv/scenes/bomb.js. Сервер подставной, темы из content/bomb.yaml. Звуков в песочнице нет.'),
  );
}

push();
