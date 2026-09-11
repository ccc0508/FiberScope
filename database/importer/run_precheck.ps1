param(
    [string]$PythonExe = "python"
)

$scriptPath = Join-Path $PSScriptRoot "precheck_data.py"
& $PythonExe $scriptPath
exit $LASTEXITCODE
