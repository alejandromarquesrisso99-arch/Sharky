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

REM Rota el log si supera ~5 MB: sin techo, un arranque diario durante meses
REM lo deja creciendo sin fin. Se conserva sólo una copia anterior.
set SHARKY_LOG_SIZE=0
if exist "logs\sharky_startup.log" for %%F in ("logs\sharky_startup.log") do set SHARKY_LOG_SIZE=%%~zF
if %SHARKY_LOG_SIZE% GTR 5242880 move /y "logs\sharky_startup.log" "logs\sharky_startup.log.old" >nul

python -m sharky.cli startup >> "logs\sharky_startup.log" 2>&1

REM Backup local del vault tras el ciclo, independientemente de si el ciclo
REM en si ha ido bien: las ediciones manuales del dia (operaciones
REM registradas, notas) tambien merecen quedar respaldadas. Ver
REM scripts\backup_vault.ps1 -- retiene las ultimas 14 copias.
powershell -ExecutionPolicy Bypass -File "%~dp0backup_vault.ps1" >> "logs\sharky_startup.log" 2>&1

REM Aviso emergente si alguna posicion ha cruzado hoy su stop-loss o su
REM take-profit. Va el ultimo a proposito: la ventana bloquea hasta que la
REM cierras, y el backup del vault no debe esperar a eso. Si no hay ningun
REM nivel cruzado -- el caso normal -- no aparece nada.
powershell -ExecutionPolicy Bypass -File "%~dp0avisar_niveles_windows.ps1" >> "logs\sharky_startup.log" 2>&1

endlocal
