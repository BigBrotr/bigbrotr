# ============================================================================
# LilBrotr Application Dockerfile
# ============================================================================
# Multi-stage build for minimal production image
# Note: LilBrotr is a lightweight implementation that does not store tags/content
# Usage: docker build -t lilbrotr -f deployments/lilbrotr/Dockerfile .
# ============================================================================

# Stage 1: Build wheels
FROM python:3.11-slim AS builder

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
FROM python:3.11-slim

# Labels
LABEL maintainer="LilBrotr Contributors"
LABEL description="LilBrotr - Lightweight Nostr data archiving (no tags/content storage)"
LABEL version="4.0.0"

# Create non-root user for security
RUN groupadd --gid 1000 lilbrotr && \
    useradd --uid 1000 --gid lilbrotr --shell /bin/bash --create-home lilbrotr

WORKDIR /app

# Install runtime dependencies for secp256k1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libsecp256k1-dev \
    && rm -rf /var/lib/apt/lists/*

# Install wheels from builder (includes bigbrotr package + console_scripts)
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy config (needed at runtime, not part of the package)
COPY --chown=lilbrotr:lilbrotr deployments/lilbrotr/config/ /app/config/

ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV LOG_LEVEL=INFO
ENV ENVIRONMENT=production

# Switch to non-root user
USER lilbrotr

# Health check (will be overridden per service)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command - can be overridden
# Usage: docker run lilbrotr bigbrotr seeder
CMD ["python", "-c", "print('LilBrotr ready. Specify service to run.')"]
