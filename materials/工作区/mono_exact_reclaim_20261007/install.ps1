param([ValidateSet('Install','Restore','Check')][string]$Mode='Install',[switch]$TestCopy)
if($Mode -eq 'Install'){
    $gate=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'RELEASE_GATE.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if(!$gate.approved){throw ('Candidate not approved: '+$gate.reason)}
}
& (Join-Path (Split-Path $PSScriptRoot -Parent) 'mono_allocator_lifecycle_20261006\install.ps1') -Mode $Mode -TestCopy:$TestCopy -TaskDirectory $PSScriptRoot
exit $LASTEXITCODE
