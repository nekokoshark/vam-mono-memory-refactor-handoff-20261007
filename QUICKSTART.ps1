param(
    [ValidateSet('Structure','Exact','Lifecycle','Baseline','Candidate','Rollback','Roots')][string]$Mode='Structure',
    [string]$Python='python',
    [string]$RunDirectory
)
$ErrorActionPreference='Stop'
$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
if(!$RunDirectory){$RunDirectory=Join-Path $PSScriptRoot ('isolated-run-'+[guid]::NewGuid().ToString('N'))}
$source=Join-Path $PSScriptRoot 'materials'
if(!(Test-Path -LiteralPath (Join-Path $source '工作区/mono_exact_reclaim_20261007/BASELINE.dll'))){throw 'Extract the complete ZIP before executing: repository materials omit binaries.'}
if(Test-Path -LiteralPath $RunDirectory){throw 'Use a new independent directory.'}
New-Item -ItemType Directory -Path $RunDirectory | Out-Null
Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $RunDirectory -Recurse
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH=Join-Path $RunDirectory 'tools/pydeps'
$task=Join-Path $RunDirectory '工作区/mono_exact_reclaim_20261007'
Push-Location -LiteralPath $task
try {
    switch($Mode){
        'Structure' {& $Python './verify.py'}
        'Exact' {& $Python './run_case.py' 'MODIFIED' 'exact'}
        'Lifecycle' {& $Python './run_case.py' 'MODIFIED' 'lifecycle'}
        'Baseline' {& $Python './validate.py' 'BASELINE'}
        'Candidate' {& $Python './validate.py' 'MODIFIED'}
        'Rollback' {& $Python './rollback.py'}
        'Roots' {& $Python './trace_root_cases.py'}
    }
    $code=$LASTEXITCODE
    Write-Output ('INDEPENDENT_RUN='+$RunDirectory)
    exit $code
} finally {Pop-Location}
