<#
.SYNOPSIS
    Comprueba el heartbeat del ciclo diario de Sharky y avisa si está obsoleto.

.DESCRIPTION
    Envoltorio de scripts\check_heartbeat.py pensado para el Programador de
    Tareas de Windows (ver instalar_heartbeat_windows.ps1). Si el último
    ciclo diario está obsoleto, muestra un aviso visible (ventana emergente)
    además de registrarlo en logs\sharky_heartbeat.log -- un aviso que sólo
    queda en un log que nadie lee no cumple el propósito de un heartbeat.

.USO
    powershell -ExecutionPolicy Bypass -File .\scripts\check_heartbeat_windows.ps1
#>

$ErrorActionPreference = "Stop"

$raiz = Join-Path $PSScriptRoot ".."
$python = Join-Path $raiz ".venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "check_heartbeat.py"
$logs = Join-Path $raiz "logs"

if (-not (Test-Path $logs)) {
    New-Item -ItemType Directory -Path $logs | Out-Null
}

if (-not (Test-Path $python)) {
    Write-Error "No se encuentra $python. Instala Sharky primero (ver README, sección 6)."
    exit 1
}

$salida = (& $python $script 2>&1 | Out-String).Trim()
$codigo = $LASTEXITCODE

$marca = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path (Join-Path $logs "sharky_heartbeat.log") -Value "[$marca] $salida"

if ($codigo -ne 0) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $salida,
        "Sharky: el ciclo diario no se está ejecutando con normalidad",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Warning
    ) | Out-Null
}

exit $codigo
