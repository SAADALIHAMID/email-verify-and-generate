Param(
    [string]$VenvPath = ".\.venv"
)

function Resolve-Python {
    param($venv)
    $python = "python"
    if (Test-Path "$venv\Scripts\python.exe") {
        $python = Join-Path $venv "Scripts\python.exe"
    }
    return $python
}

$python = Resolve-Python -venv $VenvPath
Write-Output "Using python: $python"

& $python -m pip list
if ($LASTEXITCODE -ne 0) {
    Write-Error "`pip list` failed (exit code $LASTEXITCODE)"
    exit $LASTEXITCODE
}

$code = 'import fastapi, uvicorn, pydantic; print("imports OK")'
& $python -c $code
if ($LASTEXITCODE -ne 0) {
    Write-Error "Import check failed (exit code $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Output "Environment checks completed successfully."
