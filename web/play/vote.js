// Голосование за резьбу на телефоне (модуль 06): анонимные номера и снимки, свою выбрать нельзя,
// можно воздержаться и передумать до закрытия.
import { el, clear, toast } from '/web/shared/util.js';

export function mountVote(root, link) {
  const box = el('div', { class: 'vote' });
  root.append(box);
  let v = null;

  async function choose(n) {
    const r = await link.cmd('vote', { n });
    if (!r.ok) toast(r.error || 'Голос не принят');
  }

  function render() {
    clear(box);
    if (v.phase === 'idle') {
      box.append(el('div', { class: 'qbig' }, '🎃'), el('p', { class: 'center' }, 'Скоро голосование за лучшую тыкву'));
      return;
    }
    if (v.phase === 'closed') {
      box.append(el('div', { class: 'qbig' }, 'Голосование закрыто'), el('p', { class: 'center muted' }, 'Итоги — на экране'));
      return;
    }
    const my = v.my || {};
    box.append(el('p', { class: 'center' }, my.vote ? `Твой голос: №${my.vote}. Можно передумать.` : my.abstained ? 'Ты воздержался' : 'Выбери лучшую тыкву'));
    const grid = el('div', { class: 'vote-grid' });
    for (const e of v.entries) {
      const own = e.n === my.own;
      grid.append(el('button', { class: `vote-cell${my.vote === e.n ? ' sel' : ''}${own ? ' own' : ''}`, disabled: own,
        onclick: () => choose(e.n) },
      el('img', { src: e.shots.dark, alt: '', loading: 'lazy' }),
      el('span', { class: 'vote-n' }, own ? `№${e.n} · твоя` : `№${e.n}`)));
    }
    box.append(grid, el('button', { class: `${my.abstained ? 'on' : ''}`, style: { width: '100%', marginTop: '10px' },
      onclick: () => choose(null) }, 'Воздержаться'));
  }

  return { update(next) { v = next; if (v) render(); }, unmount() {} };
}
