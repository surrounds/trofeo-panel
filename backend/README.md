# Бекенд панели Trofeo Vision 11.3 LCD

FastAPI-демон: владеет USB-устройством, рендерит кадры по конфигурации
и шлёт их на панель раз в interval секунд. HTTP API для конфигуратора
(React-фронтенд подключается к нему).

## Быстрый старт (из корня проекта)

```bash
./install.sh      # venv + зависимости + сборка фронтенда
./run.sh start    # запуск в фоне: веб-интерфейс и API на :8888
./run.sh stop     # остановка
./run.sh status   # статус (есть ещё restart)
./run.sh          # запуск на переднем плане, Ctrl+C для выхода
```

PID-файл и лог фонового режима: backend/data/panel.pid, panel.log.
Скрипты печатают адрес в локальной сети (не localhost), чтобы
интерфейс можно было открыть с любого устройства в сети.

На macOS для запуска двойным кликом из Finder: `start.command` и
`stop.command` в корне проекта (двойной клик открывает Terminal).

Деплой: `deploy/trofeo-panel.service` (systemd),
`deploy/99-trofeo.rules` (udev), `Dockerfile` (контейнер с пробросом
/dev/bus/usb; на macOS Docker USB не пробрасывает).

## Raspberry Pi: установка и обновление через git

```bash
sudo apt install -y git python3-venv libusb-1.0-0 fonts-dejavu-core
git clone --recurse-submodules https://github.com/surrounds/trofeo-panel.git ~/trofeo-panel
cd ~/trofeo-panel && ./install.sh
sudo cp deploy/99-trofeo.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo cp deploy/trofeo-panel.service /etc/systemd/system/
sudo sed -i "s|/opt/trofeo-panel|$HOME/trofeo-panel|" /etc/systemd/system/trofeo-panel.service
sudo systemctl enable --now trofeo-panel
```

Обновление в одну команду (`backend/data/` в git не входит,
конфиг панели переживает любые обновления):

```bash
cd ~/trofeo-panel && ./update.sh
```

Важно: frontend/dist закоммичен в репозиторий (на Pi нет npm).
После правок фронтенда перед push выполнить `npm run build`.

## Запуск вручную

```bash
cd backend
python3 -m venv .venv            # если ещё нет
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8888
```

Строго один воркер (по умолчанию так и есть): процесс единолично
владеет USB-устройством.

- macOS: для доступа к USB нужен root: `sudo .venv/bin/uvicorn ...`
- Linux: либо root, либо udev-правило (без перезапуска панели):

```
# /etc/udev/rules.d/99-trofeo.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5408", MODE="0666"
```

Dev-режим без панели (рендер и API работают, USB не трогается):

```bash
PANEL_NO_USB=1 .venv/bin/uvicorn app.main:app --reload
```

Если панели нет или кабель выдернут, демон не падает: пробует
переподключиться каждые 5 секунд, ошибка видна в /api/status.

## API

| Метод | Путь | Что делает |
|---|---|---|
| GET | /api/status | статус: связь с панелью, счётчик кадров, последняя ошибка |
| GET | /api/config | текущая конфигурация |
| PUT | /api/config | сохранить конфигурацию (применяется со следующего кадра) |
| GET | /api/widgets | каталог виджетов и схемы их настроек |
| POST | /api/metrics | метрики удалённой машины (Mac): панель показывает их, пока приходят чаще 10с, иначе метрики хоста |
| GET | /api/preview.png | PNG-кадр по текущему конфигу |
| POST | /api/preview.png | PNG-кадр по черновику конфига из тела (без сохранения) |
| GET | /api/images | список загруженных картинок |
| POST | /api/images | загрузить картинку (multipart, поле file) |
| DELETE | /api/images/{name} | удалить картинку |

Интерактивная документация: http://host:8888/docs

## Конфигурация

Хранится в data/config.json, редактируется через PUT /api/config.

```json
{
  "interval": 1.0,
  "jpeg_quality": 85,
  "theme": {"bg": [12,14,22], "accent": [80,200,255], "...": "остальные цвета"},
  "header": {"enabled": true, "show_host": true, "show_uptime": true,
             "show_load": true, "show_clock": true},
  "panels": [
    {"type": "cpu", "settings": {"show_cores": true, "show_temp": true}},
    {"type": "memory", "settings": {"show_swap": true}},
    {"type": "disk", "settings": {"path": "/"}},
    {"type": "network", "settings": {}}
  ]
}
```

Панелей от 1 до 4, ширина делится поровну. Одна панель с
header.enabled=false занимает весь экран (например часы или картинка
во весь экран). Типы: cpu, memory, disk, network, clock, image,
calendar (сетка месяца + события: ics_url - закрытый iCal-адрес
Google Calendar (настройки календаря -> Интеграция), разбор в
app/gcal.py: повторы через dateutil.rrule, EXDATE, таймзоны,
кэш 5 минут с фоновым обновлением; плюс ручные события строками
"ГГГГ-ММ-ДД текст"), worldclock (до 6 городов из встроенного каталога
ZONE_CATALOG в app/widgets.py: 41 город, все пояса GMT-11..GMT+14
включая получасовые; российских городов в каталоге нет намеренно,
GMT+2 - Киев, GMT+3 - Стамбул/Эр-Рияд; старый текстовый формат
"Area/City|Подпись" тоже принимается), weather (город; данные Open-Meteo без ключа,
кэш 10 минут, обновление в фоне, рендер сеть не ждёт).
interval ограничен 2с сверху: сторожевой таймер панели возвращает
заводской логотип примерно через 1-2с без кадров.

## Структура

- ../trofeo-lcd/ - отдельный pip-пакет с протоколом и USB
  (TrofeoPanel, encode_frame и т.д.; побайтово сверен с эталоном,
  формулы не менять; ставится через `pip install -e trofeo-lcd`,
  можно использовать в других проектах)
- app/sender.py - фоновый поток: рендер -> JPEG -> USB (через trofeo_lcd)
- app/render.py - сборка кадра из шапки и панелей
- app/widgets.py - виджеты и каталог для фронтенда
- app/metrics.py - срез системных метрик (psutil)
- app/config.py - pydantic-модели конфига, хранилище
- app/fonts.py - шрифты с фолбэками Linux/macOS
- data/config.json - текущая конфигурация
- data/images/ - загруженные картинки

## systemd (целевой деплой)

```ini
# /etc/systemd/system/trofeo-panel.service
[Unit]
Description=Trofeo Vision 11.3 LCD panel daemon
After=network.target

[Service]
WorkingDirectory=/opt/trofeo/backend
ExecStart=/opt/trofeo/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8888
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
