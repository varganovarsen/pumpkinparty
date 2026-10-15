// Итоги резьбы на ТВ (модуль 06, сцена carve_reveal): по одной тыкве от последнего места к первому,
// затем общая таблица. Порядок и раскрытые записи присылает сервер (vote.results).
import { el, clear } from '/web/shared/util.js';

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene reveal-tv' });
  root.append(box);
  let shown = null;

  function shotOf(n) {
    return (ctx.vote?.entries || []).find((e) => e.n === n)?.shots;
  }

  function render() {
    const v = ctx.vote || {};
    const results = v.results || [];
    const key = `${v.phase}:${results.length}:${v.revealed}`;
    if (key === shown) return;
    if (shown !== null && results.length) ctx.sfx(v.revealed ? 'game-golden' : 'correct');
    shown = key;
    clear(box);
    if (v.phase !== 'closed') {
      box.append(el('div', { class: 'qt-big' }, 'Итоги резьбы'), el('div', { class: 'qt-sub' }, 'Сначала голосование в аллее'));
      return;
    }
    if (!results.length) {
      box.append(el('div', { class: 'qt-big' }, '🎃 Итоги резьбы'), el('div', { class: 'qt-sub' }, `Тыкв: ${v.total}`));
      return;
    }
    if (v.revealed) {
      const table = el('div', { class: 'qt-table wide' }, el('h2', {}, 'Итоги резьбы'));
      for (const r of [...results].reverse()) {
        table.append(el('div', { class: 'qt-row' },
          el('span', { class: 'place' }, r.place ? `${r.place}.` : '—'),
          el('img', { class: 'qt-av', src: r.avatar_url, alt: '' }),
          el('span', { class: 'grow' }, r.name), el('span', { class: 'muted' }, `${r.votes} гол.`),
          el('b', {}, r.bonus ? `+${r.bonus}` : '')));
      }
      box.append(table);
      return;
    }
    const r = results[results.length - 1];
    const shots = shotOf(r.n) || {};
    box.append(el('div', { class: 'reveal-card' },
      el('img', { class: 'reveal-shot', src: shots.dark || '', alt: '' }),
      el('div', { class: 'reveal-info' },
        el('div', { class: 'muted' }, `Тыква №${r.n}`),
        el('div', { class: 'reveal-author' }, el('img', { class: 'qt-av big', src: r.avatar_url, alt: '' }), r.name),
        el('div', { class: 'reveal-votes' }, `Голосов: ${r.votes}`),
        el('div', { class: 'reveal-place' }, r.place ? `${r.place} место` : 'Без места'),
        r.bonus ? el('div', { class: 'reveal-bonus' }, `+${r.bonus}`) : null)));
  }

  render();
  return { update: render, onMessage(m) { if (m.t === 'vote') render(); } };
}
