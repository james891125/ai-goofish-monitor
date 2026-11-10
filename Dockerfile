# Build the checked-out fork, never a prebuilt upstream application image.
FROM node:22-alpine AS frontend-builder
WORKDIR /web-ui
COPY web-ui/package*.json ./
RUN npm ci
COPY web-ui/ .
RUN npm run build

FROM python:3.11-slim-bookworm AS python-builder
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv /opt/venv
COPY requirements-runtime.txt /tmp/requirements-runtime.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-runtime.txt

FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_DATABASE_FILE=/app/data/app.sqlite3 \
    TZ=Asia/Taipei
COPY --from=python-builder /opt/venv /opt/venv
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /app/data /app/prompts /app/logs /app/images \
    && touch /app/data/settings.env \
    && ln -s /app/data/settings.env /app/.env \
    && chown -R app:app /app
COPY --from=frontend-builder --chown=app:app /dist /app/dist
COPY --chown=app:app src /app/src
COPY --chown=app:app prompts /app/prompts
COPY --chown=app:app LICENSE DISCLAIMER.md /app/
COPY --chown=app:app docs/THIRD_PARTY_NOTICES.md /app/docs/THIRD_PARTY_NOTICES.md
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
# The container must listen internally on 0.0.0.0; Compose publishes only to 127.0.0.1.
CMD ["python", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
