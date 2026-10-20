# WebRTC 防泄漏配置

Mihomo/Xray 通过“代理连接，代理不可用时失败”降低真实公网 IP 泄漏风险；Shadowrocket 使用 STUN 应答伪装。防护只作用于**已进入代理核心的流量**；需要客户端 TUN/VPN 接管 IPv4，并在客户端或系统层阻断未接管的 IPv6。仅导入路由或打开系统 HTTP 代理不足以覆盖浏览器 UDP。

## 默认策略

只有防护配置，没有普通版或模式开关。

- Shadowrocket：使用 `Leora-ProxyRules.conf`，启用 STUN 应答伪装、UDP 不支持时拒绝，并保留原有其他分流。
- Mihomo/Xray：内部 DNS 接管 → 原本地/校园/Tailscale 绕过 → 隐私防护 → Shadowrocket 完整可转换分流顺序。国内/B站/Apple 等继续按源规则直连；Steam 下载直连、商店/社区代理。
- 隐私防护：拒绝 TCP/UDP `3478`、`5349`、`19302–19309`，以及名称中独立的 `stun`/`stun数字`/`turn`/`turn数字`/`turns` 服务标签；拒绝外部 TCP/UDP `853`，避免应用绕过配置的 DNS 使用 DoT/DoQ。这些规则影响相应语音、会议、游戏及 Tailscale 公网发现，校园/尾网已识别的本地目标优先绕过。
- Mihomo 在每条 PROXY 规则后保留同条件 UDP 拒绝兜底，节点不支持 UDP 时不落入后面的 DIRECT。Xray 代理出口失败后不会重新匹配直连规则。
- **WebRTC 部署必须配合下文浏览器限制。** 端口/域名拦截无法识别任意端口或普通域名上的 STUN，也不能阻止全部 ICE 本地信息。完整保留 DIRECT 时，核心配置不能提供 Shadowrocket STUN 伪装的相同效果。不要把修改后的配置理解为“所有设备绝对不泄漏”。
- 转换边界：USER-AGENT/URL-REGEX 不可直接转换，记录在 `conversion-report.json`；Xray ASN 使用 RIPE 公告网段快照，`IPOnDemand` 无法逐条模拟 Shadowrocket `no-resolve`。隐私规则是有意加入的优先覆盖，普通分流的来源、动作和相对顺序保持同步。
- 下载区域须在 Steam 客户端选择中国大陆；规则不能控制 Steam 实际选择哪个 CDN，未知下载域名仍走代理。依据 [SteamCN](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Shadowrocket/SteamCN/SteamCN.list) 和 [Steam](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Shadowrocket/Steam/Steam.list) 列表筛选下载端点，排除商店、社区和其他宽泛的 SteamCN 直连范围。

广告规则只能拦截覆盖范围内的广告。代理规则须由支持 UDP 的节点转发 UDP，否则拒绝；直连规则保持直连。STUN 伪装可能影响 Tailscale 公网点对点发现，实际打洞仍需设备验证。客户端退出后的持续阻断需要系统或客户端 kill switch。

## Mihomo

