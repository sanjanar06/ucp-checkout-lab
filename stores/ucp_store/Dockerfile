FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/venv UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
EXPOSE 8182 8183
HEALTHCHECK --interval=2s --timeout=3s --retries=30 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8182/.well-known/ucp')"
ENTRYPOINT ["./entrypoint.sh"]
