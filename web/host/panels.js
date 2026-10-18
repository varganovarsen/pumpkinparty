// Разделы текущей сцены на /host (модули 03-07). Каждый раздел: {el, update(S)}.
import { el, clear, toast, fmtClock, seedIcon } from '/web/shared/util.js';

function nextButton(S, run) {
  const n = S.nextStep;
  if (!n || n.cmd === 'set_scene') return null;
  return el('button', { class: 'primary', style: { width: '100%', marginTop: '8px' }, disabled: !!n.disabled,
    onclick: () => run(n.cmd, n.args || {}) }, n.label);
}

// ---------------------------------------------------------------- ambient: голова, кадр вебки
export function ambientPanel(run) {
  const root = el('div');
  return {
    el: root,
    update(S) {
      const h = S.head;
      clear(root).append(
        el('p', { class: 'muted' }, 'Фон, QR и голова-тыква. Гости делают селфи и режут тыкву на iPad.'),
        h ? el('div', { class: 'card' }, el('b', {}, 'На экране факт: '), h.text,
          el('div', { class: 'row', style: { marginTop: '8px' } },
            h.audio_url ? el('button', { class: 'grow', onclick: () => run('head_speak', {}, 'Озвучиваем') }, '🔊 Озвучить') : null,
            el('button', { class: 'grow', onclick: () => run('head_skip', {}, 'Факт убран') }, 'Убрать факт')))
          : null,
        el('button', { style: { width: '100%', marginTop: '8px' }, onclick: () => run('shot_now', {}, 'Камера готовится…') },
          '📷 Сделать кадр с вебки'));
    },
  };
}

// ---------------------------------------------------------------- игра
export function gamePanel(run) {
  const root = el('div');
  return {
    el: root,
    update(S) {
      const g = S.game || {};
      const phase = { idle: 'не начата', countdown: 'отсчёт', running: 'идёт', finished: 'окончена' }[g.phase] || g.phase;
      clear(root).append(el('div', { class: 'row' }, el('b', { class: 'grow' },
        g.mode ? `${g.mode === 'practice' ? 'Тренировка' : 'Зачёт'}: ${phase}` : 'Игра ещё не запускалась'),
      g.scored_done ? el('span', { class: 'badge' }, 'зачёт сыгран') : null));
      const list = el('div', { class: 'qh-list' });
      for (const r of g.board || []) list.append(el('div', {}, `${r.name}: ${r.score}${r.done ? ' ✓' : ''}`));
      root.append(list);
      const live = g.phase === 'countdown' || g.phase === 'running';
      root.append(el('div', { class: 'row', style: { marginTop: '8px' } },
        el('button', { class: 'grow', disabled: live, onclick: () => run('game_start', { mode: 'practice' }) }, 'Тренировка (15 с)'),
        el('button', { class: 'grow primary', disabled: live || g.scored_done, onclick: () => run('game_start', { mode: 'scored' }) }, 'Старт зачёта (45 с)')));
      root.append(el('p', { class: 'muted' }, 'Играют те, кто в сети в момент старта. Сброс игры — в аварийном разделе.'));
    },
  };
}

