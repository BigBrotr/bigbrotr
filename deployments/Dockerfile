# ============================================================================
# BigBrotr Unified Dockerfile
# ============================================================================
# Parametric multi-stage build for all deployments (bigbrotr, lilbrotr, etc.)
# Usage: docker build --build-arg DEPLOYMENT=bigbrotr -t bigbrotr -f deployments/Dockerfile .
# ============================================================================

# Build arg must be declared before FROM to be available in both stages
ARG DEPLOYMENT=bigbrotr

# Stage 1: Build wheels
FROM python:3.11.14-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    pkg-config \
    libsecp256k1-dev \
    && rm -rf /var/lib/apt/lists/*

# Build wheels from pyproject.toml (includes bigbrotr + all dependencies)
COPY pyproject.toml .
COPY src/ ./src/
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels .

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

# Install wheels from builder (includes bigbrotr package + console_scripts)
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir /wheels/* && rm -rf /wheels

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

# Default command
CMD ["python", "-m", "bigbrotr"]
