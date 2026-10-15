// Страница игрока: вход, профиль, вкладки, реакция на сцены (модуль 01, каркас).
import { Link } from '/web/shared/ws.js';
import { el, clear, toast, api, store, offlineBar, vibrate } from '/web/shared/util.js';
import { avatarPicker } from '/web/play/avatar_picker.js';
import { mountQuiz } from '/web/play/quiz.js';

const TOKEN_KEY = 'pumpkin.token';
const TAB_KEY = 'pumpkin.tab';
const app = document.getElementById('app');
const params = new URLSearchParams(location.search);
const asHost = params.get('as_host') === '1';

// Сцены без участия: тонкая плашка сверху, вкладки остаются.
const BANNERS = {
  timer: 'Перерыв',
  slideshow: 'Идёт слайд-шоу',
  final_photo: 'Финальное фото — все в кадр!',
  rating_reveal: 'Раскрываем общий рейтинг',
  carve_reveal: 'Итоги резьбы на экране',
  download: 'Фото вечера можно скачать',
};
const TABS = [
  { id: 'photo', icon: '📷', title: 'Фото' },
  { id: 'album', icon: '🖼', title: 'Альбом' },
  { id: 'facts', icon: '🎃', title: 'Факты' },
  { id: 'profile', icon: '👤', title: 'Профиль' },
];

const S = {
  info: null,
  link: null,
  me: null,
  scene: null,
  settings: {},
  facts: [],
  taken: [],
  tab: store(TAB_KEY) || 'photo',
  online: false,
};

async function boot() {
  S.info = await api('/api/info');
  if (!S.info.avatars) {
    clear(app).append(el('p', { class: 'center err', style: { marginTop: '40vh' } }, 'Нет связи с сервером. Обнови страницу.'));
    setTimeout(boot, 3000);
    return;
  }
  const token = store(TOKEN_KEY);
  if (token) startLink(token);
  else renderJoin();
}

// ---------------------------------------------------------------- вход
function renderJoin(prefillName = '') {
  S.link?.stop();
  S.link = null;
  const name = el('input', { type: 'text', maxlength: String(S.info.name_max), placeholder: 'Как тебя зовут?', autocomplete: 'off', value: prefillName });
  const err = el('div', { class: 'err' });
  const claimBox = el('div');
  const picker = avatarPicker({ avatars: S.info.avatars, taken: S.info.avatars.filter((a) => a.taken).map((a) => a.id) });
  const go = el('button', { class: 'primary', style: { width: '100%' }, type: 'submit' }, 'Войти');

  async function submit(e) {
    e.preventDefault();
    err.textContent = '';
    clear(claimBox);
    const v = picker.value;
    if (!name.value.trim()) { err.textContent = 'Введи имя'; return; }
    if (!v) { err.textContent = 'Выбери тыкву или своё фото'; return; }
    go.disabled = true;
    const r = await api('/api/join', { name: name.value, avatar_kind: v.kind, avatar_ref: v.ref, as_host: asHost });
    go.disabled = false;
    if (r.ok) { store(TOKEN_KEY, r.token); startLink(r.token); return; }
    err.textContent = r.error;
    if (r.code === 'name_taken' && r.can_claim) {
      claimBox.append(el('div', { class: 'card' },
        el('p', {}, `Игрок «${r.name}» уже есть и сейчас не в сети. Это ты?`),
        el('button', { class: 'primary', type: 'button', onclick: claim }, 'Да, это я')));
    }
    if (r.code === 'avatar_taken') {
      const info = await api('/api/info');
      if (info.avatars) picker.setTaken(info.avatars.filter((a) => a.taken).map((a) => a.id));
    }
  }
  async function claim() {
    const r = await api('/api/claim', { name: name.value });
    if (r.ok) { store(TOKEN_KEY, r.token); startLink(r.token); } else err.textContent = r.error;
  }

  clear(app).append(el('form', { class: 'join', onsubmit: submit },
    el('h1', {}, '🎃 Тыквенный спас'),
    el('p', { class: 'lead' }, asHost ? 'Профиль ведущего' : 'Представься и выбери профиль'),
    name,
    picker.el,
    claimBox,
    err,
    go,
  ));
}

// ---------------------------------------------------------------- соединение
function startLink(token) {
  S.link?.stop();
  S.link = new Link({
    role: 'player',
    token,
    onMessage,
    onStatus: (on) => { S.online = on; offlineBar(on); },
    onAuthFailed: () => { store(TOKEN_KEY, null); renderJoin(); },
  });
  S.link.connect();
}

function onMessage(m) {
  switch (m.t) {
    case 'snapshot':
      S.me = m.me; S.scene = m.scene; S.settings = m.settings; S.facts = m.facts; S.taken = m.avatars_taken;
      S.factsLocked = !!m.facts_locked; S.quiz = m.quiz;
      render();
      quizView?.update(S.quiz);
      break;
    case 'scene': {
      const was = S.scene?.participating;
      S.scene = m;
      if (m.participating && !was) vibrate(200);
      render();
      break;
    }
    case 'me': S.me = m.me; renderTop(); break;
    case 'settings': S.settings = m.settings; renderTop(); break;
    case 'facts': S.facts = m.facts; S.factsLocked = !!m.locked; if (S.tab === 'facts' && !S.scene?.participating) renderTab(); break;
    case 'quiz': S.quiz = m.quiz; quizView?.update(S.quiz); break;
    case 'avatars_taken': S.taken = m.taken; break;
    case 'reset':
      store(TOKEN_KEY, null);
      renderedKey = null;
      toast('Вечер начат заново');
      renderJoin();
      break;
    default: break;
  }
}

