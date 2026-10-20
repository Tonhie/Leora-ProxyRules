# Leora Proxy Rules

仅维护带 WebRTC 防护的配置，保留广告拦截，不含节点。

| 客户端 | 配置入口 | 用法 |
| --- | --- | --- |
| Shadowrocket | [Leora-ProxyRules.conf](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-ProxyRules.conf) | 添加远程配置，下载并选中 |
| Mihomo | [Leora-Clash-Routing.yaml](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Routing.yaml) | 与现有节点配置合并，含 DNS/TUN 设置 |
| FlClash | [Leora-FlClash-Extend.js](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-FlClash-Extend.js) | 工具 → 进阶配置 → 脚本导入；每个配置的扩展（Extend）切到脚本模式并选中 |
| Xray | [Leora-Xray-Routing.json](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Xray-Routing.json) | 合并到完整 Xray 配置 |

```bash
python3 -m pip install -r requirements.txt
python3 merge_mihomo.py --input original.yaml --output protected.yaml
python3 merge_xray.py --input original.json --output protected.json
```

FlClash 脚本由 `python3 build_flclash.py` 从同一份 Clash 规则生成，自动保留订阅节点并替换规则、DNS、TUN；应用级设置（规则模式、IPv6 关闭、TUN mixed 等）需按 [用法与验证](USAGE.md#flclash-extend-脚本) 对齐。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `Leora-FlClash-Extend.js` | FlClash「扩展 → 脚本模式」导入的发布脚本；由生成器产出，不要手工编辑。保留订阅节点/策略组/provider，替换规则、DNS、TUN，并自动选择代理目标。 |
| `build_flclash.py` | 从 `Leora-Clash-Routing.yaml` 生成 `Leora-FlClash-Extend.js`；`--check` 检查仓库内脚本是否与当前路由一致，过期时返回非零。 |
| `tests/test_flclash.py` | 用 Node 近似 FlClash 的 QuickJS `main(config)` 执行脚本，校验全部规则顺序与 UDP 兜底、目标选择、provider 合并、重复应用和报错路径；静态订阅结果与 `merge_mihomo.py` 整字典比对。 |
| `.github/workflows/build-rules.yml` | 依次重建 YAML、校验并生成 FlClash 脚本、运行全部测试，最后提交生成物；提交过期脚本会在生成前失败。 |
| `routing_policy.py` | 规则、DNS、TUN 与合并策略的唯一实现；读取配置文件时显式使用 UTF-8，Windows 本地生成不再受系统编码影响。 |

Mihomo 默认目标为 `PROXY`，Xray 为 `proxy`，可用 `--proxy-name` / `--proxy-tag` 修改。没有关闭防护或切换旧模式的参数。

**DNS/Tailscale：** 校园域名和 `ts.net` 使用 Shadowrocket `[Host]` 中的指定 DNS；校园服务及 Tailscale 地址优先直连。Tailscale 的 IPv4/IPv6 地址绕过 Mihomo TUN，需已运行 Tailscale、校园网络或对应 VPN 可达。

**分流：** 以 Shadowrocket 为唯一规则来源，Mihomo/Xray 保留全部可转换规则和优先级：广告拦截、国内服务直连、海外服务代理；Steam 下载域名直连，商店/社区代理。DNS 与 Tailscale 同步。

**隐私防护：** 公网 DNS 经代理加密查询且无系统 DNS 回退；校园/Tailscale 继续使用专用 DNS。Mihomo/Xray 增加常见 STUN/TURN 通道拦截、代理 UDP 失败拒绝和外部 DoT 阻断。保留普通直连分流时，WebRTC 防泄漏还必须配合浏览器限制及完整 TUN/VPN 接管；两种核心不能照搬 Shadowrocket 的 STUN 伪装。详见 [用法与验证](USAGE.md)。

更新：运行 GitHub Actions **Refresh Leora rules**，或执行 `python3 build_rules.py` 与 `python3 build_flclash.py` 后提交生成文件。生成器读取本地 `Leora-ProxyRules.conf` 的全部分流规则与 `[Host]` DNS 映射，逐项检查来源、动作和顺序。UA/URL 匹配及 ASN 转换差异记录在 `conversion-report.json` 和用法文档中。第三方列表权利归来源项目。
