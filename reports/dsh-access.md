# dsh.takaya-minor.ts.net 打不开：诊断报告

- 诊断时间：2026-10-29 22:2x–22:33（Asia/Shanghai）
- 主机：Leora-PC（Windows，用户 tonhi）
- 诊断方式：**全程只读**（未改动系统代理、未改注册表、未动 tailscale serve/up/down、未改 DNS）
- 结论确定性：根因已用可复现实验闭环（直连成功 / 走代理必失败 / 网卡绑定复现），非推测

---

## 0. 一句话结论

**`dsh.takaya-minor.ts.net` 这个域名本身是真实有效的（它不是假记录，也不是 Clash fake-ip）**：它是 tailnet 里的一个 **Tailscale Service VIP**（`svc:dsh` → `100.116.114.63`，由 Leora-MC 提供服务），直连可以正常打开一个 HTTP 200 的门户页。

**真正打不开的原因是：浏览器把 `*.ts.net` 流量交给了系统代理 FlClash（127.0.0.1:7890），而 FlClash 的 TUN/出站网卡自动探测把拨号绑在物理 Wi-Fi 网卡上，导致它无法通过 Tailscale 接口访问 `100.64.0.0/10` 网段 —— 表现为约 5 秒后 TLS 握手失败（浏览器侧即为「打不开」）。经代理访问 `dsh.*` 和 `leora-pc.*` 全部同样失败，直连则全部成功。**

修复方向只有一句话：**把 `*.ts.net` 从系统代理里排除（旁路直连）**，或修 FlClash 的出站网卡设置。修复命令见第 6 节（本报告未执行）。

---

## 1. 三个关键事实（先纠正两个误判）

| 疑问 | 结论 | 证据 |
|---|---|---|
| `100.116.114.63` 是自建 DNS 的静态记录？ | **不是**。它是 tailnet 里的 **Tailscale Service VIP**，由 netmap 下发 | `tailscale debug netmap` 中 `services/dsh` → `Name: "svc:dsh"`, `Ports: [tcp:443]`；同组还有 `svc:astrbot / svc:chat-plus / svc:snowluma` |
| 是 Clash fake-ip 污染？ | **不是**。fake-ip 段是 `198.18.0.0/16`；`100.116.114.63` 落在 `100.64.0.0/10`（CGNAT）里，正是 Tailscale 分配 VIP 的段 | FlClash 配置 `fake-ip-range: 198.18.0.1/16`，且 `fake-ip-filter` 明确包含 `+.ts.net`（ts.net 不做 fake-ip） |
| 是 DNS 解析错误 / 名字打错了？ | **不是**。`dsh` 与 `leora-pc` 都解析正常，且 `dsh` 是真实存在的服务名 | `tailscale ping 100.116.114.63` → `pong from leora-mc (100.64.0.3)`（VIP 被路由到 Leora-MC）；hosts 文件 MagicDNS 段与 netmap 的 `ExtraRecords` 都含 `dsh → 100.116.114.63` |

补充：`dsh.takaya-minor.ts.net` 提供的内容是 **DSH 门户页**（`Server: dsh-portal/1.0 Python/3.13.7`，标题「DeepSeek Harness · dsh」），页面里列出 Leora-MC 和 Leora-PC 两台机器最新的 DSH 访问链接。**它本身不是 DSH Web GUI 本体**；GUI 在 `leora-pc.takaya-minor.ts.net`。

---

## 2. DNS 对比表

> 说明：本机所有「直接指定 DNS 服务器」的查询（UDP 53 与 TCP 53）**全部超时/失败**，原因是 FlClash TUN 开启了 `dns-hijack: any:53` 劫持全部 53 端口流量，且系统 DNS 被改成 fake-ip DNS `198.18.0.2`。因此无法取得各服务器独立应答，只能用「Windows 解析器（hosts/MagicDNS）」+「tailscale 内部解析器」+「公网 DoH 对照」来交叉验证。

