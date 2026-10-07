$ErrorActionPreference='Stop'
$compiler='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe'
$linker='C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\link.exe'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $compiler /nologo /c /O2 /GS- /Zl /W4 /WX root_probe.c
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
    & $linker /nologo /dll /noentry /nodefaultlib /machine:x64 /out:root_probe.dll root_probe.obj
    if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
    Write-Output 'ROOT_PROBE_BUILD_PASS isolatedOnly=True'
} finally {Pop-Location}
