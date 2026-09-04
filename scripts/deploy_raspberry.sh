#!/bin/bash
# ==============================================================================
# OBSOLETO: el despliegue 24/7 en Raspberry Pi / Linux se ha retirado.
#
# Sharky ahora se ejecuta una vez al dia al iniciar sesion en Windows, en vez
# de como un servicio permanente. Ver:
#   * scripts/sharky_windows_startup.bat  — el script que se lanza al arrancar
#   * scripts/instalar_inicio_windows.ps1 — lo registra en el Programador de
#                                            Tareas de Windows (ejecutar una vez)
#
# Este archivo y scripts/sharky.service (la unidad systemd que generaba) ya no
# se usan y pueden borrarse.
# ==============================================================================
echo "Este script ya no se usa. Consulta scripts/instalar_inicio_windows.ps1."
exit 1
