// Панель ведущего (/host) и проверки (/check). Модуль 01, каркас.
import { Link } from '/web/shared/ws.js';
import { el, clear, toast, api, fmtTime, offlineBar } from '/web/shared/util.js';
import { quizPanel } from '/web/host/quiz.js';
import { ambientPanel, gamePanel, votePanel, timerPanel, ratingPanel, slideshowPanel, finalPhotoPanel, photosSection } from '/web/host/panels.js';

const S = { scene: null, scenes: [], settings: {}, players: [], log: [], nextStep: null, joinUrl: '', tvCount: null, logFilter: '', quiz: null, game: null, vote: null, timer: null, finale: null, head: null };
const MODULES = ['quiz', 'game', 'vote', 'timer', 'finale'];
const $ = (id) => document.getElementById(id);
const evening = $('evening');
const checkMain = $('check');

// ---------------------------------------------------------------- каркас вкладки «Вечер»
const box = {
  next: el('button', { class: 'primary next' }),
  scenes: el('div', { class: 'scenes' }),
  current: el('div'),
  players: el('ul', { class: 'plist' }),
  hostProfile: el('div'),
  settings: el('div'),
  head: el('div'),
  log: el('div', { class: 'log' }),
  logFilter: el('select'),
  adjPlayer: el('select'),
  photos: el('div'),
};

const adjAmount = el('input', { type: 'number', inputmode: 'numeric', placeholder: '±очки, например -50' });
const adjNote = el('input', { type: 'text', placeholder: 'Комментарий' });

evening.append(
  box.next,
  el('section', { class: 'card' }, el('h2', {}, 'Сцены'), box.scenes),
  el('section', { class: 'card' }, el('h2', {}, 'Текущая сцена'), box.current),
  el('section', { class: 'card' }, el('h2', {}, 'Игроки'), box.players, box.hostProfile),
  el('section', { class: 'card' }, el('details', {}, el('summary', {}, '🖼 Фото альбома (скрыть / удалить)'), box.photos)),
  el('section', { class: 'card' }, el('h2', {}, 'Голова-тыква'), box.head),
  el('section', { class: 'card' }, el('h2', {}, 'Настройки'), box.settings),
  el('section', { class: 'card' }, el('div', { class: 'row' }, el('h2', { class: 'grow' }, 'Журнал'), box.logFilter), box.log),
  el('section', { class: 'card danger-zone' }, el('details', {},
    el('summary', {}, '⚠️ Аварийное'),
    el('div', { class: 'row', style: { marginTop: '8px' } },
      el('button', { class: 'grow', onclick: () => run('reload_scene', {}, 'Сцена на ТВ перезагружена') }, 'Перезагрузить сцену'),
      el('button', { class: 'grow', onclick: () => run('skip_question', {}, 'Вопрос пропущен') }, 'Пропустить вопрос')),
    el('button', { style: { width: '100%', marginTop: '8px' }, onclick: () => { if (confirm('Сбросить игру? Очки за игру будут удалены, зачёт можно сыграть заново.')) run('game_reset', {}, 'Игра сброшена'); } }, 'Сбросить игру с падающими тыквами'),
    el('button', { style: { width: '100%', marginTop: '8px' }, onclick: () => { if (confirm('Сбросить голосование за резьбу? Бонусы резьбы удалятся, тыквы снова можно менять, голосование — открыть заново.')) run('vote_reset', {}, 'Голосование сброшено'); } }, 'Сбросить голосование за резьбу'),
    el('h3', { style: { marginTop: '14px' } }, 'Исправить очки игрока'),
    box.adjPlayer, el('div', { style: { height: '6px' } }), adjAmount, el('div', { style: { height: '6px' } }), adjNote,
    el('button', { style: { width: '100%', marginTop: '6px' }, onclick: adjust }, 'Записать правку'),
    el('h3', { style: { marginTop: '14px' } }, 'Сбросить вечер'),
    el('p', { class: 'muted' }, 'Удаляет игроков, очки, фото и тыквы. Перед сбросом делается копия data/.'),
    el('button', { class: 'danger', style: { width: '100%' }, onclick: resetEvening }, 'Сбросить вечер…'),
  )),
);

box.logFilter.addEventListener('change', async () => {
  S.logFilter = box.logFilter.value;
  const r = await link.cmd('get_log', { player_id: S.logFilter ? Number(S.logFilter) : null });
  if (r.ok) { S.log = r.log; renderLog(); }
});

// ---------------------------------------------------------------- команды
async function run(cmd, args = {}, okText = '') {
  let r = await link.cmd(cmd, args);
  if (!r.ok && r.code === 'confirm_required' && confirm(r.error)) r = await link.cmd(cmd, { ...args, force: true });
  if (r.ok) { if (okText) toast(okText); } else if (r.code !== 'confirm_required') toast(r.error || 'Ошибка');
  return r;
}

