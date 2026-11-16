# Leora / Umbra Proxy Rules

仅维护带 WebRTC 防护的分流与 DNS/DoT 配置，保留广告拦截，不含节点。

两个版本共用同一份显式规则，只改变"未命中规则"的默认出口：

- **Leora（白名单）**：只显式列出直连/拒绝目标，未命中的域名与 IPv4 走代理，即除国内（及显式直连）外全部代理。
- **Umbra（黑名单）**：显式规则与 Leora 完全相同，但未命中的域名与 IPv4 直连，只有显式代理列表走代理。Umbra 由 `build_rules.py` 从 `Leora-ProxyRules.conf` 生成，不要手工编辑。

IPv6 在两种模式下都保持 fail-closed：国内 IPv6 前缀直连，其余真实 IPv6 被拒绝并回退 IPv4（Xray 在 Leora 中走代理），Umbra 的 Xray 还会在 DIRECT 兜底前显式阻断 `2000::/3`。UDP 跟随路由：每条代理规则后保留同条件 UDP 拒绝兜底；Leora 未命中的 UDP 拒绝，Umbra 未命中的 UDP 跟随直连默认。浏览器 WebRTC 限制模板两种模式都适用，部署要求不变。

| 客户端 | 模式 | 配置入口 | 用法 |
| --- | --- | --- | --- |
| Shadowrocket | Leora 白名单 | [Leora-ProxyRules.conf](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-ProxyRules.conf) | 添加远程配置，下载并选中 |
| Shadowrocket | Umbra 黑名单 | [Umbra-ProxyRules.conf](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-ProxyRules.conf) | 添加远程配置，下载并选中 |
| Mihomo | Leora 白名单 | [Leora-Clash-Routing.yaml](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Routing.yaml) | 与现有节点配置合并，含 DNS/TUN 设置 |
| Mihomo | Umbra 黑名单 | [Umbra-Clash-Routing.yaml](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-Clash-Routing.yaml) | 与现有节点配置合并，含 DNS/TUN 设置 |
| Clash | Leora 白名单 | [Leora-Clash-Extend.js](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Extend.js) | 工具 → 进阶配置 → 脚本导入；扩展切到脚本模式并选中 |
| Clash | Umbra 黑名单 | [Umbra-Clash-Extend.js](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-Clash-Extend.js) | 工具 → 进阶配置 → 脚本导入；扩展切到脚本模式并选中 |
| Xray | Leora 白名单 | [Leora-Xray-Routing.json](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Xray-Routing.json) | 合并到完整 Xray 配置 |
| Xray | Umbra 黑名单 | [Umbra-Xray-Routing.json](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-Xray-Routing.json) | 合并到完整 Xray 配置 |

**别把文件槽位搞混：** `*-ProxyRules.conf` 是 Shadowrocket 的远程配置，只能加在「配置 → 远程配置」里；`*-Clash-Extend.js` 才是给 Clash/FlClash 的扩展脚本。若把 `.conf` 贴进 JS/脚本槽，QuickJS 会报 `invalid first character of private name at eval_script:1:1`——因为 `.conf` 第一行是 `#` 注释，被当成私有字段语法；换成对应的 `.js` 即可。

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --mode leora --input original.yaml --output protected.yaml
python3 merge_mihomo.py --mode umbra --input original.yaml --output protected-umbra.yaml
python3 merge_xray.py --mode leora --input original.json --output protected.json
python3 merge_xray.py --mode umbra --input original.json --output protected-umbra.json
```

Mihomo 默认目标为 `PROXY`，Xray 为 `proxy`，可用 `--proxy-name` / `--proxy-tag` 修改。`--mode` 只选择 Leora/Umbra 规则集，没有关闭防护或切换旧模式的参数。

**DNS/Tailscale：** 校园域名和 `ts.net` 使用 Shadowrocket `[Host]` 中的指定 DNS；校园服务及 Tailscale 地址优先直连。Tailscale 的 IPv4/IPv6 地址绕过 Mihomo TUN，需已运行 Tailscale、校园网络或对应 VPN 可达。**系统代理客户端还需把 `ts.net` 加入绕过域名**，否则浏览器先经系统代理，DIRECT 出站绑定物理网卡时 tailnet 会约 5 秒超时；见 [系统代理旁路](USAGE.md#系统代理旁路浏览器访问-tailnet-的前提)。

**分流：** 以 Shadowrocket 为唯一规则来源，生成 Leora 与 Umbra 两套 Mihomo/Xray 配置，保留全部可转换规则和优先级：广告拦截、国内服务直连、海外服务代理；同济内网域名（`gardilily.com`，含 `vesper-center.gardilily.com`）在校园直连块显式直连；Steam 下载域名直连，商店/社区代理。DNS 与 Tailscale 同步。IPv6 已启用但保持 fail-closed：国内/尾网 IPv6 直连（域名规则 + IPv6 前缀规则集），其余真实 IPv6 被拒绝、回退 IPv4；Umbra 的 Xray 在直接兜底前额外阻断未识别的 IPv6（见[国内 IPv6 直连](USAGE.md#国内-ipv6-直连)）。

**隐私防护：** 公网 DNS 经代理加密查询且无系统 DNS 回退；校园/Tailscale 继续使用专用 DNS。STUN 跟随路由：直连目标允许，代理目标保留同条件 UDP 拒绝兜底；Leora 未匹配 UDP 拒绝，Umbra 未匹配 UDP 跟随直连默认。外部 DoT 全局阻断。保留普通直连分流时，WebRTC 防泄漏还必须配合浏览器限制，并确认 TUN/VPN 同时接管 IPv4 与 IPv6、应用层 IPv6 已开启。详见 [用法与验证](USAGE.md)。

更新：GitHub Actions **Refresh Leora and Umbra rules** 每月 1 日自动刷新一次，也可执行 `python3 build_rules.py` 与 `python3 build_clash.py` 后提交生成文件。生成器读取 `Leora-ProxyRules.conf` 的全部分流规则与 `[Host]` DNS 映射，派生 `Umbra-ProxyRules.conf` 并生成两套配置；逐项检查来源、动作和顺序。UA/URL 匹配及 ASN 转换差异分别记录在 `conversion-report.json`、`Umbra-conversion-report.json` 和用法文档中。第三方列表权利归来源项目。
