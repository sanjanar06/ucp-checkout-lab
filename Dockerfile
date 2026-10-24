FROM python:3.13-slim
WORKDIR /app
COPY versions.lock.toml .
COPY scripts/ scripts/
