# 双平台发布（方案 A）：GitHub 推 main，Gitee 用本地 gitee 分支重建树后推 gitee:main
#
# 用法（仓库根执行）：
#   powershell -ExecutionPolicy Bypass -File 工具\发布\发布.ps1 -Platform gitee -Tag
#   powershell -ExecutionPolicy Bypass -File 工具\发布\发布.ps1 -Platform both -Tag
#   powershell -ExecutionPolicy Bypass -File 工具\发布\发布.ps1 -DryRun
#
# 机制（对应 规范/仓库通用规范.md SYS-DIST-005/007/010/011）：
#   1) GitHub 线：临时 worktree 从 main 起，渲染 github 版，只提交受管渲染产物，推 origin main；
#   2) Gitee 线：临时 worktree 基于本地 gitee 分支（不存在则从 gitee/main 起），
#      先 git read-tree -u --reset main 把树整体拉齐，再渲染 gitee 版，提交为快照，推 gitee:main；
#   3) 两条分支互不合并，全程禁止 force、禁止改写历史、禁止移动旧 tag；
#   4) 推送前校验：gitee 树与 main 的差异必须恰好是两个平台产物。
#
# 依赖：git、python（渲染与生成都用仓库内脚本）。

[CmdletBinding()]
param(
    [ValidateSet('github', 'gitee', 'both')][string]$Platform = 'both',
    [switch]$DryRun,
    [switch]$Tag,
    [string]$GiteeOwner = $env:GITEE_OWNER,
    [string]$Version = ''
)

$ErrorActionPreference = 'Stop'

$ManagedPaths = @(
    '地址.md',
    'apps/tvbox/api_index.json',
    'apps/tvbox/api_all.json',
    'README.md',
    'apps/tvbox/README.md',
    'apps/catmovie/README.md',
    'apps/reading/README.md'
)
# Gitee 分支与 main 的唯一允许差异
$PlatformDiffAllowed = @('apps/tvbox/api_index.json', 'apps/tvbox/api_all.json')

$Repo = ((& git rev-parse --show-toplevel) -join '').Trim()
if (-not $Repo) { throw '当前目录不在 git 仓库内' }
Set-Location $Repo

if (-not $Version) {
    $VersionFile = Join-Path $Repo 'apps/tvbox/version.json'
    $Version = (Get-Content $VersionFile -Raw | ConvertFrom-Json).version
}
if (-not $Version) { throw '无法从 apps/tvbox/version.json 读取版本号，请用 -Version 指定' }

$MainTag = "tvbox-v$Version"
$GiteeTag = "tvbox-v$Version-gitee"

function Invoke-Git {
    param([string]$WorkDir, [string[]]$GitArgs, [switch]$AllowFail)
    $ErrorActionPreference = 'Continue'
    $out = & git -C $WorkDir @GitArgs 2>&1
    $code = $LASTEXITCODE
    $text = @($out | ForEach-Object { $_.ToString() })
    if ($code -ne 0 -and -not $AllowFail) {
        throw ("git {0} 失败（exit {1}）：{2}" -f ($GitArgs -join ' '), $code, ($text -join "`n"))
    }
    return @{ Code = $code; Out = $text }
}

function Get-Text {
    param($Result)
    return (($Result.Out | Where-Object { $_ }) -join "`n").Trim()
}

function Test-Ref {
    param([string]$Ref)
    return ((Invoke-Git $Repo @('rev-parse', '--verify', '--quiet', $Ref) -AllowFail).Code -eq 0)
}

function Invoke-Render {
    param([string]$WorkDir, [string]$Name)
    $renderArgs = @('工具/发布/渲染.py', '--platform', $Name)
    if ($Name -eq 'gitee') {
        if (-not $GiteeOwner) { throw '渲染 gitee 版需要 Gitee 个性地址，请设置 $env:GITEE_OWNER 或 -GiteeOwner' }
        $renderArgs += @('--owner', $GiteeOwner)
    }
    Push-Location $WorkDir
    try {
        & python @renderArgs
        if ($LASTEXITCODE -ne 0) { throw "渲染失败（exit $LASTEXITCODE）" }
    }
    finally { Pop-Location }
}

