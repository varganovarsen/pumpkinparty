// Песочница игрока: настоящее приложение web/play на подставном сервере (server.js).
// Здесь только пульт ведущего: язычок у правого края открывает панель со сценами и кнопками модулей.
import { el, clear, toast } from '/web/shared/util.js';
import { host, SCENE_TITLES } from '/sandbox/server.js';
import { QUIZ_PHASES } from '/sandbox/engine_quiz.js';

const { S, quiz } = host;
const SEED_KIND = { regular: 'обычн.', golden: 'золот.', rainbow: 'радужн.' };
const PHASE = { idle: 'не начата', countdown: 'отсчёт', running: 'идёт', finished: 'окончена' };
const BOMB_PHASE = { idle: 'ждём', topic: 'тема', countdown: 'отсчёт', running: 'идёт', boom: 'взрыв', round_over: 'итоги' };

const fab = el('button', { class: 'sb-fab', 'aria-label': 'Пульт ведущего' }, '🎛');
const sheet = el('div', { class: 'sb-sheet solo', hidden: true });
document.body.append(sheet, fab);
fab.addEventListener('click', () => { sheet.hidden = !sheet.hidden; render(); });

// ссылка «Скачать фото вечера» ведёт на страницу сервера, которой здесь нет
document.addEventListener('click', (e) => {
  const a = e.target.closest?.('a[href="/download"]');
  if (a) { e.preventDefault(); toast('Страницы скачивания в песочнице нет'); }
}, true);

const btn = (label, onclick, opts = {}) => el('button', { onclick, disabled: !!opts.disabled, class: opts.primary ? 'on' : '' }, label);
const row = (...xs) => el('div', { class: 'sb-row' }, ...xs.filter(Boolean));
const field = (title, ...xs) => el('div', { class: 'sb-field' }, el('div', { class: 'sb-title' }, title), ...xs.filter(Boolean));

function seg(title, options, value, onPick) {
  return field(title, el('div', { class: 'sb-seg' }, options.map(([v, label]) =>
    el('button', { class: v === value ? 'on' : '', onclick: () => onPick(v) }, label))));
}

function quizControls() {
  const st = quiz.current();
  const rd = quiz.roundData();
  const last = quiz.steps().length - 1;
  const label = [`Р${quiz.S.round}`, st.q !== undefined ? `В${st.q + 1}` : null, QUIZ_PHASES[st.phase]].filter(Boolean).join(' · ');
  return [
    field('Квиз', row(
      btn('‹', () => quiz.go(quiz.S.step - 1), { disabled: quiz.S.step === 0 }),
      el('span', { class: 'sb-now' }, label),
      quiz.S.step === last && quiz.S.round < quiz.rounds.length
        ? btn('Раунд ›', () => quiz.setRound(quiz.S.round + 1), { primary: true })
        : btn('Дальше ›', () => quiz.go(quiz.S.step + 1), { disabled: quiz.S.step === last, primary: true }))),
    seg('Раунд', quiz.rounds.map((r, i) => [i + 1, `${i + 1}`]), quiz.S.round, quiz.setRound),
    rd.kind === 'text'
      ? seg('Ведущий решил', [[true, 'принят'], [false, 'не принят']], quiz.S.verdict, (v) => { quiz.S.verdict = v; render(); })
      : seg('Мой верный ответ пришёл', [[1, '1-м'], [2, '2-м'], [3, '3-м'], [0, 'позже']], quiz.S.place, (v) => { quiz.S.place = v; render(); }),
  ];
}

