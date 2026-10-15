// Ambient: фон-видео (или лёгкий режим), QR в углу, голова-тыква.
// Голова пока CSS-заглушка; Rive (assets/rive/head.riv, HeadSM) подключается в модуле 04.
import { el, clear } from '/web/shared/util.js';

const LEAVES = ['🍁', '🍂', '🍃'];
const TAIL_SECONDS = 3;

export function mount(root, ctx) {
  const box = el('div', { class: 'ambient' });
  const bg = el('div', { style: { position: 'absolute', inset: '0' } });
  const qr = el('div', { class: 'qr-corner' },
    el('img', { src: '/api/qr.svg?path=/', alt: '' }),
    el('div', { class: 'url' }, ctx.joinUrl.replace(/^https?:\/\//, '').replace(/\/$/, '')));
  const headBox = el('div');
  box.append(bg, qr, headBox);
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
  let head = null; // {factId, node, timer, audio}

  function hideHead() {
    if (!head) return;
    const h = head;
    head = null;
    clearTimeout(h.timer);
    h.audio?.pause();
    h.node.classList.remove('in', 'talking');
    setTimeout(() => h.node.remove(), 1300);
    ctx.link.cmd('head_done', { fact_id: h.factId });
  }

  function showHead(data, resumed = false) {
    hideHead();
    const elapsed = ctx.link.serverNow() / 1000 - data.called_at;
    if (resumed && elapsed > data.seconds) return;
    const node = el('div', { class: 'head' },
      el('div', { class: 'bubble' }, data.text),
      el('div', { class: 'face' }, el('div', { class: 'eye l' }), el('div', { class: 'eye r' }), el('div', { class: 'mouth' })));
    headBox.append(node);
    head = { factId: data.fact_id, node, timer: null, audio: null };
    const h = head;
    requestAnimationFrame(() => requestAnimationFrame(() => node.classList.add('in')));
    ctx.link.cmd('head_shown', { fact_id: data.fact_id });
    const hideIn = (s) => { clearTimeout(h.timer); h.timer = setTimeout(() => { if (head === h) hideHead(); }, s * 1000); };

    if (!resumed) ctx.sfx('fact-notify');
    if (!resumed && data.mode === 'loud' && data.audio_url) {
      const a = new Audio(data.audio_url);
      h.audio = a;
      a.addEventListener('playing', () => node.classList.add('talking'));
      a.addEventListener('ended', () => { node.classList.remove('talking'); hideIn(TAIL_SECONDS); });
      a.addEventListener('error', () => hideIn(data.seconds));
      hideIn(60); // страховка, если аудио не стартует
      setTimeout(() => a.play().catch(() => hideIn(data.seconds)), 900);
    } else {
      hideIn(resumed ? data.seconds - elapsed : data.seconds);
    }
  }

  renderBg();
  if (ctx.head) showHead(ctx.head, true);

  return {
    update() { renderBg(); },
    onMessage(m) {
      if (m.t === 'head') { if (m.head) showHead(m.head); else hideHead(); }
    },
    unmount() { if (head) { clearTimeout(head.timer); head.audio?.pause(); } },
  };
}
