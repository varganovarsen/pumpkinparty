// Финальное фото (модуль 03): «Все в кадр!», затем результат с рамкой.
import { el, clear } from '/web/shared/util.js';

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene final-tv' });
  root.append(box);
  let shownId = null;

  function render() {
    const p = ctx.finale?.final_photo;
    // результат показываем, только если снимок сделан после включения сцены
    if (p && p.created_at >= ctx.scene.started_at) {
      if (p.id === shownId) return;
      shownId = p.id;
      ctx.sfx('shutter');
      clear(box).append(el('img', { class: 'final-img', src: p.url, alt: '' }));
      return;
    }
    clear(box).append(el('div', { class: 'qt-big' }, '📸 Все в кадр!'),
      el('div', { class: 'qt-sub' }, 'Встаньте перед камерой ведущего'));
  }

  render();
  return { update: render, onMessage(m) { if (m.t === 'finale') render(); } };
}
