// Подставной квиз для песочниц: сценарий раунда и состояние модуля quiz для игрока (docs/PROTOCOL.md).
// Ведущий двигает фазы руками (go/setRound); ответ игрока — answer(), как команда quiz_answer.
const BONUS_BY_PLACE = [50, 25, 10];

const ERRORS = {
  late: { ok: false, code: 'late', error: 'Время вышло' },
  closed: { ok: false, code: 'closed', error: 'Вопрос закрыт' },
  offline: { ok: false, code: 'offline', error: 'Нет связи с сервером' },
};

export const QUIZ_PHASES = { idle: 'ожидание', intro: 'заставка', question: 'вопрос', judging: 'проверка', reveal: 'ответ', rating: 'итоги' };

export function createQuiz(rounds, onChange = () => {}) {
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

  const roundData = (r = S.round) => rounds[r - 1];

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

  const current = () => steps()[S.step];

  function resultFor(rd, question) {
    const a = S.answers[question.id];
    if (!a) return null;
    const correct = rd.kind === 'text' ? S.verdict : a.choice === question.correct;
    const bonus = correct && S.place ? BONUS_BY_PLACE[S.place - 1] : 0;
    return { points: correct ? 200 : 0, bonus, correct, skipped: false };
  }

  const roundPoints = (r) => roundData(r).questions.reduce((s, x) => s + ((S.results[x.id]?.points || 0) + (S.results[x.id]?.bonus || 0)), 0);
  const totalScore = () => Object.values(S.results).reduce((s, x) => s + x.points + x.bonus, 0);

  function snapshot() {
    const rd = roundData();
    const st = current();
    const q = {
      round: st.phase === 'idle' ? 0 : S.round,
      rounds_total: rounds.length,
      phase: st.phase,
      done: st.phase === 'rating' && S.round === rounds.length,
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
    onChange();
  }

  function setRound(r) {
    S.round = r;
    for (const x of roundData(r).questions) { delete S.answers[x.id]; delete S.results[x.id]; }
    go(1);
  }

  // фаза по имени: у того же вопроса, что сейчас (или у первого)
  function goPhase(p) {
    const st = current();
    const i = steps().findIndex((x) => x.phase === p && (x.q === undefined || x.q === (st.q ?? 0)));
    if (i >= 0) go(i);
  }

  function answer(payload) {
    if (S.error !== 'none') return ERRORS[S.error];
    if (current().phase !== 'question') return ERRORS.closed;
    if (S.deadline && Date.now() > S.deadline) return ERRORS.late;
    if (S.answers[payload.qid]) return { ok: false, code: 'already', error: 'Ответ уже принят' };
    S.answers[payload.qid] = payload.text !== undefined ? { text: String(payload.text).trim() } : { choice: payload.choice };
    onChange();
    return { ok: true };
  }

  function clearAnswer() {
    const st = current();
    if (st.q === undefined) return;
    const qid = roundData().questions[st.q].id;
    delete S.answers[qid];
    delete S.results[qid];
    go(S.step);
  }

  function reset() {
    S.answers = {};
    S.results = {};
    S.round = 1;
    go(0);
  }

  // живая фаза: во время вопроса и проверки факты закрыты (раунд 4)
  const live = () => ['question', 'judging'].includes(current().phase);

  return { S, rounds, roundData, steps, current, snapshot, go, goPhase, setRound, answer, clearAnswer, reset, totalScore, live };
}
