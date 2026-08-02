# ULTRA health check (Windows / PowerShell 5.1).
# Verifies the bot process is alive and the DB is being written to.
# Exit 0 = healthy, 1 = unhealthy. For use with uptime monitors / cron.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File deploy\healthcheck.ps1

param([int]$MaxAgeSeconds = 300)

$BotDir = Split-Path $PSScriptRoot -Parent
$PidFile = Join-Path $BotDir "data\bot.pid"
$DbPath = Join-Path $BotDir "data\ultra.db"
$ExitCode = 0

function Check([string]$Label, [bool]$Ok, [string]$Detail) {
    if ($Ok) { Write-Output "OK  $Label ($Detail)" }
    else { Write-Output "FAIL $Label ($Detail)"; $script:ExitCode = 1 }
}

# 1. PID file exists and process is running.
if (Test-Path -LiteralPath $PidFile) {
    $BotPid = (Get-Content -LiteralPath $PidFile | Select-Object -First 1).Trim()
    $Proc = Get-Process -Id $BotPid -ErrorAction SilentlyContinue
    if ($Proc) {
        Check "bot process" $true "pid=$BotPid"
    } else {
        Check "bot process" $false "pid=$BotPid not running"
    }
} else {
    Check "pid file" $false "data\bot.pid missing"
}

# 2. Database was modified recently (bot is actively persisting state).
if (Test-Path -LiteralPath $DbPath) {
    $Age = ((Get-Date) - (Get-Item -LiteralPath $DbPath).LastWriteTime).TotalSeconds
    if ($Age -le $MaxAgeSeconds) {
        Check "database writes" $true "last write $([math]::Round($Age))s ago"
    } else {
        Check "database writes" $false "stale, last write $([math]::Round($Age))s ago"
    }
} else {
    Check "database file" $false "data\ultra.db missing"
}

exit $ExitCode
