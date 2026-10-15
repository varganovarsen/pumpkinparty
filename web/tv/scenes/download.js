// Скачивание (модуль 07): крупный QR на /download и адрес текстом.
import { el } from '/web/shared/util.js';

export function mount(root, ctx) {
  const url = `${ctx.joinUrl.replace(/\/$/, '')}/download`;
  root.append(el('div', { class: 'tv-scene download-tv' },
    el('div', { class: 'qt-big small' }, '📸 Заберите фото вечера'),
    el('div', { class: 'qr-big' }, el('img', { src: '/api/qr.svg?path=/download', alt: '' })),
    el('div', { class: 'qt-sub' }, url.replace(/^https?:\/\//, ''))));
  return {};
}
