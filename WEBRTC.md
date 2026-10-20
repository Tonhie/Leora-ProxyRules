# WebRTC 防泄漏配置

本仓库通过“代理连接，代理不可用时失败”降低真实公网 IP 泄漏风险，不伪造 STUN 应答。防护只作用于**已进入代理核心的流量**；需要客户端 TUN/VPN 接管 IPv4 和 IPv6。仅导入路由或打开系统 HTTP 代理不足以覆盖浏览器 UDP。

## 选择模式

| 模式 | 行为 | 代价与限制 |
| --- | --- | --- |
| `udp`（命令默认） | 先执行广告/拒绝规则，再将剩余已接管 UDP 送往代理；TCP 的 3478、5349、19302–19309 端口及常见 stun/turn 域名也走代理 | 其他 TCP 保留原分流；无法识别未知域名或 IP 上任意端口的 TCP STUN/TURN，例如 TCP 443，因此不是完整的 WebRTC 防护 |
| `strict` | 先执行广告/拒绝规则，剩余已接管 TCP/UDP 全部走代理，包括任意端口的 STUN/TURN | 保留广告拦截，取消原有直连分流；适合隐私优先时临时使用 |

两档的优先级都是 **广告/拒绝 → WebRTC 防护 → 普通分流**。合并器稳定地将 Mihomo 的 `REJECT`/`REJECT-DROP` 和 Xray 的 `block` 规则移到防护之前，各组内部顺序保持不变；Xray 的 API 专用规则仍最优先。这会使原本排在拒绝规则之前的直连/代理例外失去优先权。只拦截现有规则覆盖的广告，不能保证拦截所有广告。

两档都不在代理失败时主动切换直连。Mihomo 的 UDP 代理规则后紧接 `REJECT`：内核可能跳过不支持 UDP 的节点，必须拦住后续规则。Xray 出站失败会失败结束，不会重新匹配直连规则。代理需要支持 UDP，才能保留正常 UDP 通话；不支持时 UDP 会失败。WebRTC 可能改用 TURN/TCP，也可能无法通话。

防护优先于原来的局域网/校园/国内直连规则，因此可能影响局域网 UDP、游戏、校园服务和 Tailscale 点对点连接。它不能同时保证“所有 WebRTC 连接不直连”和“所有国内/局域网 WebRTC 连接照常直连”。需要保留这些连接时应评估后自行添加例外；例外目标不再受本防护覆盖。

## Mihomo