// ---------------------------------------------------------------- охота за семечками
export function seedsPanel(run) {
  const root = el('div');
  const KIND = { regular: 'обычн.', golden: 'золот.', rainbow: 'радужн.' };
  let link = null;
  let last = null;
  let codesOpen = false;
  const time = el('b', { class: 'grow' });
  setInterval(() => {
    if (!last || !link) return;
    const now = link.serverNow();
    if (last.phase === 'countdown') time.textContent = `Отсчёт: ${fmtClock(last.start_at_ms - now)}`;
    else if (last.phase === 'running') time.textContent = `Идёт, осталось ${fmtClock(last.end_at_ms - now)}`;
  }, 500);
  return {
    el: root,
    setLink(l) { link = l; },
    update(S) {
      const s = S.seeds || {};
      last = s;
      const live = s.phase === 'countdown' || s.phase === 'running';
      time.textContent = { idle: 'Охота не начата', finished: 'Охота окончена' }[s.phase] || time.textContent || '…';
      const counts = Object.entries(s.counts || {}).filter(([, c]) => c.total)
        .map(([k, c]) => `${KIND[k]} ${c.found}/${c.total}`).join(' · ');
      const list = el('div', { class: 'qh-list' });
      for (const r of s.board || []) list.append(el('div', {}, `${r.name}: ${r.count} шт., +${r.points}`));
      const table = el('table', { class: 'seeds-codes' });
      for (const x of s.seeds || []) {
        table.append(el('tr', { class: x.found_by ? 'found' : '' }, el('td', {}, seedIcon(x.kind)), el('td', { class: 'code' }, x.code),
          el('td', {}, x.place || ''), el('td', {}, x.found_by || '')));
      }
      const details = el('details', { open: codesOpen }, el('summary', {}, `Коды и где спрятаны (${(s.seeds || []).length})`), table);
      details.addEventListener('toggle', () => { codesOpen = details.open; });
      clear(root).append(
        el('div', { class: 'row' }, time, el('span', {}, counts)),
        list,
        el('div', { class: 'row', style: { marginTop: '8px' } },
          el('button', { class: 'grow primary', disabled: s.phase !== 'idle', onclick: () => run('seeds_start', {}, 'Охота началась') },
            `Старт (${s.minutes ?? 5} мин)`),
          el('button', { class: 'grow', disabled: !live, onclick: () => run('seeds_time', { seconds: 60 }, '+1 минута') }, '+1 мин'),
          el('button', { class: 'grow', disabled: !live, onclick: () => run('seeds_time', { seconds: -60 }, '−1 минута') }, '−1 мин')),
        el('button', { style: { width: '100%', marginTop: '8px' }, disabled: !live,
          onclick: () => { if (confirm('Закончить охоту досрочно?')) run('seeds_stop', {}, 'Охота окончена'); } }, 'Закончить сейчас'),
        el('a', { class: 'btn', href: '/seeds/print', target: '_blank', style: { display: 'flex', justifyContent: 'center', alignItems: 'center', marginTop: '8px', textDecoration: 'none', color: 'inherit' } },
          '🖨 Лист семечек для печати'),
        details,
        el('p', { class: 'muted' }, 'Коды — в content/seeds.yaml (новые: python tools/make_seeds.py --force). Сброс охоты — в аварийном разделе.'));
    },
  };
}

