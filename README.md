# Leora / Umbra Proxy Rules

仅维护分流与 DNS/DoT 防护配置；STUN 按直连/代理路由处理，保留广告拦截，不含节点。

两个版本共用同一份显式规则，只改变"未命中规则"的默认出口：

- **Leora（白名单）**：只显式列出直连/拒绝目标，未命中的域名与 IPv4 走代理，即除国内（及显式直连）外全部代理。
- **Umbra（黑名单）**：显式规则与 Leora 完全相同，但未命中的域名与 IPv4 直连，只有显式代理列表走代理。Umbra 由 `build_rules.py` 从 `Leora-ProxyRules.conf` 生成，不要手工编辑。

IPv6 在两种模式下都保持 fail-closed：国内 IPv6 前缀直连，其余真实 IPv6 被拒绝并回退 IPv4（Xray 在 Leora 中走代理），Umbra 的 Xray 还会在 DIRECT 兜底前显式阻断 `2000::/3`。UDP 跟随路由：每条代理规则后保留同条件 UDP 拒绝兜底；Leora 未命中的 UDP 拒绝，Umbra 未命中的 UDP 跟随直连默认。浏览器 WebRTC 限制模板两种模式都适用。

| 客户端 | 模式 | 配置入口 | 用法 |
| --- | --- | --- | --- |
| Shadowrocket | Leora 白名单 | [Leora-ProxyRules.conf](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-ProxyRules.conf) | 添加远程配置，下载并选中 |
| Shadowrocket | Umbra 黑名单 | [Umbra-ProxyRules.conf](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-ProxyRules.conf) | 添加远程配置，下载并选中 |
| Mihomo | Leora 白名单 | [Leora-Clash-Routing.yaml](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Routing.yaml) | 与现有节点配置合并，含 DNS/TUN 设置 |
| Mihomo | Umbra 黑名单 | [Umbra-Clash-Routing.yaml](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-Clash-Routing.yaml) | 与现有节点配置合并，含 DNS/TUN 设置 |
| Clash / FlClash | Leora 白名单 | [Leora-Clash-Extend.js](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Extend.js) | 脚本库 → 从 URL/文件导入；目标配置的扩展（Extend）切到脚本模式并选中。FlClash 的脚本库入口是配置扩展页的「前往配置脚本」 |
| Clash / FlClash | Umbra 黑名单 | [Umbra-Clash-Extend.js](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-Clash-Extend.js) | 脚本库 → 从 URL/文件导入；目标配置的扩展（Extend）切到脚本模式并选中。Umbra 配置必须选 Umbra 脚本 |
| Xray | Leora 白名单 | [Leora-Xray-Routing.json](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Xray-Routing.json) | 合并到完整 Xray 配置 |
| Xray | Umbra 黑名单 | [Umbra-Xray-Routing.json](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Umbra-Xray-Routing.json) | 合并到完整 Xray 配置 |

