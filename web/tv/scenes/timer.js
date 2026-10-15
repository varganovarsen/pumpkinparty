// Перерыв на ТВ (модуль 07): крупные цифры и подпись. По нулю — сигнал и «Время вышло!», сцена не меняется.
import { el, fmtClock } from '/web/shared/util.js';

export function mount(root, ctx) {
  const label = el('div', { class: 'timer-label' });
  const digits = el('div', { class: 'timer-digits' });
  const note = el('div', { class: 'timer-note' });
  root.append(el('div', { class: 'tv-scene timer-tv' }, label, digits, note));
  let raf = 0;
  let wasFinished = null;

  function tick() {
    cancelAnimationFrame(raf);
    const t = ctx.timer || {};
    label.textContent = t.label || 'Перерыв';
    if (t.finished) {
      digits.textContent = '0:00';
      note.textContent = 'Время вышло!';
    } else if (t.running && t.end_at_ms) {
      digits.textContent = fmtClock(t.end_at_ms - ctx.link.serverNow());
      note.textContent = '';
      raf = requestAnimationFrame(tick);
    } else if (t.left_ms !== null && t.left_ms !== undefined) {
      digits.textContent = fmtClock(t.left_ms);
      note.textContent = 'Пауза';
    } else {
      digits.textContent = '';
      note.textContent = '';
    }
    if (wasFinished === false && t.finished) ctx.sfx('game-end');
    wasFinished = !!t.finished;
    digits.classList.toggle('done', !!t.finished);
  }

  tick();
  return { update: tick, onMessage(m) { if (m.t === 'timer') tick(); }, unmount() { cancelAnimationFrame(raf); } };
}