// ---------------------------------------------------------------- бомба
export function bombPanel(run) {
  const root = el('div');
  const PHASE = { idle: 'Раунды не начаты', topic: 'Тема выбрана, ждём старта', countdown: 'Отсчёт…', running: 'Идёт', boom: 'Взрыв!', round_over: 'Раунд окончен' };
  let link = null;
  let last = null;
  const status = el('b', { class: 'grow' });
  setInterval(() => {
    if (!last || !link || last.phase !== 'running' || !last.deadline_ms) return;
    const left = Math.max(0, (last.deadline_ms - link.serverNow()) / 1000);
    status.textContent = `💣 ${last.holder?.name}: ${left.toFixed(1)} с`;
  }, 200);

  function timingForm(t, live) {
    const num = (v, min, max) => el('input', { type: 'number', min, max, step: '0.5', value: String(v ?? ''), style: { width: '64px', padding: '6px 8px' } });
    const start = num(t.start_seconds, '2', '60');
    const step = num(t.step_seconds, '0', '10');
    const min = num(t.min_seconds, '1', '60');
    const seq = [];
    for (let s = t.start_seconds, i = 0; i < 6; i++, s = Math.max(t.min_seconds, s - t.step_seconds)) seq.push(s);
    const line = (label, inp) => el('div', { class: 'toggle' }, el('div', {}, label), el('div', {}, inp, ' с'));
    return el('div', { class: 'card' },
      el('b', {}, 'Время на ход'),
      line('Первый круг', start), line('Каждый круг короче на', step), line('Но не меньше', min),
      el('div', { class: 'muted', style: { fontSize: '.85rem', margin: '4px 0' } }, `По кругам: ${seq.join(' → ')} с…`),
      el('button', { style: { width: '100%' }, onclick: () => run('bomb_timing', {
        start_seconds: Number(start.value), step_seconds: Number(step.value), min_seconds: Number(min.value) }, 'Время на ход сохранено') },
      live ? 'Сохранить (со следующего хода)' : 'Сохранить время на ход'));
  }

  function orderList(b, live) {
    const ids = (b.order || []).map((o) => o.player_id);
    const move = (i, d) => {
      const next = [...ids];
      [next[i], next[i + d]] = [next[i + d], next[i]];
      run('bomb_order', { order: next });
    };
    const shuffle = () => {
      const next = [...ids];
      for (let i = next.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [next[i], next[j]] = [next[j], next[i]]; }
      run('bomb_order', { order: next }, 'Порядок перемешан');
    };
    const list = el('ol', { class: 'bomb-order' });
    (b.order || []).forEach((o, i) => list.append(el('li', { class: o.connected && o.can_play ? '' : 'off' },
      el('span', { class: 'grow' }, o.name, !o.can_play ? ' (не играет)' : !o.connected ? ' (не в сети)' : ''),
      el('button', { class: 'small', disabled: live || i === 0, onclick: () => move(i, -1) }, '↑'),
      el('button', { class: 'small', disabled: live || i === ids.length - 1, onclick: () => move(i, 1) }, '↓'))));
    return el('details', { class: 'card', open: !live && b.phase !== 'round_over' },
      el('summary', {}, `Порядок хода (${(b.order || []).filter((o) => o.connected && o.can_play).length} в игре)`),
      list,
      el('button', { style: { width: '100%' }, disabled: live, onclick: shuffle }, '🔀 Перемешать'),
      el('p', { class: 'muted' }, live ? 'Менять порядок можно между раундами.' : 'Играют те, кто в сети в момент старта. Каждый раунд начинает следующий по кругу.'));
  }

  return {
    el: root,
    setLink(l) { link = l; },
    update(S) {
      const b = S.bomb || {};
      last = b;
      const live = ['countdown', 'running', 'boom'].includes(b.phase);
      status.textContent = PHASE[b.phase] || b.phase || '…';
      const res = (b.results || []).map((r) => `${r.place}. ${r.name}${r.points ? ` +${r.points}` : ''}`).join(' · ');
      // кнопка шага — из состояния модуля: событие next_step приходит позже, чем bomb
      const n = b.next;
      clear(root).append(...[
        el('div', { class: 'row' }, status, el('span', { class: 'badge' }, `раунд ${b.round || 0} из ${b.rounds || 3}`)),
        b.topic ? el('div', { class: 'qh-q' }, el('div', { class: 'muted' }, 'Тема'), el('div', { class: 'qh-text' }, b.topic)) : null,
        live ? el('div', { class: 'muted' }, `Круг ${b.lap}, ${b.turn_seconds ?? '—'} с на ход, в игре ${b.alive_count}`) : null,
        res ? el('div', { class: 'qh-list' }, res) : null,
        n && !n.disabled ? el('button', { class: 'primary', style: { width: '100%', marginTop: '8px' }, onclick: () => run(n.cmd, n.args || {}) }, n.label) : null,
        el('div', { class: 'row', style: { marginTop: '8px' } },
          el('button', { class: 'grow', disabled: b.phase !== 'topic', onclick: () => run('bomb_topic', {}, 'Другая тема') }, '🎰 Другая тема'),
          el('button', { class: 'grow danger', disabled: b.phase !== 'running', onclick: () => run('bomb_boom', {}, 'Взорван') }, '💥 Взорвать')),
        el('p', { class: 'muted' }, '«Взорвать» — если игрок повторил слово или передал молча.'),
        el('button', { style: { width: '100%' }, disabled: !live,
          onclick: () => { if (confirm('Прервать раунд? Очков не будет, раунд можно начать заново с той же темой.')) run('bomb_abort', {}, 'Раунд прерван'); } }, 'Прервать раунд'),
        orderList(b, live),
        timingForm(b.timing || {}, live),
        el('p', { class: 'muted' }, 'Темы — в content/bomb.yaml. Сброс «Бомбы» — в аварийном разделе.'),
      ].filter(Boolean));
    },
  };
}

