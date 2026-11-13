FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
COPY pnpm-workspace.yaml ./
COPY frontend ./frontend
COPY public ./public
COPY tsconfig.json ./
RUN pnpm install --frozen-lockfile
RUN pnpm build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    CCTV_PDF_BROWSER=/usr/bin/chromium \
    ASSET_STORAGE_DIR=/tmp/cctv-storage

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-liberation \
        libffi8 \
        libharfbuzz-subset0 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app ./backend/app
COPY backend/alembic ./backend/alembic
COPY backend/alembic.ini ./backend/alembic.ini
COPY backend/templates ./backend/templates
COPY --from=frontend-build /app/dist ./dist

CMD ["sh", "-c", "cd /app/backend && python -m alembic -c alembic.ini upgrade head && cd /app && python -m app.render_startup && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips=*"]
