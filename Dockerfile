# Контейнер демона панели (Linux-хост с пробросом USB).
# Сборка:  docker build -t trofeo-panel .
# Запуск:  docker run -d --name trofeo-panel \
#            --device-cgroup-rule='c 189:* rwm' \
#            -v /dev/bus/usb:/dev/bus/usb \
#            -v trofeo-data:/app/backend/data \
#            -p 8888:8888 trofeo-panel
# (проще, но шире права: --privileged -v /dev/bus/usb:/dev/bus/usb)
# macOS: Docker не пробрасывает USB, используйте ./run.sh напрямую.

FROM node:22-alpine AS front
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent
COPY frontend .
RUN npm run build

FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        libusb-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY trofeo-lcd /app/trofeo-lcd
RUN pip install --no-cache-dir /app/trofeo-lcd
COPY backend/app ./app
COPY --from=front /src/dist /app/frontend/dist
VOLUME /app/backend/data
EXPOSE 8888
# Один воркер: процесс единолично владеет USB-устройством
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888"]
