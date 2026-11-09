# WebRTC 防泄漏配置

Mihomo/Xray 通过“代理连接，代理不可用时失败”降低真实公网 IP 泄漏风险；STUN 现在跟随路由：直连目标放行，代理目标关闭。防护只作用于**已进入代理核心的流量**；需要客户端 TUN/VPN 接管 IPv4 与 IPv6。Mihomo 与 Shadowrocket 的 TUN 配置会接管 IPv6；Xray 路由 JSON 不安装 TUN，客户端无法接管 IPv6 时仍须在系统或网络层阻断。仅导入路由或打开系统 HTTP 代理不足以覆盖浏览器 UDP。

## 默认策略

只有防护配置，没有普通版或模式开关。

- Shadowrocket：使用 `Leora-ProxyRules.conf`，保留原有分流和 UDP 不支持时拒绝；不再伪造 STUN 响应，STUN 直连/代理行为跟随路由。
- Mihomo/Xray：内部 DNS 接管 → 原本地/校园/Tailscale 绕过 → 隐私防护（DoT） → Shadowrocket 完整可转换分流顺序 → 国内 IP 兜底直连。国内/B站/Apple 等继续按源规则直连；Steam 下载直连、商店/社区代理。所有代理规则之后、`MATCH` 之前增加 `GEOIP,CN,DIRECT`，只兜底未被显式列表覆盖的国内 IP（游戏、QUIC/CDN 等），不抢在代理规则前面。China DIRECT 块另加国内 IPv6 前缀直连规则集，其余 IPv6 目标最终落到 `FINAL`/`MATCH` 走代理，详见[国内 IPv6 直连](#国内-ipv6-直连)。
- 同济内网：`gardilily.com` 及其子域（如 `vesper-center.gardilily.com`）在校园直连块中显式 `DIRECT`。该站点解析到校园私有地址（`10.60.150.234`），代理节点无法访问校园网，经代理必然失败；域名由公网权威 DNS 直接返回真实内网地址，因此不加入 `[Host]` 专用 DNS。离开校园网且未连校园 VPN 时直连失败属于预期边界。
- STUN/TURN：不再有全局端口/域名拒绝。STUN 服务按路由决定：直连目标允许，代理目标在同条件 UDP 拒绝兜底处关闭，未匹配 UDP 仍被最后一条 `NETWORK,udp,REJECT` 拒绝。因此国内/直连站点可以拿到真实映射，代理目标不会以真实 IP 直连。
- 隐私防护：拒绝外部 TCP/UDP `853`，避免应用绕过配置的 DNS 使用 DoT/DoQ；该规则仍在所有国内直连之前全局生效。**STUN 放行会增加浏览器 WebRTC 暴露面**：恶意网页可以利用任意直连 STUN 服务器取得真实公网 IP；因此浏览器侧 WebRTC 限制仍是必须项，路由层不再假装能完全拦截 STUN。
- Mihomo 在每条 PROXY 规则后保留同条件 UDP 拒绝兜底，节点不支持 UDP 时不落入后面的 DIRECT。Xray 代理出口失败后不会重新匹配直连规则。末尾的 `GEOIP,CN,DIRECT` 位于全部代理规则之后，不会让本应代理的流量提前直连；代理规则后的 UDP 兜底仍只作用于代理命中项。
- **WebRTC 部署必须配合下文浏览器限制。** 现在 STUN 对直连目标开放，路由层不会拦截浏览器到直连 STUN 服务器的请求，也无法阻止全部 ICE 本地信息；只有浏览器限制才能避免把真实 IP 发给网页。不要把修改后的配置理解为“所有设备绝对不泄漏”。
- 转换边界：USER-AGENT/URL-REGEX 不可直接转换，记录在 `conversion-report.json`；Xray ASN 使用 RIPE 公告网段快照，`IPOnDemand` 无法逐条模拟 Shadowrocket `no-resolve`；`GEOIP,CN` 在 Mihomo 使用 GeoIP 数据库，在 Xray 转换为 `geoip:cn`（测试需要 `geoip.dat`）。隐私规则是有意加入的优先覆盖，普通分流的来源、动作和相对顺序保持同步。
- 下载区域须在 Steam 客户端选择中国大陆；规则不能控制 Steam 实际选择哪个 CDN，未知下载域名仍走代理。依据 [SteamCN](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Shadowrocket/SteamCN/SteamCN.list) 和 [Steam](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Shadowrocket/Steam/Steam.list) 列表筛选下载端点，排除商店、社区和其他宽泛的 SteamCN 直连范围。

广告规则只能拦截覆盖范围内的广告。代理规则须由支持 UDP 的节点转发 UDP，否则拒绝；直连规则保持直连，因此直连目标可以使用 STUN，这也意味着浏览器侧必须另行限制 WebRTC。客户端退出后的持续阻断需要系统或客户端 kill switch。

## 国内 IPv6 直连

`[General]` 现为 `ipv6 = true`（`prefer-ipv6` 仍为 `false`，IPv4 保持优先）。China DIRECT 块在 `China_Domain.list` 之后、`DOMAIN-SUFFIX,tonhie.online` 之前新增一条 `RULE-SET,https://raw.githubusercontent.com/PaPerseller/chn-iplist/master/ruleset/ipv6-cidr6.list,DIRECT`。该列表与仓库既有的 proxy-special/reject-special/direct-cdn 来自同一维护者，是大陆 IPv6 前缀表（约 2018 条 `IP-CIDR6,...,no-resolve`）；Shadowrocket 直接抓取上游 URL。

- 分流效果：China 列表几乎不含 IPv6，此前 `ipv6 = false` 会丢弃 AAAA。现在按客户端分别处理：Shadowrocket 返回真实 AAAA，大陆 IPv6 目标命中前缀规则直连，其余**真实 IPv6** 命中 `IP-CIDR6,2000::/3,REJECT,no-resolve` 被立即拒绝，应用回退 IPv4；Mihomo 的 AAAA 由 fake-IP 的 IPv6 段（`fc00::/18`）应答，域名按域名规则分流（国内域名直连、境外域名代理、广告拒绝），只有字面量 IPv6 才进入前缀规则和拒绝规则；Xray 返回真实 AAAA 并在路由中按 IPv6 前缀匹配（该拒绝规则不加入 Xray，见下）。`prefer-ipv6 = false` 只影响 Shadowrocket 的地址族选择。
- 节点要求：Mihomo/Shadowrocket 的域名代理在节点侧解析域名，节点只有 IPv4 也能正常代理境外站点；只有“真实 IPv6 字面量经代理”才需要节点支持 IPv6（Shadowrocket/Clash 已直接拒绝，Xray 仍保留代理路径）。无法接受时按下面的回退步骤禁用 IPv6；上游 `chn-iplist` 的说明也是“服务器不支持 IPv6 时设为仅 IPv4”。
- Mihomo/FlClash：顶层 `ipv6: true`、`dns.ipv6: true`，TUN 写入 `inet6-address: fdfe:dcba:9876::1/126`，fake-IP 增加 IPv6 段 `fake-ip-range6: fc00::/18`（缺省时 mihomo 1.19.32 对 AAAA 直接返回空答案）。新增的 `IP-CIDR6,2000::/3,REJECT,no-resolve` 只拒绝真实 IPv6：fake-IP 的 `fc00::/18` 不在 `2000::/3` 内，且域名连接先恢复域名再匹配规则，因此境外域名按域名规则走代理，不会被误拒。该来源全部为 IP 前缀，生成器把它转成 `behavior: ipcidr` 的 rule-provider（裸 CIDR payload，托管在本仓库 `providers/` 下），并在同一 China 位置输出 `RULE-SET,<provider>,DIRECT`。
- Xray：DNS `queryStrategy` 与直连出口均为 `UseIP`；该列表在路由中展开为 `ip` 条目、`outboundTag: direct`，位置与 Shadowrocket 源顺序一致。**`IP-CIDR6,2000::/3,REJECT` 不转换到 Xray**：Xray 的 `IPOnDemand` 会对域名做 IP 规则解析，若加入这条会在域名规则之前把境外域名整体 block；因此 Xray 保留“其余 IPv6 走代理”的行为。
- 应用层要求：Clash/FlClash 的 IPv6 必须开启（工具 → 常规 → 内核 → IPv6 = 开启；Android 进阶配置 → 网络 → VPN 中开启 IPv6），否则应用会覆盖脚本并禁用 IPv6。TUN 必须保持开启，否则 IPv6 不被接管。见[必须手动对齐的 Clash 应用级设置](#必须手动对齐的-clash-应用级设置)。
- 已知取舍：大陆 IPv6 依赖“前缀命中”——不在大陆 IPv6 列表里的国内地址会被 `2000::/3` 拒绝规则拒绝；境外 IPv6-only 站点同样会被拒绝（这是“国外禁用 IPv6”的直接后果），需要访问时只能改该行为 `PROXY` 并确保节点有 IPv6。Mihomo 的 IPv6 域名连接使用 fake 地址（`fc00::/18`），IP 前缀规则不参与域名连接的分流：不在 China 域名列表里但解析到大陆 IPv6 的域名仍会走代理；直连出站对域名使用哪一地址族由核心/解析器决定，不强制 IPv6 优先（`prefer-ipv6` 固定 `false`，且只有 Shadowrocket 有该开关）。
- 未采用的替代方案：曾评估把大陆 v6 前缀加入 Shadowrocket `tun-excluded-routes` / Mihomo `tun.route-exclude-address`，但没有采用。Mihomo 的 `route-exclude-address-set` 只在 Linux auto-redirect 模式生效，普通 TUN 无效；把约 2018 条前缀内联进单一源配置会明显膨胀，且在 IPv6 已启用、内核按规则集分流后是冗余的；DIRECT 规则集同时覆盖 TUN 与系统代理路径。**但 Tailscale 的 `fd7a:115c:a1e0::/48` 必须加入 `tun-excluded-routes`（已加入）**：否则启用 IPv6 后 TUN 会接管尾网 IPv6，`leora-mc` 这类尾网主机就不再直连。结果满足目标：大陆/尾网 IPv6 直连，其余真实 IPv6 拒绝，不因直连泄漏。
- 回退：把 `ipv6` 改回 `false` 并重新运行 `build_rules.py`、`build_clash.py`，同时关闭客户端应用层 IPv6。`prefer-ipv6` 为固定值，改动会触发审计失败。仓库每天由 GitHub Actions 重新拉取该列表并提交刷新后的 provider。

## Mihomo

安装 Python 3.10+，在仓库目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --input original.yaml --output protected.yaml
# 代理节点/静态策略组不叫 PROXY 时
python3 merge_mihomo.py --input original.yaml --output protected.yaml --proxy-name MY-NODE
```

将 `protected.yaml` 作为客户端配置加载，保持 **Rule/规则模式** 并开启客户端 TUN 权限。合并结果已开启 IPv6，写入 IPv6 TUN 地址（`fdfe:dcba:9876::1/126`）和 fake-IP 的 IPv6 段（`fc00::/18`），需确认 TUN 同时接管 IPv4 与 IPv6；系统或客户端若另有 IPv6 开关，不要关闭。订阅或原配置更新后，需要重新执行合并并重新加载。

脚本保留节点及其他顶层配置，替换通用 `rules`，合并本仓库 `rule-providers`，并替换 `tun`、`dns`、`ipv6`、`mode`、`hosts`。TUN 排除列表逐项读取 Shadowrocket 的 `tun-excluded-routes`，包含其局域网、Tailscale IPv4 与 IPv6 网段。应用前检查客户端是否额外注入绕过列表、应用排除、`listeners` 的专用规则或指定出站；这些可能绕过通用规则。

DNS 使用 fake-IP，默认查询为指定代理上的加密 DoH，直连目标可使用阿里 DoH；`direct-nameserver-follow-policy` 确保校园/尾网访问仍使用专用 DNS。节点域名使用加密 DoH 引导，节点属于校园/尾网时也遵守专用策略。禁用系统 hosts，DNS 不回退到系统解析器；引导地址使用有有效 TLS 证书的 IP URL，避免明文 DNS 引导。**fake-IP 不是 STUN 伪装。** 为避免启动循环，节点域名的加密引导解析允许直连；这会向指定解析器暴露节点域名，但不使用 ISP 明文 DNS。校园及 Tailscale 的域名专用 DNS 自动从 Shadowrocket `[Host]` 同步，专用查询显式使用 DIRECT；这些域名排除 fake-IP，返回真实地址。`tailscale.com` / `tailscale.io`、`100.64.0.0/10`、`fd7a:115c:a1e0::/48` 和 `111.187.0.0/16` 在校园域名前直连；控制面和官方 DERP（HTTPS 443）因此直连，但 Tailscale 打洞的 STUN/peer UDP 仍按当前路由决定，未命中直连时会被代理或最后 UDP 兜底挡住。Mihomo 的 fake-IP 同时配置 IPv4（`198.18.0.1/16`）与 IPv6（`fc00::/18`）段：AAAA 返回 fake IPv6，域名规则对 IPv6 连接同样生效；缺少 IPv6 fake 段时 mihomo 1.19.32 会返回空 AAAA。IP 前缀规则只匹配字面量或自行解析的 IPv6（见[国内 IPv6 直连](#国内-ipv6-直连)）。

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

- 规则序列与 `Leora-Clash-Routing.yaml` 逐条一致：本地/校园/Tailscale 直连、DNS 接管、DoT 拦截、广告拒绝、Steam 下载直连、完整来源顺序和每条代理规则后的 UDP 拒绝兜底；`MATCH` 和 `#PROXY` 会替换为实际目标。当规则目标能在静态节点/策略组上核验时，输出与 `merge_mihomo.py` 的结果相同；节点或 provider 订阅由脚本自建目标，`merge_mihomo` 无法校验该目标，但规则内容与兜底仍相同。
- 末尾在 `MATCH` 之前保留 `GEOIP,CN,DIRECT`，只兜底未被前面代理/直连规则命中的国内 IP（游戏 UDP、QUIC/CDN），不会抢在代理规则前。STUN/TURN 不再全局拦截：直连目标允许，代理目标由同条件 UDP 拒绝兜底关闭；外部 DoT（853）仍全局阻断。直连 STUN 会重新暴露浏览器 WebRTC 面，浏览器限制仍是必须项。
- 自动选择规则目标：优先 `PROXY`、`节点选择`、`手动选择` 等命名策略组，其次任一可静态核验到真实节点的策略组，再退到带 provider 来源（`use`/`include-all`/`include-all-proxies`）且静态成员可核验的动态组；都没有时用全部真实节点创建 `Leora-Proxy` 选择组。若订阅既没有可用真实节点、也没有非空 `proxy-providers`，脚本会直接报错而不是落入直连；只有 provider 时用它们创建 `Leora-Proxy`。
- `rule-providers` 按名称合并：订阅自有 provider 保留，Leora provider 覆盖同名项；`proxy-providers` 原样保留。Clash 会把 provider 的 `path` 重写到自己的目录，无需手工处理。生成的 Leora provider 名由**源 URL 和动作**稳定计算，不随源规则行号变化；这样源规则调整顺序时不会把不同列表误当成同一个 provider 继续使用旧缓存。若确实改了同一源列表的内容，等待 provider 刷新周期或手动清除旧缓存即可。
- 若订阅已有名为 `leora-dns-out` 且类型不是 `dns` 的节点，脚本会报错；若同名节点本来就是 `type: dns`，会被去重后重新追加，不报错。
- 固定残余差异：Clash 会额外写入 `tun.device: Clash`、重写 provider `path`、在订阅缺少时注入空的 `proxy-providers: {}`，并强制写入端口、`log-level`、`global-ua`、`profile.store-selected` 等应用级键；因此最终配置文本不可能与 YAML 逐字相同。

### 必须手动对齐的 Clash 应用级设置

脚本无法控制以下字段：Clash 在脚本执行后一定会覆盖或合并它们。要让最终**路由相关字段**与 `Leora-Clash-Routing.yaml` 一致，请逐项设置：

| 项目 | Clash 位置 | 目标值 | 说明 |
| --- | --- | --- | --- |
| 出站模式 | 仪表盘 | **规则** | Clash 用应用级 `mode` 覆盖脚本；该值本来就应保持规则模式 |
| IPv6 | 工具 → 常规 → 内核 | **开启** | 覆盖脚本的 `ipv6: true`；Android 在进阶配置 → 网络 → VPN 中开启 IPv6。关闭会让应用覆盖脚本并禁用 IPv6，国内 IPv6 直连随之失效；TUN 也必须保持开启，否则 IPv6 不被接管 |
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

`tests/test_clash_extend.py` 用 Node 近似 Clash 的 QuickJS `main(config)` 契约（V8 而非 QuickJS，只覆盖脚本使用的语言子集）执行脚本：静态订阅与 `merge_config` 做整字典比较，节点/provider 订阅校验完整规则序列、目标、provider 合并、幂等和报错路径。修改 `Leora-ProxyRules.conf` 或 Clash 路由后，GitHub Actions 会同时刷新 YAML 与脚本；CI 在重新生成前先运行 `build_clash.py --check`，提交了过期脚本会失败。Action 另有每日定时任务，重新拉取远程列表（含国内 IPv6 前缀列表）并提交 `providers/` 下刷新后的 provider，无需手动触发。

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

**JSON 路由不会自动安装 TUN 或接管系统 UDP。** 在客户端开启 VPN/TUN，允许 UDP 转发，确认 IPv4 与 IPv6 均被接管；客户端无法接管 IPv6 时，应在系统/网络层禁用或阻断 IPv6，不能只依靠 DNS 策略。关闭应用绕过/绕过大陆/自动直连回退，配置代理故障时阻断连接。客户端停止后如需继续阻断，也需客户端或操作系统的 kill switch；这些不由路由 JSON 提供。

合并器会用同步 DNS 策略替换原 `dns`，并添加 `leora-dns-out` DNS 出站。已进入核心的传统 TCP/UDP 53 查询被导入内置 DNS；专用 DNS 的内部查询以 `leora-dns` 标签直连固定解析器，其他解析使用经代理的 DoH。公网 DoH 的内部查询显式强制走代理，不会被 China 等直连规则覆盖；未获准的内部 DNS 目的地拒绝，代理故障不使用直连或系统 DNS。为避免代理域名解析循环，合并器为 `servers`/`vnext` 中的公网节点域名添加精确匹配的 `https://223.5.5.5/dns-query` 加密直连引导；校园/尾网节点域名继续使用专用 DNS。这类引导查询不提供代理隐藏。`leora-dns` 和 `leora-bootstrap` 是保留的内部标签，不能用于普通流量入站。直连出口使用内置 DNS；除校园/尾网专用策略与节点引导外，Xray 普通域名查询统一通过代理 DoH，比 Shadowrocket 允许的直连 DNS 范围更窄。两端按源配置启用 IPv6：Mihomo 顶层 `ipv6` 与 `dns.ipv6` 为 true，并配置 IPv6 TUN 地址；Xray DNS `queryStrategy` 与直连出口均为 `UseIP`，解析失败不退回系统解析器。Xray 没有等价的全局 IPv6 开关，外部客户端必须自己接管 IPv6。大陆 IPv6 前缀由新增的 ipcidr DIRECT 规则集匹配，其余 IPv6 目标不命中直连规则、最终走代理；Mihomo 的域名连接走 fake-IP 域名规则（见[国内 IPv6 直连](#国内-ipv6-直连)）。Xray 26.3.27 内置 DNS 处理 A/AAAA，其他记录类型明确拒绝；Tailscale 原生 DNS 的查询应通过系统本地路由访问 Quad100，可保留其其他记录类型能力。应用自带 DoH（443 或其他端口）不会被 53 接管；将浏览器安全 DNS 关闭以使用代理 DNS，或配置为同一受控 DoH 并验证其出口。标准 853 端口的 DoT/DoQ 被阻断，其他端口不保证覆盖。

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

Tailscale 使用 `100.64.0.0/10` 和 `fd7a:115c:a1e0::/48`。三端保留本地直连；Shadowrocket 的 `tun-excluded-routes` 与 Mihomo 的 `route-exclude-address` 现在同时包含这两个尾网网段（IPv4 与 IPv6），否则启用 IPv6 后 TUN 会接管尾网 IPv6，`leora-mc` 这类主机就不再直连；Mihomo 还对 `ts.net` 排除 fake-IP。源配置保留的尾网 IPv6 DIRECT 规则也同步，核心内尾网 IPv6 依赖系统路由与 Tailscale 接口实际可达，优先使用尾网 IPv4。Xray JSON 无法修改外部客户端的 TUN 路由，需在客户端同步源配置的 `tun-excluded-routes`。不要把整个 UDP 或任意公网范围加入直连例外。

这些例外不安装、不启动 Tailscale，不添加操作系统的校园/子网路由。需要 Tailscale 本身运行、MagicDNS 正常，并使用完整的 `设备.尾网.ts.net` 名称；短主机名的搜索域由系统/Tailscale 管理。不要强制将本地 DNS/服务绑定到不支持相应路由的物理网卡。TUN 排除表示交由系统路由，不表示在没有 Tailscale 的机器上也能访问尾网。

### 系统代理旁路（浏览器访问 tailnet 的前提）

规则里的 `DIRECT` 只决定代理核心如何处理流量，**浏览器是否先把请求交给系统代理由操作系统设置决定**。Windows 上 Chrome/Edge 遵循 WinINET 的 `ProxyOverride`，FlClash 等客户端会用「系统代理 → 绕过域名」（`bypassDomain`）重写该值。该列表默认不含 `ts.net`，于是浏览器把 `https://<设备>.<尾网>.ts.net/` 先发到本地代理端口：

- 代理核心的 `DIRECT` 出站若绑定物理网卡（Mihomo `tun.auto-detect-interface: true` 的常见结果），发往 `100.64.0.0/10` 的包会走物理网卡而不是 Tailscale 接口，约 5 秒后 TLS 握手失败，浏览器显示 `ERR_TIMED_OUT` /「无法访问此网站」——**即使目标就是本机**也一样。TUN 的 `route-exclude-address` 不覆盖这条系统代理路径。
- 对照：`curl.exe --noproxy "*" https://<设备>.<尾网>.ts.net/` 正常（本机 DSH 未带 token 时返回 401，带 token 为 303 后 200），`curl.exe -x http://127.0.0.1:7890 https://<设备>.<尾网>.ts.net/` 约 5 秒失败。说明故障在系统代理/出站网卡，不在 Tailscale、MagicDNS 或服务端。tailscaled 是否在监听可用 `netstat -ano | findstr :443` 确认（监听地址应为 `100.64.0.0/10` 内的本机地址）。

修复（建议 1、2 都做，第 1 步保证 FlClash 重启后仍生效）：

1. FlClash → 设置 → 网络 → 系统代理 → 绕过域名，加入 `*ts.net`、`*tailscale.com`、`*tailscale.io`（FlClash 用 `*` 前缀匹配后缀，不是 `*.`）。保存后它会重写 `ProxyOverride`。
2. 运行 `pwsh -File tools/apply_system_proxy_bypass.ps1 -FlClashPrefs`：需先完全退出 FlClash，脚本会同时写入 WinINET 与 FlClash 的 `bypassDomain`，并做写入校验和备份；`-Check` 只读检查，`-Remove` 仅撤销注册表条目。
3. 临时验证：关闭 FlClash 的系统代理，或改用 `http://127.0.0.1:<DSH 端口>/?token=...` 本机地址。

修改后重启浏览器（已运行实例不一定感知 WinINET 变更），首次访问带 `?token=`，之后 30 天 cookie 有效。不要用「让代理节点访问 tailnet」的思路：远程节点不在 tailnet 内，无法路由 `100.64.0.0/10`。实例记录见 [reports/dsh-access.md](reports/dsh-access.md)。

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
- [Xray 路由与可嗅探协议](https://xtls.github.io/en/config/routing.html)：没有可直接使用的 STUN 协议路由条件；STUN 跟随普通路由，直连目标放行、代理目标由 UDP 兜底关闭，不能声称端口级 STUN 拦截生效。

浏览器 DNS 策略依据：[Chromium DnsOverHttpsMode](https://github.com/chromium/chromium/blob/main/components/policy/resources/templates/policy_definitions/Miscellaneous/DnsOverHttpsMode.yaml)、[Firefox TRR 用户设置](https://firefox-source-docs.mozilla.org/networking/dns/dns-over-https-trr.html#user-choice)。

## 基础设置同步范围

`Leora-ProxyRules.conf` 的 `[General]` 和 `[Host]` 是唯一来源。生成器和合并器检查全部 General 选项；新增选项、缺失选项或尚未支持的取值会报错，Action 不会发布悄悄忽略这些设置的配置。`conversion-report.json` 的 `general_settings` 记录每个源值及实现边界。

| 源设置 | Mihomo | Xray JSON |
| --- | --- | --- |
| `ipv6=true`、`prefer-ipv6=false` | 顶层和 DNS 均为 true，配置 IPv6 TUN 地址与 `fake-ip-range6: fc00::/18`；大陆 IPv6 前缀经 ipcidr provider 匹配 DIRECT（域名连接走 fake-IP 域名规则） | DNS `UseIP`，合并后的直连出口 `UseIP`；无全局 IPv6 开关 |
| 公共 DNS、备用 DNS | 两个代理 DoH | 两个经路由强制代理的 DoH；两种内核的选择/备用时序不完全相同 |
| 直连 DNS、不用系统 DNS、不回退代理 | 指定直连 DoH，无系统回退 | 无按出站选择 DNS 的同等开关；普通域名继续代理 DoH，专用域名用指定 DNS |
| `skip-proxy`、`tun-excluded-routes` | 从源值生成精确/通配域名及 IP 规则，TUN 排除同步 | 同步 DIRECT 规则；系统代理绕过和 TUN 排除由外部客户端设置 |
| `[Host]` | 静态 hosts 和域名专用 DNS | 静态 hosts 和域名专用 DNS |
| `use-local-host-item-for-proxy=false` | 禁用系统 hosts；静态 Host 没有同等的按代理开关 | 静态 Host 没有同等的按代理开关 |
| `private-ip-answer=true` | 允许专用 DNS 返回私网地址 | 允许专用 DNS 返回私网地址 |
| `bypass-system=false` | 不生成系统服务绕过；客户端额外绕过仍需关闭 | 不生成系统服务绕过；捕获范围由外部客户端控制 |
| UDP 不支持时 REJECT | 对应代理规则后加入 UDP 拒绝，防止落入 DIRECT | 代理出错不回退 DIRECT |
| STUN IPv4/IPv6 响应伪装 | 不再伪造；STUN 跟随路由，直连放行、代理目标 UDP 兜底 | 不再伪造；STUN 跟随路由，直连放行、代理目标不回退 DIRECT |

IPv6 设置不会修改操作系统网络栈，也不改写订阅中显式指定的 IPv6 节点地址。Mihomo 的 `fake-ip-range6` 是实现细节（源配置没有对应 General 选项），回退时随 `ipv6=false` 自动移除。回退到旧行为须把 `ipv6` 改回 `false` 并重新运行生成器，同时关闭客户端应用层的 IPv6 开关；`prefer-ipv6` 是固定值，改动会被审计拒绝。若需要整台设备禁用 IPv6，须在系统或客户端落实并实测。字段依据：[Mihomo 全局配置](https://wiki.metacubex.one/config/general/)、[Mihomo DNS](https://wiki.metacubex.one/config/dns/)、[Xray 26.3.27 Freedom 实现](https://github.com/XTLS/Xray-core/blob/v26.3.27/infra/conf/freedom.go)。
