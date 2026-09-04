@echo off
REM ==============================================================================
REM Ciclo diario de Sharky al iniciar sesion en Windows.
REM
REM Pensado para dispararse desde el Programador de Tareas (ver
REM instalar_inicio_windows.ps1) cada vez que enciendes el ordenador y entras
REM en tu cuenta. Es seguro que se dispare varias veces el mismo dia: el
REM comando `sharky.cli startup` comprueba si el ciclo de hoy ya se ejecuto y,
REM si es asi, no vuelve a llamar a la API de Claude.
REM ==============================================================================

setlocal
cd /d "%~dp0\.."

REM Pequeno margen para que la red este lista tras iniciar sesion: sin ella,
REM Sharky sigue funcionando (cotizaciones de referencia, marcadas como tal),
REM pero es mejor evitarlo cuando hay conexion de verdad disponible.
timeout /t 20 /nobreak >nul

if not exist ".venv\Scripts\activate.bat" (
    echo [Sharky] No se encontro el entorno virtual .venv en %cd%.
    echo Ejecuta antes, una sola vez:
    echo    python -m venv .venv
    echo    .venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo    pip install -e .
    exit /b 1
)

call .venv\Scripts\activate.bat

if not exist "logs" mkdir "logs"
python -m sharky.cli startup >> "logs\sharky_startup.log" 2>&1

REM Backup local del vault tras el ciclo, independientemente de si el ciclo
REM en si ha ido bien: las ediciones manuales del dia (operaciones
REM registradas, notas) tambien merecen quedar respaldadas. Ver
REM scripts\backup_vault.ps1 -- retiene las ultimas 14 copias.
powershell -ExecutionPolicy Bypass -File "%~dp0backup_vault.ps1" >> "logs\sharky_startup.log" 2>&1

endlocal
