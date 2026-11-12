FROM node:24-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 HOST=0.0.0.0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libegl1 libgles2 libglib2.0-0 libportaudio2 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && pip check
COPY . .
COPY --from=frontend /frontend/dist ./frontend/dist
RUN useradd --create-home safesight && mkdir -p artifacts/media models && chown -R safesight:safesight /app
USER safesight
CMD ["python", "-m", "safesight.backend"]