**别把文件槽位搞混：** `*-ProxyRules.conf` 是 Shadowrocket 的远程配置，只能加在「配置 → 远程配置」里；`*-Clash-Extend.js` 才是给 Clash/FlClash 的扩展脚本。若把 `.conf` 贴进 JS/脚本槽，QuickJS 会报 `invalid first character of private name at eval_script:1:1`——因为 `.conf` 第一行是 `#` 注释，被当成私有字段语法；换成对应的 `.js` 即可。导入前可先运行 `python3 tools/check_extend_script.py <文件> [--expect-mode umbra]` 自检：它会识别 `.conf`/`.yaml`/`.json`/`.js` 并给出对应用法，`--expect-mode` 还能抓出「Umbra 配置选了 Leora 脚本」这类不报错但规则静默走错的问题（FlClash 每个配置的扩展脚本是独立绑定的）。

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --mode leora --input original.yaml --output protected.yaml
python3 merge_mihomo.py --mode umbra --input original.yaml --output protected-umbra.yaml
python3 merge_xray.py --mode leora --input original.json --output protected.json
python3 merge_xray.py --mode umbra --input original.json --output protected-umbra.json
```

Clash 脚本由 `python3 build_clash.py` 从同一份 Clash 规则分别生成 Leora 与 Umbra 两版，自动保留订阅节点并替换规则、DNS、TUN；应用级设置（规则模式、IPv6 开启、TUN mixed 等）需按 [用法与验证](USAGE.md#clash-extend-脚本) 对齐。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `Leora-ProxyRules.conf` | 唯一规则源（白名单）：Shadowrocket 远程配置，同时作为 Umbra 的生成输入。 |
| `Umbra-ProxyRules.conf` | 由 Leora 派生的黑名单 Shadowrocket 配置；不要手工编辑。 |
| `Leora-Clash-Extend.js` / `Umbra-Clash-Extend.js` | Clash「扩展 → 脚本模式」导入的发布脚本；由生成器产出，不要手工编辑。保留订阅节点/策略组/provider，替换规则、DNS、TUN，并自动选择代理目标。 |
| `build_rules.py` | 从 Leora 规则源生成两套 Mihomo/Xray 路由、provider、报告和 Umbra 配置；`--mode` 可只重建一个版本。 |
| `build_clash.py` | 从两套 Clash 路由分别生成 Clash Extend 脚本；`--check` 检查仓库内脚本是否与当前路由一致，任一过期时返回非零。 |
| `tools/check_extend_script.py` | 导入 FlClash/Clash 前自检：识别 `.conf`（Shadowrocket）、`.yaml`（Mihomo 配置）、`.json`（Xray）和 `.js`，给出正确用法及 `eval_script:1:1` 等报错的含义；`--expect-mode` 检查脚本模式是否与配置匹配。 |
| `tests/test_modes.py` | 校验两版互补关系、IPv6/UDP 防泄漏不变量、报告与 provider 一致性。 |
| `tests/test_clash_extend.py` | 用 Node 近似 Clash 的 QuickJS `main(config)` 执行脚本，校验全部规则顺序与 UDP 兜底、目标选择、provider 合并、重复应用和报错路径；静态订阅结果与 `merge_mihomo.py` 整字典比对。 |
| `.github/workflows/build-rules.yml` | 每月 1 日重建两套配置，校验并生成 Clash 脚本、运行全部测试，最后提交生成物。 |
| `routing_policy.py` | 规则、DNS、TUN、模式与合并策略的唯一实现；读取配置文件时显式使用 UTF-8，Windows 本地生成不再受系统编码影响。 |

Mihomo 默认目标为 `PROXY`，Xray 为 `proxy`，可用 `--proxy-name` / `--proxy-tag` 修改。`--mode` 只选择 Leora/Umbra 规则集，没有关闭防护或切换旧模式的参数。

**DNS/Tailscale：** 校园域名和 `ts.net` 使用 Shadowrocket `[Host]` 中的指定 DNS；校园服务及 Tailscale 地址优先直连。Tailscale 的 IPv4/IPv6 地址绕过 Mihomo TUN，需已运行 Tailscale、校园网络或对应 VPN 可达。**系统代理客户端还需把 `ts.net` 加入绕过域名**，否则浏览器先经系统代理，DIRECT 出站绑定物理网卡时 tailnet 会约 5 秒超时；见 [系统代理旁路](USAGE.md#系统代理旁路浏览器访问-tailnet-的前提)。

**分流：** 以 Shadowrocket 为唯一规则来源，生成 Leora 与 Umbra 两套配置，保留全部可转换规则和优先级：广告拦截、国内服务直连、海外服务代理；同济内网域名（`gardilily.com`，含 `vesper-center.gardilily.com`）在校园直连块显式直连；Steam 下载域名直连，商店/社区代理。所有代理规则之后用 `GEOIP,CN,DIRECT` 兜底未命中的国内 IP（游戏/QUIC/CDN）；`tailscale.com` / `tailscale.io`、tailnet 地址和 `111.187.0.0/16` 提前直连，DERP 使用官方直连。STUN 跟随路由：直连目标允许，代理目标保留 UDP 兜底，外部 DoT 全局阻断。DNS 与 Tailscale 同步。IPv6 已启用但保持 fail-closed：国内/尾网 IPv6 直连（域名规则 + IPv6 前缀规则集），其余真实 IPv6 被拒绝、回退 IPv4；Umbra 的 Xray 在直接兜底前额外阻断未识别的 IPv6（见[国内 IPv6 直连](USAGE.md#国内-ipv6-直连)）。

**隐私防护：** 公网 DNS 经代理加密查询且无系统 DNS 回退；校园/Tailscale 继续使用专用 DNS。STUN 跟随路由：直连目标允许 STUN，代理目标保留同条件 UDP 拒绝兜底；Leora 未匹配 UDP 拒绝，Umbra 未匹配 UDP 跟随直连默认。外部 DoT 全局阻断。浏览器 WebRTC 限制仍需配合，实际防泄漏取决于客户端 TUN/VPN 是否同时接管 IPv4 与 IPv6、Clash/FlClash 应用层 IPv6 是否开启，以及设备测试。详见 [用法与验证](USAGE.md)。

更新：运行 GitHub Actions **Refresh Leora and Umbra rules**（每月 1 日自动执行），或执行 `python3 build_rules.py` 与 `python3 build_clash.py` 后提交生成文件。生成器读取本地 `Leora-ProxyRules.conf` 的全部分流规则与 `[Host]` DNS 映射，派生 Umbra 并生成两套配置；逐项检查来源、动作和顺序。provider 名由源 URL 和动作稳定计算，不随规则行号变化。UA/URL 匹配及 ASN 转换差异分别记录在 `conversion-report.json`、`Umbra-conversion-report.json` 和用法文档中。第三方列表权利归来源项目。
