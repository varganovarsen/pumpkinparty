// Разделы текущей сцены на /host (модули 03-07). Каждый раздел: {el, update(S)}.
import { el, clear, toast, fmtClock } from '/web/shared/util.js';

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
    if (t.finished) left.textContent = 'время вышло';
    else if (t.running) { left.textContent = fmtClock(t.end_at_ms - link.serverNow()); raf = requestAnimationFrame(() => tick(t)); }
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
