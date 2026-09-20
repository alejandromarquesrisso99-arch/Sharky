<#
.SYNOPSIS
    Muestra un aviso emergente si alguna posición ha cruzado su stop-loss o
    su take-profit en el ciclo de hoy.

.DESCRIPTION
    Lee logs\alertas_niveles.json, que el ciclo diario acaba de escribir (ver
    `sharky.level_watch.guardar`). No vuelve a valorar la cartera ni a
    consultar el mercado: enseña exactamente los mismos números que el diario
    de Obsidian, y por eso nunca puede contradecirlo.

    Sale con código 0 siempre: que no haya niveles cruzados es el caso normal,
    no un fallo -- a diferencia del heartbeat, donde un código distinto de cero
    sí significa que algo va mal.

    Se dispara desde scripts\sharky_windows_startup.bat, al final del arranque:
    el MessageBox bloquea hasta que lo cierras, así que va después del backup
    del vault para no retrasarlo.

.USO
    powershell -ExecutionPolicy Bypass -File .\scripts\avisar_niveles_windows.ps1
#>

$ErrorActionPreference = "Stop"

$raiz = Join-Path $PSScriptRoot ".."
$avisos = Join-Path $raiz "logs\alertas_niveles.json"

if (-not (Test-Path $avisos)) {
    Write-Output "[Sharky] Sin fichero de niveles todavia ($avisos). Nada que avisar."
    exit 0
}

try {
    $datos = Get-Content -Path $avisos -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Output "[Sharky] No se pudo leer $avisos : $($_.Exception.Message)"
    exit 0
}

# Un fichero de ayer significa que el ciclo de hoy no llego a escribirlo: eso
# es competencia del heartbeat (SharkyHeartbeatCheck), no de este aviso.
# Repetir aqui los stops de ayer solo entrenaria a ignorar la ventana.
$hoy = (Get-Date).ToString("yyyy-MM-dd")
if ($datos.fecha -ne $hoy) {
    Write-Output "[Sharky] El fichero de niveles es del $($datos.fecha), no de hoy. No se avisa."
    exit 0
}

$accionables = @($datos.alertas | Where-Object { $_.tipo -eq "STOP_LOSS" -or $_.tipo -eq "TAKE_PROFIT" })
if ($accionables.Count -eq 0) {
    Write-Output "[Sharky] Ningun nivel alcanzado hoy ($($datos.resumen))."
    exit 0
}

$stops = @($accionables | Where-Object { $_.tipo -eq "STOP_LOSS" })
$targets = @($accionables | Where-Object { $_.tipo -eq "TAKE_PROFIT" })

$lineas = New-Object System.Collections.Generic.List[string]
if ($stops.Count -gt 0) {
    $lineas.Add("SALIDA OBLIGATORIA - el mandato exige liquidar:")
    $lineas.Add("")
    foreach ($a in $stops) { $lineas.Add("* $($a.texto)"); $lineas.Add("") }
}
if ($targets.Count -gt 0) {
    $lineas.Add("OBJETIVO ALCANZADO - no obliga a vender:")
    $lineas.Add("")
    foreach ($a in $targets) { $lineas.Add("* $($a.texto)"); $lineas.Add("") }
}
$lineas.Add("Detalle completo en el vault: 00_Sistema\Estado_Vital.md")

$cuerpo = ($lineas -join [Environment]::NewLine)

$titulo = if ($stops.Count -gt 0) {
    "Sharky: $($stops.Count) STOP-LOSS alcanzado(s)"
} else {
    "Sharky: $($targets.Count) target alcanzado(s)"
}

Write-Output "[Sharky] Aviso emergente: $($datos.resumen)"

Add-Type -AssemblyName System.Windows.Forms

$icono = if ($stops.Count -gt 0) {
    [System.Windows.Forms.MessageBoxIcon]::Error
} else {
    [System.Windows.Forms.MessageBoxIcon]::Information
}

[System.Windows.Forms.MessageBox]::Show(
    $cuerpo,
    $titulo,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    $icono
) | Out-Null

exit 0