安装 Python 3.10+，在仓库目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --input original.yaml --output protected.yaml
# 代理节点/静态策略组不叫 PROXY 时
python3 merge_mihomo.py --input original.yaml --output protected.yaml --proxy-name MY-NODE
```

将 `protected.yaml` 作为客户端配置加载，保持 **Rule/规则模式**，开启客户端 TUN 权限并确认 IPv4 被接管、未接管的 IPv6 已阻断。订阅或原配置更新后，需要重新执行合并并重新加载。

脚本保留节点及其他顶层配置，替换通用 `rules`，合并本仓库 `rule-providers`，并替换 `tun`、`dns`、`ipv6`、`mode`、`hosts`。TUN 排除列表逐项读取 Shadowrocket 的 `tun-excluded-routes`，包含其局域网和 Tailscale IPv4 网段。应用前检查客户端是否额外注入绕过列表、应用排除、`listeners` 的专用规则或指定出站；这些可能绕过通用规则。

DNS 使用 fake-IP，默认查询为指定代理上的加密 DoH，直连目标可使用阿里 DoH；`direct-nameserver-follow-policy` 确保校园/尾网访问仍使用专用 DNS。节点域名使用加密 DoH 引导，节点属于校园/尾网时也遵守专用策略。禁用系统 hosts，DNS 不回退到系统解析器；引导地址使用有有效 TLS 证书的 IP URL，避免明文 DNS 引导。**fake-IP 不是 STUN 伪装。** 为避免启动循环，节点域名的加密引导解析允许直连；这会向指定解析器暴露节点域名，但不使用 ISP 明文 DNS。校园及 Tailscale 的域名专用 DNS 自动从 Shadowrocket `[Host]` 同步，专用查询显式使用 DIRECT；这些域名排除 fake-IP，返回真实地址。

代理目标必须是实际节点或能静态核验的策略组，组内不能包含 DIRECT、PASS 等；带动态 `use`/`include-all` 或成员过滤条件的分组无法核验，会明确报错。此时请将要用的实际节点放入 `proxies`，或建立只引用这些节点的静态策略组，再用 `--proxy-name` 指定。不要把带节点凭据的 `original.yaml`、`protected.yaml` 提交到公开仓库。

主 YAML 已包含 DNS/TUN 和防护规则，不再需要额外的 DNS 或防护模板。手动合并时必须同时保留所有字段和 `providers` 引用，建议使用脚本。

## Clash Extend 脚本

Clash 的每个配置都有**扩展（Extend）**，其中“脚本”模式会用一段 JavaScript 改写整个配置。`Leora-Clash-Extend.js` 由 `build_clash.py` 从同一份 `Leora-Clash-Routing.yaml` 生成：保留订阅的节点、策略组和 `proxy-providers`，把规则、`rule-providers`、DNS、TUN、hosts、`mode`、`ipv6` 替换为 Leora 集合，追加 `leora-dns-out` DNS 出站，并自动把规则目标指向订阅里可核验的策略组；必要时新建 `Leora-Proxy` 选择组。

### 导入与绑定

1. Clash → **工具 → 进阶配置 → 脚本** → 右上角添加 → **从 URL 导入** 或 **从文件导入**：
   - URL：`https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Extend.js`
   - 文件：仓库中的 `Leora-Clash-Extend.js`
2. **配置** → 目标配置右侧菜单 → **扩展（Extend）** → 扩展模式选 **脚本** → 选中刚导入的脚本。
3. 退出扩展页后 Clash 会自动重新应用；可在配置菜单的 **预览** 中确认规则、DNS 和 `leora-dns-out` 已出现。
4. 刷新订阅不会覆盖脚本；脚本会在每次应用配置时重新执行。

### 脚本做了什么

- 规则序列与 `Leora-Clash-Routing.yaml` 逐条一致：本地/校园/Tailscale 直连、DNS 接管、STUN/DoT 拦截、广告拒绝、Steam 下载直连、完整来源顺序和每条代理规则后的 UDP 拒绝兜底；`MATCH` 和 `#PROXY` 会替换为实际目标。当规则目标能在静态节点/策略组上核验时，输出与 `merge_mihomo.py` 的结果相同；节点或 provider 订阅由脚本自建目标，`merge_mihomo` 无法校验该目标，但规则内容与兜底仍相同。
- 自动选择规则目标：优先 `PROXY`、`节点选择`、`手动选择` 等命名策略组，其次任一可静态核验到真实节点的策略组，再退到带 provider 来源（`use`/`include-all`/`include-all-proxies`）且静态成员可核验的动态组；都没有时用全部真实节点创建 `Leora-Proxy` 选择组。若订阅既没有可用真实节点、也没有非空 `proxy-providers`，脚本会直接报错而不是落入直连；只有 provider 时用它们创建 `Leora-Proxy`。
- `rule-providers` 按名称合并：订阅自有 provider 保留，Leora provider 覆盖同名项；`proxy-providers` 原样保留。Clash 会把 provider 的 `path` 重写到自己的目录，无需手工处理。
- 若订阅已有名为 `leora-dns-out` 且类型不是 `dns` 的节点，脚本会报错；若同名节点本来就是 `type: dns`，会被去重后重新追加，不报错。
- 固定残余差异：Clash 会额外写入 `tun.device: Clash`、重写 provider `path`、在订阅缺少时注入空的 `proxy-providers: {}`，并强制写入端口、`log-level`、`global-ua`、`profile.store-selected` 等应用级键；因此最终配置文本不可能与 YAML 逐字相同。

