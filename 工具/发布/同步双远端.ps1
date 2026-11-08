# 双远端同步：一条命令把本地 main 与全部 tag 渲染并推送到 GitHub 与 Gitee
#
# 用法（仓库根执行）：
#   powershell -ExecutionPolicy Bypass -File 工具\发布\同步双远端.ps1
#   powershell -ExecutionPolicy Bypass -File 工具\发布\同步双远端.ps1 -Only gitee
#   powershell -ExecutionPolicy Bypass -File 工具\发布\同步双远端.ps1 -DryRun
#
# 机制（对应 规范/仓库通用规范.md 3.5 双平台地址维护）：
#   1) 从本地 main 起一个临时 worktree，工作区里的未提交改动不参与同步，也不会被污染；
#   2) 在临时 worktree 里跑 工具/发布/渲染.py 渲染该平台版本（api_index.json、api_all.json、地址.md）；
#   3) 只提交上述三个渲染产物，推送并合并远端历史，最后删除临时 worktree；
#   4) 若远端 main 存在非「渲染」提交，脚本拒绝推送，绝不 force push、不重写历史。
#
# 依赖：git、python（渲染与生成都用仓库内脚本）。

[CmdletBinding()]
param(
    [ValidateSet('github', 'gitee', 'both')][string]$Only = 'both',
    [switch]$DryRun,
    [switch]$SkipTags,
    [string]$GiteeOwner = $env:GITEE_OWNER,
    [string]$Message = ''
)

$ErrorActionPreference = 'Stop'
$RenderedPaths = @('地址.md', 'apps/tvbox/api_index.json', 'apps/tvbox/api_all.json', 'README.md', 'apps/tvbox/README.md', 'apps/catmovie/README.md', 'apps/reading/README.md')
$RenderPrefix = 'chore(双平台地址)'
$Repo = ((& git rev-parse --show-toplevel) -join '').Trim()
if (-not $Repo) { throw '当前目录不在 git 仓库内' }
Set-Location $Repo

function Invoke-Git {
    param([string]$WorkDir, [string[]]$GitArgs, [switch]$AllowFail)
    # 局部放宽：git 往 stderr 写提示（如 No such remote）时不应触发全局 Stop
    $ErrorActionPreference = 'Continue'
    $out = & git -C $WorkDir @GitArgs 2>&1
    $code = $LASTEXITCODE
    $text = @($out | ForEach-Object { $_.ToString() })
    if ($code -ne 0 -and -not $AllowFail) {
        throw ("git {0} 失败（exit {1}）：{2}" -f ($GitArgs -join ' '), $code, ($text -join "`n"))
    }
    return @{ Code = $code; Out = $text }
}

function Resolve-Remote {
    param([string]$Platform)
    if ($Platform -eq 'github') { return 'origin' }
    return 'gitee'
}

# 选定平台
$Platforms = @()
if ($Only -eq 'both') { $Platforms = @('github', 'gitee') } else { $Platforms = @($Only) }

if ($Platforms -contains 'gitee') {
    if (-not $GiteeOwner) {
        Write-Host '缺少 Gitee 个性地址：渲染 raw 基址需要它。' -ForegroundColor Yellow
        Write-Host '  设置方法（任选其一）：'
        Write-Host '    $env:GITEE_OWNER = "<你的 Gitee 个性地址>"; powershell -File 工具\发布\同步双远端.ps1'
        Write-Host '    powershell -File 工具\发布\同步双远端.ps1 -GiteeOwner "<个性地址>"'
        Write-Host '  个性地址可在 Gitee 个人主页地址栏看到（https://gitee.com/<个性地址>）。'
        exit 2
    }
}

Write-Host ("仓库：{0}" -f $Repo)
Write-Host ("平台：{0}　DryRun：{1}" -f ($Platforms -join '、'), [bool]$DryRun)

