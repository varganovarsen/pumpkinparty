"""Снимок с вебки ноутбука через OpenCV (модуль 03; на этапе 1 только тест с /check)."""
from __future__ import annotations

import threading

_lock = threading.Lock()


class WebcamError(Exception):
    pass


def snapshot(device: int = 0, warmup_frames: int = 8) -> bytes:
    """Снять кадр в максимальном доступном разрешении, вернуть JPEG. Блокирующий вызов."""
    try:
        import cv2
    except Exception as e:  # noqa: BLE001
        raise WebcamError(f"OpenCV не установлен: {e}") from e
    with _lock:
        cap = cv2.VideoCapture(int(device))
        try:
            if not cap.isOpened():
                raise WebcamError(f"Вебка {device} не открывается")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 4096)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
            frame = None
            for _ in range(warmup_frames + 1):  # пропустить кадры, пока подстраивается экспозиция
                ok, f = cap.read()
                if ok:
                    frame = f
            if frame is None:
                raise WebcamError("Вебка не отдаёт кадры")
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                raise WebcamError("Не удалось закодировать кадр")
            return buf.tobytes()
        finally:
            cap.release()