| 查询方式 | `dsh.takaya-minor.ts.net` | `leora-pc.takaya-minor.ts.net` | 结果 |
|---|---|---|---|
| Windows 解析器（`Resolve-DnsName`，含 hosts/MagicDNS） | A `100.116.114.63` | A `100.64.0.2` | 正常 |
| Windows DNS 客户端缓存（TTL≈601337s，来自 Tailscale 写入的 hosts 段） | `100.116.114.63` | `100.64.0.2` | 正常 |
| `tailscale dns query`（内部解析器） | A `100.116.114.63`（TTL 5） | A `100.64.0.2`（TTL 5） | 正常 |
| `Resolve-DnsName -NoHostsFile`（绕过 hosts，纯 DNS） | 超时 | 超时 | 被 TUN/dns-hijack 阻断 |
| `nslookup @199.247.155.53`（UDP 与 TCP 都试） | UDP 超时；TCP `Server failed` | 同左 | 自建 split DNS **当前不可用** |
| `nslookup @100.100.100.100`（UDP/TCP） | 超时 | 超时 | 直连查询被劫持，不可用 |
| `nslookup @198.18.0.2`（UDP/TCP） | 超时 | 超时 | fake-ip DNS 不直接应答裸查询 |
| `nslookup @1.1.1.1`（UDP/TCP） | 超时 | 超时 | 同上 |
| 公网 DoH（AliDNS）对照 | `Status=3`（NXDOMAIN，`ts.net` 的 SOA 在 dnsimple） | 同左 | **确认这些名字在公网不存在，仅 tailnet 内可解析**（符合预期，不是故障） |

结论：**DNS 侧没有问题**。`100.116.114.63` 是真实下发的 Service VIP，不是污染。

附带发现（非本故障原因，但建议清理）：`tailscale dns status` 里 `ts.net. -> 199.247.155.53 / 2620:111:8007::53` 这条自建 Split DNS 当前**连不通**（TCP 查询直接 `Server failed`，DoH 探测 10s 超时）。它没有影响到本机解析（MagicDNS 的 hosts/ExtraRecords 已经能给出答案），但属于隐患：把一个公共 VPS 作为 `ts.net` 的权威转发器，一旦该 VPS 异常，会拖慢甚至破坏所有 `*.ts.net` 解析，且会把 tailnet 名字外泄到该 VPS。建议在 admin console → DNS 里删除该 Split DNS 路由（详见 6.4）。

---

## 3. 直连验证（关键：直连是通的）

命令形态：`curl.exe -v -k --noproxy "*" --max-time 20 --connect-timeout 8 <url> -o NUL`

| 目标 | 结果 | HTTP 状态 | TLS/证书 | 耗时 |
|---|---|---|---|---|
| `https://dsh.takaya-minor.ts.net/` | **通** | `200 OK`，`Server: dsh-portal/1.0 Python/3.13.7`，`Content-Length: 9044` | SNI `dsh.takaya-minor.ts.net`，证书 `CN=dsh.takaya-minor.ts.net`，SAN 完全匹配，Let's Encrypt (YE2)，2026-10-27 → 2027-01-25 | 1.77s |
| `https://leora-pc.takaya-minor.ts.net/` | **通** | `401 Unauthorized`（DSH 要求 token，属正常鉴权） | `CN=leora-pc.takaya-minor.ts.net`，SAN 匹配，LE，2026-09-16 → 2026-12-15 | 0.08s |
| `https://leora-pc.takaya-minor.ts.net/?token=***`（token 取自 `%USERPROFILE%\.dsh-service\access-url.txt`） | **通** | `303 See Other`（换取 30 天 cookie 的跳转） | 同上 | — |
| `https://leora-pc.takaya-minor.ts.net/dsh-url` | **通** | `200`，返回 access-url 文本 | 同上 | — |
| 严格校验证书（不加 `-k`）对两个名字 | **通过** | `ssl_verify_result=0`（dsh 200 / leora-pc 401） | 证书链有效，无告警 | — |

