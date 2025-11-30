# ============================================================================
# LilBrotr Application Dockerfile
# ============================================================================
# Multi-stage build for minimal production image
# Note: LilBrotr is a lightweight implementation that does not store tags/content
# Usage: docker build -t lilbrotr .
# ============================================================================

# Stage 1: Build dependencies
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    pkg-config \
    libsecp256k1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt

# Stage 2: Production image
FROM python:3.11-slim

# Labels
LABEL maintainer="LilBrotr Contributors"
LABEL description="LilBrotr - Lightweight Nostr data archiving (no tags/content storage)"
LABEL version="0.1.0"

# Create non-root user for security
RUN groupadd --gid 1000 lilbrotr && \
    useradd --uid 1000 --gid lilbrotr --shell /bin/bash --create-home lilbrotr

WORKDIR /app

# Install runtime and build dependencies for secp256k1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libsecp256k1-dev \
    pkg-config \
    gcc \
    make \
    automake \
    libtool \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder and install
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Remove build dependencies to reduce image size (keep libsecp256k1 runtime)
RUN apt-get purge -y --auto-remove gcc pkg-config make automake libtool && \
    apt-get clean

# Copy application source and set ownership
COPY --chown=lilbrotr:lilbrotr src/ /app/src/
COPY --chown=lilbrotr:lilbrotr implementations/lilbrotr/yaml/ /app/yaml/

# Set Python path
ENV PYTHONPATH=/app/src
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
# Usage: docker run lilbrotr python -m services.initializer
CMD ["python", "-c", "print('LilBrotr ready. Specify service to run.')"]
