FROM python:3.11-alpine

# Install uv from official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Copy dependency specifications for cached layer installation
COPY pyproject.toml uv.lock ./

# Install dependencies into virtualenv (/app/.venv) using uv.lock
RUN uv sync --frozen --no-install-project --no-dev

# Copy application files
COPY . .

# Install the project itself into the virtual environment
RUN uv sync --frozen --no-dev

# Ensure directories exist and have proper permissions
RUN mkdir -p /app/syncs /app/output && chmod -R 777 /app

# Default command runs the psql-cron script
CMD ["psql-cron"]
