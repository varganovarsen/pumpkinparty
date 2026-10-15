// Игра «Падающие тыквы» на телефоне (модуль 05). Падения — по расписанию сервера, время — серверное
// (старт одновременно у всех). Корзина следует за пальцем по горизонтали. В конце — номера пойманных.
import { el, clear, vibrate } from '/web/shared/util.js';

const SPRITES = ['pumpkin', 'golden', 'rotten', 'basket'];
const KIND_SPRITE = { regular: 'pumpkin', golden: 'golden', rotten: 'rotten' };
const BASKET_W = 0.24;   // доля ширины поля
const ITEM_R = 0.055;    // радиус предмета, доля ширины
const CATCH_Y = 0.86;    // линия корзины, доля высоты

// звуки на телефоне: iOS разрешит их после первого касания поля игры
const sfx = {};
function sound(name) {
  try {
    const a = sfx[name] || (sfx[name] = new Audio(`/assets/sfx/${name}.mp3`));
    a.currentTime = 0;
    a.play().catch(() => {});
  } catch { /* без звука */ }
}

const img = {};
for (const s of SPRITES) { img[s] = new Image(); img[s].src = `/assets/game/${s}.png`; }

export function mountGame(root, link) {
  const box = el('div', { class: 'game' });
  root.append(box);
  let g = null;
  let run = null;   // текущая попытка: {key, items, caught, evaluated, score, sent}
  let raf = 0;
  let pending = null; // результат, который ещё не дошёл до сервера

  async function sendResult() {
    if (!pending) return;
    const r = await link.cmd('game_result', { caught: pending.caught });
    if (r.ok || r.code === 'closed') pending = null;
  }

  function startRun() {
    const key = `${g.mode}:${g.start_at_ms}`;
    if (run?.key === key) return;
    run = { key, items: g.items, points: g.points, caught: new Set(), evaluated: new Set(), score: 0, sent: false,
      basket: 0.5, lastProgress: 0, lastTau: null };
    // зашли посреди игры (перезагрузка, возврат): уже упавшее не засчитывается задним числом
    const tau0 = (link.serverNow() - g.start_at_ms) / 1000;
    for (const it of run.items) if (it.land <= tau0) run.evaluated.add(it.i);
    clear(box);
    const canvas = el('canvas', { class: 'game-canvas' });
    const hud = el('div', { class: 'game-hud' });
    const big = el('div', { class: 'game-count' });
    box.append(hud, canvas, big);
    const move = (e) => {
      const r = canvas.getBoundingClientRect();
      run.basket = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      e.preventDefault();
    };
    canvas.addEventListener('pointerdown', move);
    canvas.addEventListener('pointermove', move);
    run.canvas = canvas;
    run.hud = hud;
    run.big = big;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(frame);
  }

  function frame() {
    if (!run) return;
    raf = requestAnimationFrame(frame);
    const c = run.canvas;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const W = c.clientWidth;
    const H = c.clientHeight;
    if (c.width !== Math.round(W * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); }
    const ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const now = link.serverNow();
    const tau = (now - g.start_at_ms) / 1000;
    const dur = (g.end_at_ms - g.start_at_ms) / 1000;
    // отсчёт 3-2-1
    if (tau < 0) {
      const n = Math.ceil(-tau);
      run.big.textContent = n <= 3 ? String(n) : 'Готовься!';
    } else {
      run.big.textContent = tau < 0.8 ? 'Старт!' : '';
    }
    const r = ITEM_R * W;
    // экран засыпал или вкладка была в фоне: пропущенное за «прыжок» времени не ловится
    if (run.lastTau !== null && tau - run.lastTau > 0.35) {
      for (const it of run.items) if (it.land > run.lastTau && it.land <= tau) run.evaluated.add(it.i);
    }
    run.lastTau = tau;
    for (const it of run.items) {
      if (run.evaluated.has(it.i)) continue;
      if (tau >= it.land) {
        run.evaluated.add(it.i);
        if (Math.abs(it.x - run.basket) <= BASKET_W / 2 + ITEM_R * 0.6) {
          run.caught.add(it.i);
          run.score = Math.max(0, run.score + run.points[it.kind]);
          vibrate(it.kind === 'rotten' ? [40, 30, 40] : 25);
          sound(it.kind === 'rotten' ? 'game-rotten' : it.kind === 'golden' ? 'game-golden' : 'game-catch');
        }
        continue;
      }
      if (tau < it.t) continue;
      const y = ((tau - it.t) / it.fall) * CATCH_Y * H;
      const sprite = img[KIND_SPRITE[it.kind]];
      if (sprite.complete && sprite.naturalWidth) ctx.drawImage(sprite, it.x * W - r, y - r, r * 2, r * 2);
      else { ctx.fillStyle = it.kind === 'rotten' ? '#667040' : it.kind === 'golden' ? '#fad232' : '#e8761a'; ctx.beginPath(); ctx.arc(it.x * W, y, r, 0, 7); ctx.fill(); }
    }
    // корзина
    const bw = BASKET_W * W;
    const bx = run.basket * W - bw / 2;
    const by = CATCH_Y * H - bw * 0.15;
    if (img.basket.complete && img.basket.naturalWidth) ctx.drawImage(img.basket, bx, by, bw, bw / 2);
    else { ctx.fillStyle = '#965f2d'; ctx.fillRect(bx, by, bw, bw / 3); }
    const left = Math.max(0, Math.ceil(dur - Math.max(0, tau)));
    run.hud.textContent = `${g.mode === 'practice' ? 'Тренировка · ' : ''}Счёт: ${run.score} · ${left} с`;
    if (tau >= 0 && now - run.lastProgress > 1000 && g.mode === 'scored') {
      run.lastProgress = now;
      link.cmd('game_progress', { score: run.score });
    }
    if (tau >= dur + 0.3 && !run.sent) {
      run.sent = true;
      pending = { caught: [...run.caught] };
      sendResult();
      cancelAnimationFrame(raf);
      showDone(run.score);
    }
  }

  function showDone(score) {
    clear(box).append(el('div', { class: 'qbig' }, `${score}`),
      el('p', { class: 'center' }, g?.mode === 'practice' ? 'Тренировка окончена — это не в зачёт' : 'Твой счёт! Таблица — на экране.'));
  }

  function render() {
    const my = g.my || {};
    if (pending && (g.phase === 'running' || g.phase === 'countdown')) sendResult(); // вернулись после обрыва
    if ((g.phase === 'countdown' || g.phase === 'running') && my.eligible && g.items) {
      if (my.result !== null && my.result !== undefined && !run) { showDone(my.result); return; }
      startRun();
      return;
    }
    if (run && !run.sent) return; // игра на телефоне ещё идёт
    cancelAnimationFrame(raf);
    run = null;
    clear(box);
    if (g.phase === 'countdown' || g.phase === 'running') {
      box.append(el('div', { class: 'qbig' }, '👀'), el('p', { class: 'center' }, 'Игра уже идёт — в этот раз ты зритель. Смотри на экран!'));
    } else if (g.phase === 'finished') {
      const res = my.result;
      box.append(el('div', { class: 'qbig' }, res === null || res === undefined ? '—' : String(res)),
        el('p', { class: 'center muted' }, g.mode === 'practice' ? 'Тренировка окончена. Скоро зачёт!' : 'Игра окончена. Итоги на экране.'));
    } else {
      box.append(el('div', { class: 'qbig' }, '🎃🧺'),
        el('p', { class: 'center' }, 'Води пальцем — корзина поедет за ним. Обычная тыква +10, золотая +50, гнилая −30.'),
        el('p', { class: 'center muted' }, 'Сейчас ведущий запустит игру'));
    }
  }

  return {
    update(next) { g = next; if (g) render(); },
    unmount() { cancelAnimationFrame(raf); },
  };
}
