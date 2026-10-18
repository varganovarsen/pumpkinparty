// Подставная «Бомба» для песочниц: логика раунда повторяет server/bomb.py, остальные игроки — боты
// (передают бомбу сами, иногда не успевают). snapshot(role) — состояние модуля bomb (docs/PROTOCOL.md).
const COUNTDOWN = 3500;
const ROULETTE = 4000;
const BOOM_PAUSE = 3000;
const SKILL = { slow: 0.35, normal: 0.18, fast: 0.06 }; // доля ходов, на которых бот не успевает

// settings: {topics, rounds, points, timing}; players: [{id, name, avatar_url}]; me — id живого игрока
export function createBomb(settings, players, me, onChange = () => {}) {
  const B = {
    phase: 'idle', round: 0, topic: null, revealAt: 0, used: [], order: players.map((p) => p.id),
    alive: [], out: [], holder: null, next: null, startAt: 0, turnStarted: 0, deadline: 0, turnSec: 0,
    lap: 0, lapPasses: 0, passes: 0, boom: null, resumeAt: 0, results: {},
    timing: { ...settings.timing }, skill: 'normal', meOn: true,
  };
  let botTimer = 0;

  const now = () => Date.now();
  const who = (id) => {
    const p = players.find((x) => x.id === id);
    return p ? { player_id: p.id, name: p.name, avatar_url: p.avatar_url, in_scoring: true } : null;
  };
  const lineup = () => B.order.filter((id) => id !== me || B.meOn);
  const turnSeconds = () => Math.max(B.timing.min_seconds, B.timing.start_seconds - B.lap * B.timing.step_seconds);
  const after = (id, list) => list[(list.indexOf(id) + 1) % list.length];
  const live = () => ['countdown', 'running', 'boom'].includes(B.phase);
  const done = () => B.phase === 'round_over' && B.round >= settings.rounds;

  function pickTopic() {
    if (live()) return;
    if (B.phase !== 'topic') {
      if (B.round >= settings.rounds) return;
      B.round += 1;
    }
    const pool = settings.topics.filter((t) => !B.used.includes(t) && t !== B.topic);
    const list = pool.length ? pool : settings.topics.filter((t) => t !== B.topic);
    B.topic = list[Math.floor(Math.random() * list.length)];
    Object.assign(B, { phase: 'topic', revealAt: now() + ROULETTE, alive: [], out: [], holder: null, boom: null });
    onChange();
  }

  function start() {
    if (B.phase !== 'topic') return;
    let alive = lineup();
    const shift = (B.round - 1) % alive.length;
    alive = alive.slice(shift).concat(alive.slice(0, shift));
    B.used.push(B.topic);
    Object.assign(B, { phase: 'countdown', alive, out: [], startAt: now() + COUNTDOWN, holder: null, next: alive[0],
      lap: 0, lapPasses: 0, passes: 0, boom: null, revealAt: Math.min(B.revealAt, now()) });
    onChange();
  }

  function turn(id) {
    const sec = turnSeconds();
    Object.assign(B, { phase: 'running', holder: id, next: null, turnStarted: now(), deadline: now() + sec * 1000, turnSec: sec, boom: null });
    clearTimeout(botTimer);
    if (id !== me) {
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
    onChange();
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
    onChange();
  }

  function finishRound() {
    const finishers = B.alive.concat([...B.out].reverse());
    B.results[B.round] = finishers.map((id, i) => ({ player_id: id, place: i + 1, points: settings.points[i] || 0 }));
    Object.assign(B, { phase: 'round_over', holder: null, next: null, deadline: 0 });
    onChange();
  }

  function abort() {
    if (!live()) return;
    clearTimeout(botTimer);
    B.used = B.used.filter((t) => t !== B.topic);
    Object.assign(B, { phase: 'topic', alive: [], out: [], holder: null, next: null, boom: null, deadline: 0 });
    onChange();
  }

  function reset() {
    clearTimeout(botTimer);
    Object.assign(B, { phase: 'idle', round: 0, topic: null, used: [], alive: [], out: [], holder: null, next: null,
      boom: null, results: {}, lap: 0, lapPasses: 0 });
    onChange();
  }

  const ticker = setInterval(() => {
    const t = now();
    if (B.phase === 'countdown' && t >= B.startAt) { turn(B.next); onChange(); }
    else if (B.phase === 'running' && t >= B.deadline) explode();
    else if (B.phase === 'boom' && t >= B.resumeAt) { turn(B.next); onChange(); }
  }, 40);

  function places() {
    const n = B.alive.length + B.out.length;
    const out = {};
    B.out.forEach((id, i) => { out[id] = n - i; });
    if (B.phase === 'round_over' && B.alive.length) out[B.alive[0]] = 1;
    return out;
  }

  const points = (id) => Object.values(B.results).flat().filter((r) => r.player_id === id).reduce((a, r) => a + r.points, 0);

  function snapshot(role) {
    const pl = places();
    const ids = ['idle', 'topic'].includes(B.phase) ? lineup() : B.order.filter((id) => B.alive.includes(id) || B.out.includes(id));
    const last = B.results[B.round] || [];
    const sums = {};
    for (const rows of Object.values(B.results)) for (const r of rows) sums[r.player_id] = (sums[r.player_id] || 0) + r.points;
    const s = {
      phase: B.phase, round: B.round, rounds: settings.rounds, done: done(), topic: B.topic,
      topic_reveal_at_ms: B.revealAt, start_at_ms: B.startAt, deadline_ms: B.deadline || null, turn_started_ms: B.turnStarted,
      turn_seconds: B.phase === 'idle' ? null : B.turnSec || null, resume_at_ms: B.resumeAt, lap: B.lap + 1, passes: B.passes,
      holder: who(B.holder), next_holder: who(B.next),
      boom: B.boom ? { ...who(B.boom.player_id), place: B.boom.place } : null,
      players: ids.map((id) => ({ ...who(id), alive: !B.out.includes(id), place: pl[id] ?? null, connected: true })),
      alive_count: B.alive.length,
      results: B.phase === 'round_over' ? last.map((r) => ({ ...who(r.player_id), ...r })) : [],
      totals: Object.entries(sums).map(([id, p]) => ({ ...who(Number(id)), points: p })).sort((a, b) => b.points - a.points),
      timing: { ...B.timing }, points: settings.points,
    };
    if (role === 'tv' && B.phase === 'topic') {
      s.reel = settings.topics.filter((t) => t !== B.topic).sort(() => Math.random() - 0.5).slice(0, 12);
    }
    if (role === 'player') {
      const inRound = ['idle', 'topic'].includes(B.phase) ? lineup().includes(me) : B.alive.includes(me) || B.out.includes(me);
      s.my = { player_id: me, can_play: true, in_round: inRound, alive: B.alive.includes(me), holder: B.holder === me,
        place: pl[me] ?? null, points: sums[me] || 0 };
    }
    return s;
  }

  // кнопка ведущего «следующий шаг»: [подпись, действие]
  function hostAction() {
    if (B.phase === 'idle' || (B.phase === 'round_over' && !done())) return ['Тема', pickTopic];
    if (B.phase === 'topic') return ['Старт', start];
    if (B.phase === 'running') return ['💥', explode];
    if (done()) return ['Заново', reset];
    return [null, null];
  }

  // выключить: таймер и боты больше не ходят (новый состав игроков — новый движок)
  function dispose() { clearInterval(ticker); clearTimeout(botTimer); }

  return { B, pickTopic, start, pass, explode, abort, reset, snapshot, live, done, points, hostAction, dispose };
}
