FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg / pgvector + Postgres client for wait-for-db.sh
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY . .

# Make logs folder
RUN mkdir -p logs

# Make scripts executable
RUN chmod +x /app/wait-for-db.sh /app/entrypoint.sh

EXPOSE 8000

# Use entrypoint script to handle cleanup and setup
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command (can be overridden)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]