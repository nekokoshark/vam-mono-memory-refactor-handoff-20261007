param(
    [ValidateSet('Install','Restore','Check')][string]$Mode='Check',
    [switch]$TestCopy
)
$ErrorActionPreference='Stop'
$legacy=Join-Path (Split-Path $PSScriptRoot -Parent) 'mono_allocator_lifecycle_20261006\install.ps1'
& $legacy -Mode $Mode -TestCopy:$TestCopy -TaskDirectory $PSScriptRoot
exit $LASTEXITCODE