// ---------------------------------------------------------------- основной экран
let topEl, bannerEl, mainEl, tabsEl;
let quizView = null;

let renderedKey = null;

function render(force = false) {
  if (!S.me || !S.scene) return;
  const key = S.scene.participating ? `p:${S.scene.scene}` : `tabs:${S.tab}`;
  if (key === renderedKey && !force && mainEl?.isConnected) {
    // та же раскладка: обновить только верх и плашку, не трогая начатое на вкладке
    renderTop();
    renderBanner();
    return;
  }
  renderedKey = key;
  quizView?.unmount();
  quizView = null;
  topEl = el('div', { class: 'topbar' });
  bannerEl = el('div');
  mainEl = el('div');
  tabsEl = el('nav', { class: 'tabs' });
  clear(app).append(topEl, bannerEl, mainEl);
  renderTop();
  if (S.scene.participating) {
    renderParticipating();
    return;
  }
  renderBanner();
  for (const t of TABS) {
    tabsEl.append(el('button', { class: S.tab === t.id ? 'on' : '', onclick: () => { S.tab = t.id; store(TAB_KEY, t.id); render(); } },
      el('span', { class: 'ic' }, t.icon), t.title));
  }
  app.append(tabsEl);
  renderTab();
}

function renderBanner() {
  if (!bannerEl) return;
  const banner = !S.scene.participating && BANNERS[S.scene.scene];
  clear(bannerEl);
  if (banner) bannerEl.append(el('div', { class: 'scene-banner' }, banner));
}

function renderTop() {
  if (!topEl || !S.me) return;
  clear(topEl).append(
    el('img', { class: 'avatar', src: S.me.avatar_url, alt: '' }),
    el('div', {}, el('div', { class: 'name' }, S.me.name),
      S.me.is_host ? el('span', { class: 'badge' }, S.me.in_scoring ? 'ведущий' : 'ведущий · вне зачёта') : null),
    el('div', { class: 'score' }, S.me.score === null || S.me.score === undefined ? '' : `${S.me.score} очк.`),
  );
}

function renderParticipating() {
  // Полноэкранный режим без вкладок. Игра и голосование появятся в модулях 05, 06.
  if (S.scene.scene === 'quiz') {
    quizView = mountQuiz(mainEl, S.link);
    quizView.update(S.quiz);
    return;
  }
  mainEl.append(el('div', { class: 'fullscene' },
    el('div', { class: 'big' }, S.scene.title),
    el('p', { class: 'muted' }, 'Смотри на экран телевизора — сейчас начнётся!'),
  ));
}

function renderTab() {
  clear(mainEl);
  if (S.tab === 'photo') {
    mainEl.append(el('div', { class: 'card center' },
      el('h2', {}, 'Селфи'),
      el('p', { class: 'muted' }, 'Фото с фильтрами и наклейками появятся совсем скоро.')));
  } else if (S.tab === 'album') {
    mainEl.append(el('div', { class: 'card center' },
      el('h2', {}, 'Общий альбом'),
      el('p', { class: 'muted' }, 'Здесь будут фото гостей и кадры вечера.')));
  } else if (S.tab === 'facts') {
    renderFacts();
  } else {
    renderProfile();
  }
}

function renderFacts() {
  if (S.factsLocked) {
    mainEl.append(el('div', { class: 'card center' }, el('h2', {}, 'Факты от тыквы'),
      el('p', { class: 'muted' }, 'Недоступно во время раунда. Откроется после раунда «Факты».')));
    return;
  }
  const shown = S.facts.filter((f) => f.text).length;
  const list = el('ul', { class: 'facts' });
  for (const f of S.facts) {
    list.append(el('li', {}, el('span', { class: 'n' }, f.n), f.text ? el('span', {}, f.text) : el('span', { class: 'q' }, '?')));
  }
  mainEl.append(el('div', { class: 'card' },
    el('h2', {}, 'Факты от тыквы'),
    el('p', { class: 'muted' }, `Открыто ${shown} из ${S.facts.length}. Новые факты рассказывает голова-тыква на экране.`),
    S.facts.length ? list : el('p', { class: 'muted' }, 'Фактов пока нет.')));
}

function renderProfile() {
  const current = { kind: S.me.avatar_kind, ref: S.me.avatar_ref, url: S.me.avatar_url };
  let chosen = current;
  const save = el('button', { class: 'primary', style: { width: '100%' }, disabled: true }, 'Сохранить');
  const picker = avatarPicker({
    avatars: S.info.avatars, taken: S.taken, current,
    onChange: (v) => { chosen = v; save.disabled = v.ref === current.ref; },
  });
  save.addEventListener('click', async () => {
    save.disabled = true;
    const r = await S.link.cmd('update_profile', { avatar_kind: chosen.kind, avatar_ref: chosen.ref });
    if (r.ok) { toast('Профиль обновлён'); render(true); } else { picker.setError(r.error); save.disabled = false; }
  });
  mainEl.append(el('div', { class: 'card' },
    el('h2', {}, 'Профиль'),
    el('div', { class: 'center' }, el('img', { class: 'avatar big', src: S.me.avatar_url, alt: '' }), el('div', { class: 'name' }, S.me.name)),
    el('p', { class: 'muted center' }, 'Имя после входа не меняется. Аватар можно сменить.'),
    picker.el,
    save));
}

boot();
