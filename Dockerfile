# --- frontend build ---------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim
# Tesseract (+ Dutch/French) for reading scale/contours/dates from image maps;
# git for publishing the public site to GitHub Pages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-nld tesseract-ocr-fra sqlite3 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app ./backend/app
COPY --from=frontend /build/dist ./frontend/dist
COPY --from=frontend /build/dist-site ./frontend/dist-site

ENV OMAPS_DATA_DIR=/data \
    OMAPS_FRONTEND_DIST=/app/frontend/dist \
    OMAPS_SITE_DIST=/app/frontend/dist-site \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend
RUN useradd --uid 1000 --create-home omaps && mkdir -p /data && chown omaps /data
USER omaps

EXPOSE 8420
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/healthz')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420", "--proxy-headers"]
