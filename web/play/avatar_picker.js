// Выбор профиля: тыква-аватар из 8 или своё фото с круглой обрезкой (модуль 01).
// Фильтры и наклейки для фото-профиля подключатся вместе с редактором селфи (модуль 03).
import { el, clear, api } from '/web/shared/util.js';

export function avatarPicker({ avatars, taken = [], current = null, onChange }) {
  let value = current; // {kind, ref, url}
  let takenSet = new Set(taken);
  const root = el('div', { class: 'picker' });
  const tabs = el('div', { class: 'seg' });
  const body = el('div');
  const err = el('div', { class: 'err' });
  let mode = current?.kind === 'photo' ? 'photo' : 'pumpkin';

  function set(v) { value = v; onChange?.(v); render(); }

  function render() {
    clear(tabs).append(
      el('button', { class: mode === 'pumpkin' ? 'on' : '', type: 'button', onclick: () => { mode = 'pumpkin'; render(); } }, 'Тыква'),
      el('button', { class: mode === 'photo' ? 'on' : '', type: 'button', onclick: () => { mode = 'photo'; render(); } }, 'Своё фото'),
    );
    clear(body);
    if (mode === 'pumpkin') {
      const grid = el('div', { class: 'avatar-grid' });
      for (const a of avatars) {
        const mine = value?.kind === 'pumpkin' && value.ref === a.id;
        const busy = takenSet.has(a.id) && !(current?.kind === 'pumpkin' && current.ref === a.id);
        grid.append(el('button', {
          type: 'button', class: `avatar-cell${mine ? ' sel' : ''}${busy ? ' busy' : ''}`, disabled: busy,
          'aria-label': busy ? `${a.id} занят` : a.id,
          onclick: () => set({ kind: 'pumpkin', ref: a.id, url: a.url }),
        }, el('img', { src: a.url, alt: '' })));
      }
      body.append(grid);
    } else {
      const camera = el('input', { type: 'file', accept: 'image/*', capture: 'user', class: 'hidden' });
      const gallery = el('input', { type: 'file', accept: 'image/*', class: 'hidden' });
      for (const inp of [camera, gallery]) inp.addEventListener('change', () => inp.files[0] && upload(inp.files[0]));
      body.append(
        camera, gallery,
        value?.kind === 'photo' ? el('div', { class: 'center' }, el('img', { class: 'avatar big', src: value.url, alt: '' })) : null,
        el('div', { class: 'row' },
          el('button', { type: 'button', class: 'grow', onclick: () => camera.click() }, '📷 Снять'),
          el('button', { type: 'button', class: 'grow', onclick: () => gallery.click() }, '🖼 Из галереи'),
        ),
      );
    }
  }

  async function upload(file) {
    err.textContent = '';
    clear(body).append(el('p', { class: 'center muted' }, 'Загружаем фото…'));
    const fd = new FormData();
    fd.append('file', file);
    const r = await api('/api/upload_avatar', fd);
    if (!r.ok) { err.textContent = r.error; render(); return; }
    cropper(r.upload_id, r.preview_url);
  }

  function cropper(uploadId, url) {
    clear(body);
    const V = Math.min(300, window.innerWidth - 60);
    const img = el('img', { src: url, alt: '', draggable: 'false', class: 'crop-img' });
    const view = el('div', { class: 'crop-view', style: { width: `${V}px`, height: `${V}px` } }, img, el('div', { class: 'crop-mask' }));
    const zoomInput = el('input', { type: 'range', min: '1', max: '4', step: '0.01', value: '1', class: 'grow' });
    let w = 1, h = 1, base = 1, zoom = 1, ox = 0, oy = 0;

    function clamp() {
      const s = base * zoom;
      ox = Math.min(0, Math.max(V - w * s, ox));
      oy = Math.min(0, Math.max(V - h * s, oy));
      img.style.width = `${w * s}px`;
      img.style.height = `${h * s}px`;
      img.style.transform = `translate(${ox}px, ${oy}px)`;
    }
    function setZoom(z, cx = V / 2, cy = V / 2) {
      z = Math.min(4, Math.max(1, z));
      const k = z / zoom;
      ox = cx - (cx - ox) * k;
      oy = cy - (cy - oy) * k;
      zoom = z;
      zoomInput.value = String(z);
      clamp();
    }
    img.onload = () => {
      w = img.naturalWidth; h = img.naturalHeight;
      base = V / Math.min(w, h);
      ox = (V - w * base) / 2; oy = (V - h * base) / 2;
      clamp();
    };
    zoomInput.addEventListener('input', () => setZoom(parseFloat(zoomInput.value)));

    const pts = new Map();
    let last = null;
    view.addEventListener('pointerdown', (e) => { view.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); last = null; });
    view.addEventListener('pointermove', (e) => {
      if (!pts.has(e.pointerId)) return;
      const prev = pts.get(e.pointerId);
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (pts.size === 1) {
        ox += e.clientX - prev[0]; oy += e.clientY - prev[1]; clamp();
      } else if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        const r = view.getBoundingClientRect();
        if (last) setZoom(zoom * d / last, (a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top);
        last = d;
      }
    });
    const up = (e) => { pts.delete(e.pointerId); last = null; };
    view.addEventListener('pointerup', up);
    view.addEventListener('pointercancel', up);

    async function done() {
      const s = base * zoom;
      const side = V / s;
      const cx = (-ox / s + side / 2) / w;
      const cy = (-oy / s + side / 2) / h;
      const size = side / Math.min(w, h);
      const r = await api('/api/avatar_crop', { upload_id: uploadId, cx, cy, size });
      if (!r.ok) { err.textContent = r.error; return; }
      mode = 'photo';
      set({ kind: 'photo', ref: r.avatar_ref, url: r.avatar_url });
    }

    body.append(
      el('p', { class: 'muted center' }, 'Подвинь и увеличь фото, чтобы лицо было в круге'),
      el('div', { class: 'center' }, view),
      el('div', { class: 'row' }, el('span', {}, '🔍'), zoomInput),
      el('div', { class: 'row' },
        el('button', { type: 'button', class: 'grow', onclick: () => render() }, 'Отмена'),
        el('button', { type: 'button', class: 'primary grow', onclick: done }, 'Готово'),
      ),
    );
  }

  root.append(tabs, body, err);
  render();
  return {
    el: root,
    get value() { return value; },
    setTaken(list) { takenSet = new Set(list); if (mode === 'pumpkin') render(); },
    setError(text) { err.textContent = text || ''; },
  };
}