function sceneControls() {
  const g = S.game;
  const s = S.seeds;
  const b = host.bomb;
  switch (S.scene) {
    case 'quiz': return quizControls();
    case 'game': {
      const live = ['countdown', 'running'].includes(g.phase);
      return [field(`Игра: ${g.mode ? `${g.mode === 'practice' ? 'тренировка' : 'зачёт'}, ${PHASE[g.phase]}` : 'не начата'}`,
        row(btn('Тренировка', () => host.gameStart('practice'), { disabled: live }),
          btn('Старт зачёта', () => host.gameStart('scored'), { disabled: live, primary: true })))];
    }
    case 'seeds': {
      const live = ['countdown', 'running'].includes(s.phase);
      const codes = el('div', { class: 'sb-codes' }, host.seedCodes.map((c) =>
        el('span', { class: s.found[c.code] ? 'found' : '' }, `${c.code} ${SEED_KIND[c.kind]}`)));
      return [field(`Охота: ${PHASE[s.phase]}`,
        row(btn(s.phase === 'idle' ? 'Старт' : 'Заново', host.seedsStart, { disabled: live, primary: true }),
          btn('+1 мин', () => host.seedsTime(60), { disabled: !live }), btn('Стоп', host.seedsStop, { disabled: s.phase !== 'running' }))),
      field('Коды для ввода (зачёркнуты найденные)', codes)];
    }
    case 'bomb': {
      const [label, fn] = b.hostAction();
      return [field(`Бомба: ${b.B.round ? `раунд ${b.B.round}, ` : ''}${BOMB_PHASE[b.B.phase]}`,
        row(btn(label || '…', () => fn?.(), { disabled: !fn, primary: true }),
          btn('Другая тема', b.pickTopic, { disabled: b.B.phase !== 'topic' }),
          btn('Прервать', b.abort, { disabled: !b.live() }))),
      seg('Боты', [['slow', 'часто не успевают'], ['normal', 'иногда'], ['fast', 'почти всегда успевают']], b.B.skill, (v) => { b.B.skill = v; render(); })];
    }
    case 'carve_vote':
      return [seg('Голосование', [['idle', 'не открыто'], ['open', 'открыто'], ['closed', 'закрыто']], S.vote.phase, host.votePhase)];
    case 'timer':
      return [field('Перерыв', row(btn('5 мин', () => host.timerStart(5), { primary: true }), btn('1 мин', () => host.timerStart(1)),
        btn(S.timer.running ? 'Пауза' : 'Продолжить', host.timerPause, { disabled: !S.timer.running && !S.timer.left })))];
    case 'ambient':
      return [field('Голова-тыква', row(btn(`Рассказать факт (открыто ${S.factsShown})`, host.headFact)))];
    default:
      return [el('p', { class: 'sb-foot' }, 'В этой сцене телефон показывает плашку сверху, вкладки работают.')];
  }
}

function render() {
  if (sheet.hidden) return;
  const signed = !!host.human;
  clear(sheet).append(...[
    el('div', { class: 'sb-head' }, el('b', {}, 'Пульт ведущего'), el('button', { 'aria-label': 'Закрыть', onclick: () => { sheet.hidden = true; } }, '✕')),
    signed ? null : el('p', { class: 'sb-foot' }, 'Сначала войди как гость: имя и тыква (занятые — у ботов Ани, Бори, Вики и Гоши).'),
    field('Сцена на ТВ', el('div', { class: 'sb-scenes' }, Object.entries(SCENE_TITLES).map(([id, title]) =>
      el('button', { class: S.scene === id ? 'on' : '', onclick: () => host.setScene(id) }, title)))),
    ...(signed ? sceneControls() : []),
    field('Телефон', row(
      btn(S.hideTotal ? 'Показать счёт' : 'Скрыть счёт', () => host.setHideTotal(!S.hideTotal)),
      btn('Обрыв связи', () => { host.dropConnection(); toast('Связь оборвана — телефон переподключится сам'); }, { disabled: !signed }),
      btn('Выйти', host.logout, { disabled: !signed }))),
    el('p', { class: 'sb-foot' }, 'Экраны — настоящий web/play. Сервер подставной: вопросы, факты, темы и коды из content/, остальные гости — боты. Звуков нет.'),
  ].filter(Boolean));
}

host.onChange(render);
