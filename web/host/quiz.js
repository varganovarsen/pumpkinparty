// Раздел квиза на /host (модуль 02): ход раунда, ответы, вердикты раунда 4.
import { el, clear } from '/web/shared/util.js';

const LETTERS = ['A', 'B', 'C', 'D'];
const PHASES = {
  idle: 'не начат', intro: 'заставка раунда', question: 'идёт вопрос', judging: 'проверка ответов',
  reveal: 'разбор', rating: 'итоги раунда',
};

export function quizPanel(link, run) {
  const root = el('div', { class: 'quiz-host' });
  let raf = 0;
  let timerEl = null;

  function tick(q) {
    cancelAnimationFrame(raf);
    if (!timerEl || q.phase !== 'question') return;
    const left = Math.max(0, q.deadline_ms - link.serverNow());
    timerEl.textContent = `${Math.ceil(left / 1000)} с`;
    timerEl.classList.toggle('status-fail', left <= q.warn_seconds * 1000);
    if (left > 0) raf = requestAnimationFrame(() => tick(q));
  }

  function verdictRow(a) {
    const set = (ok) => run('quiz_verdict', { player_id: a.player_id, ok });
    return el('div', { class: 'qh-ans' },
      el('img', { class: 'avatar', src: a.avatar_url, alt: '' }),
      el('div', { class: 'grow' }, el('b', {}, a.name), el('div', {}, a.text), el('div', { class: 'muted' }, `${a.t} с`)),
      el('button', { class: `vbtn${a.verdict === 1 ? ' on-ok' : ''}`, onclick: () => set(a.verdict === 1 ? null : true) }, '✓'),
      el('button', { class: `vbtn${a.verdict === 0 ? ' on-bad' : ''}`, onclick: () => set(a.verdict === 0 ? null : false) }, '✗'));
  }

  function update(q) {
    cancelAnimationFrame(raf);
    timerEl = null;
    clear(root);
    if (!q) return;
    const status = q.round
      ? `Раунд ${q.round}/${q.rounds_total} «${q.round_title}»` + (q.q_index >= 0 ? `, вопрос ${q.q_index + 1}/${q.q_count}` : '')
      : 'Квиз ещё не начат';
    root.append(el('div', { class: 'row' }, el('b', { class: 'grow' }, status),
      el('span', { class: 'badge' }, q.done && q.phase === 'rating' ? 'квиз окончен' : PHASES[q.phase] || q.phase)));

    const full = q.question_full;
    if (full && ['question', 'judging', 'reveal'].includes(q.phase)) {
      const qbox = el('div', { class: 'qh-q' }, el('div', { class: 'qh-text' }, full.text));
      if (full.kind === 'choice') {
        full.options.forEach((o, i) => qbox.append(el('div', { class: i === full.correct ? 'qh-correct' : 'muted' },
          `${LETTERS[i]}. ${o}${i === full.correct ? '  ✓' : ''}`)));
      } else {
        qbox.append(el('div', { class: 'qh-correct' }, `Эталон: ${full.answer}`));
      }
      root.append(qbox);
    }

    if (q.phase === 'question') {
      timerEl = el('b');
      root.append(el('div', { class: 'row' }, el('span', {}, 'Осталось: '), timerEl,
        el('span', { class: 'grow' }), el('span', {}, `Ответили ${q.answered_count} из ${q.eligible_count}`)));
      if (q.waiting?.length) root.append(el('p', { class: 'muted' }, `Ждём: ${q.waiting.join(', ')}`));
      const list = el('div', { class: 'qh-list' });
      for (const a of q.answers || []) {
        list.append(el('div', {}, `${a.name} — ${a.t} с` + (full.kind === 'choice' ? ` (${LETTERS[a.choice]}${a.choice === full.correct ? ' ✓' : ''})` : '')));
      }
      root.append(list);
    }

    if (q.phase === 'judging') {
      const missing = (q.answers || []).filter((a) => a.verdict === null).length;
      root.append(el('p', { class: missing ? 'status-warn' : 'status-ok' },
        missing ? `Без вердикта: ${missing}` : 'Все вердикты выставлены — можно раскрывать'));
      for (const a of q.answers || []) root.append(verdictRow(a));
      if (!(q.answers || []).length) root.append(el('p', { class: 'muted' }, 'Никто не ответил'));
      root.append(el('button', { style: { width: '100%' }, disabled: !missing, onclick: () => run('quiz_verdict_rest', { ok: false }) },
        'Остальные отметить ✗'));
    }

    if (q.phase === 'reveal' && q.reveal) {
      const rv = q.reveal;
      if (rv.skipped) root.append(el('p', { class: 'status-warn' }, 'Вопрос пропущен, очков нет'));
      else if (rv.top?.length) root.append(el('p', {}, 'Бонусы: ' + rv.top.map((t) => `${t.name} +${t.bonus}`).join(', ')));
      else root.append(el('p', { class: 'muted' }, 'Правильных ответов нет'));
    }

    if (q.phase === 'rating' && q.rating) {
      const rows = el('div', { class: 'qh-list' });
      for (const r of q.rating.round) rows.append(el('div', {}, `${r.place}. ${r.name} — ${r.points}`));
      root.append(el('h3', {}, 'Рейтинг раунда'), rows);
      if (!q.rating.total) root.append(el('p', { class: 'muted' }, 'Общий рейтинг скрыт (откроется в финале)'));
    }

    // основная кнопка дублирует «Следующий шаг», чтобы управлять, не прокручивая страницу
    const nx = q.next;
    if (nx) {
      root.append(el('button', { class: 'primary', style: { width: '100%', marginTop: '10px' }, disabled: !!nx.disabled,
        onclick: () => run(nx.cmd, nx.args || {}) }, nx.label));
      if (nx.hint) root.append(el('p', { class: 'muted center' }, nx.hint));
    }
    tick(q);
  }

  return { el: root, update };
}
