# Multi-stage build for Flask backend

# Stage 1: Base dependencies
FROM python:3.11-slim as base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Development
FROM base as development

USER appuser

COPY --chown=appuser:appuser . .

ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]

# Stage 3: Production
FROM base as production

USER appuser

COPY --chown=appuser:appuser . .

ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

EXPOSE 5000

# Use gunicorn for production
RUN pip install --no-cache-dir gunicorn

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
