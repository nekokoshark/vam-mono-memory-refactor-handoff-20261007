param([ValidateSet('BASELINE','MODIFIED','ROLLBACK')][string]$Mode)
$ErrorActionPreference='Stop'
$env:PYTHONPATH='F:\vam1.22.0.12\tools\pydeps'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHON_BIN='C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Push-Location -LiteralPath $PSScriptRoot
try {
    if($Mode -eq 'ROLLBACK'){
        & $env:PYTHON_BIN rollback.py
        if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
    }
    & $env:PYTHON_BIN validate.py $Mode
    exit $LASTEXITCODE
} finally {Pop-Location}
