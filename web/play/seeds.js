// Охота за семечками на телефоне (модуль 09): цифровая клавиатура, код отправляется сам
// после последней цифры. Кто первый ввёл код — того и семечка; после нескольких неверных
// кодов подряд — пауза.
import { el, clear, vibrate, fmtClock, seedIcon } from '/web/shared/util.js';

const KIND = {
  regular: { title: 'Семечка!' },
  golden: { title: 'Золотая семечка!' },
  rainbow: { title: 'РАДУЖНАЯ МЕГАСЕМКА!' },
};

const sfx = {};
function sound(name) {
  try {
    const a = sfx[name] || (sfx[name] = new Audio(`/assets/sfx/${name}.mp3`));
    a.currentTime = 0;
    a.play().catch(() => {});
  } catch { /* без звука */ }
}

export function mountSeeds(root, link) {
  const box = el('div', { class: 'seeds' });
  root.append(box);
  let s = null;
  let layout = null;   // фаза, под которую собран экран
  let code = '';
  let busy = false;
  let cooldownUntil = 0;
  let ui = {};
  const timer = setInterval(tick, 250);

  function onKey(e) {
    if (layout !== 'running') return;
    if (/^\d$/.test(e.key)) press(e.key);
    else if (e.key === 'Backspace') press('⌫');
  }
  document.addEventListener('keydown', onKey);

  function codeLen() { return s?.code_len || 4; }

  function press(k) {
    if (busy || link.serverNow() < cooldownUntil) return;
    if (k === '⌫') code = code.slice(0, -1);
    else if (k === 'C') code = '';
    else if (code.length < codeLen()) code += k;
    setMsg('');
    drawCode();
    if (code.length === codeLen()) submit();
  }

  async function submit() {
    busy = true;
    drawCode();
    const r = await link.cmd('seeds_enter', { code });
    busy = false;
    if (r.ok) {
      celebrate(r.kind, r.points);
      code = '';
    } else {
      if (r.until_ms) cooldownUntil = r.until_ms;
      ui.slots?.classList.add('shake');
      setTimeout(() => ui.slots?.classList.remove('shake'), 400);
      vibrate([60, 40, 60]);
      if (r.code === 'wrong') sound('wrong');
      setMsg(r.error || 'Не получилось', 'err');
      code = '';
    }
    drawCode();
  }

  function celebrate(kind, points) {
    const k = KIND[kind] || KIND.regular;
    vibrate(kind === 'rainbow' ? [80, 40, 80, 40, 200] : kind === 'golden' ? [60, 30, 120] : 60);
    sound(kind === 'regular' ? 'game-catch' : 'game-golden');
    const pop = el('div', { class: `seed-pop ${kind}` }, el('div', { class: 'ic' }, seedIcon(kind)), el('div', {}, k.title), el('b', {}, `+${points}`));
    box.append(pop);
    setTimeout(() => pop.remove(), kind === 'rainbow' ? 3500 : 1800);
    setMsg(`${k.title} +${points}`, 'ok');
  }

  function setMsg(text, cls = '') {
    if (!ui.msg) return;
    ui.msg.textContent = text;
    ui.msg.className = `seeds-msg ${cls}`;
  }

  function drawCode() {
    if (!ui.slots) return;
    clear(ui.slots);
    for (let i = 0; i < codeLen(); i++) ui.slots.append(el('div', { class: `slot${i < code.length ? ' on' : ''}` }, code[i] || ''));
    ui.slots.classList.toggle('busy', busy);
  }

  function tick() {
    if (!s) return;
    const now = link.serverNow();
    if (layout === 'running' && ui.time) {
      ui.time.textContent = `⏱ ${fmtClock(s.end_at_ms - now)}`;
      const cd = cooldownUntil - now;
      ui.pad.classList.toggle('locked', cd > 0);
      if (cd > 0) setMsg(`Слишком много ошибок. Пауза ${Math.ceil(cd / 1000)} с`, 'err');
      else if (ui.msg.textContent.startsWith('Слишком много')) setMsg('');
    } else if (layout === 'countdown' && ui.big) {
      const n = Math.ceil((s.start_at_ms - now) / 1000);
      ui.big.textContent = n > 3 ? 'Готовься!' : n > 0 ? String(n) : 'Ищи!';
    }
  }

  function mine() {
    const m = s.my || {};
    return `Мои: ${m.count || 0} · +${m.points || 0}`;
  }

  function rules() {
    const p = s.points || {};
    return el('div', { class: 'seeds-rules' },
      el('p', {}, 'По комнате спрятаны бумажные семечки с кодом. Нашёл — забирай себе и вводи код.'),
      el('p', {}, seedIcon('regular'), ` обычная +${p.regular ?? 30} · `, seedIcon('golden'), ` золотая +${p.golden ?? 100} · `,
        seedIcon('rainbow'), ` радужная мегасемка +${p.rainbow ?? 300}`),
      el('p', { class: 'muted' }, 'Кто первый ввёл код — того и семечка. Подбирать коды наугад не выйдет: после ошибок будет пауза.'));
  }

  function build() {
    layout = s.phase;
    ui = {};
    clear(box);
    const my = s.my || {};
    if (!my.can_play) {
      box.append(el('div', { class: 'qbig' }, '🙈'),
        el('p', { class: 'center' }, 'Ведущий не ищет — ты же знаешь, где они 😉 Смотри на экран и подзадоривай!'));
      return;
    }
    if (s.phase === 'idle') {
      box.append(el('div', { class: 'qbig' }, seedIcon('golden'), ' 🔎'), rules(), el('p', { class: 'center muted' }, 'Сейчас ведущий даст старт'));
    } else if (s.phase === 'countdown') {
      ui.big = el('div', { class: 'qbig' }, 'Готовься!');
      box.append(ui.big, rules());
    } else if (s.phase === 'running') {
      ui.time = el('div', {});
      ui.mine = el('div', {}, mine());
      ui.slots = el('div', { class: 'seeds-slots' });
      ui.msg = el('div', { class: 'seeds-msg' });
      ui.pad = el('div', { class: 'seeds-pad' });
      for (const k of ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'C', '0', '⌫']) {
        ui.pad.append(el('button', { class: k === 'C' || k === '⌫' ? 'fn' : '', onclick: () => press(k) }, k));
      }
      box.append(el('div', { class: 'seeds-hud' }, ui.time, ui.mine), el('p', { class: 'center muted' }, 'Введи код с найденной семечки'),
        ui.slots, ui.msg, ui.pad);
      drawCode();
    } else {
      box.append(el('div', { class: 'qbig' }, `${my.count || 0} `, seedIcon()),
        el('p', { class: 'center' }, `Охота окончена! Твой улов: +${my.points || 0}`),
        el('p', { class: 'center muted' }, 'Итоги на экране.'));
    }
  }

  function render() {
    if (s.my?.cooldown_until_ms) cooldownUntil = Math.max(cooldownUntil, s.my.cooldown_until_ms);
    if (layout !== s.phase || (!!s.my?.can_play) !== (ui.canPlay ?? !!s.my?.can_play)) build();
    ui.canPlay = !!s.my?.can_play;
    if (ui.mine) ui.mine.textContent = mine();
    tick();
  }

  return {
    update(next) { s = next; if (s) render(); },
    unmount() { clearInterval(timer); document.removeEventListener('keydown', onKey); },
  };
}
