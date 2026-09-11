param(
    [string]$PythonExe = "python"
)

$scriptPath = Join-Path $PSScriptRoot "import_data.py"
& $PythonExe $scriptPath --apply
exit $LASTEXITCODE
