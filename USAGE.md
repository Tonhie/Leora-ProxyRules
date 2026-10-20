# WebRTC 防泄漏配置

Mihomo/Xray 通过“代理连接，代理不可用时失败”降低真实公网 IP 泄漏风险；Shadowrocket 使用 STUN 应答伪装。防护只作用于**已进入代理核心的流量**；需要客户端 TUN/VPN 接管 IPv4 和 IPv6。仅导入路由或打开系统 HTTP 代理不足以覆盖浏览器 UDP。

## 默认策略

只有防护配置，没有普通版或模式开关。

- Shadowrocket：使用 `Leora-ProxyRules.conf`，启用 STUN 应答伪装、UDP 不支持时拒绝，并保留原有其他分流。
- Mihomo/Xray：**广告拒绝 → UDP 代理（Mihomo 紧接拒绝兜底）→ Steam 商店代理 → 国内下载 CDN 的 TCP 80/443 直连 → 其余全部代理**。不保留普通国内/校园直连，以覆盖任意端口的 TCP STUN/TURN。
- Steam 下载例外是已知受信任 CDN 的有限直连，不是全局豁免 Steam，对 Valve 专用下载域 `steamcontent.com` 也仅允许 TCP 80/443。命中例外的 HTTP(S) 连接是有意直连，例外目标不提供代理隐藏；这不是“任何流量都不会暴露真实 IP”的承诺。
- 下载区域须在 Steam 客户端选择中国大陆；规则不能控制 Steam 实际选择哪个 CDN，未知下载域名仍走代理。依据 [SteamCN](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Shadowrocket/SteamCN/SteamCN.list) 和 [Steam](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Shadowrocket/Steam/Steam.list) 列表筛选下载端点，排除商店、社区和其他宽泛的 SteamCN 直连范围。

广告规则只能拦截覆盖范围内的广告。代理须支持 UDP 才能保留 UDP 通话；不支持时拒绝，不回退直连。局域网 UDP、Tailscale 点对点、游戏、校园服务可能受到影响。客户端退出后的持续阻断需要系统或客户端 kill switch。

## Mihomo

