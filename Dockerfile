FROM python:3.11-slim

WORKDIR /app

# tzdata es necesario: el cierre diario del scheduler se programa en hora local,
# y sin zona horaria el contenedor lo ejecutaria en UTC.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt setup.py pyproject.toml README.md ./
RUN pip install --no-cache-dir -r requirements.txt

COPY sharky/ ./sharky/
COPY vault/ ./vault/
COPY scripts/ ./scripts/

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
# Sin esto, imprimir el simbolo del euro aborta el proceso.
ENV PYTHONIOENCODING=utf-8
ENV SHARKY_VAULT_PATH=/app/vault
# Sobrescribible desde docker-compose o `docker run -e TZ=...`.
ENV TZ=Europe/Madrid

# Comprobacion de vida: la CLI debe poder valorar la cartera.
HEALTHCHECK --interval=5m --timeout=60s --start-period=30s --retries=3 \
    CMD python -m sharky.cli status > /dev/null || exit 1

CMD ["python", "-m", "sharky.cli", "service", "--interval", "60"]
