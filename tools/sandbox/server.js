// Подставной сервер для песочницы игрока: живёт в той же странице и говорит по протоколу
// docs/PROTOCOL.md. Настоящие web/shared/ws.js и web/play/* работают без правок — подменены
// только window.WebSocket и window.fetch (запросы /api/*). Гость один, остальные — боты.
import { createQuiz } from '/sandbox/engine_quiz.js';
import { createBomb } from '/sandbox/engine_bomb.js';

const LATENCY = 40; // мс: как в домашней сети
const SCENES = [
  ['ambient', 'Ambient'], ['quiz', 'Квиз'], ['game', 'Падающие тыквы'], ['seeds', 'Охота за семечками'],
  ['bomb', 'Бомба'], ['timer', 'Перерыв'], ['carve_vote', 'Аллея тыкв'], ['carve_reveal', 'Итоги резьбы'],
  ['rating_reveal', 'Общий рейтинг'], ['final_photo', 'Финальное фото'], ['slideshow', 'Слайд-шоу'], ['download', 'Скачивание фото'],
];
export const SCENE_TITLES = Object.fromEntries(SCENES);
const PARTICIPATING = new Set(['quiz', 'game', 'seeds', 'bomb', 'carve_vote']);
const BOT_NAMES = ['Аня', 'Боря', 'Вика', 'Гоша'];
const SEED_TITLES = { regular: 'семечка', golden: 'золотая семечка', rainbow: 'радужная мегасемка' };

