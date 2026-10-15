// Слайд-шоу (модуль 07): все видимые фото в случайном порядке без повторов, 6 с на фото,
// размытая копия кадра на фоне, подпись автора (📷 для вебки и финального фото). Новые фото — следующими.
import { el, clear } from '/web/shared/util.js';

const SECONDS = 6;

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene slide-tv' });
  root.append(box);
  let all = [];
  let queue = [];
  let timer = null;
  let current = null;
  let paused = !!ctx.finale?.slideshow_paused;

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }

  async function load() {
    try {
      const r = await (await fetch('/api/photos')).json();
      all = r.photos;
    } catch { all = []; }
    queue = shuffle([...all]);
    next();
  }

  function show(p) {
    current = p;
    const caption = p.kind === 'selfie' && p.author_name ? p.author_name : '📷';
    const slide = el('div', { class: 'slide' },
      el('div', { class: 'slide-bg', style: { backgroundImage: `url(${p.url})` } }),
      el('img', { class: 'slide-img', src: p.url, alt: '' }),
      el('div', { class: 'slide-cap' }, caption));
    box.append(slide);
    requestAnimationFrame(() => requestAnimationFrame(() => slide.classList.add('in')));
    const old = [...box.children].slice(0, -1);
    setTimeout(() => old.forEach((n) => n.remove()), 1500);
  }

  function next() {
    clearTimeout(timer);
    if (!all.length) {
      clear(box).append(el('div', { class: 'qt-big' }, 'Фото пока нет'));
      return;
    }
    if (!queue.length) queue = shuffle([...all]); // все показаны — перемешать заново
    show(queue.shift());
    if (!paused) timer = setTimeout(next, SECONDS * 1000);
  }

  load();
  return {
    onMessage(m) {
      if (m.t === 'photo_added' && !m.photo.hidden) {
        all.push(m.photo);
        queue.unshift(m.photo); // новое — следующим
        if (all.length === 1) next();
      }
      if (m.t === 'photo_changed' && (m.hidden || m.deleted)) {
        all = all.filter((p) => p.id !== m.id);
        queue = queue.filter((p) => p.id !== m.id);
        if (current?.id === m.id) next();
      }
      if (m.t === 'finale') {
        const p = !!ctx.finale.slideshow_paused;
        if (p !== paused) { paused = p; if (paused) clearTimeout(timer); else next(); }
      }
    },
    unmount() { clearTimeout(timer); },
  };
}