function Publish-GitHub {
    $Stamp = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $TmpDir = Join-Path ([IO.Path]::GetTempPath()) ("SL-Release-github-$Stamp")
    Invoke-Git $Repo @('worktree', 'add', '-b', "rel-gh-$Stamp", $TmpDir, 'main') | Out-Null
    try {
        Invoke-Render $TmpDir 'github'
        Invoke-Git $TmpDir (@('add', '--') + $ManagedPaths) | Out-Null
        $staged = (Invoke-Git $TmpDir @('diff', '--cached', '--name-only')).Out | Where-Object { $_ }
        if ($staged.Count -gt 0) {
            Invoke-Git $TmpDir @('commit', '-m', "chore(双平台地址): 渲染 github 版 $Version") | Out-Null
            Write-Host ("GitHub 渲染提交：{0}" -f ($staged -join ', '))
        }
        else {
            Write-Host 'GitHub 版已是最新渲染，无需新提交'
        }
        $sha = (Get-Text (Invoke-Git $TmpDir @('rev-parse', 'HEAD'))).Substring(0, 8)
        if ($Tag -and -not (Test-Ref "refs/tags/$MainTag")) {
            Invoke-Git $TmpDir @('tag', $MainTag) | Out-Null
            Write-Host ("已创建主 tag：{0}" -f $MainTag)
        }
        if ($DryRun) {
            Write-Host ("DryRun：将推送 {0}:main → origin（{1}）" -f $sha, $MainTag) -ForegroundColor Cyan
        }
        else {
            Invoke-Git $TmpDir @('push', 'origin', 'HEAD:main') | Out-Null
            if ($Tag -and (Test-Ref "refs/tags/$MainTag")) {
                Invoke-Git $TmpDir @('push', 'origin', "refs/tags/$MainTag") | Out-Null
            }
            Write-Host ("已推送 {0}:main → origin（{1}）" -f $sha, $MainTag) -ForegroundColor Green
        }
        return [pscustomobject]@{ 平台 = 'github'; 分支 = 'main'; 提交 = $sha; tag = $MainTag }
    }
    finally {
        Invoke-Git $Repo @('worktree', 'remove', '--force', $TmpDir) -AllowFail | Out-Null
        Invoke-Git $Repo @('branch', '-D', "rel-gh-$Stamp") -AllowFail | Out-Null
    }
}

