# syntax=docker/dockerfile:1

# ---- Builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

# Pillow and cryptography publish manylinux wheels, so the whole dependency
# tree resolves here and the runtime image needs no compiler or headers.
RUN pip install --upgrade pip \
    && pip wheel --wheel-dir /wheels .

# ---- Runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Debian security updates published after the base tag was built.
RUN apt-get update && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# The pipeline reads a config and writes its own working directories; nothing
# it does needs privileges. Running as a fixed unprivileged uid means a
# container escape lands on an account that owns nothing but /app.
RUN useradd --create-home --uid 10001 automation

WORKDIR /app
COPY config/config.example.yaml ./config/config.example.yaml
RUN mkdir -p /app/watched /app/backups /app/logs \
    && chown -R automation:automation /app
USER automation

# Mount the real config and the inbox at run time, e.g.
#   docker run --rm \
#     -v "$PWD/config/config.yaml:/app/config/config.yaml:ro" \
#     -v "$PWD/inbox:/app/watched/inbox" \
#     -v "$PWD/output:/app/watched/output" \
#     -e FILE_AUTOMATION_ENCRYPTION_KEY \
#     enterprise-file-automation
ENTRYPOINT ["file-automation"]
CMD ["run"]