### 必须手动对齐的 Clash 应用级设置

脚本无法控制以下字段：Clash 在脚本执行后一定会覆盖或合并它们。要让最终**路由相关字段**与 `Leora-Clash-Routing.yaml` 一致，请逐项设置：

| 项目 | Clash 位置 | 目标值 | 说明 |
| --- | --- | --- | --- |
| 出站模式 | 仪表盘 | **规则** | Clash 用应用级 `mode` 覆盖脚本；该值本来就应保持规则模式 |
| IPv6 | 工具 → 常规 → 内核 | **关闭** | 覆盖脚本的 `ipv6: false`；Android 在进阶配置 → 网络 → VPN 中关闭 IPv6 |
| TUN | 仪表盘/网络设置 | **开启**，协议栈 **mixed** | `enable`/`stack` 来自应用设置；`device` 恒为 Clash，`auto-route`/`auto-detect-interface` 被强制为 true |
| 严格路由 | TUN 设置（若提供） | **开启** | 脚本里的 `strict-route: true` 会保留；不要新增 `strict-route` 覆盖项，其默认值 false 会把 true 覆盖掉 |
| 绕过私有地址 | 进阶配置 → 网络 → 虚拟网卡 | **关闭** | 默认开启会向 `route-exclude-address` 追加 `0.0.0.0/8`、`224.0.0.0/4`、`fc00::/7` 等，超出项目清单 |
| 追加系统 DNS | 工具 → 常规 → 内核 | **关闭** | 开启会在 `nameserver` 末尾加入 `system://`，破坏“无系统 DNS 回退”；不要与其他网络设置里的“自动设置系统 DNS”混淆 |
| DNS 覆盖项 | 进阶配置 → DNS | **不要添加** | 任何被选中的 DNS 覆盖键都会覆盖脚本的 DNS 节；如已存在请清空 |
| TUN 覆盖项 | 进阶配置 → 网络 → 虚拟网卡 | 只可选加 `dns-hijack` | 这是应用级设置，会影响所有配置。除为对齐 `dns-hijack` 外不要添加其他键 |
| 附加规则 | 扩展 → 标准模式 | 不适用 | 脚本模式不加载标准模式的附加规则，也无需关闭它们 |

`dns-hijack` 有一处固定差异：Clash 强制写成 `['any:53']`（仅 UDP），项目同时写 `tcp://any:53`。TCP 53 仍会被首条 `DST-PORT,53,leora-dns-out` 规则接管，因此行为一致；若要求配置文本也完全一致，可在桌面端的 **进阶配置 → 网络 → 虚拟网卡 → TUN 覆盖项** 添加 `dns-hijack`，值为 `any:53`、`tcp://any:53`。系统代理、端口、允许局域网、外部控制器等由 Clash 管理的字段不属于路由规则，保持客户端设置即可。

因此，“完全一致”指 `rules`、`rule-providers`、DNS、hosts、`mode`、`ipv6` 以及 TUN 中除 `device` 外的项目字段语义一致（订阅自带 provider 时 `rule-providers` 是并集，Leora 同名项覆盖）；Clash 必然写入的 `tun.device`、provider `path`、端口/日志/`global-ua` 等应用级键属于固定残余差异。脚本里的 `mode`、`ipv6`、`tun.enable`、`tun.stack`、`tun.dns-hijack` 只是兜底值，Clash 应用后会用上面的应用级设置覆盖；不要依赖脚本单独改变这些开关。验证时打开配置菜单的 **预览**：脚本模式下预览内容就是最终交给核心的完整配置，可直接核对规则、DNS、TUN 和代理目标。

### 更新与校验

```bash
python3 -m pip install -r requirements.txt
python3 build_clash.py            # 重新生成 Leora-Clash-Extend.js
python3 build_clash.py --check    # 生成物与当前路由不一致时失败
python3 -m unittest discover -s tests -v
```

