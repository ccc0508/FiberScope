param(
    [string]$PostgreSqlBin = "C:\Program Files\PostgreSQL\18\bin",
    [string]$HostName = "localhost",
    [int]$Port = 5432,
    [string]$Database = "plant_fiber_db",
    [string]$UserName = "postgres",
    [string]$OutputDirectory = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Database -ne "plant_fiber_db") {
    throw "Baseline backup only supports plant_fiber_db; current database: $Database"
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $projectRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot "..\..")
    )
    $OutputDirectory = Join-Path $projectRoot "backups"
}

$pgDump = Join-Path $PostgreSqlBin "pg_dump.exe"
$pgRestore = Join-Path $PostgreSqlBin "pg_restore.exe"
if (-not (Test-Path -LiteralPath $pgDump -PathType Leaf)) {
    throw "pg_dump.exe was not found: $pgDump"
}
if (-not (Test-Path -LiteralPath $pgRestore -PathType Leaf)) {
    throw "pg_restore.exe was not found: $pgRestore"
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$resolvedOutput = (Resolve-Path -LiteralPath $OutputDirectory).Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archivePath = Join-Path $resolvedOutput "plant_fiber_db_baseline_$timestamp.dump"
$listPath = "$archivePath.restore-list.txt"
$hashPath = "$archivePath.sha256.txt"

$dumpArguments = @(
    "--host=$HostName",
    "--port=$Port",
    "--username=$UserName",
    "--format=custom",
    "--compress=9",
    "--file=$archivePath",
    "--verbose",
    $Database
)

Write-Host "Starting baseline backup for $Database. PostgreSQL will prompt if a password is required."
& $pgDump @dumpArguments
if ($LASTEXITCODE -ne 0) {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    throw "pg_dump failed; the incomplete archive was removed"
}

$restoreList = & $pgRestore --list $archivePath
if ($LASTEXITCODE -ne 0) {
    throw "pg_restore could not read the archive directory; do not use this archive as a baseline"
}
$restoreList | Set-Content -LiteralPath $listPath -Encoding UTF8

$hash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
@(
    "file=$($hash.Path)",
    "sha256=$($hash.Hash.ToLowerInvariant())",
    "created_at=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')",
    "database=$Database",
    "host=$HostName",
    "port=$Port"
) | Set-Content -LiteralPath $hashPath -Encoding UTF8

Write-Host "Baseline backup completed."
[pscustomobject]@{
    Archive = $archivePath
    RestoreList = $listPath
    Sha256Record = $hashPath
    SizeBytes = (Get-Item -LiteralPath $archivePath).Length
    Sha256 = $hash.Hash.ToLowerInvariant()
}
