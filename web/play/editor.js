// Вкладка «Фото»: селфи с фильтрами и наклейками (модуль 03). Konva — локально (window.Konva).
// Камера телефона открывается через <input capture> (HTTP: getUserMedia на iOS недоступен).
// Черновик (картинка + фильтр + наклейки) хранится в IndexedDB и переживает смену сцены.
import { el, clear, toast, api } from '/web/shared/util.js';

const MAX_SIDE = 2048;
const FILTERS = [
  { id: 'none', title: 'Оригинал' },
  { id: 'warm', title: 'Тёплая осень' },
  { id: 'sepia', title: 'Сепия' },
  { id: 'vignette', title: 'Виньетка' },
  { id: 'grain', title: 'Зерно' },
];
const UNDO_MAX = 30;

// ---------------------------------------------------------------- черновик в IndexedDB
const DB_NAME = 'pumpkin-drafts';
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore('drafts');
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
async function draftGet() {
  try {
    const db = await idb();
    return await new Promise((res) => {
      const q = db.transaction('drafts').objectStore('drafts').get('selfie');
      q.onsuccess = () => res(q.result || null);
      q.onerror = () => res(null);
    });
  } catch { return null; }
}
async function draftSet(value) {
  try {
    const db = await idb();
    const tx = db.transaction('drafts', 'readwrite');
    if (value) tx.objectStore('drafts').put(value, 'selfie'); else tx.objectStore('drafts').delete('selfie');
  } catch { /* приватный режим: без черновика */ }
}
export async function hasDraft() { return !!(await draftGet()); }

// ---------------------------------------------------------------- фильтры
function warmFilter(d) {
  const p = d.data;
  for (let i = 0; i < p.length; i += 4) {
    p[i] = Math.min(255, p[i] * 1.08 + 12);
    p[i + 1] = Math.min(255, p[i + 1] * 1.02 + 4);
    p[i + 2] = p[i + 2] * 0.86;
  }
}
function vignetteFilter(d) {
  const { width: w, height: h, data: p } = d;
  const cx = w / 2; const cy = h / 2; const maxD = Math.hypot(cx, cy);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const k = 1 - 0.75 * Math.pow(Math.hypot(x - cx, y - cy) / maxD, 2.2);
      const i = (y * w + x) * 4;
      p[i] *= k; p[i + 1] *= k; p[i + 2] *= k;
    }
  }
}
function applyFilter(node, id) {
  const K = window.Konva;
  const map = { none: [], warm: [warmFilter], sepia: [K.Filters.Sepia], vignette: [vignetteFilter], grain: [K.Filters.Noise] };
  node.filters(map[id] || []);
  node.noise(0.35);
}

// ---------------------------------------------------------------- загрузка картинки
async function fileToCanvas(file) {
  let src = null;
  try {
    src = await createImageBitmap(file, { imageOrientation: 'from-image' });
  } catch {
    try {
      src = await new Promise((res, rej) => {
        const im = new Image();
        const u = URL.createObjectURL(file);
        im.onload = () => { URL.revokeObjectURL(u); res(im); };
        im.onerror = () => { URL.revokeObjectURL(u); rej(new Error('bad image')); };
        im.src = u;
      });
    } catch {
      // браузер не открыл (HEIC на Android): сервер переведёт в JPEG
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch('/api/convert_image', { method: 'POST', body: fd });
      if (!r.ok) throw new Error('Не получилось открыть фото');
      src = await createImageBitmap(await r.blob());
    }
  }
  const w = src.width; const h = src.height;
  const k = Math.min(1, MAX_SIDE / Math.max(w, h));
  const c = document.createElement('canvas');
  c.width = Math.round(w * k);
  c.height = Math.round(h * k);
  c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
  src.close?.(); // освободить память ImageBitmap (Safari быстро перезагружает вкладку при нехватке)
  return c;
}

function canvasToBlob(c, q = 0.9) {
  return new Promise((res) => c.toBlob(res, 'image/jpeg', q));
}

async function blobToCanvas(blob) {
  const bmp = await createImageBitmap(blob);
  const c = document.createElement('canvas');
  c.width = bmp.width;
  c.height = bmp.height;
  c.getContext('2d').drawImage(bmp, 0, 0);
  return c;
}