TCP 层对照：`100.116.114.63:443` **OPEN**、`100.64.0.2:443` **OPEN**、`100.64.0.3:443` **OPEN**；`100.116.114.63:80` 拒绝（服务只开 443，正常）。
路由对照：`Find-NetRoute 100.116.114.63` → `InterfaceAlias=Tailscale, NextHop=0.0.0.0`（走 Tailscale 接口的 /32 主机路由），说明**操作系统层面的直连路径是通的**。

结论：**网络、TLS、证书、tailscale serve、3080 后端全部正常**。问题不在服务端，也不在名字。

---

## 4. 走代理验证（关键：走代理必失败）

系统代理现状（只读读出）：

```
ProxyEnable   : 1
ProxyServer   : 127.0.0.1:7890
ProxyOverride : *zhihu.com;*zhimg.com;*jd.com;...;localhost;*.local;127.*;10.*;
                172.16.*;...;172.2*;172.30.*;172.31.*;192.168.*;<local>
                ← 没有 *.ts.net，也没有 tailscale 相关项
WinHTTP proxy : Direct access (no proxy server)
env HTTP(S)_PROXY : 空
```

用 `curl` 分别模拟「走代理」的三种入站协议（HTTP CONNECT / SOCKS5h / SOCKS5），结果一致：

| 测试 | 结果 | 状态/错误 | 耗时 |
|---|---|---|---|
| `curl -x http://127.0.0.1:7890 https://dsh.takaya-minor.ts.net/` | **失败** | CONNECT 返回 `200 Connection established`，随后 `curl: (35) schannel: failed to receive handshake, SSL/TLS connection failed` | **5.0s** |
| `curl -x http://127.0.0.1:7890 https://leora-pc.takaya-minor.ts.net/` | **失败** | 同上 | **5.0s** |
| `curl -x socks5h://127.0.0.1:7890 https://dsh.../` | **失败** | 同上 | **5.0s** |
| `curl -x socks5://127.0.0.1:7890 https://dsh.../`（本地解析后按 IP 连） | **失败** | 同上 | **5.0s** |
| `curl -x http://127.0.0.1:7890 http://dsh.../`（明文 HTTP 80） | **失败** | `502 Bad Gateway` | **5.0s** |
| `curl -x http://127.0.0.1:7890 https://100.64.0.3/`（Leora-MC，按 IP） | **失败** | `curl: (35)` | **5.0s** |

代理本身健康对照（证明不是代理挂了）：

| 对照 | 结果 |
|---|---|
| `curl -x http://127.0.0.1:7890 https://example.com/` | **200**（0.86s） |
| `curl -x http://127.0.0.1:7890 http://127.0.0.1:3080/`（经代理回环直连） | **401**（Clash 的 DIRECT 到本机回环正常） |
| `curl -x socks5h://127.0.0.1:7890 https://example.com/` | **200** |

→ **同一个代理，访问公网正常、访问本机回环正常，唯独访问 `100.64.0.0/10`（tailnet）时 5 秒超时。** 这就是「浏览器打不开」的直接原因：浏览器收到系统代理，CONNECT 隧道建立后没有任何 TLS 数据回来，最终报网络错误。

---

## 5. 机制闭环：为什么 FlClash 到不了 tailnet

### 5.1 决定性实验：网卡绑定

用 .NET socket 做「绑定本机网卡 → 连接目标」对照，完全复现代理侧的超时现象：

| 源绑定 | 目标 | 结果 |
|---|---|---|
| 不绑定（默认路由，走 Tailscale /32 主机路由） | `100.116.114.63:443` | **OPEN** |
| 绑定到物理 Wi-Fi 地址 `100.80.61.130` | `100.116.114.63:443` | **TIMEOUT（6s）** |
| 绑定到物理 Wi-Fi 地址 `100.80.61.130` | `100.64.0.2:443` | **TIMEOUT（6s）** |
| 绑定到 Tailscale 地址 `100.64.0.2` | `100.116.114.63:443` | **OPEN** |

