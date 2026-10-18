// Общий рейтинг (модуль 07): по одному от последнего места к первому, ничьи — вместе.
import { el, clear } from '/web/shared/util.js';

const CATS = [['quiz', 'Квиз'], ['game', 'Игра'], ['seeds', 'Семечки'], ['bomb', 'Бомба'], ['carve', 'Резьба'], ['manual', 'Прочее']];

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene rating-tv' });
  root.append(box);
  let shown = -2;

  function card(r, big) {
    const parts = CATS.filter(([k]) => r.breakdown[k]).map(([k, t]) => `${t} ${r.breakdown[k]}`);
    return el('div', { class: `rr-card${big ? ' big' : ''}` },
      el('div', { class: 'rr-place' }, `${r.place}`),
      el('img', { class: 'rr-av', src: r.avatar_url, alt: '' }),
      el('div', { class: 'grow' }, el('div', { class: 'rr-name' }, r.name), el('div', { class: 'rr-break' }, parts.join(' · '))),
      el('div', { class: 'rr-total' }, String(r.total)));
  }

  function render() {
    const f = ctx.finale || { groups: [], step: -1 };
    if (f.step === shown) return;
    if (f.step > shown && f.step >= 0) ctx.sfx(f.step === f.groups_total - 1 ? 'game-golden' : 'correct');
    shown = f.step;
    clear(box).append(el('div', { class: 'qt-head' }, 'Общий рейтинг вечера'));
    if (f.step < 0) {
      box.append(el('div', { class: 'qt-big' }, '🏆 Кто же победил?'));
      return;
    }
    const groups = f.groups.slice(0, f.step + 1);
    const latest = groups[groups.length - 1];
    const current = el('div', { class: 'rr-current' }, ...latest.map((r) => card(r, true)));
    const earlier = el('div', { class: 'rr-list' });
    for (const g of groups.slice(0, -1).reverse()) for (const r of g) earlier.append(card(r, false));
    box.append(current, earlier);
  }

  render();
  return { update: render, onMessage(m) { if (m.t === 'finale') render(); } };
}
