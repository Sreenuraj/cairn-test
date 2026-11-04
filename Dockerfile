# syntax=docker/dockerfile:1
# ------------------------------------------------------------------------------
# cairn-test Multi-Stage Container Image (T8.4)
# Minimal, secure, zero-secret headless runner for CI/CD and remote schedulers.
# ------------------------------------------------------------------------------

# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build wheels
RUN pip install --no-cache-dir build \
    && python -m build --wheel --outdir /wheels

# ------------------------------------------------------------------------------
# Stage 2: Minimal Runtime
FROM python:3.12-slim AS runtime

# Install OpenSSH client (required for SSH signature verification) and CA certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Security: non-root execution user
RUN groupadd -g 10001 cairn && \
    useradd -u 10001 -g cairn -m -s /bin/sh cairn

# Copy and install pre-built wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Create test workspace directory
WORKDIR /workspace
RUN chown cairn:cairn /workspace

USER cairn

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    CAIRN_STRICT=1

# Default entrypoint is cairn-test CLI
ENTRYPOINT ["cairn-test"]
CMD ["--help"]