// ---------------------------------------------------------------- голосование и итоги резьбы
export function votePanel(run) {
  const root = el('div');
  return {
    el: root,
    update(S) {
      const v = S.vote || {};
      clear(root);
      const scene = S.scene?.scene;
      if (scene === 'carve_vote') {
        const slides = !!S.settings?.alley_slides;
        root.append(el('div', { class: 'toggle' }, el('div', {}, 'Аллея на ТВ', el('div', { class: 'muted' }, slides ? 'снимки (слайды)' : 'живое 3D; само переключится на снимки, если ТВ не тянет')),
          el('button', { class: 'switch', onclick: () => run('set_setting', { key: 'alley_slides', value: !slides }) }, slides ? '→ 3D' : '→ Слайды')));
        const txt = { idle: `Тыкв к голосованию: ${(S.players || []).filter((p) => p.pumpkin_version).length}`,
          open: `Голосование идёт: проголосовали ${v.voted_count} из ${v.voters_total}`, closed: 'Голосование закрыто' }[v.phase];
        root.append(el('p', {}, txt));
      }
      if (v.phase === 'closed') {
        const list = el('div', { class: 'qh-list' });
        for (const r of v.results || []) {
          list.append(el('div', {}, `№${r.n} ${r.name}: ${r.votes} гол., ${r.place ? `${r.place} место` : 'без места'}${r.bonus ? `, +${r.bonus}` : ''}`));
        }
        root.append(list);
        if (scene === 'carve_reveal') root.append(el('p', { class: 'muted' }, v.revealed ? 'Всё раскрыто' : `Раскрыто: ${Math.max(0, v.reveal_step + 1)} из ${v.total}`));
      }
      const nb = nextButton(S, run);
      if (nb) root.append(nb);
    },
  };
}

// ---------------------------------------------------------------- таймер
export function timerPanel(run) {
  const root = el('div');
  const label = el('input', { type: 'text', placeholder: 'Подпись: «Чай и пироги»', maxlength: '60' });
  const custom = el('input', { type: 'number', min: '1', max: '180', placeholder: 'мин', style: { width: '90px' } });
  const left = el('b');
  let raf = 0;
  const start = (m) => run('timer_set', { minutes: m, label: label.value || undefined });
  root.append(
    el('div', { class: 'row' }, el('span', {}, 'Осталось: '), left),
    el('div', { class: 'row', style: { marginTop: '8px' } },
      ...[5, 10, 15].map((m) => el('button', { class: 'grow', onclick: () => start(m) }, `${m} мин`)),
      custom, el('button', { onclick: () => custom.value && start(Number(custom.value)) }, '▶')),
    el('div', { class: 'row', style: { marginTop: '8px' } }, label,
      el('button', { onclick: () => run('timer_label', { label: label.value }, 'Подпись обновлена') }, 'OK')));
  const ctrl = el('div', { class: 'row', style: { marginTop: '8px' } });
  root.append(ctrl);
  let link = null;
  function tick(t) {
    cancelAnimationFrame(raf);
    if (!root.isConnected) return; // ушли из сцены «Перерыв» — цикл не нужен
    if (t.finished) left.textContent = 'время вышло';
    else if (t.running) {
      const ms = t.end_at_ms - link.serverNow();
      left.textContent = fmtClock(ms);
      if (ms > 0) raf = requestAnimationFrame(() => tick(t));
    }
    else if (t.left_ms != null) left.textContent = `${fmtClock(t.left_ms)} (пауза)`;
    else left.textContent = '—';
  }
  return {
    el: root,
    setLink(l) { link = l; },
    update(S) {
      const t = S.timer || {};
      if (document.activeElement !== label) label.value = t.label || '';
      clear(ctrl).append(
        el('button', { class: 'grow', disabled: !t.running && t.left_ms == null,
          onclick: () => run('timer_pause', { paused: t.running }) }, t.running ? '⏸ Пауза' : '▶ Продолжить'),
        el('button', { class: 'grow', disabled: !t.running && t.left_ms == null, onclick: () => run('timer_add', { seconds: 60 }) }, '+1 минута'));
      tick(t);
    },
  };
}

