// Песочница квиза: настоящий mountQuiz (web/play/quiz.js) на подставном сервере с подробным пультом.
// Собирается в один html: python tools/make_sandbox.py quiz. Данные — window.SANDBOX (вопросы из content/).
import { el, clear } from '/web/shared/util.js';
import { mountQuiz } from '/web/play/quiz.js';
import { createQuiz, QUIZ_PHASES } from '/sandbox/engine_quiz.js';

const DATA = window.SANDBOX;
const SECONDS = [60, 20, 10];
const quiz = createQuiz(DATA.rounds, () => push());
const { S } = quiz;

const link = {
  serverNow: () => Date.now(),
  async cmd(name, payload) {
    await new Promise((r) => setTimeout(r, 250));
    if (name !== 'quiz_answer') return { ok: false, error: `Песочница не знает команду ${name}` };
    return quiz.answer(payload);
  },
};

// ---------------------------------------------------------------- экран игрока
const app = document.getElementById('app');
const topEl = el('div', { class: 'topbar' });
const mainEl = el('div');
app.append(topEl, mainEl);
const view = mountQuiz(mainEl, link);

function renderTop() {
  clear(topEl).append(
    el('img', { class: 'avatar', src: DATA.avatar, alt: '' }),
    el('div', {}, el('div', { class: 'name' }, 'Маша')),
    el('div', { class: 'score' }, `${quiz.totalScore()} очк.`),
  );
}

function push() {
  view.update(quiz.snapshot());
  renderTop();
  renderBar();
  renderSheet();
}

// ---------------------------------------------------------------- пульт
const bar = el('div', { class: 'sb-bar' });
const sheet = el('div', { class: 'sb-sheet', hidden: true });
document.body.append(sheet, bar);

function stepLabel() {
  const st = quiz.current();
  const parts = [`Р${S.round}`];
  if (st.q !== undefined) parts.push(`В${st.q + 1}`);
  parts.push(QUIZ_PHASES[st.phase]);
  return parts.join(' · ');
}

function renderBar() {
  const last = quiz.steps().length - 1;
  clear(bar).append(
    el('button', { class: 'sb-nav', 'aria-label': 'Назад', disabled: S.step === 0, onclick: () => quiz.go(S.step - 1) }, '‹'),
    el('button', { class: 'sb-label', onclick: () => { sheet.hidden = !sheet.hidden; renderBar(); renderSheet(); } }, stepLabel(), el('span', { class: 'sb-hint' }, sheet.hidden ? 'пульт ▴' : 'скрыть ▾')),
    S.step === last && S.round < DATA.rounds.length
      ? el('button', { class: 'sb-nav', 'aria-label': 'Следующий раунд', onclick: () => quiz.setRound(S.round + 1) }, '»')
      : el('button', { class: 'sb-nav', 'aria-label': 'Дальше', disabled: S.step === last, onclick: () => quiz.go(S.step + 1) }, '›'),
  );
}

function seg(title, options, value, onPick) {
  return el('div', { class: 'sb-field' },
    el('div', { class: 'sb-title' }, title),
    el('div', { class: 'sb-seg' }, options.map(([v, label]) =>
      el('button', { class: v === value ? 'on' : '', onclick: () => onPick(v) }, label))));
}

function renderSheet() {
  if (sheet.hidden) return;
  const st = quiz.current();
  const rd = quiz.roundData();
  const qid = st.q !== undefined ? rd.questions[st.q].id : null;
  clear(sheet).append(
    seg('Раунд', DATA.rounds.map((r, i) => [i + 1, `${i + 1}. ${r.title}`]), S.round, quiz.setRound),
    seg('Фаза', Object.entries(QUIZ_PHASES).filter(([p]) => p !== 'judging' || rd.kind === 'text'), st.phase, quiz.goPhase),
    seg('Время на ответ', SECONDS.map((s) => [s, `${s} с`]), S.answerSeconds, (s) => {
      S.answerSeconds = s;
      if (quiz.current().phase === 'question') quiz.go(S.step);
      else push();
    }),
    seg('Я в игре', [[true, 'с начала'], [false, 'зашёл посреди вопроса']], S.eligible, (v) => { S.eligible = v; push(); }),
    rd.kind === 'text'
      ? seg('Ведущий решил', [[true, 'ответ принят'], [false, 'не принят']], S.verdict, (v) => { S.verdict = v; push(); })
      : seg('Мой верный ответ пришёл', [[1, 'первым'], [2, 'вторым'], [3, 'третьим'], [0, 'позже']], S.place, (v) => { S.place = v; push(); }),
    seg('Сервер на отправку', [['none', 'принимает'], ['late', 'поздно'], ['closed', 'закрыт'], ['offline', 'нет связи']], S.error, (v) => { S.error = v; push(); }),
    el('div', { class: 'sb-row' },
      el('button', { disabled: !qid || !S.answers[qid], onclick: quiz.clearAnswer }, 'Стереть мой ответ'),
      el('button', { onclick: quiz.reset }, 'Всё сначала')),
    el('p', { class: 'sb-foot' }, 'Экран выше — настоящий web/play/quiz.js. Сервер подставной, вопросы из content/.'),
  );
}

quiz.go(1);
