// Охота за семечками на ТВ (модуль 09): отсчёт, таймер, сколько найдено, рейтинг и лента находок.
import { el, clear, fmtClock, seedIcon } from '/web/shared/util.js';

const KINDS = ['regular', 'golden', 'rainbow'];
const TITLES = { regular: 'семечка', golden: 'золотая семечка', rainbow: 'РАДУЖНАЯ МЕГАСЕМКА' };

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene seeds-tv' });
  const layer = el('div', { class: 'seeds-layer' }); // плашки находок: не стираются перерисовкой сцены
  root.append(box, layer);
  let raf = 0;
  let key = null;
  let ui = {};
  let lastCount = null;

  function tick() {
    cancelAnimationFrame(raf);
    const s = ctx.seeds;
    if (!s || !ui.big) return;
    const now = ctx.link.serverNow();
    if (s.phase === 'countdown') {
      const n = Math.ceil((s.start_at_ms - now) / 1000);
      const txt = n > 3 ? 'Готовься!' : n > 0 ? String(n) : 'Ищите!';
      if (txt !== lastCount) { lastCount = txt; ui.big.textContent = txt; if (n <= 3 && n > 0) ctx.sfx('countdown'); }
    } else if (s.phase === 'running') {
      const left = s.end_at_ms - now;
      ui.big.textContent = left > 0 ? fmtClock(left) : 'Время!';
      ui.big.classList.toggle('warn', left < 30000);
    }
    raf = requestAnimationFrame(tick);
  }

  function counts(s) {
    return el('div', { class: 'seeds-counts' }, KINDS.filter((k) => s.counts[k]?.total).map((k) =>
      el('span', { class: `qt-chip ${k}` }, seedIcon(k), ` ${s.counts[k].found} / ${s.counts[k].total}`)));
  }

  function board(s) {
    const t = el('div', { class: 'qt-table seeds-board' }, el('h2', {}, 'Кто сколько нашёл'));
    s.board.forEach((r, i) => t.append(el('div', { class: 'qt-row' },
      el('span', { class: 'place' }, `${i + 1}.`), el('img', { class: 'qt-av', src: r.avatar_url, alt: '' }),
      el('span', { class: 'grow' }, r.name + (r.in_scoring ? '' : ' (вне зачёта)')),
      el('span', { class: 'seeds-kinds' }, KINDS.filter((k) => r.kinds[k]).flatMap((k) => [seedIcon(k), ` ${r.kinds[k]}  `])),
      el('b', {}, `+${r.points}`))));
    if (!s.board.length) t.append(el('p', { class: 'muted' }, 'Пока никто ничего не нашёл'));
    return t;
  }

  function feed(s) {
    const f = el('div', { class: 'qt-table seeds-feed' }, el('h2', {}, 'Находки'));
    for (const x of [...s.feed].reverse()) {
      f.append(el('div', { class: `qt-row seeds-find ${x.kind}` }, el('img', { class: 'qt-av', src: x.avatar_url, alt: '' }),
        seedIcon(x.kind), el('span', { class: 'grow' }, `${x.name}: ${TITLES[x.kind]}`), el('b', {}, `+${x.points}`)));
    }
    return f;
  }

  function render() {
    const s = ctx.seeds || { phase: 'idle', counts: {}, board: [], feed: [], points: {} };
    if (s.phase !== key) {
      key = s.phase;
      lastCount = null;
      if (s.phase === 'running') ctx.sfx('game-start');
      if (s.phase === 'finished') ctx.sfx('game-end');
    }
    ui = {};
    clear(box).append(el('div', { class: 'qt-head' }, 'Охота за семечками'));
    if (s.phase === 'idle') {
      const p = s.points || {};
      box.append(el('div', { class: 'qt-big' }, seedIcon('golden'), ' 🔎'),
        el('div', { class: 'qt-sub' }, 'По комнате спрятаны семечки с кодами'),
        el('div', { class: 'qt-meta' }, `Нашёл — вводи код на телефоне. Кто первый, того и семечка!`),
        el('div', { class: 'qt-meta' }, seedIcon('regular'), ` +${p.regular ?? 30} · `, seedIcon('golden'), ` золотая +${p.golden ?? 100} · `,
          seedIcon('rainbow'), ` радужная мегасемка +${p.rainbow ?? 300}`),
        el('div', { class: 'qt-meta' }, `На поиски ${s.minutes ?? 5} минут`));
      return;
    }
    if (s.phase === 'countdown') {
      ui.big = el('div', { class: 'game-big' });
      box.append(ui.big, counts(s));
      tick();
      return;
    }
    if (s.phase === 'running') {
      ui.big = el('div', { class: 'game-big seeds-time' });
      box.append(el('div', { class: 'seeds-top' }, ui.big, counts(s)), el('div', { class: 'seeds-cols' }, board(s), feed(s)));
      tick();
      return;
    }
    const left = Object.values(s.counts).reduce((a, c) => a + c.total - c.found, 0);
    box.append(el('div', { class: 'qt-big small' }, 'Итоги охоты'), counts(s),
      el('div', { class: 'seeds-cols' }, board(s)),
      el('div', { class: 'qt-meta' }, left ? `Не найдено семечек: ${left}. Ведущий, где они? 👀` : 'Найдены все семечки!'));
  }

  // крупная плашка о находке поверх сцены; радужная — на весь экран
  function announce(m) {
    const pop = el('div', { class: `seeds-announce ${m.kind}` },
      el('img', { class: 'qt-av', src: m.avatar_url, alt: '' }),
      seedIcon(m.kind, 'big'), el('div', {}, el('div', { class: 'who' }, m.name), el('div', {}, TITLES[m.kind])),
      el('b', {}, `+${m.points}`));
    layer.append(pop);
    ctx.sfx(m.kind === 'regular' ? 'game-catch' : 'game-golden');
    setTimeout(() => pop.remove(), m.kind === 'rainbow' ? 6000 : 3000);
  }

  render();
  return {
    update: render,
    onMessage(m) {
      if (m.t === 'seeds') render();
      if (m.t === 'seed_found') announce(m);
    },
    unmount() { cancelAnimationFrame(raf); layer.remove(); },
  };
}
