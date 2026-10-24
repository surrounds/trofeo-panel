"""Фоновый поток отправки кадров: рендер -> JPEG -> USB.

Поток единолично владеет устройством. Если панели нет (dev-режим или
кабель выдернут), поток продолжает жить и пытается переподключиться,
а API и предпросмотр работают как обычно.
"""
import os
import threading
import time

from trofeo_lcd import TrofeoPanel, encode_frame

from . import metrics
from .config import ConfigStore
from .render import render_frame, disk_paths

# Через сколько секунд пробовать открыть панель заново
RECONNECT_SEC = 5.0


class Sender(threading.Thread):
    def __init__(self, store: ConfigStore, usb_enabled: bool = True):
        super().__init__(name="panel-sender", daemon=True)
        self.store = store
        self.usb_enabled = usb_enabled
        self.panel = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Статистика для /api/status
        self.frames_sent = 0
        self.last_error = None
        self.last_frame_ts = None
        self.started_ts = time.time()
        self._next_open_ts = 0.0

    # ── Жизненный цикл ────────────────────────────────────────────
    def stop(self):
        self._stop.set()

    def run(self):
        print(f"[sender] старт, usb={'вкл' if self.usb_enabled else 'выкл (dev-режим)'}")
        while not self._stop.is_set():
            cfg = self.store.get()
            t0 = time.time()
            try:
                self._tick(cfg)
            except Exception as e:
                self.last_error = str(e)
                print(f"[sender] ошибка: {e}")
                self._drop_panel(hard=True)
            # Держим период: рендер и отправка уже заняли часть интервала
            elapsed = time.time() - t0
            self._stop.wait(max(0.05, cfg.interval - elapsed))
        self._drop_panel()
        print("[sender] остановлен")

    # ── Один цикл ─────────────────────────────────────────────────
    def _tick(self, cfg):
        img = render_frame(cfg, metrics.snapshot(
            disk_paths(cfg), cfg.metrics_fallback_sec))
        if not self.usb_enabled:
            return
        if self.panel is None:
            if time.time() < self._next_open_ts:
                return
            try:
                self.panel = TrofeoPanel.open()
                self.last_error = None
            except Exception as e:
                self.last_error = str(e)
                self._next_open_ts = time.time() + RECONNECT_SEC
                return
        jpeg, field = encode_frame(img, cfg.jpeg_quality)
        self.panel.send_frame(jpeg, field)
        self.frames_sent += 1
        self.last_frame_ts = time.time()

    def _drop_panel(self, hard=False):
        if self.panel is None:
            return
        try:
            if hard:
                self.panel.recover(hard=True)
        except Exception:
            pass
        try:
            self.panel.close()
        except Exception:
            pass
        self.panel = None
        self._next_open_ts = time.time() + 2.0

    # ── Статус для API ────────────────────────────────────────────
    def status(self):
        return {
            "usb_enabled": self.usb_enabled,
            "connected": self.panel is not None,
            "frames_sent": self.frames_sent,
            "last_error": self.last_error,
            "last_frame_ts": self.last_frame_ts,
            "uptime_sec": round(time.time() - self.started_ts, 1),
        }