→ 结论明确：**只要出站被绑到物理 Wi-Fi 网卡，就必然到不了 tailnet（超时）；只有走 Tailscale 接口才能通。** 这与代理侧 5 秒超时的现象一致。

### 5.2 FlClash 侧对应配置（只读确认）

FlClash 运行配置：`%APPDATA%\com.follow\clash\config.yaml`（FlClashCore 6:36:35 启动，配置 6:36:36 生成）

```yaml
interface-name: ""                # 未显式指定出站网卡
tun:
  enable: true
  auto-route: true
  auto-detect-interface: true     # ← 自动探测物理出口网卡（Wi-Fi）
  strict-route: true
  dns-hijack: [ "any:53" ]
  route-exclude-address: [ "100.64.0.0/10", "10.0.0.0/8", ... ]
```

注意：用户其实**已经**为 ts.net 配了旁路逻辑，而且写得对：

```yaml
dns:
  enhanced-mode: "fake-ip"
  fake-ip-range: "198.18.0.1/16"
  fake-ip-filter: [ "+.ts.net", ... ]                     # ts.net 不做 fake-ip
  nameserver-policy: { "+.ts.net": "udp://100.100.100.100#DIRECT" }
rules:
  - "DOMAIN,ts.net,DIRECT"
  - "DOMAIN-REGEX,^.*\\.ts\\.net$,DIRECT"
  - "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve"
  - "DOMAIN-SUFFIX,ts.net,DIRECT"
```

也就是说：**规则层面 ts.net 确实被判定为 DIRECT，DNS 也确实走了 `100.100.100.100`；失败发生在「DIRECT 出站拨号」这一步——mihomo 的 DIRECT 出站被 `tun.auto-detect-interface: true` 绑到了物理 Wi-Fi 网卡，于是绕过了 Tailscale 的 /32 主机路由，包从校园网 Wi-Fi 发往 `100.116.x`（公网不可达）→ 5 秒超时。** 规则正确但出站网卡错误，正好解释「配置看着都对，还是打不开」。

### 5.3 为什么「换个名字也一样」

`leora-pc.takaya-minor.ts.net`（100.64.0.2）与 `dsh.*`（100.116.114.63）都在 `100.64.0.0/10`，走代理时同样 5 秒失败。所以用户感觉「所有 ts.net 都打不开」。

---

## 6. 修复方案（本报告只写命令，**未执行**）

### 6.1 首选：让 `*.ts.net` 不进系统代理（效果等价于已验证的 `--noproxy` 直连）

**方式 A（推荐，持久，不会被覆盖）：在 FlClash 里改**

FlClash → 设置 → 网络 → 系统代理 → **绕过域名（bypassDomain）** 增加：

```
*.ts.net
*.tailscale.com
```

保存/应用后，FlClash 会自己重写 Windows 的 `ProxyOverride`；然后再访问 `https://leora-pc.takaya-minor.ts.net/` 即可（Chrome/Edge 走直连 → 经 Tailscale 接口 → 正常）。

**方式 B（命令行等价物，注意 FlClash 重启/切换配置时可能覆盖）：**

```powershell
# 只读查看当前值
$cur = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings').ProxyOverride

# 追加 ts.net 旁路（需要时执行；本报告未执行）
Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' `
  -Name ProxyOverride -Value ($cur + ';*.ts.net;*.tailscale.com')

# 让 WinINET 立即生效（可选）
# 重启浏览器即可，通常无需重启系统
```

**方式 C（临时验证，不持久）**：浏览器装代理插件，把 `*.ts.net` 设为「直连」；或临时关闭 FlClash 的“系统代理”开关再访问。

### 6.2 备选：修 FlClash 的出站网卡（治本于 mihomo 侧）

在 FlClash 的「覆盖 / Patch」里把 TUN 的 `auto-detect-interface` 关掉：

```yaml
tun:
  auto-detect-interface: false
