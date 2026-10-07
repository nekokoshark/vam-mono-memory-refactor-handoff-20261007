param([ValidateSet('Install','Restore','Check')][string]$Mode='Install',[switch]$TestCopy)
& (Join-Path (Split-Path $PSScriptRoot -Parent) 'mono_allocator_lifecycle_20261006\install.ps1') -Mode $Mode -TestCopy:$TestCopy -TaskDirectory $PSScriptRoot
exit $LASTEXITCODE
