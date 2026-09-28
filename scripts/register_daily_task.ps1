<#
.SYNOPSIS
    Registra en el Programador de tareas de Windows la corrida diaria de BeautyMatch
    (python -m src.daily_run): scrapers, carga, embeddings y matching.

.DESCRIPTION
    Correrlo una vez, desde la raíz del proyecto, en PowerShell (no requiere administrador):

        powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1
        powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1 -Time 21:30 -WakeToRun

    La tarea:
    - corre todos los días a la hora indicada, con pythonw.exe (sin ventana);
    - si el computador estaba apagado o suspendido a esa hora, corre apenas se pueda;
    - no arranca una segunda corrida si la anterior sigue en curso;
    - corre también con batería, y se corta si pasa 2 horas;
    - solo corre con tu sesión iniciada (puede estar bloqueada): Docker Desktop
      necesita una sesión de usuario.

    Revisar resultados:  python -m src.daily_run --status
    Log de cada corrida: artifacts\runs\run_<fecha>.log
    Correrla ahora:      Start-ScheduledTask -TaskName "BeautyMatch - corrida diaria"
    Quitarla:            Unregister-ScheduledTask -TaskName "BeautyMatch - corrida diaria"

.PARAMETER Time
    Hora diaria, formato HH:mm (por defecto 09:00).

.PARAMETER WakeToRun
    Despertar el equipo si está suspendido a esa hora (requiere que Windows
    permita los temporizadores de activación en el plan de energía).
#>
param(
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Time = "09:00",
    [string]$TaskName = "BeautyMatch - corrida diaria",
    [switch]$WakeToRun
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $project ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    throw "No existe $pythonw. Crea el entorno virtual e instala las dependencias primero (docs/api.md)."
}
if (-not (Test-Path (Join-Path $project "src\daily_run.py"))) {
    throw "No se encontro src\daily_run.py bajo $project."
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m src.daily_run" -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -WakeToRun:$WakeToRun
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Force `
    -Description "BeautyMatch CL: scraping diario de precios (python -m src.daily_run). Log en artifacts\runs." | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
Write-Host "Tarea registrada: $TaskName"
Write-Host "  Corre todos los dias a las $Time (siguiente: $(($task | Get-ScheduledTaskInfo).NextRunTime))"
Write-Host "  Programa: $pythonw -m src.daily_run"
Write-Host "  Carpeta:  $project"
Write-Host ""
Write-Host "Antes de la primera corrida, dejar automatico:"
Write-Host "  1. Docker Desktop > Settings > General > 'Start Docker Desktop when you sign in'"
Write-Host "  2. docker update --restart unless-stopped bm-pg"
