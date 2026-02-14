# ============================================================================
# BigBrotr Unified Dockerfile
# ============================================================================
# Parametric multi-stage build for all deployments (bigbrotr, lilbrotr, etc.)
# Usage: docker build --build-arg DEPLOYMENT=bigbrotr -t bigbrotr -f deployments/Dockerfile .
# ============================================================================

# Build arg must be declared before FROM to be available in both stages
ARG DEPLOYMENT=bigbrotr

# Stage 1: Build with uv
FROM python:3.11.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /bin/uv

WORKDIR /app

# Install build dependencies (native extensions for asyncpg, nostr-sdk)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    pkg-config \
    libsecp256k1-dev \
    && rm -rf /var/lib/apt/lists/*

# Layer 1: Install dependencies only (cached unless pyproject.toml or uv.lock change)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

# Layer 2: Install the project itself (rebuilds when src/ changes)
COPY README.md ./
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Stage 2: Production image
FROM python:3.11.14-slim

# Re-declare ARGs after FROM to make them available in this stage
ARG DEPLOYMENT=bigbrotr
ARG VERSION=dev

# Labels
LABEL maintainer="BigBrotr Contributors"
LABEL org.opencontainers.image.title="${DEPLOYMENT}"
LABEL org.opencontainers.image.description="BigBrotr - Nostr data archiving and monitoring system"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.source="https://github.com/BigBrotr/bigbrotr"
LABEL org.opencontainers.image.licenses="MIT"

# Create non-root user with deployment name
RUN groupadd -g 1000 ${DEPLOYMENT} && \
    useradd -u 1000 -g ${DEPLOYMENT} -m ${DEPLOYMENT}

WORKDIR /app

# Install runtime dependencies (libpq for asyncpg, libsecp256k1 for crypto, tini for PID 1)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libsecp256k1-dev \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Remove pre-installed system Python packages (pip, setuptools, wheel and transitive deps).
# The production image uses .venv exclusively; these are unused and trigger Trivy findings.
RUN rm -rf /usr/local/lib/python*/dist-packages /usr/local/lib/python*/ensurepip \
    && rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/wheel

# Copy the virtual environment from builder (no pip/setuptools in production image)
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy deployment-specific config (needed at runtime, not part of the package)
COPY --chown=${DEPLOYMENT}:${DEPLOYMENT} deployments/${DEPLOYMENT}/config/ /app/config/

ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV LOG_LEVEL=INFO
ENV ENVIRONMENT=production

# Switch to non-root user
USER ${DEPLOYMENT}

# Proper signal handling
STOPSIGNAL SIGTERM

# Use tini as PID 1 init process
ENTRYPOINT ["tini", "--"]

# Health check (Prometheus metrics endpoint)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/metrics')" || exit 1

# Default command (uses console_scripts entry point)
CMD ["bigbrotr"]
