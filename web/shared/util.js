// Мелкие помощники интерфейса.

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else if (k === 'html') node.innerHTML = v;
    else if (v === true) node.setAttribute(k, '');
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

let toastTimer = null;
export function toast(text, ms = 2500) {
  let t = document.getElementById('toast');
  if (!t) { t = el('div', { id: 'toast', class: 'toast' }); document.body.append(t); }
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), ms);
}

export function vibrate(pattern) {
  try { if (navigator.vibrate) navigator.vibrate(pattern); } catch { /* iOS: нет вибрации */ }
}

export function fmtClock(ms) {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

export async function api(path, body = null) {
  const opts = body instanceof FormData
    ? { method: 'POST', body }
    : body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {};
  try {
    const r = await fetch(path, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok && data.ok === undefined) data.ok = false;
    if (!r.ok && !data.error) data.error = `Ошибка ${r.status}`;
    return data;
  } catch {
    return { ok: false, code: 'offline', error: 'Нет связи с сервером' };
  }
}

export function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* приватный режим */ }
  return null;
}

// Баннер «Нет связи» поверх страницы.
export function offlineBar(online) {
  let b = document.getElementById('offline-bar');
  if (!b) { b = el('div', { id: 'offline-bar', class: 'offline-bar' }, 'Нет связи — переподключаемся…'); document.body.append(b); }
  b.classList.toggle('show', !online);
}

// Тыквенная семечка (CSS, как на листе для печати): kind — regular | golden | rainbow.
export function seedIcon(kind = 'regular', cls = '') {
  return el('i', { class: `seed-ic ${kind} ${cls}`.trim(), 'aria-hidden': 'true' });
}
