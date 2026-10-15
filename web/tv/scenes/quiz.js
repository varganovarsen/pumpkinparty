// Квиз на телевизоре (модуль 02): заставка раунда, вопрос с таймером, разбор, рейтинги.
import { el, clear } from '/web/shared/util.js';

const LETTERS = ['A', 'B', 'C', 'D'];

export function mount(root, ctx) {
  const box = el('div', { class: 'quiz-tv' });
  root.append(box);
  let key = null;
  let raf = 0;
  let timer = null;
  let lastTick = null;
  let countEl = null;

  function head(q) {
    const parts = [`Раунд ${q.round} · ${q.round_title || ''}`];
    if (q.q_index >= 0 && ['question', 'judging', 'reveal'].includes(q.phase)) parts.push(`Вопрос ${q.q_index + 1} из ${q.q_count}`);
    return el('div', { class: 'qt-head' }, parts.join('   ·   '));
  }

  function avatar(url) { return el('img', { class: 'qt-av', src: url, alt: '' }); }

  function tick() {
    cancelAnimationFrame(raf);
    const q = ctx.quiz;
    if (!timer || q?.phase !== 'question') return;
    const left = q.deadline_ms - ctx.link.serverNow();
    const secs = Math.max(0, Math.ceil(left / 1000));
    const warn = left > 0 && left <= q.warn_seconds * 1000;
    timer.fill.style.width = `${Math.max(0, Math.min(100, left / (q.answer_seconds * 1000) * 100))}%`;
    timer.num.textContent = left > 0 ? String(secs) : '0';
    timer.bar.classList.toggle('warn', warn);
    if (warn && secs !== lastTick) { lastTick = secs; ctx.sfx('warning-tick'); }
    if (left > 0) raf = requestAnimationFrame(tick);
  }

  function questionView(q) {
    const nodes = [head(q)];
    const body = el('div', { class: 'qt-body' });
    if (q.question.image_url) {
      body.append(el('div', { class: 'qt-img' }, el('img', {
        src: q.question.image_url, alt: '',
        onerror: (e) => { e.target.replaceWith(el('div', { class: 'qt-noimg' }, 'нет картинки')); },
      })));
    }
    const main = el('div', { class: 'qt-main' }, el('div', { class: 'qt-text' }, q.question.text));
    if (q.question.kind === 'choice') {
      const grid = el('div', { class: 'qt-opts' });
      q.question.options.forEach((o, i) => grid.append(el('div', { class: 'qt-opt' }, el('span', { class: 'qt-letter' }, LETTERS[i]), o)));
      main.append(grid);
    }
    body.append(main);
    nodes.push(body);
    timer = { fill: el('div', { class: 'fill' }), num: el('div', { class: 'qt-num' }) };
    timer.bar = el('div', { class: 'qt-timer' }, timer.fill);
    countEl = el('div', { class: 'qt-count' });
    nodes.push(el('div', { class: 'qt-foot' }, timer.bar, timer.num, countEl));
    return nodes;
  }

  function revealView(q) {
    const rv = q.reveal || {};
    const nodes = [head(q), el('div', { class: 'qt-text small' }, q.question.text)];
    if (rv.skipped) { nodes.push(el('div', { class: 'qt-big' }, 'Вопрос пропущен')); return nodes; }
    if (q.question.kind === 'choice') {
      const total = Math.max(1, rv.counts.reduce((a, b) => a + b, 0));
      const grid = el('div', { class: 'qt-opts reveal' });
      q.question.options.forEach((o, i) => grid.append(el('div', { class: `qt-opt${i === rv.correct ? ' correct' : ' wrong'}` },
        el('span', { class: 'qt-letter' }, LETTERS[i]), el('span', { class: 'grow' }, o),
        el('span', { class: 'qt-cnt' }, String(rv.counts[i])),
        el('div', { class: 'qt-share', style: { width: `${(rv.counts[i] / total) * 100}%` } }))));
      nodes.push(grid);
      if (rv.explain) nodes.push(el('div', { class: 'qt-explain' }, rv.explain));
    } else {
      nodes.push(el('div', { class: 'qt-ref' }, `Ответ: ${rv.answer}`));
      const grid = el('div', { class: 'qt-answers' });
      for (const a of rv.answers || []) {
        grid.append(el('div', { class: `qt-ans ${a.verdict ? 'ok' : 'bad'}` }, avatar(a.avatar_url),
          el('div', { class: 'grow' }, el('b', {}, a.name), el('div', {}, a.text)), el('div', { class: 'mark' }, a.verdict ? '✓' : '✗')));
      }
      nodes.push(grid);
    }
    if (rv.top?.length) {
      const top = el('div', { class: 'qt-top' }, el('span', { class: 'muted' }, 'Быстрее всех:'));
      rv.top.forEach((t) => top.append(el('span', { class: 'qt-chip' }, avatar(t.avatar_url), `${t.name} +${t.bonus}`)));
      nodes.push(top);
    }
    return nodes;
  }

  function table(title, rows, cls = '') {
    const t = el('div', { class: `qt-table ${cls}` }, el('h2', {}, title));
    for (const r of rows) {
      t.append(el('div', { class: 'qt-row' }, el('span', { class: 'place' }, `${r.place}.`), avatar(r.avatar_url),
        el('span', { class: 'grow' }, r.name), el('b', {}, String(r.points))));
    }
    if (!rows.length) t.append(el('p', { class: 'muted' }, 'Пока никого'));
    return t;
  }

  function ratingView(q) {
    const rt = q.rating || { round: [], total: null };
    return [el('div', { class: 'qt-big' }, `Итоги раунда ${q.round}`), el('div', { class: 'qt-ratings' },
      table('Раунд', rt.round),
      rt.total ? table('Всего', rt.total) : el('div', { class: 'qt-table hidden-total' }, el('h2', {}, 'Всего'),
        el('p', {}, 'Общий рейтинг скрыт до финала 🤫')))];
  }

  function render() {
    const q = ctx.quiz;
    if (!q) return;
    const k = `${q.phase}:${q.round}:${q.q_index}`;
    if (k === key) {
      // тот же экран: обновить только счётчик ответов
      if (countEl) countEl.textContent = `Ответили ${q.answered_count ?? 0} из ${q.eligible_count ?? 0}`;
      return;
    }
    if (q.phase === 'reveal' && !key?.startsWith('reveal') && !q.reveal?.skipped) {
      ctx.sfx(q.reveal?.top?.length || q.reveal?.answers?.some((a) => a.verdict) ? 'correct' : 'wrong');
    }
    key = k;
    timer = null;
    countEl = null;
    lastTick = null;
    clear(box);
    let nodes;
    switch (q.phase) {
      case 'intro':
        nodes = [el('div', { class: 'qt-big' }, `Раунд ${q.round}`), el('div', { class: 'qt-sub' }, q.round_title || ''),
          el('div', { class: 'qt-meta' }, `${q.q_count} вопросов`)];
        break;
      case 'question': nodes = questionView(q); break;
      case 'judging':
        nodes = [head(q), el('div', { class: 'qt-text' }, q.question.text),
          el('div', { class: 'qt-meta' }, `Ответили ${q.answered_count} из ${q.eligible_count}. Ведущий проверяет ответы…`)];
        break;
      case 'reveal': nodes = revealView(q); break;
      case 'rating': nodes = ratingView(q); break;
      default:
        nodes = [el('div', { class: 'qt-big' }, q.done ? 'Квиз окончен!' : 'Квиз'), el('div', { class: 'qt-sub' }, q.done ? '' : 'Скоро начнём')];
    }
    box.append(...nodes);
    if (countEl) countEl.textContent = `Ответили ${q.answered_count ?? 0} из ${q.eligible_count ?? 0}`;
    tick();
  }

  render();
  return {
    update: render,
    onMessage(m) { if (m.t === 'quiz') render(); },
    unmount() { cancelAnimationFrame(raf); },
  };
}
