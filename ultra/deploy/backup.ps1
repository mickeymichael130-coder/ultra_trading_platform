# ULTRA daily backup (Windows / PowerShell 5.1).
# Archives the SQLite DB and logs into a dated zip, then prunes old backups.
#
# Usage (Task Scheduler, daily):
#   powershell -ExecutionPolicy Bypass -File deploy\backup.ps1

param(
    [int]$KeepDays = 14,
    [string]$BackupRoot = "backups"
)

$BotDir = Split-Path $PSScriptRoot -Parent
$DataDir = Join-Path $BotDir "data"
$LogDir = Join-Path $BotDir "logs"
$DbPath = Join-Path $DataDir "ultra.db"
if ([System.IO.Path]::IsPathRooted($BackupRoot)) {
    $BackupDir = $BackupRoot
} else {
    $BackupDir = Join-Path $BotDir $BackupRoot
}

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Archive = Join-Path $BackupDir "ultra_backup_$Stamp.zip"
$TempDir = Join-Path $BackupDir "_tmp_$Stamp"

function Log([string]$Message) {
    Write-Output "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}

if (-not (Test-Path -LiteralPath $DbPath)) {
    Log "WARNING: no database found at $DbPath. Backing up logs only."
}

# Copy the DB to a temp dir first so SQLite's WAL mode doesn't block / corrupt.
New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
if (Test-Path -LiteralPath $DbPath) {
    Copy-Item -LiteralPath $DbPath -Destination (Join-Path $TempDir "ultra.db")
    Copy-Item -LiteralPath "$DbPath-wal" -Destination $TempDir -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath "$DbPath-shm" -Destination $TempDir -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath $LogDir) {
    Copy-Item -Path (Join-Path $LogDir "*") -Destination $TempDir -Recurse -ErrorAction SilentlyContinue
}

Compress-Archive -Path (Join-Path $TempDir "*") -DestinationPath $Archive -Force
Remove-Item -LiteralPath $TempDir -Recurse -Force

Log "Backup created: $Archive"

# Prune backups older than KeepDays.
$Cutoff = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem -Path $BackupDir -Filter "ultra_backup_*.zip" | Where-Object {
    $_.LastWriteTime -lt $Cutoff
} | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Force
    Log "Pruned old backup: $($_.Name)"
}
