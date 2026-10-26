FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY samples /app/samples
COPY --from=frontend /app/frontend/dist /app/frontend/dist
RUN useradd --create-home yueji \
    && mkdir -p /app/data \
    && chown -R yueji:yueji /app/data
USER yueji
ENV PORT=8000 \
    YUEJI_DATA_DIR=/app/data \
    YUEJI_SEED_SAMPLES=true \
    YUEJI_AUTH_REQUIRED=true \
    YUEJI_ENV=production \
    YUEJI_SECURE_COOKIES=true
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health', timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
