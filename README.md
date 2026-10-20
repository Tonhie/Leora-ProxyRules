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

**DNS/Tailscale：** 校园域名和 `ts.net` 使用 Shadowrocket `[Host]` 中的指定 DNS；校园服务及 Tailscale 地址优先直连。Tailscale 的 IPv4/IPv6 地址绕过 Mihomo TUN，需已运行 Tailscale、校园网络或对应 VPN 可达。

**Steam：已识别的国内下载 CDN 直连，商店/社区走代理。** Mihomo/Xray 仅放行这些 CDN 的 TCP 80/443 直连，UDP 仍代理或拒绝；除校园/Tailscale 本地例外，其他流量在广告拦截后代理。下载区域需在 Steam 中选择中国大陆，未列入的 CDN 走代理，不保证强制分配国内 CDN。

Shadowrocket 使用 STUN 应答伪装并保留其他原分流；Mihomo/Xray 不伪造 STUN。客户端必须接管 IPv4/IPv6 和 UDP；配置文件不能保证所有设备都不泄漏。详见 [用法与验证](USAGE.md)。

更新：运行 GitHub Actions **Refresh Leora rules**，或执行 `python3 build_rules.py` 后提交生成文件。生成器读取本地 `Leora-ProxyRules.conf` 的广告来源；DNS 映射自动同步 `[Host]`；Steam 和 Tailscale 策略集中维护于 `routing_policy.py`，三端一致性由测试检查。第三方列表权利归来源项目。
