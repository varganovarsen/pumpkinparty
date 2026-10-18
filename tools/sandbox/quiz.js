// Песочница квиза: настоящий mountQuiz (web/play/quiz.js) на подставном сервере.
// Собирается в один html: python tools/make_sandbox.py. Данные — window.SANDBOX (вопросы из content/).
const DATA = window.SANDBOX;
const SECONDS = [60, 20, 10];
const BONUS_BY_PLACE = [50, 25, 10];

const S = {
  round: 1,
  step: 0,                 // номер шага в сценарии раунда
  answerSeconds: 20,
  deadline: 0,
  eligible: true,
  place: 1,                // каким по счёту среди верных пришёл мой ответ (0 — не в тройке)
  verdict: true,           // раунд 4: что решил ведущий
  error: 'none',           // как сервер ответит на отправку
  answers: {},             // qid -> {choice?, text?}
  results: {},             // qid -> {points, bonus, correct, skipped}
};

const ERRORS = {
  late: { ok: false, code: 'late', error: 'Время вышло' },
  closed: { ok: false, code: 'closed', error: 'Вопрос закрыт' },
  offline: { ok: false, code: 'offline', error: 'Нет связи с сервером' },
};

// ---------------------------------------------------------------- сценарий раунда
function roundData(r = S.round) {
  return DATA.rounds[r - 1];
}

// idle → intro → (question → [judging] → reveal) × N → rating
function steps(r = S.round) {
  const rd = roundData(r);
  const out = [{ phase: 'idle' }, { phase: 'intro' }];
  rd.questions.forEach((_, i) => {
    out.push({ phase: 'question', q: i });
    if (rd.kind === 'text') out.push({ phase: 'judging', q: i });
    out.push({ phase: 'reveal', q: i });
  });
  out.push({ phase: 'rating' });
  return out;
}

function current() {
  return steps()[S.step];
}

function resultFor(rd, question) {
  const a = S.answers[question.id];
  if (!a) return null;
  const correct = rd.kind === 'text' ? S.verdict : a.choice === question.correct;
  const bonus = correct && S.place ? BONUS_BY_PLACE[S.place - 1] : 0;
  return { points: correct ? 200 : 0, bonus, correct, skipped: false };
}

function roundPoints(r) {
  return roundData(r).questions.reduce((s, x) => s + ((S.results[x.id]?.points || 0) + (S.results[x.id]?.bonus || 0)), 0);
}

function totalScore() {
  return Object.values(S.results).reduce((s, x) => s + x.points + x.bonus, 0);
}

// состояние модуля quiz для игрока, как его шлёт сервер (docs/PROTOCOL.md)
function snapshot() {
  const rd = roundData();
  const st = current();
  const q = {
    round: st.phase === 'idle' ? 0 : S.round,
    rounds_total: DATA.rounds.length,
    phase: st.phase,
    done: st.phase === 'rating' && S.round === DATA.rounds.length,
    round_title: rd.title,
    q_index: st.q ?? -1,
    q_count: rd.questions.length,
    answer_seconds: S.answerSeconds,
    warn_seconds: Math.min(10, Math.floor(S.answerSeconds / 2)),
    deadline_ms: S.deadline,
    my: { eligible: S.eligible, answered: false },
  };
  if (st.q !== undefined) {
    const src = rd.questions[st.q];
    q.question = { id: src.id, kind: rd.kind, text: src.text, options: src.options };
    const a = S.answers[src.id];
    if (a) Object.assign(q.my, { answered: true }, a);
    if (st.phase === 'reveal') {
      q.my.result = S.results[src.id] || { points: 0, bonus: 0, correct: false, skipped: false };
      q.reveal = rd.kind === 'text' ? { skipped: false, answer: src.answer } : { skipped: false, correct: src.correct };
    }
  }
  if (st.phase === 'rating') {
    q.my.round_points = roundPoints(S.round);
    q.my.round_place = q.my.round_points ? Math.max(1, 4 - S.place) : 0;
  }
  return q;
}

// ---------------------------------------------------------------- подставной сервер
const link = {
  serverNow: () => Date.now(),
  async cmd(name, payload) {
    await new Promise((r) => setTimeout(r, 250));
    if (name !== 'quiz_answer') return { ok: false, error: `Песочница не знает команду ${name}` };
    if (S.error !== 'none') return ERRORS[S.error];
    if (current().phase !== 'question') return ERRORS.closed;
    if (S.deadline && Date.now() > S.deadline) return ERRORS.late;
    if (S.answers[payload.qid]) return { ok: false, code: 'already', error: 'Ответ уже принят' };
    S.answers[payload.qid] = payload.text !== undefined ? { text: payload.text.trim() } : { choice: payload.choice };
    push();
    return { ok: true };
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
    el('div', { class: 'score' }, `${totalScore()} очк.`),
  );
}