安装 Python 3.10+，在仓库目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --input original.yaml --output protected.yaml
# 代理节点/静态策略组不叫 PROXY 时
python3 merge_mihomo.py --input original.yaml --output protected.yaml --proxy-name MY-NODE
```

将 `protected.yaml` 作为客户端配置加载，保持 **Rule/规则模式**，开启客户端 TUN 权限并确认 IPv4/IPv6 均被接管。订阅或原配置更新后，需要重新执行合并并重新加载。

脚本保留节点及其他顶层配置，替换通用 `rules`，合并本仓库 `rule-providers`，并替换 `tun`、`dns`、`ipv6`、`mode`。旧 TUN 排除列表不会保留。应用前检查客户端是否额外注入绕过列表、应用排除、`listeners` 的专用规则或指定出站；这些可能绕过通用规则。

DNS 使用 fake-IP 和经代理的 DoH。**fake-IP 不是 STUN 伪装。** 为避免启动循环，DNS 服务器和节点域名的引导解析允许直连；不声称完全隐藏引导 DNS。原校园/Tailscale DNS 策略不会自动保留。

代理目标必须是实际节点或能静态核验的策略组，组内不能包含 DIRECT、PASS 等；带动态 `use`/`include-all` 或成员过滤条件的分组无法核验，会明确报错。此时请将要用的实际节点放入 `proxies`，或建立只引用这些节点的静态策略组，再用 `--proxy-name` 指定。不要把带节点凭据的 `original.yaml`、`protected.yaml` 提交到公开仓库。

主 YAML 已包含 DNS/TUN 和防护规则，不再需要额外的 DNS 或防护模板。手动合并时必须同时保留所有字段和 `providers` 引用，建议使用脚本。

## Xray

在仓库目录执行；默认代理出口标签为 `proxy`：

```bash
python3 merge_xray.py --input original.json --output protected.json
python3 merge_xray.py --input original.json --output protected.json --proxy-tag MY-NODE
# 已有 balancer
python3 merge_xray.py --input original.json --output protected.json --proxy-balancer MY-POOL
```

将 `protected.json` 加载到使用 Xray 的客户端。它必须是包含 `outbounds` 的完整 Xray 对象或对象数组；不是任意厂商的 JSON 订阅格式。默认且始终应用防护，无普通模式。

脚本保留 DNS、节点、传输和 balancer，替换公共路由，按 API 专用规则、广告/拒绝、防护、其余分流的顺序组装。目标出口、balancer 候选及 `fallbackTag` 不能指向 freedom 直连等非代理出口。启用防护时拒绝带自定义路由脚本的叠加层，避免脚本覆盖防护。不要把含节点凭据的输入/输出文件上传公开仓库。

**JSON 路由不会自动安装 TUN 或接管系统 UDP。** 在客户端开启 VPN/TUN，允许 UDP 转发，确认 IPv6 被接管；客户端无法接管 IPv6 时，应在系统/网络层禁用或阻断 IPv6，不能只依靠 DNS 禁止 AAAA。关闭应用绕过/绕过大陆/自动直连回退，配置代理故障时阻断连接。客户端停止后如需继续阻断，也需客户端或操作系统的 kill switch；这些不由路由 JSON 提供。

保留原 DNS 意味着本脚本没有为 Xray 自动完成 DNS 防泄漏配置，需要按客户端配置 DNS 接管。不要把“WebRTC 公网 IP 未泄漏”与“DNS 不泄漏”视为同一个测试。

主 JSON 已包含广告拒绝、Steam 例外及防护规则，不再提供纯防护或无防护模板。

## 浏览器单独加强（可选）

这些是可选模板，不会自动修改本机浏览器。它们只改变浏览器 WebRTC 行为，不会给游戏或 Tailscale 设置进程规则；使用本仓库核心防护时，核心对其他应用的影响仍然存在。

- **桌面 Chrome/Chromium**：将 [Chrome-policy.json](browser/Chrome-policy.json) 中的 `WebRtcIPHandling` 设置为 `disable_non_proxied_udp`，通过浏览器支持的受管策略部署。Linux Google Chrome 可将 JSON 安装到 `/etc/opt/chrome/policies/managed/`；macOS/Windows 按 [Chrome 官方管理方式](https://support.google.com/chrome/a/answer/187202)部署。到 `chrome://policy` 重新加载并确认策略有效。不要把 JSON 导入代理客户端，也不要把它当作可直接导入 macOS 的描述文件。
- Chrome 的同等扩展设置是 `chrome.privacy.network.webRTCIPHandlingPolicy.set({value: "disable_non_proxied_udp"})`；需要具有 `privacy` 权限的扩展管理，普通网页控制台无法设置。见 [官方 API](https://developer.chrome.com/docs/extensions/reference/api/privacy)。这限制非代理 UDP，仍可能使用 TCP；它不是完全禁用 WebRTC，依然需要正确的 TCP 代理/路由。仅开启 TUN 不等于浏览器识别到了 SOCKS/HTTP 代理。
- **桌面 Firefox、不需要网页通话时**：在 `about:config` 将 `media.peerconnection.enabled` 设为 `false`，重开测试页确认无法建立 PeerConnection；恢复为 `true` 可重新启用。也可将 [Firefox-user.js](browser/Firefox-user.js) 的设置追加到 `about:profiles` 所示目标配置目录的 `user.js`，再重启。恢复时需删除这一行并在 `about:config` 重置该项，否则重启会再次禁用。不要覆盖已有 `user.js`。该项的行为见 [Mozilla 说明](https://wiki.mozilla.org/Media/WebRTC/Privacy)。

关闭摄像头/麦克风权限不等于关闭 WebRTC。禁用或限制 WebRTC 可能使会议、语音和网页点对点功能失败；需要这些功能时，保留 WebRTC 并配合完整隧道及设备测试。

## 验证

基础回归测试：

```bash
python3 -m unittest discover -s tests -v
# 准备 Mihomo、Xray 官方二进制后执行本地数据包测试
python3 tests/verify_cores.py --mihomo /absolute/path/to/mihomo --xray /absolute/path/to/xray
```

已用 Mihomo **1.19.32**、Xray **26.3.27** 验证主配置及合并结果。测试覆盖广告 TCP/UDP 优先拒绝、UDP 经代理收发、UDP 不支持/代理不可用时不落入直连、任意端口 TCP 经代理，以及 Steam 国内下载 TCP 80 的直连路径、同一 CDN 的其他端口/UDP 代理、商店代理。

测试使用本地 SOCKS 代理、回环接收端和固定 DNS 映射，不连接实际 Steam 服务。Steam 下载直连通过核心路由日志确认；这不是下载测速或 CDN 地域检测。关闭防护的配置仅在临时测试目录作为直连对照组生成，不发布。测试不启用系统 TUN，不修改本机网络；Shadowrocket 的 STUN 设置及 Steam 优先级做配置静态检查，未运行 iOS 客户端。

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
| 恢复 | 恢复原节点和配置，验证网络与必要的通话功能恢复正常 | 待测 |

本地核心测试不能替代这些设备测试。没有启用 kill switch 时，路由 JSON/YAML 无法承诺客户端退出后继续阻断流量。

## 依据

- [Mihomo 路由规则](https://wiki.metacubex.one/config/rules/)、[UDP 不支持时继续匹配的核心实现](https://github.com/MetaCubeX/mihomo/blob/v1.19.32/tunnel/tunnel.go#L643)
- [Mihomo TUN](https://wiki.metacubex.one/config/inbound/tun/)、[DNS 与指定代理](https://wiki.metacubex.one/config/dns/)
- [Xray 路由与可嗅探协议](https://xtls.github.io/en/config/routing.html)：没有可直接使用的 STUN 协议路由条件，不能写一个 `protocol: stun` 假装防护生效。