`tests/test_clash_extend.py` 用 Node 近似 Clash 的 QuickJS `main(config)` 契约（V8 而非 QuickJS，只覆盖脚本使用的语言子集）执行脚本：静态订阅与 `merge_config` 做整字典比较，节点/provider 订阅校验完整规则序列、目标、provider 合并、幂等和报错路径。修改 `Leora-ProxyRules.conf` 或 Clash 路由后，GitHub Actions 会同时刷新 YAML 与脚本；CI 在重新生成前先运行 `build_clash.py --check`，提交了过期脚本会失败。

## Xray

在仓库目录执行；默认代理出口标签为 `proxy`：

```bash
python3 merge_xray.py --input original.json --output protected.json
python3 merge_xray.py --input original.json --output protected.json --proxy-tag MY-NODE
# 已有 balancer
python3 merge_xray.py --input original.json --output protected.json --proxy-balancer MY-POOL
```

将 `protected.json` 加载到使用 Xray 的客户端。它必须是包含 `outbounds` 的完整 Xray 对象或对象数组；不是任意厂商的 JSON 订阅格式。默认且始终应用防护，无普通模式。

脚本保留节点、传输和 balancer，替换 DNS 与公共路由。顺序为 API 专用规则、内部 DNS 出口及接管、本地绕过、隐私规则、Shadowrocket 完整分流顺序。目标出口、balancer 候选及 `fallbackTag` 不能指向 freedom 直连等非代理出口。启用防护时拒绝带自定义路由脚本的叠加层，避免脚本覆盖防护。不要把含节点凭据的输入/输出文件上传公开仓库。

**JSON 路由不会自动安装 TUN 或接管系统 UDP。** 在客户端开启 VPN/TUN，允许 UDP 转发，确认 IPv6 被接管；客户端无法接管 IPv6 时，应在系统/网络层禁用或阻断 IPv6，不能只依靠 DNS 禁止 AAAA。关闭应用绕过/绕过大陆/自动直连回退，配置代理故障时阻断连接。客户端停止后如需继续阻断，也需客户端或操作系统的 kill switch；这些不由路由 JSON 提供。

合并器会用同步 DNS 策略替换原 `dns`，并添加 `leora-dns-out` DNS 出站。已进入核心的传统 TCP/UDP 53 查询被导入内置 DNS；专用 DNS 的内部查询以 `leora-dns` 标签直连固定解析器，其他解析使用经代理的 DoH。公网 DoH 的内部查询显式强制走代理，不会被 China 等直连规则覆盖；未获准的内部 DNS 目的地拒绝，代理故障不使用直连或系统 DNS。为避免代理域名解析循环，合并器为 `servers`/`vnext` 中的公网节点域名添加精确匹配的 `https://223.5.5.5/dns-query` 加密直连引导；校园/尾网节点域名继续使用专用 DNS。这类引导查询不提供代理隐藏。`leora-dns` 和 `leora-bootstrap` 是保留的内部标签，不能用于普通流量入站。直连出口使用内置 DNS；除校园/尾网专用策略与节点引导外，Xray 普通域名查询统一通过代理 DoH，比 Shadowrocket 允许的直连 DNS 范围更窄。两端按源配置关闭 DNS AAAA；Mihomo 同时关闭顶层 IPv6，不再配置 IPv6 TUN 地址；Xray 直连解析使用 `ForceIPv4`，解析失败不退回系统解析器。DNS 不返回 AAAA 不等于阻断字面量 IPv6，Xray 没有等价的全局 IPv6 开关，外部客户端必须阻断未接管的 IPv6。Xray 26.3.27 内置 DNS 处理 A/AAAA，其他记录类型明确拒绝；Tailscale 原生 DNS 的查询应通过系统本地路由访问 Quad100，可保留其其他记录类型能力。应用自带 DoH（443 或其他端口）不会被 53 接管；将浏览器安全 DNS 关闭以使用代理 DNS，或配置为同一受控 DoH 并验证其出口。标准 853 端口的 DoT/DoQ 被阻断，其他端口不保证覆盖。

主 JSON 已包含广告拒绝、Steam 例外及防护规则，不再提供纯防护或无防护模板。

## 域名专用 DNS 与 Tailscale 同步

唯一 DNS 映射来源为 `Leora-ProxyRules.conf` 的 `[Host]`，修改后运行生成器；Mihomo/Xray 合并器也读取同一来源。域名本身及其全部子域名都适用：

