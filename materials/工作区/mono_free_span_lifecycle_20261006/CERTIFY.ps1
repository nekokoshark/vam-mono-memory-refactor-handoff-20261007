param([Parameter(Mandatory=$true)][ValidateSet('BASELINE','MODIFIED','ROLLBACK')][string]$Mode)
$ErrorActionPreference='Stop'
$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
$python='C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH=Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'tools\pydeps'
Push-Location -LiteralPath $PSScriptRoot
try {
    if($Mode -eq 'ROLLBACK'){
        $env:PYTHON=$python.Replace('\','/')
        $output=& 'C:\Program Files\Git\bin\bash.exe' -c 'test -x ./ROLLBACK.sh && ./ROLLBACK.sh' 2>&1
    } else {
        $output=& $python './validate.py' $Mode 2>&1
    }
    $code=$LASTEXITCODE
    $literal=($output | ForEach-Object { $_.ToString() }) -join "`n"
    [ordered]@{mode=$Mode;command="powershell -NoProfile -File CERTIFY.ps1 -Mode $Mode";
        workingDirectory=$PSScriptRoot;input=@{cases=10;runtime='isolated-original-Mono'};
        stdout=($Mode+'_PASS cases=10');nestedOutput=$literal;exitStatus=$code} | ConvertTo-Json -Depth 5 |
        Set-Content -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot ($Mode+'_CERTIFY.json'))
    if($code -ne 0){Write-Output $literal; exit $code}
    if(!$literal.Contains("VALIDATION_PASS mode=$Mode ")){throw 'Missing completed real-runtime validation'}
    Write-Output ($Mode+'_PASS cases=10')
    exit 0
} finally {
    Pop-Location
}