```

或者干脆在访问 tailnet 时关闭 TUN 模式。注意：关掉后若某些场景需要“指定出口网卡”可能受影响，改完需观察公网代理是否仍正常。
（如果不确定，优先用 6.1，风险最小；6.1 的效果已用 `curl --noproxy` 实测通过。）

### 6.3 访问地址（名字选对）

| 用途 | 地址 |
|---|---|
| **DSH Web GUI（本机 Leora-PC，推荐）** | `https://leora-pc.takaya-minor.ts.net/` |
| 首次访问（带 token，浏览器会换成 30 天 cookie） | `https://leora-pc.takaya-minor.ts.net/?token=<见 C:\Users\tonhi\.dsh-service\access-url.txt 或门户页>` |
| 本机自用（不经 tailscale serve） | `http://127.0.0.1:3080/?token=<同上>` |
| DSH 门户页（Leora-MC 提供，列出两台机器的链接） | `https://dsh.takaya-minor.ts.net/` |

说明：`dsh.takaya-minor.ts.net` **不是错误名字**，它是 tailnet Service `svc:dsh` 的门户；只是它本来就不是 GUI 本身。用户如果只是想打开 DSH 界面，用 `leora-pc.` 那条最直接。

### 6.4 可选清理（非本故障原因，但建议做）

1. **删除 `ts.net` 的自建 Split DNS**（admin console → DNS → Split DNS）：当前 `ts.net. -> 199.247.155.53 / 2620:111:8007::53` 不可用（TCP 查询 `Server failed`、DoH 10s 超时），且 MagicDNS 本来就能解析 `*.ts.net`。删除后解析更稳、也避免 tailnet 域名外泄到公网 VPS。
2. **不要手动编辑 hosts**：`C:\Windows\System32\drivers\etc\hosts` 里的 `# TailscaleHostsSectionStart ... End` 段由 Tailscale 自动维护（本次看到的 `100.116.114.63 dsh.takaya-minor.ts.net.` 就是它写的），手改会被覆盖。
3. token 泄露提醒：门户页会把两台机器的 `?token=` 明文展示（页面设计如此），分享截图前注意打码；`access-url.txt` 里的 token 每次 `dsh web` 重启会变。

---

## 7. 排除项清单（这些都不是原因，已验证）

| 检查项 | 状态 |
|---|---|
| `dsh` 是否为不存在/打错的节点 | ❌ 不是，`svc:dsh` VIP 真实存在，`tailscale ping` 从 Leora-MC 回 pong |
| 是否有 fake-ip 污染 | ❌ 不是，`100.116.114.63` 不在 `198.18.0.0/16`，且 `+.ts.net` 已在 fake-ip 白名单 |
| hosts 文件是否有错误静态记录 | ❌ 无，hosts 里是 Tailscale 自动写入的 MagicDNS 段，内容与 netmap 一致 |
| `tailscale serve` 是否正常 | ✅ 正常：443 监听（PID 9108），`/` → `http://127.0.0.1:3080`，`/dsh-url` → access-url.txt，`serve status --json` 结构正确 |
| DSH 3080 是否在跑 | ✅ 正常：127.0.0.1:3080 LISTEN（PID 2052），带 token 返回 303，不带 token 401 |
| 证书是否过期/SAN 不符 | ❌ 两个名字证书都有效、SAN 精确匹配、严格校验通过 |
| 系统代理未旁路 ts.net | ✅ **是原因之一（触发条件）**：`ProxyOverride` 无 `*.ts.net` |
| FlClash 出站到 CGNAT 失败 | ✅ **主因**：走代理 5s 超时，绑定 Wi-Fi 实验可复现 |
| Split DNS 是否导致 100.116.114.63 | ❌ 不是；该 DNS 当前不可用，答案来自 MagicDNS/netmap 的 ExtraRecords |
| 端口/防火墙 | ❌ 不是；443 全通，80 关闭属正常（serve 只开 443） |

---

## 8. 复现命令附录（只读）

