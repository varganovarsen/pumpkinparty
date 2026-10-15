// Вкладка «Альбом» (модуль 03): общий альбом, новые сверху, фильтр «Мои», просмотр и скачивание.
import { el, clear } from '/web/shared/util.js';

export function mountAlbum(root, { getMe }) {
  const box = el('div', { class: 'album' });
  root.append(box);
  let photos = [];
  let mine = false;
  let viewer = null;

  async function load() {
    try { photos = (await (await fetch('/api/photos')).json()).photos; } catch { photos = []; }
    render();
  }

  function open(p) {
    viewer?.remove();
    viewer = el('div', { class: 'viewer', onclick: (e) => { if (e.target === viewer) close(); } },
      el('img', { src: p.url, alt: '' }),
      el('div', { class: 'row viewer-bar' },
        el('span', { class: 'grow' }, p.author_name || '📷'),
        el('a', { class: 'btn', href: `${p.url}?dl=1`, download: '' }, '⬇ Скачать'),
        el('button', { onclick: close }, '✕')),
      el('p', { class: 'muted center' }, 'На iPhone: зажми фото → «Сохранить в Фото»'));
    document.body.append(viewer);
  }
  function close() { viewer?.remove(); viewer = null; }

  function render() {
    const me = getMe();
    const list = mine ? photos.filter((p) => p.author_id === me?.id) : photos;
    clear(box).append(el('div', { class: 'seg' },
      el('button', { class: mine ? '' : 'on', onclick: () => { mine = false; render(); } }, 'Все'),
      el('button', { class: mine ? 'on' : '', onclick: () => { mine = true; render(); } }, 'Мои')));
    if (!list.length) {
      box.append(el('p', { class: 'center muted' }, mine ? 'Твоих фото пока нет — сделай селфи!' : 'Фото пока нет'));
      return;
    }
    const grid = el('div', { class: 'album-grid' });
    for (const p of list) grid.append(el('button', { class: 'album-cell', onclick: () => open(p) }, el('img', { src: p.thumb_url, alt: '', loading: 'lazy' })));
    box.append(grid);
  }

  load();
  return {
    onMessage(m) {
      if (m.t === 'photo_added' && !m.photo.hidden) { photos.unshift(m.photo); render(); }
      if (m.t === 'photo_changed') {
        if (m.hidden || m.deleted) { photos = photos.filter((p) => p.id !== m.id); render(); } else load();
      }
    },
    unmount() { close(); },
  };
}
