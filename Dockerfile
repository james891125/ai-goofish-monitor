# Stage 1: Build the Vue application
FROM node:22-alpine AS frontend-builder
WORKDIR /web-ui
COPY web-ui/package*.json ./
RUN npm ci
COPY web-ui/ .
RUN npm run build

# Stage 2: Build the python environment with dependencies
FROM python:3.11-slim-bookworm AS builder

# 設定環境變數以防止互動式提示
ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# 建立虛擬環境並安裝 Python 執行時依賴
RUN python3 -m venv $VIRTUAL_ENV
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

# Stage 3: Create the final, lean image
FROM python:3.11-slim-bookworm

WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RUNNING_IN_DOCKER=true \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Asia/Taipei

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata \
        tini \
        libzbar0 \
    && playwright install --with-deps --no-shell chromium \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=frontend-builder /dist /app/dist

COPY src /app/src
COPY spider_v2.py /app/spider_v2.py
COPY prompts /app/prompts
COPY static /app/static
COPY config.json.example /app/config.json.example

RUN mkdir -p /app/data /app/state /app/logs /app/images /app/jsonl /app/price_history

EXPOSE 8000

USER root

ENTRYPOINT ["tini", "--"]

CMD ["python", "-m", "src.app"]
