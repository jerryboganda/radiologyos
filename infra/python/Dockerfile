# Claude Code CLI (ADR 0010): installed in a throwaway Node stage and copied as
# a single native binary, so the runtime image carries no Node toolchain.
FROM node:22-bookworm-slim AS claude
ARG CLAUDE_CODE_VERSION=2.1.283
RUN npm install -g --omit=dev "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && cp "$(npm root -g)/@anthropic-ai/claude-code/bin/claude.exe" /claude \
    && /claude --version

# Codex CLI (ADR 0035): ChatGPT models on the owner's subscription, copied as its
# static native binary. The sign-in lives in CODEX_HOME on the host, never here.
FROM node:22-bookworm-slim AS codex
ARG CODEX_VERSION=0.157.1
RUN npm install -g --omit=dev "@openai/codex@${CODEX_VERSION}" \
    && cp "$(npm root -g)/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex" /codex \
    && /codex --version

FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DISABLE_AUTOUPDATER=1 \
    HOME=/srv/home

# LibreOffice converts DOCX/PPTX to PDF for page rendering (headless only).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libreoffice-impress libreoffice-writer libreoffice-core \
       fonts-dejavu-core fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /srv/home

COPY --from=claude /claude /usr/local/bin/claude
COPY --from=codex /codex /usr/local/bin/codex

COPY pyproject.toml ./
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY packages ./packages
COPY alembic.ini ./

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "apps.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
