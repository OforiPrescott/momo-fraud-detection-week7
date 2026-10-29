FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MOMO_DB_PATH=/app/var/momo.db

# XGBoost needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# API + trained model + precomputed data, results, and the ready-built dashboard (frontend/dist is committed;
# rebuild it with `npm run build` in frontend/ before building the image if you changed the UI)
COPY backend ./backend
COPY reports ./reports
COPY frontend/dist ./frontend/dist

# user accounts live here; docker-compose mounts it so they survive rebuilds
VOLUME /app/var

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