| 域名 | DNS |
| --- | --- |
| `ts.net` | `100.100.100.100` |
| `tongji.edu.cn` | `202.120.190.208` |
| `tsinghua.edu.cn` | `166.111.8.28` |
| `pku.edu.cn` | `162.105.129.122` |
| `fudan.edu.cn` | `202.120.224.26` |
| `sjtu.edu.cn` | `202.120.2.100` |
| `buaa.edu.cn` | `202.112.128.51` |

Mihomo 使用 `nameserver-policy`，Xray 使用 `servers.domains`，专用 DNS 无记录/失败时不转给公共解析器。校园域名访问本地直连以使用校园网络或校园 VPN；解析器不从公网可达时，这些域名会解析失败，这是预期边界。

Tailscale 使用 `100.64.0.0/10` 和 `fd7a:115c:a1e0::/48`。三端保留本地直连；Shadowrocket 保留原 IPv4 TUN 排除，并加入 IPv6 直连规则（iOS 实际接管行为仍需客户端验证）；Mihomo 按源配置保留 IPv4 TUN 排除，并对 `ts.net` 排除 fake-IP。源配置保留的尾网 IPv6 DIRECT 规则也同步，但禁用 IPv6 时不能承诺核心内尾网 IPv6 可用，应优先使用尾网 IPv4。Xray JSON 无法修改外部客户端的 TUN 路由，需在客户端同步源配置的 `tun-excluded-routes`。不要把整个 UDP 或任意公网范围加入直连例外。

这些例外不安装、不启动 Tailscale，不添加操作系统的校园/子网路由。需要 Tailscale 本身运行、MagicDNS 正常，并使用完整的 `设备.尾网.ts.net` 名称；短主机名的搜索域由系统/Tailscale 管理。不要强制将本地 DNS/服务绑定到不支持相应路由的物理网卡。TUN 排除表示交由系统路由，不表示在没有 Tailscale 的机器上也能访问尾网。

