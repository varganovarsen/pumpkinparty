// Сцена-заглушка этапа 1: название и состояние. Настоящие сцены придут в модулях 02-07.
import { el, clear } from '/web/shared/util.js';

export function mount(root, ctx) {
  const box = el('div', { class: 'stub-scene' });
  root.append(box);

  function render() {
    const s = ctx.scene;
    const online = ctx.players.filter((p) => p.connected).length;
    clear(box).append(el('h1', {}, s.title));
    if (s.scene === 'download') {
      box.append(
        el('div', { class: 'qr-big' }, el('img', { src: '/api/qr.svg?path=/download', alt: '' })),
        el('div', { class: 'url' }, `${ctx.joinUrl.replace(/\/$/, '')}/download`),
      );
    }
    box.append(el('p', { class: 'meta' }, `Сцена «${s.scene}» · игроков в сети: ${online} из ${ctx.players.length}`));
    if (s.payload && Object.keys(s.payload).length) box.append(el('pre', { class: 'meta' }, JSON.stringify(s.payload, null, 2)));
  }
  render();
  return { update: render };
}