function push() {
  view.update(snapshot());
  renderTop();
  renderBar();
  renderSheet();
}

function go(step) {
  const all = steps();
  S.step = Math.max(0, Math.min(all.length - 1, step));
  const st = all[S.step];
  if (st.phase === 'question') S.deadline = Date.now() + S.answerSeconds * 1000;
  if (st.phase === 'reveal') {
    const rd = roundData();
    const question = rd.questions[st.q];
    S.results[question.id] = resultFor(rd, question) || { points: 0, bonus: 0, correct: false, skipped: false };
  }
  push();
}

function setRound(r) {
  S.round = r;
  for (const x of roundData(r).questions) { delete S.answers[x.id]; delete S.results[x.id]; }
  go(1);
}

// ---------------------------------------------------------------- пульт
const PHASE_NAMES = { idle: 'ожидание', intro: 'заставка', question: 'вопрос', judging: 'проверка', reveal: 'ответ', rating: 'итоги' };

const bar = el('div', { class: 'sb-bar' });
const sheet = el('div', { class: 'sb-sheet', hidden: true });
document.body.append(sheet, bar);

function stepLabel() {
  const st = current();
  const parts = [`Р${S.round}`];
  if (st.q !== undefined) parts.push(`В${st.q + 1}`);
  parts.push(PHASE_NAMES[st.phase]);
  return parts.join(' · ');
}

function renderBar() {
  const last = steps().length - 1;
  clear(bar).append(
    el('button', { class: 'sb-nav', 'aria-label': 'Назад', disabled: S.step === 0, onclick: () => go(S.step - 1) }, '‹'),
    el('button', { class: 'sb-label', onclick: () => { sheet.hidden = !sheet.hidden; renderBar(); renderSheet(); } }, stepLabel(), el('span', { class: 'sb-hint' }, sheet.hidden ? 'пульт ▴' : 'скрыть ▾')),
    S.step === last && S.round < DATA.rounds.length
      ? el('button', { class: 'sb-nav', 'aria-label': 'Следующий раунд', onclick: () => setRound(S.round + 1) }, '»')
      : el('button', { class: 'sb-nav', 'aria-label': 'Дальше', disabled: S.step === last, onclick: () => go(S.step + 1) }, '›'),
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
  const st = current();
  const rd = roundData();
  const qid = st.q !== undefined ? rd.questions[st.q].id : null;
  clear(sheet).append(
    seg('Раунд', DATA.rounds.map((r, i) => [i + 1, `${i + 1}. ${r.title}`]), S.round, setRound),
    seg('Фаза', Object.entries(PHASE_NAMES).filter(([p]) => p !== 'judging' || rd.kind === 'text'), st.phase, (p) => {
      // фаза вопроса — у того же вопроса, что сейчас (или у первого)
      const i = steps().findIndex((x) => x.phase === p && (x.q === undefined || x.q === (st.q ?? 0)));
      if (i >= 0) go(i);
    }),
    seg('Время на ответ', SECONDS.map((s) => [s, `${s} с`]), S.answerSeconds, (s) => {
      S.answerSeconds = s;
      if (current().phase === 'question') go(S.step);
      else push();
    }),
    seg('Я в игре', [[true, 'с начала'], [false, 'зашёл посреди вопроса']], S.eligible, (v) => { S.eligible = v; push(); }),
    rd.kind === 'text'
      ? seg('Ведущий решил', [[true, 'ответ принят'], [false, 'не принят']], S.verdict, (v) => { S.verdict = v; push(); })
      : seg('Мой верный ответ пришёл', [[1, 'первым'], [2, 'вторым'], [3, 'третьим'], [0, 'позже']], S.place, (v) => { S.place = v; push(); }),
    seg('Сервер на отправку', [['none', 'принимает'], ['late', 'поздно'], ['closed', 'закрыт'], ['offline', 'нет связи']], S.error, (v) => { S.error = v; push(); }),
    el('div', { class: 'sb-row' },
      el('button', { disabled: !qid || !S.answers[qid], onclick: () => { delete S.answers[qid]; delete S.results[qid]; go(S.step); } }, 'Стереть мой ответ'),
      el('button', { onclick: () => { S.answers = {}; S.results = {}; S.round = 1; go(0); } }, 'Всё сначала')),
    el('p', { class: 'sb-foot' }, 'Экран выше — настоящий web/play/quiz.js. Сервер подставной, вопросы из content/.'),
  );
}

go(1);