依据：[Quad100](https://tailscale.com/docs/reference/quad100)、[Tailscale IPv6](https://tailscale.com/docs/concepts/ipv6)、[Xray DNS](https://xtls.github.io/config/dns.html)。

## 浏览器 WebRTC 限制（防泄漏部署必做）

这些模板不会自动修改本机浏览器。保留完整直连分流时，需要部署并确认相应设置生效；尚未部署的设备不能认定 WebRTC 防泄漏完成。它们只改变浏览器 WebRTC 行为，不会给游戏或 Tailscale 设置进程规则；使用本仓库核心防护时，核心对其他应用的影响仍然存在。

- **桌面 Chrome/Chromium**：将 [Chrome-policy.json](browser/Chrome-policy.json) 中的 `WebRtcIPHandling` 设置为 `disable_non_proxied_udp`，通过浏览器支持的受管策略部署。Linux Google Chrome 可将 JSON 安装到 `/etc/opt/chrome/policies/managed/`；macOS/Windows 按 [Chrome 官方管理方式](https://support.google.com/chrome/a/answer/187202)部署。模板同时设置 `DnsOverHttpsMode: off`，让 DNS 交给代理核心；必须先开启 TUN/VPN。到 `chrome://policy` 重新加载并确认两项策略有效。不要把 JSON 导入代理客户端，也不要把它当作可直接导入 macOS 的描述文件。
- Chrome 的同等扩展设置是 `chrome.privacy.network.webRTCIPHandlingPolicy.set({value: "disable_non_proxied_udp"})`；需要具有 `privacy` 权限的扩展管理，普通网页控制台无法设置。见 [官方 API](https://developer.chrome.com/docs/extensions/reference/api/privacy)。这限制非代理 UDP，仍可能使用 TCP；它不是完全禁用 WebRTC，依然需要正确的 TCP 代理/路由。仅开启 TUN 不等于浏览器识别到了 SOCKS/HTTP 代理。
- **桌面 Firefox、不需要网页通话时**：在 `about:config` 将 `media.peerconnection.enabled` 设为 `false`，重开测试页确认无法建立 PeerConnection；恢复为 `true` 可重新启用。也可将 [Firefox-user.js](browser/Firefox-user.js) 的设置追加到 `about:profiles` 所示目标配置目录的 `user.js`，再重启。模板还设置 `network.trr.mode=5`，关闭 Firefox 自行选择的 DoH，让 DNS 交给代理核心；必须先开启 TUN/VPN。恢复时需删除添加的两项设置并在 `about:config` 重置相应项，否则重启会再次禁用。不要覆盖已有 `user.js`。该项的行为见 [Mozilla 说明](https://wiki.mozilla.org/Media/WebRTC/Privacy)。

关闭摄像头/麦克风权限不等于关闭 WebRTC。禁用或限制 WebRTC 可能使会议、语音和网页点对点功能失败；需要这些功能时，保留 WebRTC 并配合完整隧道及设备测试。

## 验证

基础回归测试：

```bash
python3 -m unittest discover -s tests -v
# 准备 Mihomo、Xray 官方二进制后执行本地数据包测试
python3 tests/verify_cores.py --mihomo /absolute/path/to/mihomo --xray /absolute/path/to/xray
python3 tests/verify_dns.py --mihomo /absolute/path/to/mihomo --xray /absolute/path/to/xray
python3 tests/verify_privacy.py --mihomo /absolute/path/to/mihomo --xray /absolute/path/to/xray
python3 tests/verify_profiles.py --mihomo /absolute/path/to/mihomo --xray /absolute/path/to/xray
```

已用 Mihomo **1.19.32**、Xray **26.3.27** 验证主配置及合并结果。测试覆盖全部远程来源、动作与逐项规则顺序；广告 TCP/UDP 拒绝、代理 UDP 收发、不支持 UDP/代理不可用时不落入后续 DIRECT、普通 DIRECT 的 TCP/UDP，以及 Steam 下载 TCP/UDP 直连、商店代理。

Action 使用固定版本且校验 SHA-256 的官方核心，运行上述全部检查后才发布生成文件。DNS 测试用本地解析器替身验证七组域名的根域/子域和专用 DNS 无记录时不回退，并验证公网 TCP/UDP 53 接管、默认路由为 DIRECT 时仍走指定代理、代理断开没有直连 DNS 回退；另验证尾网域名的 TCP/UDP 直连路径。没有实测校园 DNS 或实际尾网可达性。

测试使用本地 SOCKS 代理、回环接收端和固定 DNS 映射，不连接实际 Steam 服务。Steam 下载直连通过核心路由日志确认；这不是下载测速或 CDN 地域检测。公网 DNS 路由测试将 HTTPS 临时替换为本地 DNS-over-TCP 替身，测试路由与故障路径；生成配置的 HTTPS 要求另由静态回归检查，测试不修改系统证书信任。关闭防护的配置仅在临时测试目录作为直连对照组生成，不发布。测试不启用系统 TUN，不修改本机网络；Shadowrocket 的 STUN 设置及 Steam 优先级做配置静态检查，未运行 iOS 客户端。

部署到实际设备后，打开 [BrowserLeaks WebRTC](https://browserleaks.com/webrtc)：比较 HTTP 与 WebRTC 公网地址，确认没有出现本地 ISP 的真实公网 IPv4/IPv6；再测试 Wi-Fi/移动网络切换和代理故障。mDNS 名称、局域网地址与真实公网地址属于不同暴露范围；代理不能保证浏览器不生成或向网页暴露本地 ICE 信息。若连本地信息也不希望暴露，应限制或禁用浏览器 WebRTC，这可能影响通话。

### 设备实测记录（尚待在实际客户端执行）

| 场景 | 操作与预期 | 结果 |
| --- | --- | --- |
| 广告与普通访问 | 从当前广告 provider 选一个确实命中的目标，检查日志为 REJECT/block；普通网页可访问 | 待测 |
| WebRTC/IPv6 | 双栈网络测试 HTTP 与 ICE 公网地址，不应出现 ISP 真实公网 IPv4/IPv6；局域网或 mDNS 候选另行记录 | 待测 |
| 网络切换 | 在测试中切换 Wi-Fi/移动网络或其他网络，重建 PeerConnection 后重复检查 | 待测 |
| 代理故障 | 临时选不可用节点，关闭网页旧连接后重新测试；应失败或使用另一真实代理，不能直连 | 待测 |
| 客户端退出/崩溃 | 在已有 kill switch 的前提下退出客户端；应阻断连接，不应恢复 ISP 直连 | 待测 |
| 浏览器限制 | 确认受管策略有效或 Firefox 设置生效，刷新测试页；再检查所需语音/会议功能 | 待测 |
| 校园/Tailscale | 在相应网络内查询上述域名；检查返回真实地址，并验证尾网 IPv4/IPv6、TCP/UDP 可达 | 待测 |
| 恢复 | 恢复原节点和配置，验证网络与必要的通话功能恢复正常 | 待测 |

本地核心测试不能替代这些设备测试。没有启用 kill switch 时，路由 JSON/YAML 无法承诺客户端退出后继续阻断流量。

## 依据

- [Mihomo 路由规则](https://wiki.metacubex.one/config/rules/)、[UDP 不支持时继续匹配的核心实现](https://github.com/MetaCubeX/mihomo/blob/v1.19.32/tunnel/tunnel.go#L643)
- [Mihomo TUN](https://wiki.metacubex.one/config/inbound/tun/)、[DNS 与指定代理](https://wiki.metacubex.one/config/dns/)
- [Xray 路由与可嗅探协议](https://xtls.github.io/en/config/routing.html)：没有可直接使用的 STUN 协议路由条件，不能写一个 `protocol: stun` 假装防护生效。

浏览器 DNS 策略依据：[Chromium DnsOverHttpsMode](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/DnsOverHttpsMode.yaml)、[Firefox TRR 用户设置](https://firefox-source-docs.mozilla.org/networking/dns/dns-over-https-trr.html#user-choice)。

## 基础设置同步范围

`Leora-ProxyRules.conf` 的 `[General]` 和 `[Host]` 是唯一来源。生成器和合并器检查全部 15 个 General 选项；新增选项、缺失选项或尚未支持的取值会报错，Action 不会发布悄悄忽略这些设置的配置。`conversion-report.json` 的 `general_settings` 记录每个源值及实现边界。

| 源设置 | Mihomo | Xray JSON |
| --- | --- | --- |
| `ipv6=false`、`prefer-ipv6=false` | 顶层和 DNS 均为 false，不配置 IPv6 TUN 地址 | DNS `UseIPv4`，合并后的直连出口 `ForceIPv4`；无全局 IPv6 开关 |
| 公共 DNS、备用 DNS | 两个代理 DoH | 两个经路由强制代理的 DoH；两种内核的选择/备用时序不完全相同 |
| 直连 DNS、不用系统 DNS、不回退代理 | 指定直连 DoH，无系统回退 | 无按出站选择 DNS 的同等开关；普通域名继续代理 DoH，专用域名用指定 DNS |
| `skip-proxy`、`tun-excluded-routes` | 从源值生成精确/通配域名及 IP 规则，TUN 排除同步 | 同步 DIRECT 规则；系统代理绕过和 TUN 排除由外部客户端设置 |
| `[Host]` | 静态 hosts 和域名专用 DNS | 静态 hosts 和域名专用 DNS |
| `use-local-host-item-for-proxy=false` | 禁用系统 hosts；静态 Host 没有同等的按代理开关 | 静态 Host 没有同等的按代理开关 |
| `private-ip-answer=true` | 允许专用 DNS 返回私网地址 | 允许专用 DNS 返回私网地址 |
| `bypass-system=false` | 不生成系统服务绕过；客户端额外绕过仍需关闭 | 不生成系统服务绕过；捕获范围由外部客户端控制 |
| UDP 不支持时 REJECT | 对应代理规则后加入 UDP 拒绝，防止落入 DIRECT | 代理出错不回退 DIRECT |
| STUN IPv4/IPv6 响应伪装 | 无原生等价；端口/域名拦截与浏览器限制 | 无原生等价；端口/域名拦截与浏览器限制 |

IPv6 设置不会修改操作系统网络栈，也不改写订阅中显式指定的 IPv6 节点地址。若需要整台设备禁用 IPv6，须在系统或客户端落实并实测。字段依据：[Mihomo 全局配置](https://wiki.metacubex.one/config/general/)、[Mihomo DNS](https://wiki.metacubex.one/config/dns/)、[Xray 26.3.27 Freedom 实现](https://github.com/XTLS/Xray-core/blob/v26.3.27/infra/conf/freedom.go)。
