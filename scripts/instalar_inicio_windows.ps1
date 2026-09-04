<#
.SYNOPSIS
    Registra una tarea programada de Windows que ejecuta Sharky al iniciar
    sesion, en sustitucion del despliegue 24/7 en Raspberry Pi.

.DESCRIPTION
    Crea la tarea "SharkyStartup" con el Programador de Tareas de Windows,
    disparada "al iniciar sesion" del usuario actual, que lanza
    scripts\sharky_windows_startup.bat. Ese script activa el entorno virtual y
    ejecuta `python -m sharky.cli startup`: el ciclo diario completo (mercados,
    cartera, stop-loss, radar de oportunidades, diario en Obsidian y, el dia 1
    de cada mes, la propuesta de rebalanceo), con una sola llamada a la API de
    Claude al dia como maximo, sin importar cuantas veces enciendas el
    ordenador ese dia.

    No requiere permisos de administrador: la tarea se registra en el ambito
    del usuario actual (/rl limited).

.USO
    Ejecutar UNA VEZ desde la carpeta del proyecto:

        powershell -ExecutionPolicy Bypass -File .\scripts\instalar_inicio_windows.ps1

.DESINSTALAR
        schtasks /delete /tn SharkyStartup /f
#>

$ErrorActionPreference = "Stop"

$script = Join-Path $PSScriptRoot "sharky_windows_startup.bat"

if (-not (Test-Path $script)) {
    Write-Error "No se encuentra $script. Ejecuta este instalador desde el repositorio de Sharky (scripts\instalar_inicio_windows.ps1)."
    exit 1
}

$tarea = "SharkyStartup"

schtasks /create /tn $tarea /tr "`"$script`"" /sc onlogon /rl limited /f

# `schtasks.exe` es un ejecutable externo: si falla (p.ej. "Acceso denegado"),
# PowerShell NO lo trata como un error que detenga el script pese a
# $ErrorActionPreference = "Stop" -- ese ajuste sólo afecta a los propios
# cmdlets de PowerShell. Sin comprobar $LASTEXITCODE a mano, el script sigue
# adelante e imprime "registrada" aunque la tarea NO se haya creado.
if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks no pudo crear la tarea '$tarea' (código $LASTEXITCODE). Ver el mensaje de arriba -- 'Acceso denegado' suele significar que hace falta ejecutar PowerShell como Administrador."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Tarea '$tarea' registrada."
Write-Host "Sharky se ejecutara automaticamente cada vez que inicies sesion en Windows."
Write-Host "Log de cada ejecucion: logs\sharky_startup.log"
Write-Host ""
Write-Host "Comprobar el registro:   schtasks /query /tn $tarea"
Write-Host "Probarla ahora mismo:    schtasks /run /tn $tarea"
Write-Host "Desinstalarla:           schtasks /delete /tn $tarea /f"