export function createServer(DATA) {
  const now = () => Date.now();
  const avatarUrl = (ref) => DATA.avatars[Number(ref.split('-')[1]) - 1];
  const bots = BOT_NAMES.map((name, i) => ({ id: i + 2, name, avatar_kind: 'pumpkin', avatar_ref: `pumpkin-${i + 2}`, bot: true }));
  const uploads = new Map();      // upload_id -> objectURL исходника
  const avatarsByRef = new Map(); // p_… -> dataURL обрезанного фото
  const conns = new Set();
  const listeners = new Set();    // пульт: перерисоваться при любом изменении
  let human = null;               // {id, name, token, avatar_kind, avatar_ref}
  let nextId = 100;
  let photoId = 1;

  const S = {
    scene: 'ambient', startedAt: now(), hideTotal: false, factsShown: Math.min(9, DATA.facts.length),
    photos: [], ledger: { game: 0, seeds: 0, carve: 0 },
    game: { mode: null, phase: 'idle', scored_done: false, start_at: 0, end_at: 0, result: null, eligible: false, bots: {} },
    seeds: { phase: 'idle', start_at: 0, end_at: 0, found: {}, feed: [], fails: { n: 0, until: 0 } },
    vote: { phase: 'idle', vote: null, abstained: false, own: 3 },
    timer: { label: 'Перерыв', running: false, finished: false, end_at: 0, left: null },
  };

  const players = () => [...bots, ...(human ? [human] : [])];
  const who = (p) => ({ player_id: p.id, name: p.name, avatar_url: urlOf(p), in_scoring: true });
  function urlOf(p) { return p.avatar_kind === 'photo' ? avatarsByRef.get(p.avatar_ref) : avatarUrl(p.avatar_ref); }

  // ---------------------------------------------------------------- модули сцен
  const quiz = createQuiz(DATA.quiz, () => { emitModule('quiz'); emitFacts(); });
  let bomb = null;
  function makeBomb() {
    bomb?.dispose();
    const list = [human, ...bots].filter(Boolean).map((p) => ({ id: p.id, name: p.name, avatar_url: urlOf(p) }));
    bomb = createBomb(DATA.bomb, list, human ? human.id : -1, () => emitModule('bomb'));
  }
  makeBomb();

  function score() {
    if (!human) return 0;
    return quiz.totalScore() + bomb.points(human.id) + S.ledger.game + S.ledger.seeds + S.ledger.carve;
  }

  function me() {
    return { id: human.id, name: human.name, avatar_url: urlOf(human), avatar_kind: human.avatar_kind, avatar_ref: human.avatar_ref,
      is_host: false, in_scoring: true, score: S.hideTotal ? null : score() };
  }

  function facts() {
    const locked = factsLocked();
    return DATA.facts.map((text, i) => ({ n: i + 1, text: !locked && i < S.factsShown ? text : null }));
  }
  const factsLocked = () => S.scene === 'quiz' && quiz.S.round === 4 && quiz.live();

  // игра: расписание падений сгенерировано сервером при сборке (server/game.py)
  function gameState() {
    const g = S.game;
    const spec = g.mode ? DATA.game[g.mode] : null;
    const board = g.phase === 'idle' ? [] : [human, ...bots].filter(Boolean).map((p) => ({
      player_id: p.id, name: p.name, avatar_url: urlOf(p), in_scoring: true,
      score: p.bot ? (g.bots[p.id] || 0) : (g.result ?? 0), done: g.phase === 'finished' }))
      .sort((a, b) => b.score - a.score);
    const out = { mode: g.mode, phase: g.phase, scored_done: g.scored_done, start_at_ms: g.start_at || null,
      end_at_ms: g.end_at || null, board, duration: spec?.seconds, my: { eligible: g.eligible, result: g.result } };
    if (g.eligible && ['countdown', 'running'].includes(g.phase)) {
      out.items = spec.items;
      out.points = DATA.game.points;
    }
    return out;
  }

  function gameStart(mode) {
    const g = S.game;
    if (['countdown', 'running'].includes(g.phase)) return;
    const sec = DATA.game[mode].seconds;
    Object.assign(g, { mode, phase: 'countdown', start_at: now() + 3500, end_at: now() + 3500 + sec * 1000, result: null,
      eligible: !!human, bots: {} });
    emitModule('game');
  }

  function gameResult(caught) {
    const g = S.game;
    if (!g.eligible || !['running', 'finished'].includes(g.phase)) return { ok: false, code: 'closed', error: 'Игра закончилась' };
    if (g.result !== null) return { ok: true, score: g.result };
    const items = DATA.game[g.mode].items;
    const set = new Set(caught || []);
    const sum = items.filter((it) => set.has(it.i)).reduce((a, it) => a + (DATA.game.points[it.kind] || 0), 0);
    g.result = Math.max(0, Math.min(500, sum));
    if (g.mode === 'scored') S.ledger.game = g.result;
    emitModule('game');
    emitMe();
    return { ok: true, score: g.result };
  }

  // охота за семечками: коды из content/seeds.yaml (видны на пульте)
  const seedPoints = (kind) => DATA.seeds.points[kind] || 0;
  function seedsState() {
    const s = S.seeds;
    const counts = { regular: { total: 0, found: 0 }, golden: { total: 0, found: 0 }, rainbow: { total: 0, found: 0 } };
    for (const c of DATA.seeds.codes) { counts[c.kind].total++; if (s.found[c.code]) counts[c.kind].found++; }
    const rows = {};
    for (const f of Object.values(s.found)) {
      const p = players().find((x) => x.id === f.player_id);
      if (!p) continue;
      const r = rows[p.id] || (rows[p.id] = { ...who(p), count: 0, points: 0, kinds: { regular: 0, golden: 0, rainbow: 0 } });
      r.count++; r.points += seedPoints(f.kind); r.kinds[f.kind]++;
    }
    const mine = human ? Object.values(s.found).filter((f) => f.player_id === human.id) : [];
    return {
      phase: s.phase, start_at_ms: s.start_at || null, end_at_ms: s.end_at || null, minutes: DATA.seeds.minutes,
      points: DATA.seeds.points, counts, board: Object.values(rows).sort((a, b) => b.points - a.points), feed: s.feed,
      code_len: Math.max(4, ...DATA.seeds.codes.map((c) => c.code.length)),
      my: { can_play: true, count: mine.length, points: mine.reduce((a, f) => a + seedPoints(f.kind), 0),
        kinds: { regular: mine.filter((f) => f.kind === 'regular').length, golden: mine.filter((f) => f.kind === 'golden').length,
          rainbow: mine.filter((f) => f.kind === 'rainbow').length },
        cooldown_until_ms: s.fails.until > now() ? s.fails.until : null },
    };
  }

  function seedsFind(p, code) {
    const seed = DATA.seeds.codes.find((c) => c.code === code);
    S.seeds.found[code] = { player_id: p.id, kind: seed.kind, ts: now() };
    S.seeds.feed = [...S.seeds.feed, { ...who(p), kind: seed.kind, points: seedPoints(seed.kind), ts: now() }].slice(-8);
    if (Object.keys(S.seeds.found).length >= DATA.seeds.codes.length) S.seeds.phase = 'finished';
    return seed;
  }

  function seedsEnter(raw) {
    const s = S.seeds;
    if (s.phase === 'countdown') return { ok: false, code: 'not_started', error: 'Ещё не началось — ждём старта' };
    if (s.phase !== 'running') return { ok: false, code: 'closed', error: 'Охота сейчас не идёт' };
    if (now() < s.fails.until) return { ok: false, code: 'cooldown', error: 'Пауза после неверных кодов', until_ms: s.fails.until };
    const code = String(raw || '').replace(/\D/g, '');
    const seed = DATA.seeds.codes.find((c) => c.code === code);
    if (!seed) {
      s.fails.n++;
      const extra = {};
      if (s.fails.n >= DATA.seeds.wrong_limit) { s.fails.n = 0; s.fails.until = now() + DATA.seeds.cooldown_seconds * 1000; extra.until_ms = s.fails.until; }
      return { ok: false, code: 'wrong', error: 'Нет такой семечки', ...extra };
    }
    const got = s.found[code];
    if (got) {
      if (got.player_id === human.id) return { ok: false, code: 'mine', error: 'Эта семечка уже твоя' };
      return { ok: false, code: 'taken', error: `Эту уже нашли: ${players().find((x) => x.id === got.player_id)?.name || 'кто-то'}` };
    }
    s.fails.n = 0;
    seedsFind(human, code);
    S.ledger.seeds += seedPoints(seed.kind);
    emitModule('seeds');
    emitMe();
    return { ok: true, kind: seed.kind, points: seedPoints(seed.kind) };
  }

  // голосование за резьбу: вместо снимков тыкв — картинки аватаров
  function voteState() {
    const v = S.vote;
    const entries = DATA.avatars.slice(0, 6).map((url, i) => ({ n: i + 1, shots: { lit: url, dark: url, side: url } }));
    return { phase: v.phase, entries, revealed: false, reveal_step: -1, voted_count: (v.vote ? 1 : 0) + 3, voters_total: players().length,
      my: { own: v.own, vote: v.vote, abstained: v.abstained } };
  }

  function timerState() {
    const t = S.timer;
    return { label: t.label, running: t.running, finished: t.finished, end_at_ms: t.running ? t.end_at : null, left_ms: t.left };
  }

  const finaleState = () => ({ step: -1, groups_total: 0, groups: [], slideshow_paused: false, final_photo: null });

  const MODULES = { quiz: () => quiz.snapshot(), game: gameState, seeds: seedsState, bomb: () => bomb.snapshot('player'),
    vote: voteState, timer: timerState, finale: finaleState };

  // ---------------------------------------------------------------- таймеры модулей
  setInterval(() => {
    const t = now();
    const g = S.game;
    if (g.phase === 'countdown' && t >= g.start_at) { g.phase = 'running'; emitModule('game'); }
    else if (g.phase === 'running' && t >= g.end_at) {
      g.phase = 'finished';
      if (g.mode === 'scored') g.scored_done = true;
      for (const b of bots) g.bots[b.id] = Math.round((120 + Math.random() * 330) / 10) * 10;
      emitModule('game');
    }
    const s = S.seeds;
    if (s.phase === 'countdown' && t >= s.start_at) { s.phase = 'running'; emitModule('seeds'); }
    else if (s.phase === 'running' && t >= s.end_at) { s.phase = 'finished'; s.end_at = t; emitModule('seeds'); }
    else if (s.phase === 'running' && Math.random() < 0.004) {
      // бот иногда находит семечку (примерно раз в 10 с)
      const left = DATA.seeds.codes.filter((c) => !s.found[c.code]);
      if (left.length) { seedsFind(bots[Math.floor(Math.random() * bots.length)], left[Math.floor(Math.random() * left.length)].code); emitModule('seeds'); }
    }
    if (S.timer.running && t >= S.timer.end_at) { Object.assign(S.timer, { running: false, finished: true, left: 0 }); emitModule('timer'); }
  }, 40);

  // ---------------------------------------------------------------- рассылка
  function sendAll(msg) { for (const c of conns) c._recv(msg); }
  function emitModule(name) { if (human) sendAll({ t: name, [name]: MODULES[name]() }); emitMe(); }
  function emitMe() { if (human) sendAll({ t: 'me', me: me() }); changed(); }
  function emitFacts() { if (human) sendAll({ t: 'facts', facts: facts(), locked: factsLocked() }); }
  function changed() { for (const f of listeners) f(); }

  function sceneInfo() {
    return { scene: S.scene, payload: {}, started_at: S.startedAt / 1000, participating: PARTICIPATING.has(S.scene), title: SCENE_TITLES[S.scene] };
  }

  function snapshot() {
    const out = { t: 'snapshot', speed: 1, server_ms: now(), me: me(), scene: sceneInfo(),
      settings: { hide_total: S.hideTotal, host_in_scoring: false, quiz_started: true }, facts: facts(), facts_locked: factsLocked(),
      avatars_taken: bots.map((b) => b.avatar_ref) };
    for (const [name, fn] of Object.entries(MODULES)) out[name] = fn();
    return out;
  }

  // ---------------------------------------------------------------- команды игрока
  const COMMANDS = {
    snapshot: (c) => { c._recv(snapshot()); return {}; },
    quiz_answer: (c, m) => quiz.answer(m),
    bomb_pass: () => bomb.pass(human.id),
    game_progress: () => ({}),
    game_result: (c, m) => gameResult(m.caught),
    seeds_enter: (c, m) => seedsEnter(m.code),
    vote: (c, m) => {
      if (S.vote.phase !== 'open') return { ok: false, code: 'closed', error: 'Голосование закрыто' };
      if (m.n === S.vote.own) return { ok: false, code: 'own', error: 'За свою тыкву голосовать нельзя' };
      Object.assign(S.vote, { vote: m.n ?? null, abstained: m.n == null });
      emitModule('vote');
      return {};
    },
    update_profile: (c, m) => {
      if (m.avatar_kind === 'pumpkin' && bots.some((b) => b.avatar_ref === m.avatar_ref)) return { ok: false, code: 'avatar_taken', error: 'Этот аватар уже занят' };
      Object.assign(human, { avatar_kind: m.avatar_kind, avatar_ref: m.avatar_ref });
      emitMe();
      return {};
    },
  };

  // ---------------------------------------------------------------- WebSocket
  class FakeSocket {
    constructor(url) {
      const q = new URL(url, location.href).searchParams;
      this.role = q.get('role');
      this.token = q.get('token');
      this.readyState = 0;
      setTimeout(() => {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        this.onopen?.();
        if (this.role !== 'player' || !human || this.token !== human.token) {
          this._recv({ t: 'auth_failed' });
          this.close(4401);
          return;
        }
        conns.add(this);
        this._recv(snapshot());
      }, LATENCY * 2);
    }

    send(text) {
      if (this.readyState !== 1) return;
      const m = JSON.parse(text);
      setTimeout(() => {
        if (this.readyState !== 1) return;
        if (m.t === 'ping') { this._recv({ t: 'pong', c: m.c, s: now() }); return; }
        if (m.t !== 'cmd') return;
        const fn = COMMANDS[m.cmd];
        const r = fn ? fn(this, m) : { ok: false, code: 'unknown', error: `Песочница не знает команду ${m.cmd}` };
        this._recv({ t: 'reply', id: m.id, ok: r.ok !== false, ...r });
      }, LATENCY);
    }

    close(code = 1000) {
      if (this.readyState === 3) return;
      this.readyState = 3;
      conns.delete(this);
      setTimeout(() => this.onclose?.({ code }), 0);
    }

    _recv(msg) {
      if (this.readyState === 1) setTimeout(() => this.onmessage?.({ data: JSON.stringify(msg) }), LATENCY);
    }
  }

  // ---------------------------------------------------------------- HTTP (/api/*)
  const json = (status, data) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
  const fail = (status, code, error, extra = {}) => json(status, { ok: false, code, error, ...extra });

  async function sampleAlbum() {
    // несколько «фото» гостей для альбома: тёплый фон, тыква и подпись
    const marks = ['🎃', '🍂', '🥧', '🕯', '🌻', '🍁'];
    for (let i = 0; i < 6; i++) {
      const c = document.createElement('canvas');
      c.width = 600; c.height = 800;
      const g = c.getContext('2d');
      const grd = g.createLinearGradient(0, 0, 600, 800);
      grd.addColorStop(0, `hsl(${20 + i * 9}, 70%, ${30 + i * 4}%)`);
      grd.addColorStop(1, `hsl(${8 + i * 6}, 60%, 12%)`);
      g.fillStyle = grd; g.fillRect(0, 0, 600, 800);
      g.font = '260px serif'; g.textAlign = 'center'; g.fillText(marks[i], 300, 470);
      g.fillStyle = '#fff8'; g.font = 'bold 40px system-ui, sans-serif'; g.fillText(`фото ${bots[i % bots.length].name}`, 300, 720);
      const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.8));
      const url = URL.createObjectURL(blob);
      const b = bots[i % bots.length];
      S.photos.unshift({ id: photoId++, url, thumb_url: url, author_id: b.id, author_name: b.name, kind: 'selfie', hidden: false });
    }
  }
  const albumReady = sampleAlbum();

  async function cropAvatar(src, cx, cy, size) {
    const im = new Image();
    await new Promise((res, rej) => { im.onload = res; im.onerror = rej; im.src = src; });
    const side = size * Math.min(im.naturalWidth, im.naturalHeight);
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    c.getContext('2d').drawImage(im, cx * im.naturalWidth - side / 2, cy * im.naturalHeight - side / 2, side, side, 0, 0, 256, 256);
    return c.toDataURL('image/png');
  }

  const API = {
    'GET /api/info': () => json(200, {
      join_url: '', name_max: 20, stickers: DATA.stickers,
      avatars: DATA.avatars.map((url, i) => ({ id: `pumpkin-${i + 1}`, url, taken: bots.some((b) => b.avatar_ref === `pumpkin-${i + 1}`) })),
    }),
    'POST /api/join': (body) => {
      const name = String(body.name || '').replace(/\s+/g, ' ').trim();
      if (name.length < 1 || name.length > 20) return fail(400, 'bad_name', 'Имя должно быть от 1 до 20 символов');
      const same = players().find((p) => p.name.toLowerCase() === name.toLowerCase());
      if (same) return fail(400, 'name_taken', 'Это имя уже занято', { can_claim: false, name: same.name });
      if (body.avatar_kind === 'pumpkin' && bots.some((b) => b.avatar_ref === body.avatar_ref)) return fail(400, 'avatar_taken', 'Этот аватар уже занят');
      human = { id: nextId++, name, token: `sb-${Math.random().toString(36).slice(2)}`, avatar_kind: body.avatar_kind, avatar_ref: body.avatar_ref };
      makeBomb();
      changed();
      return json(200, { ok: true, token: human.token, me: me() });
    },
    'POST /api/claim': () => fail(400, 'not_found', 'Игрок с таким именем не найден'),
    'POST /api/upload_avatar': (body) => {
      const id = Math.random().toString(16).slice(2);
      const url = URL.createObjectURL(body.get('file'));
      uploads.set(id, url);
      return json(200, { ok: true, upload_id: id, preview_url: url });
    },
    'POST /api/avatar_crop': async (body) => {
      const src = uploads.get(body.upload_id);
      if (!src) return fail(400, 'not_found', 'Фото не найдено, загрузите ещё раз');
      const ref = `p_${Math.random().toString(16).slice(2, 18).padEnd(16, '0')}.png`;
      avatarsByRef.set(ref, await cropAvatar(src, body.cx, body.cy, body.size));
      return json(200, { ok: true, avatar_ref: ref, avatar_url: avatarsByRef.get(ref) });
    },
    'POST /api/photo': async (body) => {
      if (!human || body.get('token') !== human.token) return fail(403, 'auth', 'Войдите заново');
      await albumReady;
      const url = URL.createObjectURL(body.get('file'));
      const photo = { id: photoId++, url, thumb_url: url, author_id: human.id, author_name: human.name, kind: 'selfie', hidden: false };
      S.photos.unshift(photo);
      sendAll({ t: 'photo_added', photo });
      return json(200, { ok: true, photo });
    },
    'GET /api/photos': async () => { await albumReady; return json(200, { photos: S.photos }); },
    'POST /api/convert_image': () => fail(415, 'bad_image', 'Песочница не умеет HEIC: выберите JPEG или PNG'),
  };

  const realFetch = window.fetch.bind(window);
  async function fakeFetch(input, init = {}) {
    const u = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (!u.pathname.startsWith('/api/')) return realFetch(input, init);
    const method = (init.method || 'GET').toUpperCase();
    const fn = API[`${method} ${u.pathname}`];
    await new Promise((r) => setTimeout(r, LATENCY * 3));
    if (!fn) return fail(404, 'not_found', `Песочница не знает ${method} ${u.pathname}`);
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    return fn(body, u.searchParams);
  }

  window.WebSocket = FakeSocket;
  window.fetch = fakeFetch;

  // ---------------------------------------------------------------- пульт ведущего
  const host = {
    S, quiz, get bomb() { return bomb; }, get human() { return human; }, seedCodes: DATA.seeds.codes,
    onChange(f) { listeners.add(f); },
    setScene(scene) {
      S.scene = scene;
      S.startedAt = now();
      if (scene === 'timer' && !S.timer.running && !S.timer.finished && S.timer.left === null) host.timerStart(5);
      if (human) sendAll({ t: 'scene', ...sceneInfo() });
      emitFacts();
      changed();
    },
    gameStart,
    seedsStart() {
      if (S.seeds.phase !== 'idle') Object.assign(S.seeds, { found: {}, feed: [], fails: { n: 0, until: 0 } });
      Object.assign(S.seeds, { phase: 'countdown', start_at: now() + 3500, end_at: now() + 3500 + DATA.seeds.minutes * 60000 });
      emitModule('seeds');
    },
    seedsTime(sec) { if (['countdown', 'running'].includes(S.seeds.phase)) { S.seeds.end_at = Math.max(now() + 1000, S.seeds.end_at + sec * 1000); emitModule('seeds'); } },
    seedsStop() { if (S.seeds.phase === 'running') { Object.assign(S.seeds, { phase: 'finished', end_at: now() }); emitModule('seeds'); } },
    votePhase(phase) { S.vote.phase = phase; if (phase === 'idle') Object.assign(S.vote, { vote: null, abstained: false }); emitModule('vote'); },
    timerStart(min) { Object.assign(S.timer, { running: true, finished: false, end_at: now() + min * 60000, left: null }); emitModule('timer'); },
    timerPause() {
      const t = S.timer;
      if (t.running) Object.assign(t, { running: false, left: Math.max(0, t.end_at - now()) });
      else if (t.left) Object.assign(t, { running: true, end_at: now() + t.left, left: null });
      emitModule('timer');
    },
    headFact() { if (S.factsShown < DATA.facts.length) { S.factsShown++; emitFacts(); changed(); } },
    setHideTotal(v) { S.hideTotal = v; if (human) sendAll({ t: 'settings', settings: { hide_total: v } }); emitMe(); },
    dropConnection() { for (const c of [...conns]) c.close(1006); }, // телефон потерял сеть: ws.js переподключится сам
    logout() { if (human) sendAll({ t: 'reset' }); human = null; makeBomb(); changed(); },
    score,
  };
  return host;
}

// сервер встаёт до play.js: тот сразу запрашивает /api/info
export const host = createServer(window.SANDBOX);
