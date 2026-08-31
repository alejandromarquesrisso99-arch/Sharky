FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de dependencias
COPY requirements.txt setup.py pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente y la bóveda base
COPY sharky/ ./sharky/
COPY vault/ ./vault/

# Instalar el paquete en modo editable
RUN pip install -e .

# Variables de entorno por defecto
ENV PYTHONUNBUFFERED=1
ENV SHARKY_VAULT_PATH=/app/vault

# Ejecutar el servicio autónomo 24/7
CMD ["python", "-m", "sharky.cli", "service", "--interval", "60"]
