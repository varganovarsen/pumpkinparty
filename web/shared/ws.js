// Связь с сервером: один WebSocket, автопереподключение, синхронизация часов, команды.
// SPEC раздел 11, docs/PROTOCOL.md.

const PING_SAMPLES = 5;
const HEARTBEAT_MS = 8000;
const DEAD_MS = 20000;

export class Link {
  constructor({ role, token = null, onMessage = () => {}, onStatus = () => {}, onAuthFailed = () => {} }) {
    this.role = role;
    this.token = token;
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.onAuthFailed = onAuthFailed;
    this.ws = null;
    this.online = false;
    this.stopped = false;
    this.retry = 0;
    this.nextId = 1;
    this.pending = new Map();
    this.lastSeen = 0;
    // часы: serverNow() = anchorS + (performance.now() - anchorL) * speed
    this.anchorS = Date.now();
    this.anchorL = performance.now();
    this.bestRtt = Infinity;
    this.speed = 1;
    this._timer = null;

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') this.kick();
    });
    window.addEventListener('online', () => this.kick());
    window.addEventListener('pageshow', () => this.kick());
    setInterval(() => this._heartbeat(), HEARTBEAT_MS / 2);
  }

  url() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const q = new URLSearchParams({ role: this.role });
    if (this.token) q.set('token', this.token);
    return `${proto}://${location.host}/ws?${q}`;
  }

  connect() {
    if (this.stopped) return;
    clearTimeout(this._timer);
    let ws;
    try {
      ws = new WebSocket(this.url());
    } catch (e) {
      this._scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.lastSeen = performance.now();
      this.bestRtt = Infinity;
      for (let i = 0; i < PING_SAMPLES; i++) setTimeout(() => this._ping(), i * 120);
    };
    ws.onmessage = (ev) => {
      this.lastSeen = performance.now();
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this._dispatch(msg);
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this._setOnline(false);
      for (const [, p] of this.pending) p.resolve({ ok: false, code: 'offline', error: 'Нет связи' });
      this.pending.clear();
      if (ev.code === 4401 || ev.code === 4403 || ev.code === 4400) return; // переподключение не поможет
      this._scheduleReconnect();
    };
    ws.onerror = () => {};
  }

  kick() {
    // телефон проснулся: проверить соединение сразу
    if (this.stopped) return;
    if (!this.ws || this.ws.readyState > 1) { this.retry = 0; this.connect(); }
    else this._ping();
  }

  stop() {
    this.stopped = true;
    clearTimeout(this._timer);
    if (this.ws) this.ws.close();
  }

  _scheduleReconnect() {
    clearTimeout(this._timer);
    const delay = Math.min(5000, 400 * 2 ** this.retry) + Math.random() * 300;
    this.retry++;
    this._timer = setTimeout(() => this.connect(), delay);
  }

  _setOnline(v) {
    if (this.online !== v) { this.online = v; this.onStatus(v); }
  }

  _heartbeat() {
    if (!this.ws || this.ws.readyState !== 1) return;
    if (performance.now() - this.lastSeen > DEAD_MS) { this.ws.close(); return; }
    this._ping();
  }

  _ping() {
    this.send({ t: 'ping', c: performance.now() });
  }

  _dispatch(msg) {
    if (msg.t === 'pong') {
      const now = performance.now();
      const rtt = now - msg.c;
      if (rtt <= this.bestRtt * 1.5 || rtt < 60) {
        if (rtt < this.bestRtt) this.bestRtt = rtt;
        this.anchorS = msg.s + (rtt / 2) * this.speed;
        this.anchorL = now;
      }
      return;
    }
    if (msg.t === 'snapshot') {
      this.speed = msg.speed || 1;
      if (this.bestRtt === Infinity) { this.anchorS = msg.server_ms; this.anchorL = performance.now(); }
      this._setOnline(true);
    }
    if (msg.t === 'auth_failed') { this.onAuthFailed(); return; }
    if (msg.t === 'reply') {
      const p = this.pending.get(msg.id);
      if (p) { this.pending.delete(msg.id); p.resolve(msg); }
      return;
    }
    this.onMessage(msg);
  }

  send(obj) {
    if (this.ws && this.ws.readyState === 1) { this.ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  // Команда серверу. Возвращает Promise с ответом {ok, error, ...}.
  cmd(name, args = {}) {
    const id = this.nextId++;
    return new Promise((resolve) => {
      if (!this.send({ t: 'cmd', cmd: name, id, ...args })) {
        resolve({ ok: false, code: 'offline', error: 'Нет связи' });
        return;
      }
      this.pending.set(id, { resolve });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          resolve({ ok: false, code: 'timeout', error: 'Сервер не ответил' });
        }
      }, 10000);
    });
  }

  // Текущее серверное время в мс (учитывает смещение часов и ускорение симулятора).
  serverNow() {
    return this.anchorS + (performance.now() - this.anchorL) * this.speed;
  }
}
