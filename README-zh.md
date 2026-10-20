# Leora Proxy Rules

Shadowrocket、Mihomo（Clash Meta）和 Xray 分流规则。不含代理节点，需配合已有节点使用。

## 使用

| 客户端 | 配置地址 | 用法 |
| --- | --- | --- |
| Shadowrocket | [Leora-Shadowrocket-Rules.conf](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Shadowrocket-Rules.conf) | 在「配置」中添加远程配置，下载并选中 |
| Mihomo | [Leora-Clash-Routing.yaml](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Clash-Routing.yaml) | 将 `rule-providers` 和 `rules` 合并进已有配置；需有 `PROXY` 代理或策略组 |
| Xray | [Leora-Xray-Routing.json](https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-Xray-Routing.json) | 使用下方命令合并进完整的 Xray JSON 配置 |

Mihomo 可按需合并 [DNS 示例](Leora-Clash-DNS.yaml)；校园和 Tailscale DNS 需对应网络可达。旧版 Clash 不保证兼容。

```bash
# 在本仓库目录运行；默认代理出口标签为 proxy
python3 merge_xray.py --input original.json --output routed.json
# 其他代理出口标签
python3 merge_xray.py --input original.json --output routed.json --proxy-tag your-proxy-tag
```

合并会替换原有通用路由，保留 API 专用路由；使用前备份原配置。

## 更新

在 GitHub Actions 中运行 **Refresh Leora rules**，或本地执行：

```bash
python3 -m pip install -r requirements.txt
python3 build_rules.py
```

需要 Python 3.10+。生成器读取仓库 `main` 分支的 `Leora-ProxyRules.conf`；修改后先推送该文件。`source/` 为来源快照，Shadowrocket 配置单独维护；转换文件本地生成后需提交并推送。

## 差异

跨客户端转换不完全等价：USER-AGENT/URL-REGEX 不转换，Xray 的 DNS 解析及 ASN 匹配存在差异。Mihomo/Xray 路由文件不包含 Shadowrocket 的 STUN 伪装及全部 DNS/TUN 设置，不能单独保证防止 WebRTC 泄漏。详见 [转换报告](conversion-report.json)。第三方规则权利归各来源项目。
