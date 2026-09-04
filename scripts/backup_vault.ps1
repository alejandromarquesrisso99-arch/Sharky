<#
.SYNOPSIS
    Copia de seguridad local del vault de Obsidian de Sharky.

.DESCRIPTION
    Comprime `vault\` en un .zip con marca de tiempo dentro de `backups\`
    (fuera del control de versiones -- ver .gitignore) y conserva sólo las
    últimas $Retener copias para no llenar el disco sin límite.

    El vault ya está versionado con git, pero un backup local aparte cubre lo
    que git no cubre: un fallo de disco antes de hacer commit, o un `git push`
    que sencillamente no se ha ejecutado todavía. `Cartera_Real.md` y
    `Estado_Vital.md` son la única fuente de verdad del NAV -- perder esa
    carpeta sin backup es perder el registro de la propia cartera.

    Pensado para dispararse automáticamente al final de cada ciclo diario
    (ver sharky_windows_startup.bat), pero se puede ejecutar suelto en
    cualquier momento.

.USO
    powershell -ExecutionPolicy Bypass -File .\scripts\backup_vault.ps1
#>

param(
    [int]$Retener = 14
)

$ErrorActionPreference = "Stop"

$raiz = Join-Path $PSScriptRoot ".."
$vault = Join-Path $raiz "vault"
$backups = Join-Path $raiz "backups"

if (-not (Test-Path $vault)) {
    Write-Error "No se encuentra la carpeta vault en $raiz."
    exit 1
}

if (-not (Test-Path $backups)) {
    New-Item -ItemType Directory -Path $backups | Out-Null
}

$marca = Get-Date -Format "yyyy-MM-dd_HHmmss"
$destino = Join-Path $backups "vault_$marca.zip"

Compress-Archive -Path (Join-Path $vault "*") -DestinationPath $destino -CompressionLevel Optimal

Write-Host "[Sharky] Backup del vault creado: $destino"

# Retención: conserva sólo los últimos $Retener backups, el resto se borra.
$existentes = Get-ChildItem -Path $backups -Filter "vault_*.zip" | Sort-Object LastWriteTime -Descending
if ($existentes.Count -gt $Retener) {
    $existentes | Select-Object -Skip $Retener | ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Host "[Sharky] Backup antiguo eliminado: $($_.Name)"
    }
}
