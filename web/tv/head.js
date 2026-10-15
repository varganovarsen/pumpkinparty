// Голова-тыква на ТВ (модуль 04): пузырь с фактом, звук оповещения, озвучка с липсинком.
// Rive: assets/rive/head.riv, state machine HeadSM, входы appear/leave (trigger), talk (bool),
// mouth (0-100), viseme (0-4), mood. Любого необязательного входа может не быть.
// Если .riv — заглушка или не загрузился, рисуется CSS-голова с тем же поведением.
import { el } from '/web/shared/util.js';

const TAIL_SECONDS = 3;
let riveLoading = null;

function loadRiveRuntime() {
  if (window.rive) return Promise.resolve(window.rive);
  if (!riveLoading) {
    riveLoading = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = '/web/vendor/rive/rive.js';
      s.onload = () => {
        // офлайн: wasm только локальный (по умолчанию Rive качает его с CDN)
        window.rive.RuntimeLoader.setWasmUrl('/web/vendor/rive/rive.wasm');
        window.rive.RuntimeLoader.setWasmFallbackUrl('/web/vendor/rive/rive_fallback.wasm');
        resolve(window.rive);
      };
      s.onerror = reject;
      document.head.append(s);
    });
  }
  return riveLoading;
}

export function createHead(container, ctx) {
  let state = null; // {factId, node, timer, audio, raf}
  let rive = null;
  let inputs = {};
  const useRive = !(ctx.stubs || []).includes('rive/head.riv');

  // ---------------------------------------------------------------- Rive или CSS
  const canvas = useRive ? el('canvas', { class: 'head-rive', width: '800', height: '800' }) : null;
  if (canvas) {
    container.append(canvas);
    loadRiveRuntime().then((R) => {
      rive = new R.Rive({
        src: '/assets/rive/head.riv', canvas, stateMachines: 'HeadSM', autoplay: true,
        onLoad: () => {
          rive.resizeDrawingSurfaceToCanvas();
          for (const i of rive.stateMachineInputs('HeadSM') || []) inputs[i.name] = i;
        },
        onLoadError: () => { canvas.remove(); rive = null; },
      });
    }).catch(() => { canvas.remove(); });
  }

  function setInput(name, value) {
    const i = inputs[name];
    if (!i) return;
    if (value === 'fire') i.fire?.(); else i.value = value;
  }

  function mouth(node, value, viseme) {
    setInput('mouth', value);
    if (viseme !== undefined) setInput('viseme', viseme);
    const m = node?.querySelector('.mouth');
    if (m) m.style.height = `${1 + (value / 100) * 5}vh`;
  }

  // ---------------------------------------------------------------- показ
  function visible() { return !!state; }

  function finish() {
    if (!state) return;
    const s = state;
    state = null;
    clearTimeout(s.timer);
    cancelAnimationFrame(s.raf);
    s.audio?.pause();
    setInput('talk', false);
    setInput('leave', 'fire');
    s.node.classList.remove('in', 'talking');
    canvas?.classList.remove('in');
    setTimeout(() => s.node.remove(), 1300);
    ctx.link.cmd('head_done', { fact_id: s.factId });
  }

  function hideIn(s, seconds) {
    clearTimeout(s.timer);
    s.timer = setTimeout(() => { if (state === s) finish(); }, Math.max(0, seconds) * 1000);
  }

  async function playAudio(s, data) {
    s.audio?.pause();
    cancelAnimationFrame(s.raf);
    const a = new Audio(data.audio_url);
    s.audio = a;
    let frames = null;
    if (data.lipsync_url) {
      try { frames = await (await fetch(data.lipsync_url)).json(); } catch { frames = null; }
    }
    const loop = () => {
      if (state !== s || a.paused) return;
      if (frames?.frames?.length) {
        const f = frames.frames[Math.min(frames.frames.length - 1, Math.floor(a.currentTime * frames.fps))];
        mouth(s.node, f.mouth, f.viseme);
      } else {
        mouth(s.node, 50 + 45 * Math.sin(a.currentTime * 14)); // запасная анимация без JSON
      }
      s.raf = requestAnimationFrame(loop);
    };
    a.addEventListener('playing', () => {
      setInput('talk', true);
      s.node.classList.toggle('talking', !frames && !rive);
      s.raf = requestAnimationFrame(loop);
    });
    a.addEventListener('ended', () => {
      setInput('talk', false);
      mouth(s.node, 0, 0);
      s.node.classList.remove('talking');
      hideIn(s, TAIL_SECONDS);
    });
    a.addEventListener('error', () => hideIn(s, data.seconds));
    hideIn(s, 90); // страховка, если аудио не стартует
    a.play().catch(() => hideIn(s, data.seconds));
  }

  function show(data, resumed = false) {
    if (state) finish();
    const elapsed = ctx.link.serverNow() / 1000 - data.called_at;
    if (resumed && elapsed > data.seconds) return;
    const node = el('div', { class: `head${rive ? ' rive' : ''}` },
      el('div', { class: 'bubble' }, data.text),
      rive ? null : el('div', { class: 'face' }, el('div', { class: 'eye l' }), el('div', { class: 'eye r' }), el('div', { class: 'mouth' })));
    container.append(node);
    const s = { factId: data.fact_id, data, node, timer: null, audio: null, raf: 0 };
    state = s;
    requestAnimationFrame(() => requestAnimationFrame(() => { node.classList.add('in'); canvas?.classList.add('in'); }));
    setInput('appear', 'fire');
    ctx.link.cmd('head_shown', { fact_id: data.fact_id });
    if (!resumed) ctx.sfx('fact-notify');
    if (!resumed && data.mode === 'loud' && data.audio_url) {
      setTimeout(() => { if (state === s) playAudio(s, data); }, 900);
    } else {
      hideIn(s, resumed ? data.seconds - elapsed : data.seconds);
    }
  }

  // «Озвучить» в тихом режиме: озвучка с начала, показ до конца речи + 3 с
  function speak() {
    if (state?.data.audio_url) playAudio(state, state.data);
  }

  return {
    show, speak, visible,
    hide: finish,
    destroy() {
      if (state) { clearTimeout(state.timer); cancelAnimationFrame(state.raf); state.audio?.pause(); }
      state = null;
      rive?.cleanup?.();
    },
  };
}
