@echo off
REM ==============================================================================
REM Abre la app de gestion de Sharky: servidor local + ventana de aplicacion.
REM
REM Usa pythonw (sin consola). Si la app ya esta en marcha, solo abre otra
REM ventana. Para cerrar el servidor: Sistema > Apagar la app.
REM Para crear accesos directos en el Escritorio y el menu Inicio:
REM    powershell -ExecutionPolicy Bypass -File .\scripts\instalar_app_windows.ps1
REM ==============================================================================

setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\pythonw.exe" (
    echo [Sharky] No se encontro el entorno virtual .venv en %cd%.
    echo Ejecuta antes, una sola vez:
    echo    python -m venv .venv
    echo    .venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo    pip install -e .
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -m sharky.app
