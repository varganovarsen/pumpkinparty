// Квиз на телефоне игрока (модуль 02): кнопки A-D или поле ответа, таймер, результат.
import { el, clear, toast, vibrate } from '/web/shared/util.js';

const LETTERS = ['A', 'B', 'C', 'D'];
const PLACE_BONUS = { 50: 'ты первый!', 25: 'ты второй!', 10: 'ты третий!' };

export function mountQuiz(root, link) {
  const box = el('div', { class: 'quiz' });
  root.append(box);
  let q = null;
  let key = null;          // что сейчас нарисовано (чтобы не сбрасывать ввод)
  let timerEl = null;
  let raf = 0;
  let warned = false;
  let ended = false;
  let draft = '';

  function header() {
    if (!q.round) return null;
    const parts = [`Раунд ${q.round}`];
    if (q.round_title) parts.push(q.round_title);
    if (q.q_index >= 0 && ['question', 'judging', 'reveal'].includes(q.phase)) parts.push(`вопрос ${q.q_index + 1} из ${q.q_count}`);
    return el('div', { class: 'quiz-head' }, parts.join(' · '));
  }

  function tickTimer() {
    cancelAnimationFrame(raf);
    if (!timerEl || q.phase !== 'question' || !q.deadline_ms) return;
    const total = q.answer_seconds * 1000;
    const left = q.deadline_ms - link.serverNow();
    const warn = left <= q.warn_seconds * 1000;
    timerEl.style.width = `${Math.max(0, Math.min(100, (left / total) * 100))}%`;
    timerEl.parentElement.classList.toggle('warn', warn && left > 0);
    timerEl.parentElement.dataset.left = left > 0 ? `${Math.ceil(left / 1000)} с` : 'Время вышло';
    if (warn && !warned && left > 0) { warned = true; vibrate([80, 60, 80]); }
    if (left <= 0 && !ended) { ended = true; vibrate(300); }
    if (left > 0) raf = requestAnimationFrame(tickTimer);
  }

  function timerBar() {
    const bar = el('div', { class: 'qtimer' }, timerEl = el('div', { class: 'fill' }));
    return bar;
  }

  async function send(payload, btns) {
    btns.forEach((b) => { b.disabled = true; });
    const r = await link.cmd('quiz_answer', { qid: q.question.id, ...payload });
    if (!r.ok) {
      toast(r.error || 'Ответ не принят');
      if (r.code !== 'already' && r.code !== 'closed') btns.forEach((b) => { b.disabled = false; });
    } else {
      draft = '';
    }
  }

  function renderQuestion() {
    const my = q.my || {};
    const out = [header(), timerBar(), el('div', { class: 'qtext' }, q.question.text)];
    if (!my.eligible) {
      out.push(el('div', { class: 'qnote' }, 'Идёт вопрос, подключишься со следующего'));
      return out;
    }
    if (my.answered) {
      const mine = q.question.kind === 'choice'
        ? `${LETTERS[my.choice]}. ${q.question.options[my.choice]}` : my.text;
      out.push(el('div', { class: 'qdone' }, el('div', { class: 'big' }, '✓ Ответ принят'), el('div', {}, mine)));
      return out;
    }
    if (q.question.kind === 'choice') {
      const btns = [];
      const grid = el('div', { class: 'qopts' });
      q.question.options.forEach((o, i) => {
        const b = el('button', { class: 'qopt', onclick: () => send({ choice: i }, btns) },
          el('span', { class: 'letter' }, LETTERS[i]), el('span', {}, o));
        btns.push(b);
        grid.append(b);
      });
      out.push(grid);
    } else {
      const ta = el('textarea', { rows: '3', maxlength: '200', placeholder: 'Твой ответ' });
      ta.value = draft;
      ta.addEventListener('input', () => { draft = ta.value; });
      const b = el('button', { class: 'primary', style: { width: '100%', marginTop: '10px' } }, 'Отправить');
      b.addEventListener('click', () => {
        if (!ta.value.trim()) { toast('Напиши ответ'); return; }
        send({ text: ta.value }, [b, ta]);
      });
      out.push(ta, b, el('p', { class: 'muted center' }, 'Отправить можно один раз, исправить нельзя'));
    }
    return out;
  }

  function resultCard() {
    const my = q.my || {};
    const res = my.result || {};
    if (res.skipped) return el('div', { class: 'qres' }, el('div', { class: 'big' }, 'Вопрос пропущен'));
    if (!my.answered) return el('div', { class: 'qres' }, el('div', { class: 'big' }, my.eligible ? 'Нет ответа' : 'Подключишься со следующего вопроса'));
    if (res.correct) {
      const sum = res.points + res.bonus;
      return el('div', { class: 'qres ok' },
        el('div', { class: 'big' }, `+${sum}${res.bonus ? `, ${PLACE_BONUS[res.bonus] || 'бонус!'}` : ''}`),
        q.question.kind === 'text' ? el('div', {}, 'Ответ принят') : null);
    }
    return el('div', { class: 'qres bad' }, el('div', { class: 'big' }, q.question.kind === 'text' ? 'Ответ не принят' : 'Неверно'));
  }

  function renderReveal() {
    const out = [header(), el('div', { class: 'qtext' }, q.question.text), resultCard()];
    const rv = q.reveal || {};
    if (q.question.kind === 'choice' && rv.correct !== undefined) {
      out.push(el('p', { class: 'center muted' }, `Правильный ответ: ${LETTERS[rv.correct]}. ${q.question.options[rv.correct]}`));
    } else if (rv.answer) {
      out.push(el('p', { class: 'center muted' }, `Эталон: ${rv.answer}`));
    }
    return out;
  }

  function render() {
    const k = `${q.phase}:${q.round}:${q.q_index}:${q.my?.answered}:${q.my?.eligible}`;
    if (k === key && q.phase === 'question') { tickTimer(); return; } // идёт ввод — не перерисовывать
    const newQuestion = q.phase === 'question' && !key?.startsWith(`question:${q.round}:${q.q_index}:`);
    key = k;
    timerEl = null;
    clear(box);
    let parts;
    switch (q.phase) {
      case 'intro':
        parts = [el('div', { class: 'qbig' }, `Раунд ${q.round}`), el('div', { class: 'qtext' }, q.round_title || ''),
          el('p', { class: 'muted center' }, 'Готовься! Вопрос появится здесь, картинки — на экране.')];
        break;
      case 'question':
        if (newQuestion) { warned = false; ended = false; draft = ''; vibrate(150); }
        parts = renderQuestion();
        break;
      case 'judging':
        parts = [header(), el('div', { class: 'qtext' }, q.question.text),
          q.my?.answered ? el('div', { class: 'qdone' }, el('div', {}, 'Твой ответ:'), el('div', { class: 'big' }, q.my.text)) : null,
          el('p', { class: 'muted center' }, 'Ведущий проверяет ответы…')];
        break;
      case 'reveal':
        parts = renderReveal();
        break;
      case 'rating': {
        const my = q.my || {};
        parts = [el('div', { class: 'qbig' }, `Итоги раунда ${q.round}`),
          el('div', { class: 'qres' }, el('div', { class: 'big' }, `+${my.round_points || 0} за раунд`),
            my.round_place ? el('div', {}, `${my.round_place} место в раунде`) : null),
          el('p', { class: 'muted center' }, q.done ? 'Квиз окончен!' : 'Рейтинг на экране телевизора')];
        break;
      }
      default:
        parts = [el('div', { class: 'qbig' }, 'Квиз'), el('p', { class: 'muted center' }, 'Скоро начнём — смотри на экран!')];
    }
    box.append(...parts.filter(Boolean));
    tickTimer();
  }

  return {
    update(next) { q = next; if (q) render(); },
    unmount() { cancelAnimationFrame(raf); },
  };
}
