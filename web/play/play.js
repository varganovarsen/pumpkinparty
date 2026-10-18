// Страница игрока: вход, профиль, вкладки, реакция на сцены (модуль 01, каркас).
import { Link } from '/web/shared/ws.js';
import { el, clear, toast, api, store, offlineBar, vibrate, fmtClock } from '/web/shared/util.js';
import { avatarPicker } from '/web/play/avatar_picker.js';
import { mountQuiz } from '/web/play/quiz.js';
import { mountGame } from '/web/play/game.js';
import { mountSeeds } from '/web/play/seeds.js';
import { mountBomb } from '/web/play/bomb.js';
import { mountVote } from '/web/play/vote.js';
import { mountPhotoTab } from '/web/play/editor.js';
import { mountAlbum } from '/web/play/album.js';

const TOKEN_KEY = 'pumpkin.token';
const TAB_KEY = 'pumpkin.tab';
const app = document.getElementById('app');
const params = new URLSearchParams(location.search);
const asHost = params.get('as_host') === '1';

// Сцены без участия: тонкая плашка сверху, вкладки остаются.
const BANNERS = {
  slideshow: 'Идёт слайд-шоу',
  final_photo: 'Финальное фото — все в кадр!',
  rating_reveal: 'Раскрываем общий рейтинг',
  carve_reveal: 'Итоги резьбы на экране',
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
  offlineBar(true); // убрать плашку «Нет связи», если она осталась от прошлого соединения
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
  const link = new Link({
    role: 'player',
    token,
    onMessage,
    // остановленное соединение (выход на экран входа) закрывается позже и не должно показывать «Нет связи»
    onStatus: (on) => { if (S.link !== link) return; S.online = on; offlineBar(on); },
    onAuthFailed: () => { store(TOKEN_KEY, null); teardown(); renderJoin(); },
  });
  S.link = link;
  link.connect();
}

const MODULES = ['quiz', 'game', 'seeds', 'bomb', 'vote', 'timer', 'finale'];
const VIEWS = { quiz: [mountQuiz, 'quiz'], game: [mountGame, 'game'], seeds: [mountSeeds, 'seeds'], bomb: [mountBomb, 'bomb'], carve_vote: [mountVote, 'vote'] };

function onMessage(m) {
  switch (m.t) {
    case 'snapshot':
      S.me = m.me; S.scene = m.scene; S.settings = m.settings; S.facts = m.facts; S.taken = m.avatars_taken;
      S.factsLocked = !!m.facts_locked;
      for (const name of MODULES) S[name] = m[name];
      render();
      view?.update(S[view.module]);
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
    case 'quiz': case 'game': case 'seeds': case 'bomb': case 'vote': case 'timer': case 'finale':
      S[m.t] = m[m.t];
      if (view?.module === m.t) view.update(S[m.t]);
      if (m.t === 'timer') renderBanner();
      break;
    case 'photo_added': case 'photo_changed': tabView?.onMessage?.(m); break;
    case 'avatars_taken': S.taken = m.taken; break;
    case 'reset':
      store(TOKEN_KEY, null);
      teardown();
      toast('Вечер начат заново');
      renderJoin();
      break;
    default: break;
  }
}

// ---------------------------------------------------------------- основной экран
let topEl, bannerEl, mainEl, tabsEl;
let view = null;     // полноэкранная сцена с участием: {module, update, unmount}
let tabView = null;  // вкладка «Фото» или «Альбом»
let bannerTimer = null;

let renderedKey = null;

// выход на экран входа: остановить сцены, вкладки и таймеры плашек
function teardown() {
  view?.unmount();
  view = null;
  tabView?.unmount();
  tabView = null;
  clearInterval(bannerTimer);
  renderedKey = null;
}

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
  clearInterval(bannerTimer);
  view?.unmount();
  view = null;
  tabView?.unmount();
  tabView = null;
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
  clearInterval(bannerTimer);
  clear(bannerEl);
  if (S.scene.participating) return;
  const scene = S.scene.scene;
  if (scene === 'timer') {
    const b = el('div', { class: 'scene-banner' });
    const upd = () => {
      const t = S.timer || {};
      const left = t.finished ? 'время вышло' : t.running ? fmtClock(t.end_at_ms - S.link.serverNow()) : t.left_ms != null ? `${fmtClock(t.left_ms)} (пауза)` : '';
      b.textContent = `${t.label || 'Перерыв'}${left ? `: ${left}` : ''}`;
    };
    upd();
    bannerTimer = setInterval(upd, 500);
    bannerEl.append(b);
  } else if (scene === 'download') {
    bannerEl.append(el('a', { class: 'btn primary scene-banner big-link', href: '/download' }, '📸 Скачать фото вечера'));
  } else if (BANNERS[scene]) {
    bannerEl.append(el('div', { class: 'scene-banner' }, BANNERS[scene]));
  }
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
  // Полноэкранный режим без вкладок: квиз, игра, голосование за резьбу
  const spec = VIEWS[S.scene.scene];
  if (!spec) return;
  const [mount, module] = spec;
  view = { module, ...mount(mainEl, S.link) };
  view.update(S[module]);
}

function renderTab() {
  clear(mainEl);
  if (S.tab === 'photo') {
    tabView = mountPhotoTab(mainEl, { link: S.link, getToken: () => store(TOKEN_KEY), stickers: S.info.stickers || [] });
  } else if (S.tab === 'album') {
    tabView = mountAlbum(mainEl, { getMe: () => S.me });
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
