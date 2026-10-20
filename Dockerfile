# Сборка в два этапа: Node собирает мини-приложение, в итоговый образ попадает только Python и статика
FROM node:24-alpine AS webapp
WORKDIR /web
COPY webapp/package.json webapp/package-lock.json ./
RUN npm ci
COPY webapp/ ./
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
# Сначала только зависимости: этот слой кэшируется и не пересобирается при правке кода
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY niches ./niches
RUN uv sync --frozen --no-dev
COPY --from=webapp /web/dist ./webapp/dist
RUN useradd --system shop
USER shop
ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8085
EXPOSE 8085
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/health')"
# Миграции при старте: новая версия сама обновит схему базы
CMD ["sh", "-c", "booking migrate && booking run"]