function Publish-Gitee {
    if (-not $GiteeOwner) {
        Write-Host '缺少 Gitee 个性地址：渲染 raw 基址需要它。' -ForegroundColor Yellow
        Write-Host '  $env:GITEE_OWNER = "<个性地址>"; powershell -File 工具\发布\发布.ps1 -Platform gitee'
        exit 2
    }
    $want = "git@gitee.com:$GiteeOwner/SL-Sources.git"
    $cur = Invoke-Git $Repo @('remote', 'get-url', 'gitee') -AllowFail
    if ($cur.Code -ne 0) {
        Invoke-Git $Repo @('remote', 'add', 'gitee', $want) | Out-Null
    }
    elseif ((Get-Text $cur) -ne $want) {
        Invoke-Git $Repo @('remote', 'set-url', 'gitee', $want) | Out-Null
    }

    # 只取分支不取 tag，避免两平台同名 tag 冲突（SYS-DIST-011）
    $fetch = Invoke-Git $Repo @('fetch', 'gitee', '--no-tags', '--prune') -AllowFail
    if ($fetch.Code -ne 0) {
        Write-Host ("提示：拉取 gitee 失败（首次推送或仓库未创建时正常）：{0}" -f (Get-Text $fetch)) -ForegroundColor Yellow
    }

    $Stamp = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $TmpDir = Join-Path ([IO.Path]::GetTempPath()) ("SL-Release-gitee-$Stamp")
    $baseRef = $null
    if (Test-Ref 'refs/heads/gitee') { $baseRef = 'gitee'; $newBranch = $false }
    elseif (Test-Ref 'refs/remotes/gitee/main') { $baseRef = 'refs/remotes/gitee/main'; $newBranch = $true }
    else { $baseRef = 'main'; $newBranch = $true }

    if ($newBranch) {
        Invoke-Git $Repo @('worktree', 'add', '-b', 'gitee', $TmpDir, $baseRef) | Out-Null
    }
    else {
        Invoke-Git $Repo @('worktree', 'add', $TmpDir, 'gitee') | Out-Null
    }
    try {
        # 整树拉齐到 main：不是 merge，结构上不会产生冲突（SYS-DIST-010）
        Invoke-Git $TmpDir @('read-tree', '-u', '--reset', 'main') | Out-Null
        Invoke-Render $TmpDir 'gitee'

        Invoke-Git $TmpDir @('add', '-A') | Out-Null
        $diff = (Invoke-Git $TmpDir @('diff', '--name-only', 'main')).Out | Where-Object { $_ } | Sort-Object
        $unexpected = @($diff | Where-Object { $_ -notin $PlatformDiffAllowed })
        if ($unexpected.Count -gt 0) {
            throw ("Gitee 树与 main 的差异超出许可范围，请先跑 GitHub 线渲染：{0}" -f ($unexpected -join ', '))
        }
        Write-Host ("Gitee 与 main 差异（应为两个平台产物）：{0}" -f ($diff -join ', '))

        $staged = (Invoke-Git $TmpDir @('diff', '--cached', '--name-only')).Out | Where-Object { $_ }
        if ($staged.Count -gt 0) {
            Invoke-Git $TmpDir @('commit', '-m', "release(gitee): $Version") | Out-Null
        }
        else {
            Write-Host 'Gitee 快照已是最新，无需新提交'
        }
        $sha = (Get-Text (Invoke-Git $TmpDir @('rev-parse', 'HEAD'))).Substring(0, 8)

        if ($Tag -and -not (Test-Ref "refs/tags/$GiteeTag")) {
            Invoke-Git $TmpDir @('tag', $GiteeTag) | Out-Null
            Write-Host ("已创建平台 tag：{0}" -f $GiteeTag)
        }
        if ($DryRun) {
            Write-Host ("DryRun：将推送 {0}:main → gitee（{1}）" -f $sha, $GiteeTag) -ForegroundColor Cyan
        }
        else {
            Invoke-Git $TmpDir @('push', 'gitee', 'HEAD:main') | Out-Null
            if ($Tag -and (Test-Ref "refs/tags/$GiteeTag")) {
                Invoke-Git $TmpDir @('push', 'gitee', "refs/tags/$GiteeTag") | Out-Null
            }
            Write-Host ("已推送 {0}:main → gitee（{1}）" -f $sha, $GiteeTag) -ForegroundColor Green
        }
        return [pscustomobject]@{ 平台 = 'gitee'; 分支 = 'gitee→main'; 提交 = $sha; tag = $GiteeTag }
    }
    finally {
        Invoke-Git $Repo @('worktree', 'remove', '--force', $TmpDir) -AllowFail | Out-Null
        # 保留本地 gitee 分支（下次发布要继续在其上快照）
    }
}

Write-Host ("仓库：{0}" -f $Repo)
Write-Host ("版本：{0}　DryRun：{1}　Tag：{2}" -f $Version, [bool]$DryRun, [bool]$Tag)

$Summary = @()
if ($Platform -in @('github', 'both')) { $Summary += Publish-GitHub }
if ($Platform -in @('gitee', 'both')) { $Summary += Publish-Gitee }

Write-Host ''
Write-Host '==== 汇总 ===='
$Summary | Format-Table -AutoSize | Out-String | Write-Host
if ($DryRun) { Write-Host 'DryRun 未推送任何内容。' -ForegroundColor Yellow }
