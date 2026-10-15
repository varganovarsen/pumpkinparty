// Игра «Падающие тыквы» на ТВ (модуль 05): отсчёт 3-2-1, таймер, живой рейтинг, итоговая таблица.
import { el, clear } from '/web/shared/util.js';

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene game-tv' });
  root.append(box);
  let raf = 0;
  let key = null;
  let bigEl = null;
  let boardEl = null;
  let lastCount = null;

  function board(rows) {
    clear(boardEl);
    rows.forEach((r, i) => boardEl.append(el('div', { class: `qt-row${r.done ? ' done' : ''}` },
      el('span', { class: 'place' }, `${i + 1}.`), el('img', { class: 'qt-av', src: r.avatar_url, alt: '' }),
      el('span', { class: 'grow' }, r.name + (r.in_scoring ? '' : ' (вне зачёта)')), el('b', {}, String(r.score)))));
    if (!rows.length) boardEl.append(el('p', { class: 'muted' }, 'Нет игроков в сети'));
  }

  function tick() {
    cancelAnimationFrame(raf);
    const g = ctx.game;
    if (!g || !bigEl) return;
    const now = ctx.link.serverNow();
    if (g.phase === 'countdown') {
      const n = Math.ceil((g.start_at_ms - now) / 1000);
      const txt = n > 3 ? 'Готовься!' : n > 0 ? String(n) : 'Старт!';
      if (txt !== lastCount) { lastCount = txt; bigEl.textContent = txt; if (n <= 3 && n > 0) ctx.sfx('countdown'); }
    } else if (g.phase === 'running') {
      const left = Math.max(0, Math.ceil((g.end_at_ms - now) / 1000));
      bigEl.textContent = left > 0 ? `${left} с` : 'Время!';
    }
    raf = requestAnimationFrame(tick);
  }

  function render() {
    const g = ctx.game || { phase: 'idle', board: [] };
    const k = `${g.phase}:${g.mode}`;
    if (k !== key) {
      key = k;
      lastCount = null;
      if (g.phase === 'running') ctx.sfx('game-start');
      if (g.phase === 'finished') ctx.sfx('game-end');
      const title = g.mode === 'practice' ? 'Тренировка' : 'Падающие тыквы';
      bigEl = el('div', { class: 'game-big' });
      boardEl = el('div', { class: 'qt-table game-board' });
      clear(box).append(el('div', { class: 'qt-head' }, title));
      if (g.phase === 'idle') {
        box.append(el('div', { class: 'qt-big' }, '🎃 Падающие тыквы'),
          el('div', { class: 'qt-sub' }, 'Лови тыквы корзиной на телефоне! Золотая +50, гнилая −30'));
        bigEl = null;
        return;
      }
      if (g.phase === 'finished') {
        box.append(el('div', { class: 'qt-big small' }, g.mode === 'practice' ? 'Тренировка окончена' : 'Итоги игры'));
        bigEl = null;
      } else {
        box.append(bigEl);
      }
      box.append(boardEl);
    }
    board(g.board || []);
    tick();
  }

  render();
  return {
    update: render,
    onMessage(m) {
      if (m.t === 'game') render();
      if (m.t === 'game_live' && ctx.game) { ctx.game.board = m.board; board(m.board); }
    },
    unmount() { cancelAnimationFrame(raf); },
  };
}
