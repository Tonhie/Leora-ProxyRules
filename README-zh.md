# Leora Proxy Rules

仅维护带 WebRTC 防护的配置，保留广告拦截，不含节点。

| 客户端 | 配置入口 | 用法 |
| --- | --- | --- |
| Shadowrocket | [Leora-ProxyRules.conf](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-ProxyRules.conf) | 添加远程配置，下载并选中 |
| Mihomo | [Leora-Clash-Routing.yaml](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Routing.yaml) | 与现有节点配置合并，含 DNS/TUN 设置 |
| Xray | [Leora-Xray-Routing.json](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Xray-Routing.json) | 合并到完整 Xray 配置 |

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --input original.yaml --output protected.yaml
python3 merge_xray.py --input original.json --output protected.json
```

Mihomo 默认目标为 `PROXY`，Xray 为 `proxy`，可用 `--proxy-name` / `--proxy-tag` 修改。没有关闭防护或切换旧模式的参数。

**DNS/Tailscale：** 校园域名和 `ts.net` 使用 Shadowrocket `[Host]` 中的指定 DNS；校园服务及 Tailscale 地址优先直连。Tailscale 的 IPv4/IPv6 地址绕过 Mihomo TUN，需已运行 Tailscale、校园网络或对应 VPN 可达。**系统代理客户端还需把 `ts.net` 加入绕过域名**，否则浏览器先经系统代理，DIRECT 出站绑定物理网卡时 tailnet 会约 5 秒超时；见 [系统代理旁路](USAGE.md#系统代理旁路浏览器访问-tailnet-的前提)。

**分流：** 以 Shadowrocket 为唯一规则来源，Mihomo/Xray 保留全部可转换规则和优先级：广告拦截、国内服务直连、海外服务代理；Steam 下载域名直连，商店/社区代理。DNS 与 Tailscale 同步。IPv6 已启用：国内/尾网 IPv6 直连（域名规则 + 新增 IPv6 前缀规则集），其余真实 IPv6 被拒绝、回退 IPv4（Xray 仍走代理）（见[国内 IPv6 直连](USAGE.md#国内-ipv6-直连)）。

**隐私防护：** 公网 DNS 经代理加密查询且无系统 DNS 回退；校园/Tailscale 继续使用专用 DNS。STUN 跟随路由：直连目标允许，代理目标保留同条件 UDP 拒绝兜底，未匹配 UDP 仍拒绝；外部 DoT 全局阻断。保留普通直连分流时，WebRTC 防泄漏还必须配合浏览器限制，并确认 TUN/VPN 同时接管 IPv4 与 IPv6、应用层 IPv6 已开启。详见 [用法与验证](USAGE.md)。

更新：运行 GitHub Actions **Refresh Leora rules**，或执行 `python3 build_rules.py` 后提交生成文件。生成器读取本地 `Leora-ProxyRules.conf` 的全部分流规则与 `[Host]` DNS 映射，逐项检查来源、动作和顺序。UA/URL 匹配及 ASN 转换差异记录在 `conversion-report.json` 和用法文档中。第三方列表权利归来源项目。
