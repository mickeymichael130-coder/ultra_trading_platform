# ULTRA auto-restart supervisor (Windows / PowerShell 5.1).
# Keeps the bot alive: on crash it is relaunched, with a bounded backoff.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File deploy\start.ps1 paper
#   powershell -ExecutionPolicy Bypass -File deploy\start.ps1 live

param([string]$Mode = "paper")

$BotDir = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $BotDir "venv\Scripts\python.exe"
$LogDir = Join-Path $BotDir "logs"
$SupervisorLog = Join-Path $LogDir "supervisor.log"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Write-Output $line
    Add-Content -Path $SupervisorLog -Value $line
}

Log "ULTRA supervisor starting (mode=$Mode, dir=$BotDir)"

$ConsecutiveFailures = 0
$MaxConsecutive = 10

while ($true) {
    Log "Launching bot (mode=$Mode) ..."
    & $Python (Join-Path $BotDir "main.py") --mode $Mode
    $ExitCode = $LASTEXITCODE

    if ($ExitCode -eq 0) {
        Log "Bot exited cleanly (code=0). Supervisor exiting."
        break
    }

    $ConsecutiveFailures++
    Log "Bot exited unexpectedly (code=$ExitCode). Attempt $ConsecutiveFailures."

    if ($ConsecutiveFailures -ge $MaxConsecutive) {
        Log "Too many consecutive failures. Giving up - notify an operator."
        exit 1
    }

    Start-Sleep -Seconds 5
}