const setScene = (scene) => run('set_scene', { scene });
const setSetting = (key, value) => run('set_setting', { key, value });

async function adjust() {
  const amount = parseInt(adjAmount.value, 10);
  if (!box.adjPlayer.value || !amount) { toast('Выберите игрока и число'); return; }
  const r = await run('adjust_score', { player_id: Number(box.adjPlayer.value), amount, note: adjNote.value }, 'Правка записана');
  if (r.ok) { adjAmount.value = ''; adjNote.value = ''; }
}

async function resetEvening() {
  if (!confirm('Сбросить весь вечер? Игроки, очки и фото будут удалены (копия сохранится).')) return;
  const word = prompt('Для подтверждения напишите СБРОС');
  if ((word || '').trim().toUpperCase() !== 'СБРОС') { toast('Сброс отменён'); return; }
  const r = await link.cmd('reset_evening', { confirm: 'СБРОС' });
  toast(r.ok ? `Вечер сброшен, копия: ${r.backup}` : r.error, 5000);
}

// ---------------------------------------------------------------- отрисовка
function title(sceneId) { return S.scenes.find((s) => s.id === sceneId)?.title || sceneId; }

function renderHeader() {
  $('scene-name').textContent = S.scene ? `Сцена: ${S.scene.title}` : '…';
  $('tv-state').textContent = S.tvCount === null ? '' : S.tvCount ? '· ТВ ✓' : '· ТВ не подключён';
  $('tv-state').className = S.tvCount ? 'muted' : 'status-fail';
}

function renderNext() {
  const n = S.nextStep;
  box.next.textContent = n ? `Следующий шаг: ${n.label}` : 'Вечер завершён';
  box.next.disabled = !n || !!n.disabled;
  box.next.onclick = () => n && run(n.cmd, n.args || {});
}

function renderScenes() {
  renderNext();
  clear(box.scenes);
  for (const s of S.scenes) {
    box.scenes.append(el('button', { class: S.scene?.scene === s.id ? 'on' : '', onclick: () => setScene(s.id) }, s.title));
  }
  clear(box.current);
  const scene = S.scene?.scene;
  if (scene === 'quiz') {
    box.current.append(quiz.el);
    quiz.update(S.quiz);
  } else if (panels[scene]) {
    box.current.append(panels[scene].el);
    panels[scene].update(S);
  } else {
    box.current.append(el('p', { class: 'muted' }, 'QR на скачивание фото — на экране. Сервер не выключать, пока гости скачивают.'));
  }
  // в слайд-шоу по спеке только «Пауза/Продолжить» и «Закончить»
  if (scene !== 'slideshow') box.current.append(el('button', { style: { marginTop: '10px' }, onclick: () => setScene('ambient'), disabled: scene === 'ambient' }, '← В ambient'));
}

// обновить раздел текущей сцены без перестройки (например, пришло новое состояние модуля)
function refreshPanel() {
  const scene = S.scene?.scene;
  if (scene === 'quiz') quiz.update(S.quiz);
  else panels[scene]?.update(S);
}

function renderPlayers() {
  clear(box.players);
  for (const p of S.players) {
    box.players.append(el('li', {},
      el('img', { class: 'avatar', src: p.avatar_url, alt: '' }),
      el('span', { class: `dot${p.connected ? ' on' : ''}`, title: p.connected ? 'в сети' : 'не в сети' }),
      el('span', { class: 'pname' }, p.name,
        p.is_host ? el('span', { class: 'badge' }, 'ведущий') : null,
        !p.in_scoring ? el('span', { class: 'badge' }, 'вне зачёта') : null),
      el('span', { class: 'pscore' }, p.score ?? 0),
    ));
  }
  if (!S.players.length) box.players.append(el('li', { class: 'muted' }, 'Пока никого. Гости заходят по QR с экрана.'));
  const online = S.players.filter((p) => p.connected).length;
  clear(box.hostProfile).append(el('p', { class: 'muted' }, `В сети ${online} из ${S.players.length}.`));
  if (!S.players.some((p) => p.is_host)) {
    box.hostProfile.append(el('a', { class: 'btn', href: '/?as_host=1', target: '_blank', style: { display: 'inline-block', textDecoration: 'none' } }, 'Создать мой профиль игрока ↗'));
  }
  for (const sel of [box.adjPlayer, box.logFilter]) {
    const keep = sel.value;
    clear(sel).append(el('option', { value: '' }, sel === box.logFilter ? 'Все игроки' : 'Игрок…'));
    for (const p of S.players) sel.append(el('option', { value: String(p.id) }, p.name));
    sel.value = keep;
  }
}

