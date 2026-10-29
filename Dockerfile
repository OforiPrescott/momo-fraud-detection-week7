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

# API + trained model (+ its checksum) + precomputed data, results, and the ready-built dashboard
# (frontend/dist is committed; run `npm run build` in frontend/ first if you changed the UI)
COPY backend ./backend
COPY reports ./reports
COPY frontend/dist ./frontend/dist

# Run as an unprivileged user: a compromise of the app cannot modify the code or the model
RUN useradd --system --uid 10001 --no-create-home momo \
    && mkdir -p /app/var && chown momo:momo /app/var
USER momo

# user accounts live here; docker-compose mounts it so they survive rebuilds
VOLUME /app/var

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
