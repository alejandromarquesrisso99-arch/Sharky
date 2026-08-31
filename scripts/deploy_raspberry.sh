#!/bin/bash
# ==============================================================================
# Script de Instalación Automatizada de Sharky 24/7 para Raspberry Pi / Linux
# ==============================================================================

set -e

echo "🦈 [Sharky Installer] Iniciando instalación en Raspberry Pi / Servidor..."

# 1. Actualizar paquetes del sistema
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv git

# 2. Crear entorno virtual
if [ ! -d ".venv" ]; then
    echo "📦 Creando entorno virtual .venv..."
    python3 -m venv .venv
fi

# 3. Activar e instalar dependencias
echo "📥 Instalando dependencias de Python..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

# 4. Crear archivo .env si no existe
if [ ! -f ".env" ]; then
    echo "⚙️ Creando archivo .env desde plantilla..."
    cp .env.example .env
fi

# 5. Configurar servicio systemd
echo "🚀 Configurando servicio systemd para arranque automático..."
USER_NAME=$(whoami)
CURRENT_DIR=$(pwd)

sed -i "s|User=pi|User=$USER_NAME|g" scripts/sharky.service
sed -i "s|/home/pi/Sharky|$CURRENT_DIR|g" scripts/sharky.service

sudo cp scripts/sharky.service /etc/systemd/system/sharky.service
sudo systemctl daemon-reload
sudo systemctl enable sharky.service
sudo systemctl restart sharky.service

echo ""
echo "✅ ¡SHARKY ESTÁ VIVO Y CORRIENDO 24/7!"
echo "   - Para ver el estado del servicio: sudo systemctl status sharky"
echo "   - Para ver los logs en tiempo real: journalctl -u sharky -f"
echo "   - Para detener el servicio: sudo systemctl stop sharky"
echo "=============================================================================="
