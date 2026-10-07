param(
    [ValidateSet('Install','Restore','Check')][string]$Mode='Install',
    [switch]$TestCopy,
    [string]$TaskDirectory=$PSScriptRoot
)
$ErrorActionPreference='Stop'
$task=[IO.Path]::GetFullPath($TaskDirectory)
$root=Split-Path (Split-Path $task -Parent) -Parent
$patch=Get-Content -LiteralPath (Join-Path $task 'PATCH.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$target=Join-Path $root 'Mono\EmbedRuntime\mono.dll'
$status=Join-Path $task 'DEPLOYMENT.json'
if($TestCopy){
    $target=Join-Path $task 'deployment_test\mono.dll'
    $status=Join-Path $task 'DEPLOYMENT_TEST.json'
}
$source=Join-Path $task 'MODIFIED_FILE.dll'
$desired=$patch.modifiedSHA256
if($Mode -eq 'Restore'){
    $source=Join-Path $task 'BASELINE.dll'
    $desired=$patch.baselineSHA256
}

function Save-Status([string]$state,[string]$hash,[string]$detail){
    [ordered]@{state=$state;mode=$Mode;target=$target;testCopy=[bool]$TestCopy;
        sha256=$hash;detail=$detail;runtimeModified=$false;utc=[DateTime]::UtcNow.ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
}
function Hash-Stream([IO.Stream]$stream){
    $stream.Position=0
    $sha=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
}

$lock=$null
$stage=$null
try {
    $absolute=[IO.Path]::GetFullPath($target)
    $expected=[IO.Path]::GetFullPath((Join-Path $root 'Mono\EmbedRuntime\mono.dll'))
    if($TestCopy){$expected=[IO.Path]::GetFullPath((Join-Path $task 'deployment_test\mono.dll'))}
    if($absolute -ne $expected){throw 'Resolved target differs from bound file'}
    foreach($p in @($target,$source)){
        $item=Get-Item -LiteralPath $p
        while($item){
            if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Reparse path rejected'}
            if($item -is [IO.DirectoryInfo]){$item=$item.Parent}else{$item=$item.Directory}
        }
    }
    $hash=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if($hash -notin @($patch.baselineSHA256,$patch.modifiedSHA256)){throw 'Unexpected target hash'}
    if(!$TestCopy -and @(Get-Process -Name VaM -ErrorAction SilentlyContinue).Count){
        Save-Status 'pending-game-exit' $hash 'Production unchanged'
        Write-Output 'INSTALL_PENDING gameRunning=True diskModified=False'
        exit 2
    }
    if($Mode -eq 'Check'){
        Save-Status 'ready' $hash 'Read-only check'
        Write-Output 'INSTALL_READY gameRunning=False diskModified=False'
        exit 0
    }
    if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -ne $desired){throw 'Source hash changed'}
    # Deny new readers/writers while permitting an atomic filename replacement.
    $lock=[IO.File]::Open($target,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Delete)
    if((Hash-Stream $lock) -ne $hash){throw 'Target changed before lock'}
    if(!$TestCopy -and @(Get-Process -Name VaM -ErrorAction SilentlyContinue).Count){
        Save-Status 'pending-game-exit' $hash 'Process appeared during locked check'
        Write-Output 'INSTALL_PENDING gameRunning=True diskModified=False'
        exit 2
    }
    if($hash -ne $desired){
        $stage=Join-Path (Split-Path $target -Parent) ('.mono-reclaim-'+[Guid]::NewGuid().ToString('N')+'.tmp')
        $bytes=[IO.File]::ReadAllBytes($source)
        $writer=[IO.File]::Open($stage,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try {$writer.Write($bytes,0,$bytes.Length);$writer.Flush($true)} finally {$writer.Dispose()}
        if((Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash.ToLowerInvariant() -ne $desired){throw 'Stage hash changed'}
        [IO.File]::Replace($stage,$target,[NullString]::Value)
        $stage=$null
    }
    $lock.Dispose();$lock=$null
    $after=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
    if($after -ne $desired){throw 'Reopened installed hash mismatch'}
    Save-Status 'disk-installed' $after 'Original remains in BASELINE.dll; candidate remains changed'
    if(!$TestCopy){
        & (Join-Path $root '工作区\版本管理\更新运行快照.ps1') -GameRoot $root
        Save-Status 'disk-installed-snapshot-verified' $after 'Next natural game start uses this file'
    }
    Write-Output "INSTALL_PASS mode=$Mode testCopy=$TestCopy sha256=$after runtimeModified=False"
    exit 0
} catch {
    Save-Status 'error' '' $_.Exception.Message
    Write-Output ('INSTALL_FAIL '+$_.Exception.Message)
    exit 70
} finally {
    if($lock){$lock.Dispose()}
    if($stage -and (Test-Path -LiteralPath $stage)){
        if([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($stage)) -ne [IO.Path]::GetDirectoryName($absolute)){throw 'Stage path escaped target directory'}
        Remove-Item -LiteralPath $stage
    }
}
