# Google's official UCP conformance suite, at the commit pinned in versions.lock.toml.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ARG CONFORMANCE_COMMIT=016ecbc22240affdec4429a60d539bedd04ab51b
WORKDIR /conformance
RUN git init -q . \
 && git fetch -q --depth 1 https://github.com/Universal-Commerce-Protocol/conformance "$CONFORMANCE_COMMIT" \
 && git checkout -q FETCH_HEAD && rm -rf .git
# The suite expects a sibling checkout of python-sdk; use the pinned PyPI release instead.
RUN sed -i '/^\[tool.uv.sources\]/,/^$/d' pyproject.toml
ENV UV_PROJECT_ENVIRONMENT=/venv
RUN uv sync --no-install-project
ENTRYPOINT ["uv", "run", "--no-sync", "pytest", "-q", "-rs"]
