# Leora 订阅分流规则

以提供的 Leora-ProxyRules.conf 为来源生成。提供 Shadowrocket 配置，以及 Clash/Mihomo、Xray 的**路由叠加层**。不含节点、密码或订阅标识，需配合已有节点或订阅使用。

## 文件与快速入口

| 文件 | 用途 |
| --- | --- |
| `Leora-ProxyRules.conf` | 原始规则，供生成器从本仓库读取 |
| `source/Leora-ProxyRules.conf` | 随本次转换附带的来源快照 |
| `Leora-Shadowrocket-Rules.conf` | Shadowrocket 远程配置，含规则及 DNS 设置 |
| `Leora-Clash-Routing.yaml` | Clash/Mihomo 路由叠加层，需配合 `providers/` |
| `Leora-Clash-DNS.yaml` | 可选的 Mihomo 客户端 DNS 叠加示例 |
| `Leora-Xray-Routing.json` | 原生 Xray 路由叠加层 |
| `merge_xray.py` | 将 Xray 路由合并进已有 JSON 订阅 |
| `build_rules.py`、`requirements.txt` | 规则生成器及 Python 依赖 |
| `conversion-report.json` | 转换来源、校验值和不支持条目记录 |
| `validation.json` | 随附版本的既有验证记录，不会随生成器自动更新 |
| `.github/workflows/build-rules.yml` | 手动或源文件更新时重新生成规则 |

### Shadowrocket

在 Shadowrocket 的「配置」页面添加下面的远程配置地址，下载后选中该配置，并使用已有节点。更新规则时重新更新远程配置：

```text
https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Shadowrocket-Rules.conf
```

这是含 `[General]`、`[Rule]`、`[Host]` 的配置，会应用其中的 DNS、IPv6 及局域网设置。校园 DNS 和 Tailscale DNS 需要相应网络可达；STUN 伪装设置可能影响 WebRTC 和 Tailscale 点对点发现。导入前可备份当前配置。

### Clash / Mihomo 路由地址

```text
https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Routing.yaml
```

### 原生 Xray 路由地址

```text
https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Xray-Routing.json
```

仓库文件位于 `main` 分支根目录，`providers/` 必须一并保留。若改仓库、分支或目录，请运行下面的生成命令修改 `--base`，否则主文件会引用错误的 providers 地址。

## Clash / Mihomo：可使用当前面板现有入口

进入 `Panel Settings → Subscription → Clash / Mihomo`：

1. 打开 `Enable routing`。
2. `Global routing rules` 填入上面的 `Leora-Clash-Routing.yaml` Raw 地址。
3. Save，按照页面提示重启面板；用户更新 Clash/Mihomo 订阅。

主 YAML 只有 `rule-providers` 与 `rules`，面板继续生成节点和已有 `PROXY` 组；兜底为 `MATCH,PROXY`。不替换节点、不写死服务器。现代 Mihomo 支持其中的 DOMAIN-REGEX 与 IP-ASN；不保证停止维护的旧版 Clash 内核支持全部规则。

共 46 个原始远程规则来源，编排为 50 个链接 provider：24 个直接使用经内容比较验证的上游文件，26 个使用本仓库转换文件。部分来源拆为“上游等价子集 + 转换差集”，相邻条目保持同一动作，不改变与其他来源的优先级。详见 `conversion-report.json`。

每个 provider 的更新间隔为 86400 秒。直接引用的上游文件由客户端更新；转换文件需要重新运行生成脚本并提交。面板自身的远程主文件缓存也可能导致改动稍后才出现。

`Leora-Clash-DNS.yaml` 是可选的**客户端 DNS 叠加示例**，不是面板 Global routing rules 的输入：当前面板只导入 groups/providers/rules，DNS 字段不会通过该入口生效。示例包含原配置的校园及 Tailscale 分流 DNS，需相应网络可达。仅使用主路由 YAML 时保留客户端原有 DNS。

## Xray JSON：不能直接填入当前面板的 routing profile 字段

`Leora-Xray-Routing.json` 是原生 Xray 的 `routing.rules` 叠加层，按原来源顺序生成了 117 个有序条件块，保留最终代理规则。链接型列表已展开；ASN 使用 RIPEstat announced-prefixes 快照转换为 CIDR，并在每次生成时刷新。

**当前面板界面的 `JSON subscription routing profile` 对应的是 Happ/INCY 分组模型，不是任意 Xray 配置。** 所查 3x-ui 实现只读取 `DirectSites/DirectIp/ProxySites/ProxyIp/BlockSites/BlockIp/RouteOrder` 等字段，不能表达原配置交错的直连、代理优先级。其远程读取实现还具有 16 KiB 响应及 8 KiB Routing 头限制。本文件约 3 MB；将其链接直接粘贴到该字段不能完成接入。

因此本仓库没有提供一个会被忽略、或重排优先级的伪兼容 Happ 文件。JSON 用户要在每次更新订阅时自动得到这些规则，需在**JSON 订阅生成后、返回给客户端前**合并原生路由；也可以扩展面板使其支持原生有序 routing JSON，并为大文件设置独立缓存与大小上限，不发送到 Routing 响应头。