$Summary = @()
foreach ($Platform in $Platforms) {
    $Remote = Resolve-Remote $Platform
    Write-Host ''
    Write-Host ("==== {0}（远端 {1}）====" -f $Platform, $Remote)

    # Gitee 远端统一走 SSH，不影响 origin（GitHub）的 https 配置
    if ($Platform -eq 'gitee') {
        $want = "git@gitee.com:$GiteeOwner/SL-Sources.git"
        $cur = (Invoke-Git $Repo @('remote', 'get-url', $Remote) -AllowFail)
        if ($cur.Code -ne 0) {
            Invoke-Git $Repo @('remote', 'add', $Remote, $want) | Out-Null
            Write-Host ("已添加远端 {0} → {1}" -f $Remote, $want)
        }
        elseif ((($cur.Out -join '').Trim()) -ne $want) {
            Invoke-Git $Repo @('remote', 'set-url', $Remote, $want) | Out-Null
            Write-Host ("已校正远端 {0} → {1}" -f $Remote, $want)
        }
    }

    # 拉取远端引用与 tag；远端仓库还不存在时容错继续（首次推送）
    $fetch = Invoke-Git $Repo @('fetch', $Remote, '--tags', '--prune') -AllowFail
    if ($fetch.Code -ne 0) {
        Write-Host ("提示：拉取 {0} 失败（首次推送或仓库尚未创建时属正常）：{1}" -f $Remote, (($fetch.Out -join ' ').Trim())) -ForegroundColor Yellow
    }

    $Stamp = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $TmpDir = Join-Path ([IO.Path]::GetTempPath()) ("SL-Sync-$Platform-$Stamp")
    $Branch = "sync-$Platform-$Stamp"
    $Tag = if ($Message) { $Message } else { "$RenderPrefix" + ": 渲染 $Platform 版地址" }

    Invoke-Git $Repo @('worktree', 'add', '-b', $Branch, $TmpDir, 'main') | Out-Null
    try {
        # 1) 渲染该平台版本
        $renderArgs = @('工具/发布/渲染.py', '--platform', $Platform)
        if ($Platform -eq 'gitee') { $renderArgs += @('--owner', $GiteeOwner) }
        Push-Location $TmpDir
        try {
            & python @renderArgs
            if ($LASTEXITCODE -ne 0) { throw "渲染失败（exit $LASTEXITCODE）" }
        }
        finally { Pop-Location }

        # 2) 只提交渲染产物，其他改动不进入本次提交
        Invoke-Git $TmpDir (@('add', '--') + $RenderedPaths) | Out-Null

        $staged = (Invoke-Git $TmpDir @('diff', '--cached', '--name-only')).Out
        if ($staged.Count -gt 0) {
            Invoke-Git $TmpDir (@('commit', '-m', $Tag)) | Out-Null
            Write-Host ("已提交渲染：{0}" -f (($staged | Where-Object { $_ }) -join ', '))
        }
        else {
            Write-Host '本地 main 已是最新渲染，无需新提交'
        }

        # 3) 与远端 main 的关系：仅在远端多出「渲染」提交时用 -s ours 合并（树保持本地渲染结果）
        $remoteRef = "refs/remotes/$Remote/main"
        $probe = Invoke-Git $TmpDir @('rev-parse', '--verify', $remoteRef) -AllowFail
        if ($probe.Code -eq 0) {
            $behind = [int]((Invoke-Git $TmpDir @('rev-list', '--count', "HEAD..$remoteRef")).Out -join '')
            if ($behind -gt 0) {
                $subjects = (Invoke-Git $TmpDir @('log', '--format=%s', "HEAD..$remoteRef")).Out | Where-Object { $_ }
                $allRender = $true
                foreach ($s in $subjects) {
                    if ($s -notmatch "^$([regex]::Escape($RenderPrefix))") { $allRender = $false; break }
                }
                if (-not $allRender) {
                    throw ("远端 {0}/main 存在非渲染提交，脚本拒绝推送：{1}" -f $Remote, ($subjects -join ' / '))
                }
                Invoke-Git $TmpDir @('merge', '-s', 'ours', '-m', "$RenderPrefix 合并远端上次渲染", $remoteRef) | Out-Null
                Write-Host ("已合并远端 {0}/main 的 {1} 个渲染提交（保留本地渲染结果）" -f $Remote, $behind)
            }
        }
        else {
            Write-Host '远端 main 尚不存在：本次为首次推送'
        }

        $headSha = ((Invoke-Git $TmpDir @('rev-parse', 'HEAD')).Out -join '').Trim()

        # 4) 推送（禁止 force）
        if ($DryRun) {
            Write-Host ("DryRun：将推送 {0}:main → {1}（{2}）" -f $headSha.Substring(0, 8), $Remote, $Platform) -ForegroundColor Cyan
        }
        else {
            Invoke-Git $TmpDir @('push', $Remote, 'HEAD:main') | Out-Null
            Write-Host ("已推送 {0}:main → {1}（{2}）" -f $headSha.Substring(0, 8), $Remote, $Platform) -ForegroundColor Green
            if (-not $SkipTags) {
                Invoke-Git $TmpDir @('push', $Remote, '--tags') | Out-Null
                $tagCount = ((Invoke-Git $TmpDir @('tag', '--list')).Out | Where-Object { $_ }).Count
                Write-Host ("已推送 {0} 个 tag → {1}" -f $tagCount, $Remote)
            }
        }
        $Summary += [pscustomobject]@{ 平台 = $Platform; 远端 = $Remote; 提交 = $headSha.Substring(0, 8); 已推送 = (-not $DryRun) }
    }
    finally {
        Invoke-Git $Repo @('worktree', 'remove', '--force', $TmpDir) -AllowFail | Out-Null
        Invoke-Git $Repo @('branch', '-D', $Branch) -AllowFail | Out-Null
    }
}

Write-Host ''
Write-Host '==== 汇总 ===='
$Summary | Format-Table -AutoSize | Out-String | Write-Host
$dirty = ((Invoke-Git $Repo @('status', '--short')).Out | Where-Object { $_ }).Count
Write-Host ("本地工作区未提交改动 {0} 项，未受同步影响（渲染只在临时 worktree 内发生）" -f $dirty)
if ($DryRun) { Write-Host 'DryRun 未推送任何内容。' -ForegroundColor Yellow }
