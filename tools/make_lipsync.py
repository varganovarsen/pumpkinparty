"""Липсинк для головы-тыквы (модуль 04): для каждого content/audio/<id>.mp3 создать <id>.lipsync.json.

    python tools/make_lipsync.py                      # все mp3 в content/audio
    python tools/make_lipsync.py content/audio/f001.mp3 --smooth 3 --silence 0.08

Формат: {"fps": 30, "frames": [{"t": 0.0, "mouth": 0-100, "viseme": 0-4}, ...]}.
mouth — сглаженная огибающая громкости; viseme — по «светлости» звука (спектральный центроид):
0 закрыт, 1 слегка открыт, 2 широко («а»), 3 кружок («о/у»), 4 растянут («э/и»).
Предпросмотр: /tools/lipsync-preview на запущенном сервере.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
FPS = 30


def analyse(path: Path, smooth: int = 3, silence: float = 0.08, small: float = 30.0,
            low_hz: float = 900.0, high_hz: float = 2200.0) -> dict:
    data, sr = sf.read(str(path), always_2d=True, dtype="float32")
    mono = data.mean(axis=1)
    hop = sr / FPS
    n = int(np.ceil(len(mono) / hop))
    win = int(hop * 2)
    rms = np.zeros(n)
    cent = np.zeros(n)
    window = np.hanning(win)
    freqs = np.fft.rfftfreq(win, 1 / sr)
    for i in range(n):
        a = int(i * hop)
        seg = mono[a:a + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        rms[i] = np.sqrt(np.mean(seg ** 2))
        spec = np.abs(np.fft.rfft(seg * window))
        cent[i] = float((freqs * spec).sum() / spec.sum()) if spec.sum() > 1e-9 else 0.0
    if smooth > 1:
        k = np.ones(smooth) / smooth
        rms = np.convolve(rms, k, mode="same")
    peak = np.percentile(rms, 95) if rms.max() > 0 else 1.0
    env = np.clip(rms / max(peak, 1e-9), 0, 1)
    mouth = np.clip((env - silence) / (1 - silence), 0, 1) * 100
    frames = []
    for i in range(n):
        m = float(mouth[i])
        if m < 8:
            v = 0
        elif m < small:
            v = 1
        elif cent[i] < low_hz:
            v = 3
        elif cent[i] > high_hz:
            v = 4
        else:
            v = 2
        frames.append({"t": round(i / FPS, 3), "mouth": int(round(m)), "viseme": v})
    return {"fps": FPS, "frames": frames}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="mp3 (по умолчанию все в content/audio)")
    ap.add_argument("--smooth", type=int, default=3, help="сглаживание, кадров (по умолчанию 3)")
    ap.add_argument("--silence", type=float, default=0.08, help="порог тишины 0..1 (по умолчанию 0.08)")
    ap.add_argument("--small", type=float, default=30, help="mouth ниже этого — «слегка открыт» (по умолчанию 30)")
    ap.add_argument("--low", type=float, default=900, help="центроид ниже, Гц — «о/у» (по умолчанию 900)")
    ap.add_argument("--high", type=float, default=2200, help="центроид выше, Гц — «э/и» (по умолчанию 2200)")
    args = ap.parse_args()
    files = [Path(f) for f in args.files] or sorted((ROOT / "content" / "audio").glob("*.mp3"))
    if not files:
        print("Нет mp3 в content/audio")
        return 0
    bad = 0
    for f in files:
        try:
            data = analyse(f, args.smooth, args.silence, args.small, args.low, args.high)
        except Exception as e:  # noqa: BLE001
            print(f"ОШИБКА {f.name}: {e}")
            bad += 1
            continue
        out = f.with_suffix(".lipsync.json")
        out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        print(f"{f.name}: {len(data['frames'])} кадров → {out.name}")
    return 1 if bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
