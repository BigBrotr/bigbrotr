# ============================================================================
# BigBrotr Implementation Template - Dockerfile
# ============================================================================
# Multi-stage build for minimal production image
# Usage: docker build -t myimpl .
# ============================================================================

# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

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

# Labels - CUSTOMIZE these for your implementation
LABEL maintainer="Your Name <your@email.com>"
LABEL description="MyImpl - Custom BigBrotr implementation"
LABEL version="0.1.0"

# Create non-root user for security
# CUSTOMIZE: Change group/user names if desired
RUN groupadd --gid 1000 bigbrotr && \
    useradd --uid 1000 --gid bigbrotr --shell /bin/bash --create-home bigbrotr

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
COPY --chown=bigbrotr:bigbrotr src/ /app/src/

# CUSTOMIZE: Update the config path to your implementation
COPY --chown=bigbrotr:bigbrotr deployments/_template/config/ /app/config/

# Set Python path
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Default environment variables
ENV LOG_LEVEL=INFO
ENV ENVIRONMENT=production

# Switch to non-root user
USER bigbrotr

# Health check (will be overridden per service in docker-compose)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command - override in docker-compose.yaml
# Example: python -m bigbrotr seeder
CMD ["python", "-c", "print('BigBrotr ready. Specify service to run.')"]

# ============================================================================
# BUILD & RUN EXAMPLES
# ============================================================================
#
# Build image:
#   docker build -t myimpl -f deployments/myimpl/Dockerfile .
#
# Run seeder:
#   docker run --rm -e DB_PASSWORD=xxx myimpl python -m bigbrotr seeder
#
# Run with docker-compose (recommended):
#   docker-compose up -d
#
# ============================================================================
