"""Локализация текстов панели: английский (по умолчанию) и украинский.

Язык задаётся конфигом и выставляется на время рендера кадра через
contextvar: поток отправки и обработчики предпросмотра не мешают
друг другу.
"""
from contextvars import ContextVar

_lang: ContextVar[str] = ContextVar("panel_lang", default="en")


def set_lang(lang: str):
    _lang.set("uk" if lang == "uk" else "en")


def is_uk() -> bool:
    return _lang.get() == "uk"


def tr(en: str, uk: str) -> str:
    """Строка по текущему языку."""
    return uk if is_uk() else en


MONTHS_GEN_EN = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November",
                 "December"]
MONTHS_GEN_UK = ["січня", "лютого", "березня", "квітня", "травня", "червня",
                 "липня", "серпня", "вересня", "жовтня", "листопада",
                 "грудня"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday"]
WEEKDAYS_UK = ["Понеділок", "Вівторок", "Середа", "Четвер",
               "П'ятниця", "Субота", "Неділя"]


def months_gen():
    return MONTHS_GEN_UK if is_uk() else MONTHS_GEN_EN


def weekdays():
    return WEEKDAYS_UK if is_uk() else WEEKDAYS_EN


# Коды погоды WMO
WMO_EN = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog",
    51: "drizzle", 53: "drizzle", 55: "dense drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm, hail", 99: "thunderstorm, hail",
}
WMO_UK = {
    0: "ясно", 1: "майже ясно", 2: "мінлива хмарність", 3: "похмуро",
    45: "туман", 48: "паморозь",
    51: "мряка", 53: "мряка", 55: "сильна мряка",
    56: "крижана мряка", 57: "крижана мряка",
    61: "невеликий дощ", 63: "дощ", 65: "сильний дощ",
    66: "крижаний дощ", 67: "крижаний дощ",
    71: "невеликий сніг", 73: "сніг", 75: "сильний сніг", 77: "снігова крупа",
    80: "невелика злива", 81: "злива", 82: "сильна злива",
    85: "снігопад", 86: "сильний снігопад",
    95: "гроза", 96: "гроза з градом", 99: "гроза з градом",
}


def wmo_desc(code: int) -> str:
    return (WMO_UK if is_uk() else WMO_EN).get(code, "")
