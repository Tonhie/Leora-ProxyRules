#requires -Version 5.1
<#
.SYNOPSIS
  给 Windows 系统代理加入 tailnet 直连旁路，并可选修复 FlClash 的 bypassDomain。

.DESCRIPTION
  本仓库生成的规则把 ts.net、100.64.0.0/10、fd7a:115c:a1e0::/48 判为 DIRECT，但浏览器是否
  先把请求交给系统代理由操作系统设置决定。Windows 上 Chrome/Edge 遵循 WinINET 的
  ProxyOverride，FlClash 等客户端会用「绕过域名」（bypassDomain）重写该值。该列表默认不含
  ts.net，于是浏览器把 https://<设备>.<尾网>.ts.net/ 发给本地代理端口；代理核心的 DIRECT 出站
  若绑定物理网卡（Mihomo tun.auto-detect-interface: true 的常见结果），发往 100.64.0.0/10 的包
  会走物理网卡而不是 Tailscale 接口，约 5 秒后 TLS 握手失败，即使目标就是本机。

  本脚本：
    1. 向 HKCU WinINET ProxyOverride 追加 *ts.net / *tailscale.com / *tailscale.io；
    2. 可选（-FlClashPrefs）在 FlClash 退出后写入 shared_preferences.json 的
       networkProps.bypassDomain，使重启后仍生效。

  修改后需要重启浏览器；FlClash 重启后会按 bypassDomain 重新写入 ProxyOverride。

.PARAMETER Check
  只读检查当前状态，不修改任何设置。

.PARAMETER Remove
  从 ProxyOverride 移除上述条目（不撤销 FlClash 配置）。

.PARAMETER FlClashPrefs
  同时写 FlClash 配置，要求 FlClash 已退出。

.EXAMPLE
  pwsh -File tools/apply_system_proxy_bypass.ps1 -Check

.EXAMPLE
  pwsh -File tools/apply_system_proxy_bypass.ps1 -FlClashPrefs
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Remove,
    [switch]$FlClashPrefs
)

$ErrorActionPreference = 'Stop'

$bypassEntries = @('*ts.net', '*tailscale.com', '*tailscale.io')
$regPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$prefsPath = Join-Path $env:APPDATA 'com.follow\clash\shared_preferences.json'

function Split-BypassList {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return @() }
    return @($Value -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
}

function Get-WinInetState {
    $item = Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue
    [pscustomobject]@{
        ProxyEnable   = $item.ProxyEnable
        ProxyServer   = $item.ProxyServer
        ProxyOverride = $item.ProxyOverride
        Bypass        = (Split-BypassList $item.ProxyOverride)
    }
}

function Get-FlClashBypass {
    if (-not (Test-Path -LiteralPath $prefsPath)) { return $null }
    $root = Get-Content -LiteralPath $prefsPath -Raw | ConvertFrom-Json
    $config = $root.'flutter.config' | ConvertFrom-Json
    return @($config.networkProps.bypassDomain)
}

function Test-EntryMissing {
    param([string[]]$Current, [string[]]$Required)
    return @($Required | Where-Object { $Current -notcontains $_ })
}

if ($Check) {
    $state = Get-WinInetState
    "ProxyEnable   : $($state.ProxyEnable)"
    "ProxyServer   : $($state.ProxyServer)"
    "ProxyOverride : $($state.ProxyOverride)"
    $missing = Test-EntryMissing -Current $state.Bypass -Required $bypassEntries
    if ($missing.Count -eq 0) {
        'tailnet 旁路    : 已存在'
    } else {
        "tailnet 旁路    : 缺失 $($missing -join ', ')"
    }
    $fl = Get-FlClashBypass
    if ($null -eq $fl) {
        'FlClash 配置    : 未找到'
    } else {
        $missingFl = Test-EntryMissing -Current $fl -Required $bypassEntries
        if ($missingFl.Count -eq 0) {
            'FlClash 旁路    : 已存在'
        } else {
            "FlClash 旁路    : 缺失 $($missingFl -join ', ')"
        }
    }
    if ((Get-Process FlClash -ErrorAction SilentlyContinue) -and $fl -and $missingFl.Count -gt 0) {
        '提示            : 修复 FlClash 配置前需先完全退出 FlClash'
    }
    exit 0
}

