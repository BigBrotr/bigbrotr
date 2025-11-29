# ============================================================================
# BigBrotr Application Dockerfile
# ============================================================================
# Multi-stage build for minimal production image
# Usage: docker build -t bigbrotr .
# ============================================================================

# Stage 1: Build dependencies
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels -r requirements.txt

# Stage 2: Production image
FROM python:3.11-slim

# Labels
LABEL maintainer="BigBrotr Contributors"
LABEL description="BigBrotr - Nostr data archiving and monitoring system"
LABEL version="0.1.0"

# Create non-root user for security
RUN groupadd --gid 1000 bigbrotr && \
    useradd --uid 1000 --gid bigbrotr --shell /bin/bash --create-home bigbrotr

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder and install
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application source
COPY src/ /app/src/
COPY implementations/bigbrotr/yaml/ /app/yaml/

# Set Python path
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV LOG_LEVEL=INFO
ENV ENVIRONMENT=production

# Switch to non-root user
USER bigbrotr

# Health check (will be overridden per service)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command - can be overridden
# Usage: docker run bigbrotr python -m services.initializer
CMD ["python", "-c", "print('BigBrotr ready. Specify service to run.')"]
