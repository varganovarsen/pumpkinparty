// Ambient: фон-видео (или лёгкий режим), QR в углу, голова-тыква с фактами, карточка нового селфи.
// Голова: Rive (assets/rive/head.riv, state machine HeadSM) или CSS-заглушка, пока .riv — заглушка.
import { el, clear } from '/web/shared/util.js';
import { createHead } from '/web/tv/head.js';

const LEAVES = ['🍁', '🍂', '🍃'];

export function mount(root, ctx) {
  const box = el('div', { class: 'ambient' });
  const bg = el('div', { style: { position: 'absolute', inset: '0' } });
  const qr = el('div', { class: 'qr-corner' },
    el('img', { src: '/api/qr.svg?path=/', alt: '' }),
    el('div', { class: 'url' }, ctx.joinUrl.replace(/^https?:\/\//, '').replace(/\/$/, '')));
  const headBox = el('div', { class: 'head-layer' });
  const cardBox = el('div');
  box.append(bg, qr, cardBox, headBox);
  root.append(box);

  let light = null;
  function renderBg() {
    const want = !!ctx.settings.light_mode;
    if (want === light) return;
    light = want;
    clear(bg);
    if (light) {
      const leaves = el('div', { class: 'leaves' });
      for (let i = 0; i < 14; i++) {
        leaves.append(el('span', {
          class: 'leaf',
          style: { left: `${Math.random() * 100}vw`, animationDuration: `${9 + Math.random() * 10}s`, animationDelay: `${-Math.random() * 15}s` },
        }, LEAVES[i % LEAVES.length]));
      }
      bg.append(el('div', { class: 'light-bg', style: { backgroundImage: 'url(/assets/img/ambient-light.jpg)' } }), leaves);
    } else {
      const v = el('video', { src: '/assets/video/ambient.webm', autoplay: true, muted: true, loop: true, playsinline: true });
      v.muted = true;
      // видео не открылось: тёплый градиент вместо чёрного экрана
      v.addEventListener('error', () => { bg.style.background = 'radial-gradient(circle at 60% 40%, #4a2410, #120a06)'; });
      bg.append(v);
      v.play().catch(() => {});
    }
  }

  // ---------------------------------------------------------------- голова
  const head = createHead(headBox, ctx);

  // ---------------------------------------------------------------- карточка нового селфи
  let cardTimer = null;
  function showCard(photo) {
    if (!ctx.settings.new_photo_card || photo.kind !== 'selfie' || head.visible()) return;
    clearTimeout(cardTimer);
    clear(cardBox).append(el('div', { class: 'photo-card' },
      el('img', { src: photo.thumb_url, alt: '' }),
      el('div', {}, el('div', { class: 'muted' }, 'Новое фото'), el('b', {}, `от ${photo.author_name || 'гостя'}`))));
    requestAnimationFrame(() => cardBox.firstChild?.classList.add('in'));
    cardTimer = setTimeout(() => {
      cardBox.firstChild?.classList.remove('in');
      setTimeout(() => clear(cardBox), 800);
    }, (ctx.config.new_photo_card_seconds || 7) * 1000);
  }

  renderBg();
  if (ctx.head) head.show(ctx.head, true);

  return {
    update() { renderBg(); },
    onMessage(m) {
      if (m.t === 'head') { if (m.head) head.show(m.head); else head.hide(); }
      if (m.t === 'head_speak') head.speak();
      if (m.t === 'photo_added') showCard(m.photo);
    },
    unmount() { head.destroy(); clearTimeout(cardTimer); },
  };
}