function toggle(label, key, hint = '', disabled = false) {
  const v = !!S.settings[key];
  return el('div', { class: 'toggle' },
    el('div', {}, label, hint ? el('div', { class: 'muted', style: { fontSize: '.85rem' } }, hint) : null),
    el('button', { class: `switch${v ? ' on' : ''}`, disabled, onclick: () => setSetting(key, !v) }, v ? 'Вкл' : 'Выкл'));
}

function renderSettings() {
  clear(box.settings).append(
    toggle('Ведущий в зачёте', 'host_in_scoring', S.settings.quiz_started ? 'Квиз уже начался — менять нельзя' : 'Менять можно до начала квиза', !!S.settings.quiz_started),
    toggle('Скрыть общий рейтинг', 'hide_total', 'Телефоны не показывают сумму очков'),
    toggle('Лёгкий фон (без видео)', 'light_mode', 'Если ноутбук не тянет видео'),
    toggle('Карточка новых фото', 'new_photo_card'),
    toggle('Случайные кадры вебки', 'shots_enabled', 'Только в ambient и перерыве, не поверх головы'),
  );
  // частота кадров вебки: случайно между «от» и «до» минут; кнопка — кадр сразу, в любой сцене
  const shotsInput = (key) => {
    const inp = el('input', { type: 'number', min: '1', max: '120', step: '1', value: String(S.settings[key] ?? ''), style: { width: '68px', padding: '6px 8px' } });
    inp.addEventListener('change', () => setSetting(key, Number(inp.value)));
    return inp;
  };
  const next = S.settings.shots_enabled && S.settings.shot_next_at ? `следующий около ${fmtTime(S.settings.shot_next_at)}` : 'по таймеру не снимаются';
  box.settings.append(
    el('div', { class: 'toggle' },
      el('div', {}, 'Интервал кадров, минут', el('div', { class: 'muted', style: { fontSize: '.85rem' } }, next)),
      el('div', { style: { whiteSpace: 'nowrap' } }, 'от ', shotsInput('shots_min_minutes'), ' до ', shotsInput('shots_max_minutes'))),
    el('button', { style: { width: '100%', marginTop: '8px' }, onclick: () => run('shot_now', {}, 'Камера готовится…') },
      '📷 Сделать кадр сейчас'),
  );
  const loud = S.settings.head_mode === 'loud';
  const interval = el('input', { type: 'number', min: '1', max: '60', value: String(S.settings.head_interval_minutes ?? 6), style: { width: '90px' } });
  interval.addEventListener('change', () => setSetting('head_interval_minutes', Number(interval.value)));
  clear(box.head).append(
    el('div', { class: 'row' },
      el('button', { class: `grow${!loud ? ' on' : ''}`, onclick: () => setSetting('head_mode', 'quiet') }, '🤫 Тихий'),
      el('button', { class: `grow${loud ? ' on' : ''}`, onclick: () => setSetting('head_mode', 'loud') }, '🔊 Громкий')),
    el('div', { class: 'row', style: { marginTop: '8px' } },
      el('button', { class: 'primary grow', onclick: () => run('head_call', {}, 'Голова зовётся') }, 'Позвать голову сейчас'),
      el('button', { class: 'grow', onclick: () => run('head_skip', {}, 'Факт пропущен') }, 'Пропустить факт')),
    el('div', { class: 'row', style: { marginTop: '8px' } },
      el('button', { class: 'grow', onclick: () => setSetting('head_mode', 'quiet') }, 'Тихий режим одним нажатием')),
    toggle('Голова по таймеру', 'head_enabled', 'Каждые N минут ± 1 в ambient, не раньше 3 минут после другой сцены'),
    el('div', { class: 'toggle' }, el('div', {}, 'Интервал, минут'), interval),
  );
}

function renderLog() {
  clear(box.log);
  for (const e of S.log) box.log.append(el('div', {}, el('span', { class: 'ts' }, fmtTime(e.ts)), e.text));
  box.log.scrollTop = box.log.scrollHeight;
}

function renderAll() { renderHeader(); renderScenes(); renderPlayers(); renderSettings(); renderLog(); }

