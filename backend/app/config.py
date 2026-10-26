"""Конфигурация панели: pydantic-модели, загрузка и сохранение JSON.

Конфиг хранится в data/config.json рядом с бекендом. Доступ через
ConfigStore потокобезопасен: его читают поток отправки и HTTP-обработчики.
"""
import json
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"
IMAGES_DIR = DATA_DIR / "images"

Color = tuple[int, int, int]


class Theme(BaseModel):
    """Цвета в RGB. Значения по умолчанию - тёмная тема из monitor.py."""
    bg: Color = (12, 14, 22)
    panel: Color = (24, 28, 40)
    border: Color = (40, 50, 70)
    fg: Color = (220, 230, 240)
    dim: Color = (130, 140, 160)
    accent: Color = (80, 200, 255)
    good: Color = (90, 220, 130)
    warn: Color = (255, 180, 60)
    crit: Color = (255, 80, 80)
    track: Color = (35, 40, 55)


class HeaderConfig(BaseModel):
    enabled: bool = True
    show_host: bool = True
    show_uptime: bool = True
    show_load: bool = True
    show_clock: bool = True


WidgetType = Literal["cpu", "memory", "disk", "network", "clock", "image",
                     "calendar", "worldclock", "weather"]


class PanelConfig(BaseModel):
    """Одна панель на экране. offline - виджет на то время, когда нет
    связи с приложением (метрики от него не приходят); None = обычное
    поведение (No data у системных виджетов). settings зависят от типа:

    cpu:     {"show_cores": bool, "show_temp": bool}
    memory:  {"show_swap": bool}
    disk:    {"path": str}
    network: {}
    clock:   {"show_date": bool, "show_seconds": bool}
    image:   {"name": str, "fit": "cover"|"contain"}
    """
    type: WidgetType
    settings: dict = Field(default_factory=dict)
    offline: "PanelConfig | None" = None


PanelConfig.model_rebuild()


class AppConfig(BaseModel):
    language: Literal["en", "uk"] = "en"
    # Через сколько секунд без метрик от приложения показать метрики
    # этой машины; 0 = никогда, показывать "No data"
    metrics_fallback_sec: int = Field(default=0, ge=0)
    interval: float = Field(default=1.0, ge=0.2, le=2.0,
                            description="период обновления, сек; больше 2с "
                                        "нельзя из-за сторожевого таймера панели")
    jpeg_quality: int = Field(default=85, ge=50, le=95)
    theme: Theme = Field(default_factory=Theme)
    header: HeaderConfig = Field(default_factory=HeaderConfig)
    panels: list[PanelConfig] = Field(
        default_factory=lambda: [
            PanelConfig(type="cpu"),
            PanelConfig(type="memory"),
            PanelConfig(type="disk", settings={"path": "/"}),
            PanelConfig(type="network"),
        ],
        min_length=1, max_length=4)

    @field_validator("panels")
    @classmethod
    def check_disk_paths(cls, panels):
        for p in panels:
            for w in (p, p.offline):
                if w is not None and w.type == "disk":
                    path = w.settings.get("path", "/")
                    if not Path(path).exists():
                        raise ValueError(f"disk: path does not exist: {path}")
        return panels


class ConfigStore:
    """Потокобезопасное хранилище конфига с сохранением на диск."""

    def __init__(self, path: Path = CONFIG_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._cfg = self._load()

    def _load(self) -> AppConfig:
        if self._path.exists():
            try:
                return AppConfig.model_validate(
                    json.loads(self._path.read_text(encoding="utf-8")))
            except Exception as e:
                print(f"[config] {self._path} не читается ({e}), "
                      "используются значения по умолчанию")
        return AppConfig()

    def get(self) -> AppConfig:
        with self._lock:
            return self._cfg.model_copy(deep=True)

    def set(self, cfg: AppConfig) -> AppConfig:
        with self._lock:
            self._cfg = cfg
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Предыдущая версия уходит в .bak: страховка от потери
            # настроек при ошибочной перезаписи
            if self._path.exists():
                self._path.with_suffix(".json.bak").write_text(
                    self._path.read_text(encoding="utf-8"), encoding="utf-8")
            self._path.write_text(
                json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8")
            return self._cfg
