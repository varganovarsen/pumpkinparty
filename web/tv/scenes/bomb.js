// «Бомба» на ТВ (модуль 10): рулетка тем, крупно — у кого бомба, тема и таймер хода,
// внизу круг игроков в порядке хода; взрыв, итоги раунда и сумма за все раунды.
import { el, clear } from '/web/shared/util.js';

const R = 46; // радиус кольца-фитиля в единицах viewBox 100×100
const C = 2 * Math.PI * R;

export function mount(root, ctx) {
  const box = el('div', { class: 'tv-scene bomb-tv' });
  root.append(box);
  const put = (...xs) => box.append(...xs.filter(Boolean)); // append() печатает null как текст
  let raf = 0;
  let key = null;
  let ui = {};
  let lastSec = null;
  let lastCount = null;

  function chip(p, s) {
    const holder = s.holder?.player_id === p.player_id;
    return el('div', { class: `bomb-chip${p.alive ? '' : ' out'}${holder ? ' holder' : ''}${p.connected === false ? ' off' : ''}` },
      el('img', { class: 'qt-av', src: p.avatar_url, alt: '' }),
      el('span', { class: 'nm' }, p.name),
      p.place ? el('span', { class: 'pl' }, `${p.place}`) : null,
      holder ? el('span', { class: 'bm' }, '💣') : null);
  }

  function ring(s) {
    return el('div', { class: 'bomb-ring' }, (s.players || []).map((p) => chip(p, s)));
  }

  function topicLine(s) {
    return el('div', { class: 'bomb-topic-tv' }, el('span', { class: 'lbl' }, 'Тема'), s.topic || '');
  }

  function fuse(p) {
    const svg = `<svg viewBox="0 0 100 100" class="bomb-fuse-ring" aria-hidden="true">
      <circle cx="50" cy="50" r="${R}" class="track"/>
      <circle cx="50" cy="50" r="${R}" class="burn" stroke-dasharray="${C}" stroke-dashoffset="0"/></svg>`;
    const wrap = el('div', { class: 'bomb-avatar' }, el('img', { src: p.avatar_url, alt: '' }), el('span', { class: 'bomb-badge' }, '💣'));
    wrap.insertAdjacentHTML('afterbegin', svg);
    return wrap;
  }

  function tick() {
    cancelAnimationFrame(raf);
    const s = ctx.bomb;
    if (!s) return;
    const now = ctx.link.serverNow();
    if (s.phase === 'countdown' && ui.big) {
      const n = Math.ceil((s.start_at_ms - now) / 1000);
      const txt = n > 3 ? 'Готовься!' : n > 0 ? String(n) : 'Поехали!';
      if (txt !== lastCount) { lastCount = txt; ui.big.textContent = txt; if (n <= 3 && n > 0) ctx.sfx('countdown'); }
    } else if (s.phase === 'running' && ui.secs && s.deadline_ms) {
      const left = Math.max(0, s.deadline_ms - now);
      const total = (s.turn_seconds || 1) * 1000;
      ui.secs.textContent = (left / 1000).toFixed(1);
      ui.burn?.setAttribute('stroke-dashoffset', String(C * (1 - left / total)));
      const hot = left < Math.min(2000, total / 2);
      ui.card?.classList.toggle('hot', hot);
      const sec = Math.ceil(left / 1000);
      if (sec !== lastSec && left > 0) { lastSec = sec; ctx.sfx('warning-tick'); }
    } else if (s.phase === 'topic' && ui.reel) {
      spin(now, s);
    }
    raf = requestAnimationFrame(tick);
  }

  // рулетка тем: мелькают и замедляются, к моменту раскрытия встаёт выбранная
  function spin(now, s) {
    const left = s.topic_reveal_at_ms - now;
    if (left <= 0) { render(true); return; }
    const words = ui.reelWords;
    const step = Math.floor(Math.pow(Math.max(0, 4000 - left) / 4000, 0.45) * 40);
    if (step !== ui.reelStep) {
      ui.reelStep = step;
      ui.reel.textContent = words[step % words.length];
      ui.reel.classList.remove('flick');
      void ui.reel.offsetWidth;
      ui.reel.classList.add('flick');
    }
  }

  function render(force = false) {
    const s = ctx.bomb || { phase: 'idle', players: [], points: [], timing: {} };
    const revealed = s.phase !== 'topic' || ctx.link.serverNow() >= s.topic_reveal_at_ms;
    const k = [s.phase, s.round, s.holder?.player_id, s.boom?.player_id, revealed].join(':');
    if (k === key && !force) {
      if (ui.ring) ui.ring.replaceWith(ui.ring = ring(s));
      return;
    }
    const prev = key;
    key = k;
    lastCount = null;
    lastSec = null;
    ui = {};
    cancelAnimationFrame(raf);
    clear(box);
    box.className = `tv-scene bomb-tv ${s.phase}`;
    put(el('div', { class: 'bomb-top' },
      el('div', { class: 'qt-head' }, s.round ? `Бомба · раунд ${s.round} из ${s.rounds}` : 'Бомба'),
      s.phase === 'running' || s.phase === 'boom'
        ? el('div', { class: 'qt-chip bomb-lap' }, `Круг ${s.lap} · ${s.turn_seconds ?? s.timing.start_seconds} с на ход · в игре ${s.alive_count}`)
        : null));

    if (s.phase === 'idle') {
      const t = s.timing || {};
      put(el('div', { class: 'qt-big' }, '💣 Бомба'),
        el('div', { class: 'qt-sub' }, 'Называй слово на тему — и передавай бомбу!'),
        el('div', { class: 'qt-meta' }, `Первый круг ${t.start_seconds ?? 5} с на ход, каждый следующий на ${t.step_seconds ?? 1} с меньше.`),
        el('div', { class: 'qt-meta' }, 'Не успел — взорвался. Повторять слова нельзя. Последний выживший побеждает.'),
        el('div', { class: 'qt-meta' }, `Очки за места: ${(s.points || []).map((p, i) => `${i + 1} — ${p}`).join(' · ')}`),
        ui.ring = ring(s));
      return;
    }
    if (s.phase === 'topic' && !revealed) {
      ui.reelWords = [...(s.reel || []), s.topic].filter(Boolean);
      ui.reel = el('div', { class: 'bomb-reel' }, ui.reelWords[0] || '…');
      put(el('div', { class: 'bomb-reel-lbl' }, 'Выбираем тему'), ui.reel, ui.ring = ring(s));
      tick();
      return;
    }
    if (s.phase === 'topic') {
      if (prev && !prev.endsWith(':true')) ctx.sfx('correct');
      put(el('div', { class: 'bomb-reel-lbl' }, 'Тема раунда'), el('div', { class: 'bomb-reel chosen' }, s.topic),
        el('div', { class: 'qt-meta' }, 'Придумывайте слова! Ведущий сейчас даст старт.'), ui.ring = ring(s));
      return;
    }
    if (s.phase === 'countdown') {
      ui.big = el('div', { class: 'game-big' });
      put(topicLine(s), ui.big,
        s.next_holder ? el('div', { class: 'qt-meta' }, `Первым ходит: ${s.next_holder.name}`) : null, ui.ring = ring(s));
      tick();
      return;
    }
    if (s.phase === 'running' && s.holder) {
      if (prev?.startsWith('running:')) ctx.sfx('game-catch');
      else ctx.sfx('game-start');
      const f = fuse(s.holder);
      ui.burn = f.querySelector('.burn');
      ui.secs = el('div', { class: 'bomb-secs' });
      ui.card = el('div', { class: 'bomb-card' }, f, el('div', { class: 'bomb-info' }, el('div', { class: 'bomb-name' }, s.holder.name), ui.secs));
      put(topicLine(s), ui.card, ui.ring = ring(s));
      tick();
      return;
    }
    if (s.phase === 'boom' && s.boom) {
      ctx.sfx('game-rotten');
      put(topicLine(s),
        el('div', { class: 'bomb-explode' },
          el('div', { class: 'bomb-avatar dead' }, el('img', { src: s.boom.avatar_url, alt: '' }), el('span', { class: 'bomb-flash' }, '💥')),
          el('div', { class: 'bomb-info' }, el('div', { class: 'bomb-name' }, s.boom.name), el('div', { class: 'bomb-out' }, `выбывает · ${s.boom.place} место`))),
        s.next_holder ? el('div', { class: 'qt-meta' }, `Дальше ходит: ${s.next_holder.name}`) : null,
        ui.ring = ring(s));
      return;
    }
    if (s.phase === 'round_over') {
      ctx.sfx('game-end');
      const res = s.results || [];
      const win = res[0];
      const table = el('div', { class: 'qt-table bomb-results' }, el('h2', {}, `Раунд ${s.round}: «${s.topic}»`));
      for (const r of res) {
        table.append(el('div', { class: 'qt-row' }, el('span', { class: 'place' }, `${r.place}.`),
          el('img', { class: 'qt-av', src: r.avatar_url, alt: '' }),
          el('span', { class: 'grow' }, r.name + (r.in_scoring ? '' : ' (вне зачёта)')),
          el('b', {}, r.points ? `+${r.points}` : '')));
      }
      const cols = el('div', { class: 'bomb-cols' }, table);
      if (s.done) {
        const tot = el('div', { class: 'qt-table bomb-results' }, el('h2', {}, 'За все раунды'));
        s.totals.forEach((r, i) => tot.append(el('div', { class: 'qt-row' }, el('span', { class: 'place' }, `${i + 1}.`),
          el('img', { class: 'qt-av', src: r.avatar_url, alt: '' }), el('span', { class: 'grow' }, r.name), el('b', {}, `+${r.points}`))));
        cols.append(tot);
      }
      put(win ? el('div', { class: 'bomb-winner' }, el('div', { class: 'bomb-avatar win' }, el('img', { src: win.avatar_url, alt: '' }), el('span', { class: 'bomb-crown' }, '👑')),
        el('div', { class: 'bomb-info' }, el('div', { class: 'qt-meta' }, 'Победитель раунда'), el('div', { class: 'bomb-name' }, win.name))) : null,
      cols, s.done ? el('div', { class: 'qt-meta' }, 'Бомба окончена!') : null);
    }
  }

  render();
  return {
    update: () => render(),
    onMessage(m) { if (m.t === 'bomb') render(); },
    unmount() { cancelAnimationFrame(raf); },
  };
}