# --- 1. WinINET ProxyOverride ---
$state = Get-WinInetState
$list = [System.Collections.Generic.List[string]]::new()
foreach ($entry in $state.Bypass) { $list.Add($entry) }

if ($Remove) {
    foreach ($entry in $bypassEntries) { [void]$list.Remove($entry) }
} else {
    foreach ($entry in $bypassEntries) {
        if (-not $list.Contains($entry)) { $list.Add($entry) }
    }
}

$newOverride = ($list -join ';')
if ($newOverride -ne $state.ProxyOverride) {
    Set-ItemProperty -Path $regPath -Name ProxyOverride -Value $newOverride
    try {
        Add-Type -Namespace WinInet -Name Native -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("wininet.dll", SetLastError = true)]
public static extern bool InternetSetOption(System.IntPtr hInternet, int dwOption, System.IntPtr lpBuffer, int dwBufferLength);
'@
        [void][WinInet.Native]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0) # INTERNET_OPTION_SETTINGS_CHANGED
        [void][WinInet.Native]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0) # INTERNET_OPTION_REFRESH
    } catch {
        Write-Warning 'WinINET 变更通知未发送，重启浏览器后生效。'
    }
    if ($Remove) {
        "已从 ProxyOverride 移除: $($bypassEntries -join ', ')"
    } else {
        "已写入 ProxyOverride: $($bypassEntries -join ', ')"
    }
} else {
    'ProxyOverride 已包含所需条目，未修改。'
}

# --- 2. 可选：FlClash bypassDomain ---
if ($FlClashPrefs) {
    if ($Remove) {
        throw '-Remove 只撤销 WinINET 条目；撤销 FlClash 配置请在 FlClash 界面删除绕过域名。'
    }
    if (-not (Test-Path -LiteralPath $prefsPath)) {
        throw "未找到 FlClash 配置: $prefsPath（非 FlClash 用户可省略 -FlClashPrefs）"
    }
    if (Get-Process FlClash -ErrorAction SilentlyContinue) {
        throw 'FlClash 正在运行。请先在托盘完全退出 FlClash，再执行 -FlClashPrefs，否则配置会在退出时被覆盖。'
    }

    $raw = Get-Content -LiteralPath $prefsPath -Raw
    $escapedMarker = '\"bypassDomain\":['
    if (-not $raw.Contains($escapedMarker)) {
        throw '未在 FlClash 配置中找到 networkProps.bypassDomain，客户端版本可能不同；请在 FlClash 界面手动添加绕过域名。'
    }

    $missingFl = Test-EntryMissing -Current (Get-FlClashBypass) -Required $bypassEntries
    if ($missingFl.Count -eq 0) {
        'FlClash bypassDomain 已包含所需条目，未修改。'
    } else {
        $backup = Join-Path $env:TEMP ("flclash-prefs-backup-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Copy-Item -LiteralPath $prefsPath -Destination $backup
        $insert = (($missingFl | ForEach-Object { '\"' + $_ + '\"' }) -join ',') + ','
        $patched = $raw.Replace($escapedMarker, $escapedMarker + $insert)
        Set-Content -LiteralPath $prefsPath -Value $patched -NoNewline -Encoding utf8
        # 校验：能解析且条目存在
        $check = (Get-Content -LiteralPath $prefsPath -Raw | ConvertFrom-Json).'flutter.config' | ConvertFrom-Json
        $missingFl = Test-EntryMissing -Current @($check.networkProps.bypassDomain) -Required $bypassEntries
        if ($missingFl.Count -gt 0) {
            Copy-Item -LiteralPath $backup -Destination $prefsPath
            throw "FlClash 配置写入校验失败，已回滚。备份: $backup"
        }
        "已写入 FlClash bypassDomain: $($bypassEntries -join ', ')（备份: $backup）"
    }
    '启动 FlClash 后可用 -Check 复核 WinINET ProxyOverride 是否被正确重写。'
}

'完成。请重启浏览器后访问 https://<设备>.<尾网>.ts.net/（首次带 ?token=）。'