// ---------------------------------------------------------------- проверки (/check)
async function renderCheck() {
  clear(checkMain).append(el('p', { class: 'muted center' }, 'Проверяем…'));
  const r = await api('/api/check');
  if (!r.items) { clear(checkMain).append(el('p', { class: 'err' }, r.error || 'Нет связи')); return; }
  const webcamBox = el('div');
  const icon = { ok: '✓', warn: '!', fail: '✗', info: 'ℹ' };
  const list = el('ul', { class: 'checks' });
  for (const it of r.items) {
    list.append(el('li', {},
      el('span', { class: `st status-${it.status}` }, icon[it.status] || '?'),
      el('b', {}, it.title), ': ', el('span', { class: 'muted' }, it.detail),
      it.items.length ? el('details', {}, el('summary', { class: 'muted' }, `подробно (${it.items.length})`), el('ul', {}, it.items.map((x) => el('li', {}, x)))) : null));
  }
  clear(checkMain).append(
    el('section', { class: 'card center' },
      el('h2', {}, 'Адрес для гостей'),
      el('div', { class: 'qr-box' }, el('img', { src: `/api/qr.svg?path=/&t=${Date.now()}`, alt: '' })),
      el('p', {}, el('b', {}, S.joinUrl))),
    el('section', { class: 'card' },
      el('div', { class: 'row' }, el('h2', { class: 'grow' }, `Проверки: красных ${r.summary.fail}, жёлтых ${r.summary.warn}`),
        el('button', { class: 'small', onclick: renderCheck }, '↻')),
      list),
    el('section', { class: 'card' },
      el('h2', {}, 'Тесты'),
      el('div', { class: 'row' },
        el('button', { class: 'grow', onclick: () => run('sound_test', {}, 'Звук отправлен на ТВ') }, '🔊 Тест звука на ТВ'),
        el('button', { class: 'grow', onclick: () => webcamTest(webcamBox) }, '📷 Тест вебки')),
      webcamBox),
  );
}

async function webcamTest(target) {
  clear(target).append(el('p', { class: 'muted' }, 'Снимаем…'));
  try {
    const resp = await fetch('/api/webcam_test');
    if (!resp.ok) {
      const j = await resp.json().catch(() => ({}));
      clear(target).append(el('p', { class: 'err' }, j.error || `Ошибка ${resp.status}`));
      return;
    }
    const url = URL.createObjectURL(await resp.blob());
    clear(target).append(el('img', { class: 'webcam-img', src: url, alt: 'кадр с вебки' }));
  } catch {
    clear(target).append(el('p', { class: 'err' }, 'Нет связи'));
  }
}

function showTab(tab) {
  for (const b of document.querySelectorAll('.htabs button')) b.classList.toggle('on', b.dataset.tab === tab);
  evening.classList.toggle('hidden', tab !== 'evening');
  checkMain.classList.toggle('hidden', tab !== 'check');
  history.replaceState(null, '', tab === 'check' ? '/check' : '/host');
  if (tab === 'check') renderCheck();
}
for (const b of document.querySelectorAll('.htabs button')) b.addEventListener('click', () => showTab(b.dataset.tab));

// ---------------------------------------------------------------- связь
function onMessage(m) {
  switch (m.t) {
    case 'snapshot':
      S.scene = m.scene; S.scenes = m.scenes; S.settings = m.settings; S.players = m.players;
      S.log = m.log; S.nextStep = m.next_step; S.joinUrl = m.join_url; S.tvCount = m.tv_count; S.head = m.head;
      for (const name of MODULES) S[name] = m[name];
      if (S.logFilter) box.logFilter.dispatchEvent(new Event('change'));
      renderAll();
      break;
    case 'scene': S.scene = m; renderHeader(); renderScenes(); break;
    case 'next_step': S.nextStep = m.next_step; renderNext(); break;
    case 'quiz': case 'game': case 'vote': case 'timer': case 'finale':
      S[m.t] = m[m.t];
      refreshPanel();
      break;
    case 'game_live': if (S.game) { S.game.board = m.board; refreshPanel(); } break;
    case 'head': S.head = m.head; refreshPanel(); break;
    case 'photo_added': case 'photo_changed': photos.reload(); break;
    case 'players': S.players = m.players; renderPlayers(); if (S.scene?.scene === 'carve_vote') refreshPanel(); break;
    case 'settings': S.settings = m.settings; renderSettings(); refreshPanel(); break;
    case 'tv_count': S.tvCount = m.count; renderHeader(); break;
    case 'log':
      if (!S.logFilter || String(m.entry.player_id) === S.logFilter) {
        S.log.push(m.entry);
        if (S.log.length > 50) S.log.shift();
        renderLog();
      }
      break;
    case 'reset': toast('Вечер сброшен'); break;
    default: break;
  }
}

const link = new Link({
  role: 'host',
  onMessage,
  onStatus: (on) => { $('conn').classList.toggle('on', on); offlineBar(on); },
});
const quiz = quizPanel(link, run);
const timer = timerPanel(run);
timer.setLink(link);
const vote = votePanel(run);
const panels = {
  ambient: ambientPanel(run), game: gamePanel(run), carve_vote: vote, carve_reveal: vote, timer,
  rating_reveal: ratingPanel(run), slideshow: slideshowPanel(run, (s) => setScene(s)), final_photo: finalPhotoPanel(),
};
const photos = photosSection(run);
box.photos.append(photos.el);
link.connect();
if (location.pathname === '/check') showTab('check');