安装 Python 3.10+，在仓库目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --input original.yaml --output protected.yaml --webrtc udp
# 隐私优先：全部 TCP/UDP 走代理
python3 merge_mihomo.py --input original.yaml --output protected.yaml --webrtc strict
# 代理节点/静态策略组不叫 PROXY 时
python3 merge_mihomo.py --input original.yaml --output protected.yaml --proxy-name MY-NODE --webrtc udp
```

将 `protected.yaml` 作为客户端配置加载，保持 **Rule/规则模式**，开启客户端 TUN 权限并确认 IPv4/IPv6 均被接管。订阅或原配置更新后，需要重新执行合并并重新加载。

脚本保留节点及其他顶层配置，替换通用 `rules`，合并本仓库 `rule-providers`，并替换 `tun`、`dns`、`ipv6`、`mode`。旧 TUN 排除列表不会保留。应用前检查客户端是否额外注入绕过列表、应用排除、`listeners` 的专用规则或指定出站；这些可能绕过通用规则。

DNS 使用 fake-IP 和经代理的 DoH。**fake-IP 不是 STUN 伪装。** 为避免启动循环，DNS 服务器和节点域名的引导解析允许直连；不声称完全隐藏引导 DNS。原校园/Tailscale DNS 策略不会自动保留。

代理目标必须是实际节点或能静态核验的策略组，组内不能包含 DIRECT、PASS 等；带动态 `use`/`include-all` 或成员过滤条件的分组无法核验，会明确报错。此时请将要用的实际节点放入 `proxies`，或建立只引用这些节点的静态策略组，再用 `--proxy-name` 指定。不要把带节点凭据的 `original.yaml`、`protected.yaml` 提交到公开仓库。

也可手动合并 [Leora-Mihomo-WebRTC.yaml](Leora-Mihomo-WebRTC.yaml)：它是 **strict 全代理叠加层**，不含节点。合并其顶层字段，先提取普通分流中的广告/拒绝规则，再放入模板中的三条规则，最后放普通分流的其余规则，并确保 `PROXY` 组只包含真实代理。模板本身不带广告规则，不能作为完整节点订阅使用。建议使用上面的合并命令，避免遗漏广告 provider。

## Xray

在仓库目录执行；默认代理出口标签为 `proxy`：

```bash
python3 merge_xray.py --input original.json --output protected.json --webrtc udp
python3 merge_xray.py --input original.json --output protected.json --webrtc strict
python3 merge_xray.py --input original.json --output protected.json --proxy-tag MY-NODE --webrtc udp
# 已有 balancer
python3 merge_xray.py --input original.json --output protected.json --proxy-balancer MY-POOL --webrtc strict
```

将 `protected.json` 加载到使用 Xray 的客户端。它必须是包含 `outbounds` 的完整 Xray 对象或对象数组；不是任意厂商的 JSON 订阅格式。不加 `--webrtc` 时保持原合并行为。

脚本保留 DNS、节点、传输和 balancer，替换公共路由，按 API 专用规则、广告/拒绝、防护、其余分流的顺序组装。目标出口、balancer 候选及 `fallbackTag` 不能指向 freedom 直连等非代理出口。启用防护时拒绝带自定义路由脚本的叠加层，避免脚本覆盖防护。不要把含节点凭据的输入/输出文件上传公开仓库。

**JSON 路由不会自动安装 TUN 或接管系统 UDP。** 在客户端开启 VPN/TUN，允许 UDP 转发，确认 IPv6 被接管；客户端无法接管 IPv6 时，应在系统/网络层禁用或阻断 IPv6，不能只依靠 DNS 禁止 AAAA。关闭应用绕过/绕过大陆/自动直连回退，配置代理故障时阻断连接。客户端停止后如需继续阻断，也需客户端或操作系统的 kill switch；这些不由路由 JSON 提供。

保留原 DNS 意味着本脚本没有为 Xray 自动完成 DNS 防泄漏配置，需要按客户端配置 DNS 接管。不要把“WebRTC 公网 IP 未泄漏”与“DNS 不泄漏”视为同一个测试。

[Leora-Xray-WebRTC.json](Leora-Xray-WebRTC.json) 是 **strict 全代理路由叠加层**，供手动集成时参考；通过脚本使用 `--webrtc strict` 即可，脚本会完成目标检查与出口重映射。模板本身不含广告规则、节点、入站或系统 TUN；直接只用此模板不会获得广告拦截，应通过上面的命令合并完整路由。

## 浏览器单独加强（可选）

这些是可选模板，不会自动修改本机浏览器。它们只改变浏览器 WebRTC 行为，不会给游戏或 Tailscale 设置进程规则；如果同时使用核心 `udp`/`strict` 防护，核心对其他应用的影响仍然存在。

- **桌面 Chrome/Chromium**：将 [Chrome-WebRTC-policy.json](browser/Chrome-WebRTC-policy.json) 中的 `WebRtcIPHandling` 设置为 `disable_non_proxied_udp`，通过浏览器支持的受管策略部署。Linux Google Chrome 可将 JSON 安装到 `/etc/opt/chrome/policies/managed/`；macOS/Windows 按 [Chrome 官方管理方式](https://support.google.com/chrome/a/answer/187202)部署。到 `chrome://policy` 重新加载并确认策略有效。不要把 JSON 导入代理客户端，也不要把它当作可直接导入 macOS 的描述文件。
- Chrome 的同等扩展设置是 `chrome.privacy.network.webRTCIPHandlingPolicy.set({value: "disable_non_proxied_udp"})`；需要具有 `privacy` 权限的扩展管理，普通网页控制台无法设置。见 [官方 API](https://developer.chrome.com/docs/extensions/reference/api/privacy)。这限制非代理 UDP，仍可能使用 TCP；它不是完全禁用 WebRTC，依然需要正确的 TCP 代理/路由。仅开启 TUN 不等于浏览器识别到了 SOCKS/HTTP 代理。
- **桌面 Firefox、不需要网页通话时**：在 `about:config` 将 `media.peerconnection.enabled` 设为 `false`，重开测试页确认无法建立 PeerConnection；恢复为 `true` 可重新启用。也可将 [Firefox-disable-WebRTC.user.js](browser/Firefox-disable-WebRTC.user.js) 的设置追加到 `about:profiles` 所示目标配置目录的 `user.js`，再重启。恢复时需删除这一行并在 `about:config` 重置该项，否则重启会再次禁用。不要覆盖已有 `user.js`。该项的行为见 [Mozilla 说明](https://wiki.mozilla.org/Media/WebRTC/Privacy)。

关闭摄像头/麦克风权限不等于关闭 WebRTC。禁用或限制 WebRTC 可能使会议、语音和网页点对点功能失败；需要这些功能时，保留 WebRTC 并配合完整隧道及设备测试。

## 验证

基础回归测试：

```bash
python3 -m unittest discover -s tests -v
# 准备 Mihomo、Xray 官方二进制后执行本地数据包测试
python3 tests/verify_cores.py --mihomo /absolute/path/to/mihomo --xray /absolute/path/to/xray
```

已用 Mihomo **1.19.32**、Xray **26.3.27** 检查合并本仓库完整路由后的两档配置。数据包测试运行本地 SOCKS 代理及 TCP/UDP 接收端，验证两档模式下广告目标的 TCP/UDP 均先拒绝、不进入代理或直连接收端，并验证非广告连接的代理路径、不支持 UDP/代理故障时不落入直连、strict 对任意端口 TCP 的保护，以及关闭防护后确实能观察到直连的对照组。测试不启用系统 TUN，不修改本机网络。

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