附有可用的合并函数与命令行工具 `merge_xray.py`：

```bash
python merge_xray.py --input original-subscription.json --output routed-subscription.json
```

默认要求原订阅代理出口名为 `proxy`。其他情况指定：

```bash
python merge_xray.py --input original.json --output routed.json --proxy-tag actual-proxy-tag
python merge_xray.py --input original.json --output routed.json --proxy-balancer actual-balancer-tag
```

它支持单个配置或配置数组，保留节点、传输参数、DNS、balancers、顶层 observatory 等；替换原有公共流量路由，保留专门的 API 入站规则。缺少 direct/block 出口时补充 freedom/blackhole。目标代理或 balancer 不存在时明确失败，不退化为直连。**它不连接你的服务器，也没有自动安装到当前网站。** 若在服务端集成，必须对每次 JSON 响应执行同等合并并保留原订阅流量/到期响应头；只在电脑上运行一次不会改变所有用户的订阅。

不要把这些分流规则写入 `Xray Configs` 的服务器出站路由来替代客户端订阅配置，那是另一条数据路径。

## 持续维护

需要 Python 3.10+ 与 PyYAML：

```bash
python -m pip install -r requirements.txt
python build_rules.py --base https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main
```

生成器通过上面的原规则 Raw 地址读取根目录 `Leora-ProxyRules.conf`，然后读取远程列表和 ASN 前缀。修改原规则时，先提交并推送根目录文件；`source/` 中的文件仅作快照，修改它不会触发重建。脚本会校验规则类型，优先引用逐项等价的上游文件（或等价子集），仅转换无法安全复用的部分。必需来源获取失败或出现新规则类型时停止，不静默删除规则。若上游需要认证，本脚本不支持、也不会索要订阅凭证。

仓库附带 `.github/workflows/build-rules.yml`。Actions 支持手动 `Refresh Leora rules → Run workflow`，以及源 conf／生成器变更后重建。没有启用定时计划。若仓库禁止 Actions 写入，可本地运行后手动提交生成文件。它会写入本仓库的生成文件，不会修改网站。

## 转换边界

- 保留各来源的全局先后顺序、browserleaks.com/ip138.com 代理例外、tonhie.online 直连、AI/AppleNews 在普通 Apple 直连前的优先级，以及最终代理。
- 原 `skip-proxy` 与排除的本地 IPv4 网络转换为开头的本地直连规则；保留 ts.net 本地路由意图。这不会安装或启动 Tailscale。
- 原列表包含 170 条 USER-AGENT/URL-REGEX 来源条目（有重复来源）。这类按 HTTP 信息匹配的规则不能在此跨内核方案中通用等价转换，已逐条列在 `conversion-report.json`，没有误转换为域名规则。相同服务的域名/IP规则继续保留；本仓库不增加 HTTPS 解密。
- DOMAIN-SET 中 `.example.com` 转成域名后缀匹配；裸域名转成精确匹配。HOST/DOMAIN 通配符转成锚定正则，不扩大成整个父域名。
- Xray 没有相同的逐条 `no-resolve` 开关。此版使用 `IPOnDemand` 保持 IP 条件在原有位置参与匹配，但触发 DNS 的时机不能与 Shadowrocket 完全相同；保留原订阅 DNS，未声称复现原 [General]/[Host] 的全部 DNS 行为。
- Xray ASN 前缀来自公开 BGP 快照，与客户端 ASN 地理库可能存在差异；Mihomo 保留 IP-ASN，需其正常获取 ASN 数据库。
- 原配置的 STUN 应答伪装、系统路由/TUN 设置、UDP 不支持行为等客户端专有功能不属于这些路由叠加层，没有伪装成通用规则。
- 外链后续内容可变化；本次检查保证的是生成时取得的内容。原始 conf 的后续修改不会仅因用户刷新订阅自动重新转换，需先运行生成器发布结果。

## 验证与来源

已用 Xray 26.3.27 将原生路由与测试出站合并后运行 `xray run -test`；用 Mihomo 1.19.32 检查 YAML，并在本地加载所有 provider（测试时将外链替换为本次下载内容，不依赖尚未发布的 GitHub 地址）。这些是解析与加载检查，不代表真实节点连通性、DNS 泄漏或所有目标站点访问测试。

- 原规则：https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-ProxyRules.conf
- Mihomo providers：https://wiki.metacubex.one/config/rule-providers/
- Mihomo provider 内容：https://wiki.metacubex.one/config/rule-providers/content/
- Xray 路由：https://xtls.github.io/config/routing.html
- 所查面板实现：https://github.com/MHSanaei/3x-ui/blob/main/internal/sub/json_routing.go
- 所查远程缓存实现：https://github.com/MHSanaei/3x-ui/blob/main/internal/sub/remote_routing.go

`conversion-report.json` 记录每个来源、SHA-256、上游/转换链接、不可移植条目和 ASN 数据来源。第三方列表的权利及许可证归各自项目；发布转换文件时应遵守各来源授权要求。
