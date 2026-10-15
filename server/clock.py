"""Единый источник времени сервера (модуль 08: перемотка для симулятора).

Весь серверный код берёт время только отсюда. При speed > 1 время идёт быстрее
реального: минута ответа в квизе сжимается до секунд.
"""
from __future__ import annotations

import asyncio
import time


class Clock:
    def __init__(self, speed: float = 1.0):
        self.speed = float(speed) if speed and speed > 0 else 1.0
        self._real0 = time.time()
        self._mono0 = time.monotonic()

    def now(self) -> float:
        """Серверное время в секундах (эпоха Unix, ускоренная при speed > 1)."""
        return self._real0 + (time.monotonic() - self._mono0) * self.speed

    def now_ms(self) -> int:
        return int(self.now() * 1000)

    async def sleep(self, seconds: float) -> None:
        """Спать `seconds` серверных секунд."""
        await asyncio.sleep(max(0.0, seconds) / self.speed)
