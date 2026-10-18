// «Бомба» на телефоне (модуль 10): у кого бомба — называет слово на тему и жмёт «Передать».
// Не успел — взорвался и выбыл. Остальные видят, у кого бомба и не они ли следующие.
import { el, clear, vibrate } from '/web/shared/util.js';

export function mountBomb(root, link) {
  const box = el('div', { class: 'bomb' });
  root.append(box);
  const put = (...xs) => box.append(...xs.filter(Boolean)); // append() печатает null как текст
  let s = null;
  let key = null;        // что сейчас нарисовано
  let ui = {};
  let raf = 0;
  let sending = false;

  function who(p) {
    return el('span', { class: 'bomb-who' }, el('img', { class: 'avatar', src: p.avatar_url, alt: '' }), p.name);
  }

  function topicEl(cls = '') {
    return el('div', { class: `bomb-topic ${cls}` }, el('div', { class: 'muted' }, 'Тема'), el('div', { class: 'big' }, s.topic || ''));
  }

  // следующий живой после того, у кого бомба (по кругу)
  function nextAfterHolder() {
    const ring = s.players || [];
    const from = s.holder || s.next_holder;
    const i = ring.findIndex((p) => p.player_id === from?.player_id);
    if (i < 0) return null;
    for (let k = 1; k < ring.length; k++) {
      const p = ring[(i + k) % ring.length];
      if (p.alive) return p;
    }
    return null;
  }

  async function pass() {
    if (sending) return;
    sending = true;
    ui.btn?.setAttribute('disabled', '');
    const r = await link.cmd('bomb_pass', {});
    sending = false;
    if (r.ok) vibrate(40);
    else ui.btn?.removeAttribute('disabled');
  }

  function tick() {
    cancelAnimationFrame(raf);
    if (!s) return;
    const now = link.serverNow();
    if (ui.count && s.phase === 'countdown') {
      const n = Math.ceil((s.start_at_ms - now) / 1000);
      ui.count.textContent = n > 3 ? 'Готовься!' : n > 0 ? String(n) : 'Поехали!';
    }
    if (ui.left && s.phase === 'running' && s.deadline_ms) {
      const left = Math.max(0, s.deadline_ms - now);
      ui.left.textContent = (left / 1000).toFixed(1);
      if (ui.fuse) ui.fuse.style.width = `${Math.min(100, (left / (s.turn_seconds * 1000)) * 100)}%`;
    }
    if (ui.reveal && s.phase === 'topic' && now >= s.topic_reveal_at_ms) { render(true); return; }
    raf = requestAnimationFrame(tick);
  }

  function build() {
    const my = s.my || {};
    const revealed = s.phase !== 'topic' || link.serverNow() >= s.topic_reveal_at_ms;
    ui = {};
    clear(box);
    box.className = 'bomb';
    const head = el('div', { class: 'quiz-head' }, s.round ? `Бомба · раунд ${s.round} из ${s.rounds}` : 'Бомба');
    if (s.phase === 'idle') {
      put(head, el('div', { class: 'qbig' }, '💣'),
        el('div', { class: 'bomb-rules' },
          el('p', {}, 'На экране появится тема. Бомба ходит по кругу: когда она у тебя — назови вслух слово на тему и жми «Передать».'),
          el('p', {}, `Не успел — взорвался и выбыл. Каждый круг времени меньше: ${s.timing?.start_seconds ?? 5} с, потом на ${s.timing?.step_seconds ?? 1} с меньше.`),
          el('p', { class: 'muted' }, `Повторять слова нельзя — ведущий следит. Последний выживший побеждает, очки получают пятеро последних: ${(s.points || []).join(', ')}.`)),
        el('p', { class: 'center muted' }, 'Ждём тему'));
      return;
    }
    if (s.phase === 'topic') {
      if (!revealed) {
        ui.reveal = el('div', { class: 'qbig bomb-spin' }, '🎰');
        put(head, ui.reveal, el('p', { class: 'center muted' }, 'Выбираем тему — смотри на экран!'));
        return;
      }
      put(head, topicEl(), my.in_round
        ? el('p', { class: 'center' }, 'Придумывай слова заранее! Ждём старта.')
        : el('p', { class: 'center muted' }, my.can_play ? 'Ты в этом раунде смотришь: зайди в сеть до старта' : 'Ведущий в этот раз смотрит'));
      return;
    }
    if (!my.in_round) {
      put(head, topicEl(), s.holder ? el('p', { class: 'center' }, 'Сейчас ходит ', who(s.holder)) : null,
        el('p', { class: 'center muted' }, s.phase === 'round_over' ? 'Раунд окончен' : 'Ты смотришь этот раунд. Сыграешь в следующем!'));
      return;
    }
    if (s.phase === 'countdown') {
      ui.count = el('div', { class: 'qbig' }, 'Готовься!');
      const first = s.next_holder;
      put(head, topicEl(), ui.count,
        first ? el('p', { class: 'center' }, first.player_id === my_id() ? 'Бомба сначала у тебя!' : ['Первым ходит ', who(first)]) : null);
      return;
    }
    if (s.phase === 'running' && my.holder) {
      box.className = 'bomb hot';
      ui.left = el('div', { class: 'bomb-left' });
      ui.fuse = el('div', { class: 'fill' });
      ui.btn = el('button', { class: 'bomb-pass', onclick: pass }, el('span', { class: 'ic' }, '💣'), 'Передать');
      put(topicEl('hot'), el('div', { class: 'bomb-fuse' }, ui.fuse), ui.left,
        el('p', { class: 'center' }, 'Назови слово вслух и жми!'), ui.btn);
      return;
    }
    if ((s.phase === 'running' || s.phase === 'boom') && my.alive) {
      const nxt = nextAfterHolder();
      const mineNext = nxt?.player_id === my_id();
      ui.left = s.phase === 'running' ? el('div', { class: 'bomb-left small' }) : null;
      put(head, topicEl(),
        s.phase === 'boom'
          ? el('div', { class: 'bomb-boom' }, '💥 Бах! Выбывает ', who(s.boom))
          : el('div', { class: 'bomb-holder' }, el('div', { class: 'muted' }, 'Сейчас ходит'), who(s.holder)),
        ui.left,
        mineNext ? el('div', { class: 'bomb-next' }, 'Ты следующий — готовь слово!') : null,
        el('p', { class: 'center muted' }, `Круг ${s.lap} · ${s.turn_seconds ?? s.timing?.start_seconds} с на ход · в игре ${s.alive_count}`));
      return;
    }
    if (s.phase === 'round_over') {
      const mine = (s.results || []).find((r) => r.player_id === my_id());
      const winner = (s.results || [])[0];
      put(head,
        el('div', { class: 'qbig' }, mine?.place === 1 ? '🏆' : '💥'),
        el('div', { class: 'qres ok' }, el('div', { class: 'big' }, mine ? `${mine.place} место` : 'Раунд окончен'),
          mine?.points ? el('div', {}, `+${mine.points}`) : null),
        winner && winner.player_id !== my_id() ? el('p', { class: 'center' }, 'Победитель: ', who(winner)) : null,
        el('p', { class: 'center muted' }, s.done ? `Бомба окончена! Всего за бомбу: +${my.points || 0}` : 'Следующий раунд — по команде ведущего'));
      return;
    }
    // выбыл
    put(head, topicEl(),
      el('div', { class: 'qres bad' }, el('div', { class: 'big' }, '💥 Бах! Ты выбываешь'), my.place ? el('div', {}, `${my.place} место в раунде`) : null),
      s.holder ? el('p', { class: 'center' }, 'Сейчас ходит ', who(s.holder)) : null,
      el('p', { class: 'center muted' }, 'Смотри на экран и болей!'));
  }

  function my_id() { return s.my?.player_id; }

  function render(force = false) {
    const my = s.my || {};
    const k = [s.phase, s.round, s.holder?.player_id, s.boom?.player_id, my.in_round, my.alive, s.lap,
      s.phase === 'topic' && link.serverNow() >= s.topic_reveal_at_ms].join(':');
    if (k !== key || force) {
      const gotIt = my.holder && !key?.startsWith(`running:${s.round}:${s.holder?.player_id}:`);
      key = k;
      if (gotIt) vibrate([120, 60, 120]);
      if (s.phase === 'boom' && !my.alive && s.boom?.player_id === my_id()) vibrate(500);
      build();
    }
    tick();
  }

  return {
    update(next) {
      s = next;
      if (s) render();
    },
    unmount() { cancelAnimationFrame(raf); },
  };
}
