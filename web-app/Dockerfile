# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV VITE_MEMO_BASE=/memo/
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MEMO_ENV=production FLASHCARD_WEB_AUTH=1 FLASHCARD_WEB_REQUIRE_HTTPS=1 \
    FLASHCARD_WEB_IMPORT_DESKTOP=0 FLASHCARD_WEB_DATA=/data MEMO_COOKIE_PATH=/memo
COPY backend/requirements.lock.txt /app/requirements.lock.txt
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-impress fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && groupadd --gid 10001 memo \
    && useradd --uid 10001 --gid memo --no-create-home memo \
    && mkdir /data && chown memo:memo /data
COPY --chown=memo:memo backend/ /app/backend/
COPY --from=frontend --chown=memo:memo /build/dist/ /app/frontend/dist/
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--root-path", "/memo", "--proxy-headers", "--forwarded-allow-ips", "*"]
