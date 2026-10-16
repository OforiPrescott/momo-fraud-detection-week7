FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps for Node + Python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend code
COPY backend ./backend
COPY src ./src
COPY data ./data 2>/dev/null || true
COPY reports ./reports 2>/dev/null || true

# Frontend code + build
COPY frontend ./frontend
WORKDIR /app/frontend
RUN npm install && npm run build

WORKDIR /app

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
