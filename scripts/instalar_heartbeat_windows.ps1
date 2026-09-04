<#
.SYNOPSIS
    Registra una tarea programada de Windows que comprueba a diario si el
    ciclo diario de Sharky sigue ejecutándose con normalidad.

.DESCRIPTION
    Crea la tarea "SharkyHeartbeatCheck", disparada al iniciar sesión (igual
    que SharkyStartup, pero como tarea independiente, con 2 minutos de
    margen para que el ciclo del día tenga ocasión de terminar antes). Si el
    último ciclo lleva más de 36 horas sin refrescarse -- o
    Estado_Vital.md nunca se llegó a escribir --, muestra un aviso emergente
    además de registrar el resultado en logs\sharky_heartbeat.log.

    Por qué existe: Sharky no es un servicio permanente, así que un fallo
    silencioso de SharkyStartup (entorno virtual roto, red caída, una
    excepción no capturada) no se nota en ningún sitio hasta que alguien
    abre el vault a propósito. Esta tarea es la que efectivamente avisa.

    No requiere permisos de administrador: la tarea se registra en el ámbito
    del usuario actual (/rl limited), igual que SharkyStartup.

.USO
    Ejecutar UNA VEZ desde la carpeta del proyecto, después de instalar
    SharkyStartup (scripts\instalar_inicio_windows.ps1):

        powershell -ExecutionPolicy Bypass -File .\scripts\instalar_heartbeat_windows.ps1

.DESINSTALAR
        schtasks /delete /tn SharkyHeartbeatCheck /f
#>

$ErrorActionPreference = "Stop"

$script = Join-Path $PSScriptRoot "check_heartbeat_windows.ps1"

if (-not (Test-Path $script)) {
    Write-Error "No se encuentra $script. Ejecuta este instalador desde el repositorio de Sharky (scripts\instalar_heartbeat_windows.ps1)."
    exit 1
}

$tarea = "SharkyHeartbeatCheck"
$comando = "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""

schtasks /create /tn $tarea /tr $comando /sc onlogon /rl limited /delay 0002:00 /f

# Ver el mismo comentario en instalar_inicio_windows.ps1: `schtasks.exe` es un
# ejecutable externo y su fallo no detiene el script por sí solo, así que hay
# que comprobar $LASTEXITCODE explícitamente o el script miente al decir
# "registrada" cuando en realidad no se creó nada.
if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks no pudo crear la tarea '$tarea' (código $LASTEXITCODE). Ver el mensaje de arriba -- 'Acceso denegado' suele significar que hace falta ejecutar PowerShell como Administrador."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Tarea '$tarea' registrada (se dispara 2 minutos despues de iniciar sesion)."
Write-Host "Si el ciclo diario lleva mas de 36h sin ejecutarse, veras un aviso emergente."
Write-Host "Log de cada comprobacion: logs\sharky_heartbeat.log"
Write-Host ""
Write-Host "Comprobar el registro:   schtasks /query /tn $tarea"
Write-Host "Probarla ahora mismo:    schtasks /run /tn $tarea"
Write-Host "Desinstalarla:           schtasks /delete /tn $tarea /f"
