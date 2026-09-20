<#
.SYNOPSIS
    Crea accesos directos "Sharky" a la app de gestion en el Escritorio y en
    el menu Inicio.

.DESCRIPTION
    El acceso directo lanza `pythonw -m sharky.app` desde la carpeta del
    proyecto (sin ventana de consola): arranca el servidor local y abre la app
    en una ventana propia de Edge. Si la app ya esta en marcha, solo abre otra
    ventana.

    No necesita permisos de administrador. Para quitarlos, borra los dos
    "Sharky.lnk" que indica la salida.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\instalar_app_windows.ps1
#>

$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
$icono = Join-Path $raiz "sharky\app\static\icono.ico"

if (-not (Test-Path $pythonw)) {
    Write-Host "[Sharky] No se encontro $pythonw" -ForegroundColor Red
    Write-Host "Crea antes el entorno virtual (ver README, seccion Instalacion)."
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$destinos = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("Programs")
)

foreach ($carpeta in $destinos) {
    $ruta = Join-Path $carpeta "Sharky.lnk"
    $acceso = $shell.CreateShortcut($ruta)
    $acceso.TargetPath = $pythonw
    $acceso.Arguments = "-m sharky.app"
    $acceso.WorkingDirectory = $raiz
    $acceso.IconLocation = "$icono,0"
    $acceso.Description = "Sharky Capital Management"
    $acceso.Save()
    Write-Host "[Sharky] Acceso directo creado: $ruta" -ForegroundColor Green
}

Write-Host ""
Write-Host "Abre 'Sharky' desde el Escritorio o el menu Inicio."
Write-Host "Cerrar la ventana no detiene el servidor: usa Sistema > Apagar la app."