// ---------------------------------------------------------------- общий рейтинг
export function ratingPanel(run) {
  const root = el('div');
  return {
    el: root,
    update(S) {
      const f = S.finale || {};
      clear(root);
      const list = el('div', { class: 'qh-list' });
      (f.groups || []).forEach((g, i) => list.append(el('div', { class: i <= f.step ? '' : 'muted' },
        `${g[0].place}. ${g.map((r) => `${r.name} (${r.total})`).join(', ')}${i <= f.step ? ' ✓' : ''}`)));
      root.append(el('p', { class: 'muted' }, 'Раскрывается от последнего места к первому; ведущий вне зачёта не показывается.'), list);
      const nb = nextButton(S, run);
      if (nb) root.append(nb);
      root.append(el('button', { style: { marginTop: '8px' }, onclick: () => { if (confirm('Пересчитать места и начать раскрытие заново?')) run('rating_restart'); } }, '↺ Начать заново'));
    },
  };
}

// ---------------------------------------------------------------- слайд-шоу
export function slideshowPanel(run, setScene) {
  const root = el('div');
  return {
    el: root,
    update(S) {
      const paused = !!S.finale?.slideshow_paused;
      clear(root).append(el('div', { class: 'row' },
        el('button', { class: 'grow', onclick: () => run('slideshow_pause', { paused: !paused }) }, paused ? '▶ Продолжить' : '⏸ Пауза'),
        el('button', { class: 'grow', onclick: () => setScene('ambient') }, '⏹ Закончить')));
    },
  };
}

// ---------------------------------------------------------------- финальное фото
export function finalPhotoPanel() {
  const root = el('div');
  const input = el('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'hidden' });
  const preview = el('div');
  let file = null;
  input.addEventListener('change', () => {
    file = input.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    const img = el('img', { src: url, alt: '', class: 'final-preview' });
    img.onload = () => {
      if (img.naturalHeight > img.naturalWidth) toast('Кадр вертикальный — будет обрезан до 4:3. Лучше переверни телефон и пересними', 5000);
    };
    clear(preview).append(img, el('div', { class: 'row' },
      el('button', { class: 'grow', onclick: () => input.click() }, '↺ Переснять'),
      el('button', { class: 'grow primary', onclick: send }, '⬆ Отправить')));
  });
  async function send() {
    if (!file) return;
    clear(preview).append(el('p', { class: 'muted' }, 'Обрабатываем…'));
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await (await fetch('/api/final_photo', { method: 'POST', body: fd })).json();
      if (!r.ok) throw new Error(r.error);
      clear(preview).append(el('img', { src: r.photo.thumb_url, alt: '', class: 'final-preview' }), el('p', {}, 'Готово — фото на экране и в альбоме.'));
    } catch (e) {
      toast(e.message || 'Не отправилось');
      clear(preview);
    }
    file = null;
  }
  root.append(input,
    el('p', { class: 'muted' }, 'Держи телефон горизонтально. Рамка и подпись наложатся автоматически.'),
    el('button', { class: 'primary', style: { width: '100%' }, onclick: () => input.click() }, '📸 Открыть камеру'),
    preview);
  return { el: root, update() {} };
}

// ---------------------------------------------------------------- модерация фото
export function photosSection(run) {
  const root = el('div', { class: 'ph-grid' });
  let photos = [];
  async function load() {
    try { photos = (await (await fetch('/api/photos?all=1')).json()).photos; } catch { photos = []; }
    render();
  }
  function render() {
    clear(root);
    if (!photos.length) { root.append(el('p', { class: 'muted' }, 'Фото пока нет')); return; }
    for (const p of photos) {
      root.append(el('div', { class: `ph-cell${p.hidden ? ' hidden-ph' : ''}` },
        el('img', { src: `${p.thumb_url}?all=1`, alt: '', loading: 'lazy' }),
        el('div', { class: 'ph-meta' }, p.kind === 'selfie' ? (p.author_name || '?') : p.kind === 'webcam' ? '📷 вебка' : '🏁 финал'),
        el('div', { class: 'row' },
          el('button', { class: 'small grow', onclick: () => run('photo_hide', { id: p.id, hidden: !p.hidden }) }, p.hidden ? 'Показать' : 'Скрыть'),
          el('button', { class: 'small danger', onclick: () => { if (confirm('Удалить фото? Файл уйдёт в data/_deleted/')) run('photo_delete', { id: p.id }); } }, '🗑'))));
    }
  }
  load();
  return { el: root, reload: load };
}