```powershell
# 1) 看名字的真实身份（Services/VIP）
& "C:\Program Files\Tailscale\tailscale.exe" status --json      # ExtraRecords 含 dsh -> 100.116.114.63
& "C:\Program Files\Tailscale\tailscale.exe" debug netmap       # services/dsh -> svc:dsh, tcp:443
& "C:\Program Files\Tailscale\tailscale.exe" ping -c 3 100.116.114.63   # pong from leora-mc

# 2) 直连（应通）
curl.exe -v -k --noproxy "*" --max-time 20 https://dsh.takaya-minor.ts.net/ -o NUL
curl.exe -v -k --noproxy "*" --max-time 20 https://leora-pc.takaya-minor.ts.net/ -o NUL

# 3) 走代理（应失败，约 5s 后 curl 35 / 502）
curl.exe -v -k -x http://127.0.0.1:7890 --max-time 20 https://dsh.takaya-minor.ts.net/ -o NUL
curl.exe -v -k -x socks5h://127.0.0.1:7890 --max-time 20 https://leora-pc.takaya-minor.ts.net/ -o NUL

# 4) 系统代理现状
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
  Select-Object ProxyEnable,ProxyServer,ProxyOverride

# 5) 路由（直连为什么能通）
Find-NetRoute -RemoteIPAddress 100.116.114.63 | Select-Object InterfaceAlias,IPAddress,NextHop
```

---

## 9. 如果修完还不通，下一步该看什么

1. 确认浏览器确实走了直连：`curl` 测试能通但浏览器不通时，检查是否还有别的代理层（浏览器插件、Clash 的 TUN 仍劫持了 TLS 之外的流量）。
2. 确认 FlClash 没有把改动覆盖回去：改完看 `ProxyOverride` 里是否仍有 `*.ts.net`（FlClash 切换配置/重启会重写）。
3. 如果必须让 tailnet 流量**走 FlClash 的代理节点**（远程出口访问 tailnet），正常情况下是不行的：远程节点不在你的 tailnet 里，无法路由 `100.64.0.0/10`。要远程访问，应该用 Tailscale 自己的机制（同 tailnet 设备 / funnel / serve），而不是 Clash 代理。

---

## 10. 修复记录（2026-10-31，已执行）

结论与第 0 节一致：本机 Tailscale、MagicDNS、tailscaled 443、证书均正常；修复的是**系统代理绕过名单**。

已做：

1. 完全退出 FlClash 后，把 `*ts.net`、`*tailscale.com`、`*tailscale.io` 写入 `C:\Users\tonhi\AppData\Roaming\com.follow\clash\shared_preferences.json` 的 `networkProps.bypassDomain`（备份：`%TEMP%\flclash-prefs-backup-20261031.json`），再启动 FlClash。FlClash 启动后会按 `bypassDomain` 自动重写 WinINET `ProxyOverride`。
2. 脚本化入口：`pwsh -File tools/apply_system_proxy_bypass.ps1 -FlClashPrefs`（需先退出 FlClash；`-Check` 只读检查，`-Remove` 仅撤销注册表条目）。注意 FlClash 的写法是 `*ts.net`（`*` 前缀），不是 `*.ts.net`。

验证：

- `System.Net.WebRequest.GetSystemWebProxy()`：`https://leora-pc.takaya-minor.ts.net/` 与 `https://100.64.0.2/` 解析为直连，`https://www.google.com/` 仍为 `127.0.0.1:7890`。
- 真实 Chrome（headless，走系统代理）访问 `https://leora-pc.takaya-minor.ts.net/` 得到 DSH 的 `dsh web authentication required` 401 页面；修复前同一路径约 5 秒 TLS 失败。
- 直连带 token：`303 → 200`，cookie 30 天有效。
- 入口：首次 `https://leora-pc.takaya-minor.ts.net/?token=<见 access-url.txt>`，之后裸地址即可；本机等价地址 `http://127.0.0.1:3080/?token=...`。

遗留（非本次故障）：第 6.4 节的自建 `ts.net` Split DNS 仍不可用，建议在 admin console 删除。