// ---------------------------------------------------------------- вкладка
export function mountPhotoTab(root, { link, getToken, stickers }) {
  const box = el('div', { class: 'photo-tab' });
  root.append(box);
  let editor = null;

  async function start() {
    clear(box);
    const camera = el('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'hidden' });
    const selfie = el('input', { type: 'file', accept: 'image/*', capture: 'user', class: 'hidden' });
    const gallery = el('input', { type: 'file', accept: 'image/*', class: 'hidden' });
    for (const inp of [camera, selfie, gallery]) {
      inp.addEventListener('change', async () => {
        const f = inp.files[0];
        if (!f) return;
        clear(box).append(el('p', { class: 'center muted' }, 'Открываем фото…'));
        try {
          const c = await fileToCanvas(f);
          openEditor({ canvas: c, filter: 'none', stickers: [] });
        } catch (e) {
          toast(e.message || 'Не получилось открыть фото');
          start();
        }
      });
    }
    const draft = await draftGet();
    box.append(camera, selfie, gallery, el('div', { class: 'card center' },
      el('h2', {}, 'Селфи вечера'),
      el('p', { class: 'muted' }, 'Сними фото, добавь фильтр и наклейки — и в общий альбом!'),
      draft ? el('button', { class: 'primary big-btn', onclick: () => resume(draft) }, '↩ Продолжить черновик') : null,
      el('button', { class: draft ? 'big-btn' : 'primary big-btn', onclick: () => selfie.click() }, '🤳 Сделать селфи'),
      el('button', { class: 'big-btn', onclick: () => camera.click() }, '📷 Основная камера'),
      el('button', { class: 'big-btn', onclick: () => gallery.click() }, '🖼 Из галереи')));
  }

  async function resume(draft) {
    try {
      const c = await blobToCanvas(draft.image);
      openEditor({ canvas: c, filter: draft.filter, stickers: draft.stickers || [] });
    } catch {
      await draftSet(null);
      toast('Черновик не открылся');
      start();
    }
  }

  // ---------------------------------------------------------------- редактор
  function openEditor({ canvas: base, filter, stickers: initial }) {
    const K = window.Konva;
    clear(box);
    const holder = el('div', { class: 'ed-stage' });
    const filtersRow = el('div', { class: 'ed-row' });
    const stickersRow = el('div', { class: 'ed-row stickers' });
    const tools = el('div', { class: 'ed-tools' });
    box.append(holder, filtersRow, stickersRow, tools);

    const W = Math.min(box.clientWidth || window.innerWidth - 28, 520);
    const scale = W / base.width;
    const H = Math.round(base.height * scale);
    const stage = new K.Stage({ container: holder, width: W, height: H });
    const layer = new K.Layer();
    stage.add(layer);
    const photo = new K.Image({ image: base, width: W, height: H });
    layer.add(photo);
    const tr = new K.Transformer({ rotateEnabled: true, keepRatio: true, enabledAnchors: ['top-left', 'top-right', 'bottom-left', 'bottom-right'],
      anchorSize: 18, borderStroke: '#ffd27a', anchorStroke: '#ffd27a', anchorFill: '#2b1a10' });
    layer.add(tr);
    const exportScale = 1 / scale;
    let current = filter;
    let selected = null;
    const undo = [];

    function stickerNodes() { return layer.find('.sticker'); }
    function state() {
      return {
        filter: current,
        stickers: stickerNodes().map((n) => ({ src: n.getAttr('src'), x: n.x() / W, y: n.y() / H, w: n.width() / W,
          sx: n.scaleX(), sy: n.scaleY(), r: n.rotation() })),
      };
    }
    function pushUndo() {
      undo.push(JSON.stringify(state()));
      if (undo.length > UNDO_MAX) undo.shift();
      undoBtn.disabled = false;
    }
    let saveTimer = null;
    function saveDraft() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(async () => {
        await draftSet({ image: await canvasToBlob(base, 0.92), ...state() });
      }, 400);
    }

    function setFilter(id, record = true) {
      if (record && id !== current) pushUndo();
      current = id;
      applyFilter(photo, id);
      if (id === 'none') photo.clearCache(); else photo.cache({ pixelRatio: exportScale });
      for (const b of filtersRow.children) b.classList.toggle('on', b.dataset.id === id);
      layer.batchDraw();
      saveDraft();
    }

    function select(node) {
      selected = node;
      tr.nodes(node ? [node] : []);
      delBtn.disabled = !node;
      layer.batchDraw();
    }

    function addSticker(spec, record = true) {
      const im = new Image();
      im.onload = () => {
        const w = (spec.w || 0.3) * W;
        const h = w * (im.naturalHeight / im.naturalWidth);
        const n = new K.Image({ image: im, name: 'sticker', src: spec.src, width: w, height: h, offsetX: w / 2, offsetY: h / 2,
          x: (spec.x ?? 0.5) * W, y: (spec.y ?? 0.5) * H, scaleX: spec.sx || 1, scaleY: spec.sy || 1, rotation: spec.r || 0,
          draggable: true });
        n.on('dragstart transformstart', () => pushUndo());
        n.on('dragend transformend', () => saveDraft());
        n.on('pointerdown', () => select(n));
        layer.add(n);
        tr.moveToTop();
        if (record) select(n);
        layer.batchDraw();
        saveDraft();
      };
      im.src = spec.src;
    }

    function restore(json) {
      const s = JSON.parse(json);
      stickerNodes().forEach((n) => n.destroy());
      select(null);
      setFilter(s.filter, false);
      s.stickers.forEach((st) => addSticker(st, false));
    }

    // щипок двумя пальцами: масштаб и поворот выбранной наклейки
    let pinch = null;
    stage.on('touchmove', (e) => {
      const t = e.evt.touches;
      if (t.length !== 2 || !selected) { pinch = null; return; }
      e.evt.preventDefault();
      const d = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      const a = Math.atan2(t[1].clientY - t[0].clientY, t[1].clientX - t[0].clientX) * 180 / Math.PI;
      if (!pinch) { pushUndo(); pinch = { d, a, sx: selected.scaleX(), r: selected.rotation() }; return; }
      const k = Math.max(0.2, Math.min(6, pinch.sx * d / pinch.d));
      selected.scale({ x: k, y: k });
      selected.rotation(pinch.r + a - pinch.a);
      layer.batchDraw();
    });
    stage.on('touchend', () => { if (pinch) saveDraft(); pinch = null; });
    stage.on('pointerdown', (e) => { if (e.target === photo || e.target === stage) select(null); });

    for (const f of FILTERS) {
      filtersRow.append(el('button', { class: 'small', 'data-id': f.id, onclick: () => setFilter(f.id) }, f.title));
    }
    for (const src of stickers) {
      stickersRow.append(el('button', { class: 'sticker-btn', onclick: () => { pushUndo(); addSticker({ src }); } },
        el('img', { src, alt: '' })));
    }
    if (!stickers.length) stickersRow.append(el('span', { class: 'muted' }, 'Наклеек пока нет'));
    const undoBtn = el('button', { disabled: true, onclick: () => { if (undo.length) restore(undo.pop()); undoBtn.disabled = !undo.length; saveDraft(); } }, '↶ Отменить');
    const delBtn = el('button', { disabled: true, onclick: () => { if (selected) { pushUndo(); selected.destroy(); select(null); saveDraft(); } } }, '🗑 Наклейку');
    tools.append(
      el('div', { class: 'row' }, undoBtn, delBtn,
        el('button', { onclick: async () => { if (confirm('Выбросить это фото?')) { await draftSet(null); start(); } } }, '✕ Заново')),
      el('button', { class: 'primary big-btn', onclick: () => finish(true) }, '⬆ В общий альбом и себе'),
      el('button', { class: 'big-btn', onclick: () => finish(false) }, '⬇ Только скачать себе'));

    async function finish(toAlbum) {
      clearTimeout(saveTimer); // отложенная запись черновика не должна воскресить уже сохранённое фото
      select(null);
      const blob = await stage.toBlob({ pixelRatio: exportScale, mimeType: 'image/jpeg', quality: 0.9 });
      if (toAlbum) {
        const fd = new FormData();
        fd.append('token', getToken());
        fd.append('file', blob, 'selfie.jpg');
        clear(box).append(el('p', { class: 'center muted' }, 'Отправляем в альбом…'));
        const r = await api('/api/photo', fd);
        if (!r.ok) { toast(r.error || 'Не отправилось'); openEditor({ canvas: base, ...state() }); return; }
        toast('Фото в общем альбоме!');
      }
      await draftSet(null);
      showResult(blob, toAlbum);
    }

    setFilter(filter, false);
    initial.forEach((s) => addSticker(s, false));
    editor = { stage };
    saveDraft();
  }

  // ---------------------------------------------------------------- результат: сохранить на телефон
  let resultUrl = null;
  function showResult(blob, inAlbum) {
    editor?.stage.destroy();
    editor = null;
    if (resultUrl) URL.revokeObjectURL(resultUrl);
    const url = resultUrl = URL.createObjectURL(blob);
    const file = new File([blob], 'tykvenny-spas.jpg', { type: 'image/jpeg' });
    const canShare = navigator.canShare?.({ files: [file] });
    clear(box).append(el('div', { class: 'card center' },
      el('h2', {}, inAlbum ? 'Готово! Фото в альбоме' : 'Готово!'),
      el('img', { class: 'result-img', src: url, alt: 'фото' }),
      el('p', { class: 'muted' }, 'На iPhone: зажми фото и выбери «Сохранить в Фото».'),
      el('a', { class: 'btn big-btn', href: url, download: 'tykvenny-spas.jpg' }, '⬇ Скачать'),
      canShare ? el('button', { class: 'big-btn', onclick: () => navigator.share({ files: [file] }).catch(() => {}) }, 'Поделиться') : null,
      el('button', { class: 'primary big-btn', onclick: start }, '📷 Ещё фото')));
  }

  start();
  return { unmount() { editor?.stage.destroy(); if (resultUrl) URL.revokeObjectURL(resultUrl); } };
}
