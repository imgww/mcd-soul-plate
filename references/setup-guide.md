# 配置指引 · mcd-soul-plate

本 Skill **离线模式无需任何配置**。仓库内已附带脱敏后的真实响应样本，
以下命令开箱即用，不需要 Token、不需要网络：

```bash
python scripts/check_environment.py
python src/soul_plate.py --compare --offline samples/nutrition-foods.raw.json
python src/soul_plate.py --soul 哦不人 --offline samples/nutrition-foods.raw.json
```

只有需要**拉取最新菜单数据**时才需继续配置。

本指南覆盖四项依赖，逐项说明：

| 依赖 | 类型 | 是否必需 | 说明 |
|---|---|---|---|
| `python-runtime` | runtime | **必需** | Python 3.10+，零第三方包 |
| `mcd-mcp` | mcp + token | 可选 | 联网取数才需要 |
| `nutrition-sample` | local-tool | **必需** | 离线数据，已脱敏入库 |
| `chrome-for-figures` | cli | 可选 | 仅重新生成配图时需要 |

---

## 一、python-runtime（必需）

| 项 | 内容 |
|---|---|
| 官方下载 | <https://www.python.org/downloads/> |
| 官方文档 | <https://docs.python.org/3/> |
| 核验日期 | 2026-10-09 |

要求 Python 3.10 及以上——源码使用 `X | None` 联合类型注解，低于 3.10 需改写为
`Optional[X]`。

**零第三方依赖**：不需要 `pip install`，只用标准库（urllib / json / itertools /
datraclasses / argparse / re）。

```bash
python --version          # 需输出 3.10 或更高
```

若版本过低：优先升级 Python；无法升级时按源码提示手工替换联合类型注解，
替换后**必须重跑全部测试**确认无回归。

**安全说明**：不引入任何第三方包以避免供应链风险；不使用 `eval` / `exec`；
不执行从网络下载的代码。

---

## 二、mcd-mcp（可选，联网模式需要）

| 项 | 内容 |
|---|---|
| 官方入口 | <https://open.mcd.cn/mcp> |
| 使用指南 | <https://github.com/M-China/mcd-mcp-server> |
| 登录页 | <https://open.mcd.cn/mcp>（点击右上角「登录」，手机号验证） |
| 凭据获取 | <https://open.mcd.cn/mcp> |
| 控制台路径 | 控制台 → 激活 → 同意服务协议 → 复制 Token |
| 核验日期 | 2026-10-09 |

登录成功后右上角「登录」变为「控制台」，点击打开控制台弹窗，
点「激活」申请 MCP Token，阅读并同意服务协议后即可一键复制。

### 权限范围（最小权限）

本 Skill **只调用 `list-nutrition-foods`**（读取常见餐品营养成分，零必填参数、纯只读）。

刻意不接入（边界声明，非遗漏）：

- **写操作**：`create-order`、`cancel-order`、`auto-bind-coupons`、`draw-lottery`、
  `mall-create-order`、`party-order-create`
- **个人资产查询**：`query-my-account`、`query-my-coupons`、`order-list`、`query-my-prizes`

前者有真实资损与不可逆风险；后者依赖登录会员态且涉及个人信息。

**不需要**门店信息、配送地址或会员资产。若发现它在请求这些，说明配置有误。

### 安全存储

**只走环境变量，绝不写进任何文件。**

```bash
# Windows PowerShell
$env:MCD_MCP_TOKEN = "你的Token"

# macOS / Linux / Git Bash
export MCD_MCP_TOKEN="你的Token"
```

**绝不要做**（会泄露凭证，违反赛事信息安全声明）：

- 写进 `mcp-config.json`、`.env` 或任何提交文件
- 硬编码进源码
- 在 Issue、截图、对话记录里粘贴完整 Token

仓库 `.gitignore` 已拦截 `.env`、`*token*`、`*secret*`、`*credential*`、
`mcp-config.json`；`mcp-config.example.json` 只含 `${MCD_MCP_TOKEN}` 占位符。
代码侧：Token 仅从环境变量读取，异常信息经 `mask_secret()` 兜底替换。

### 验证

```bash
python src/soul_plate.py --list-tools     # 应列出 35 个工具
python src/soul_plate.py --compare        # 应输出 154 项餐品的对比表
```

### 轮换与撤销

**轮换**：回到 <https://open.mcd.cn/mcp> 控制台重新「激活」，旧 Token 作废，
更新本地环境变量即可。

**撤销**：删除本地环境变量即停止使用；如需彻底作废该 Token，到控制台按平台入口处理。

**Token 泄露处置**：①立即重新激活使旧 Token 失效；②检查是否有文件或提交含该 Token，
若有则从历史清除；③本 Skill 不存储个人资产数据，泄露影响限于调用配额。

---

## 三、nutrition-sample（必需）

| 项 | 内容 |
|---|---|
| 数据来源 | <https://open.mcd.cn/mcp> |
| 使用指南 | <https://github.com/M-China/mcd-mcp-server> |
| 本地路径 | `samples/nutrition-foods.raw.json` |
| 核验日期 | 2026-10-09 |

仓库已附带 2026-10-09 实测的脱敏样本（160 行记录，归一化 154 项餐品），
使评审无需 Token 即可复现全部输出。

### 验证

```bash
python -c "import json;d=json.load(open('samples/nutrition-foods.raw.json',encoding='utf-8'));print(len(d['data'].splitlines()))"
# 输出 161（1 行表头 + 160 条记录）
```

### 样本缺失时如何重建

```bash
export MCD_MCP_TOKEN="你的Token"
python src/soul_plate.py --probe-dump samples/nutrition-foods.raw.json
python docs/sanitize_sample.py            # 必须先脱敏再入库
```

`sanitize_sample.py` 会递归检查 15 类禁止字段（token / secret / openid / memberid 等）
并把 `traceId` 替换为占位符。**不要**直接 `git add -f` 提交未脱敏的响应。

### 安全说明

样本仅含营养成分表；`.gitignore` 默认拦截所有 `*.raw.json`，仅对本文件开白名单，
新增样本前必须先跑脱敏脚本。

---

## 四、chrome-for-figures（可选）

| 项 | 内容 |
|---|---|
| 官方下载 | <https://www.google.com/chrome/> |
| 官方支持 | <https://support.google.com/chrome/> |
| 核验日期 | 2026-10-09 |

**仅在需要重新生成 `docs/` 配图时**才需要 Chrome。正常推荐与对比功能完全不需要浏览器——
三张 PNG 已随仓库提供。

```bash
chrome --version    # 有版本输出即就绪
```

### 安全说明

仅以 headless 模式调用截图能力，本地渲染本地 SVG，
不访问外部网络资源，不执行任何下载内容。

---

## 五、可选环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `MCD_MCP_TOKEN` | 联网模式必需 | 无 |
| `MCD_MCP_URL` | MCP 端点 | `https://mcp.mcd.cn` |
| `MCD_MCP_TIMEOUT` | 单次请求超时（秒） | `60` |
| `MCD_ALLOW_ONLINE_PROBE` | 设为 `1` 才允许在线探测 `tools/list` | 不探测 |

在线探测默认关闭。若要验证 Token 有效性：

```bash
MCD_ALLOW_ONLINE_PROBE=1 python scripts/check_environment.py
```

该探测只调用 `tools/list`（零业务副作用），不发 `tools/call`。

---

## 六、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 提示缺 MCD_MCP_TOKEN | 未设置环境变量 | 按第二节设置 |
| 状态 `needs_setup` | 既无 Token 也无样本 | 按二、三节补齐 |
| 状态 `partial` 但离线可用 | 无网络或无 Token | 加 `--offline samples/nutrition-foods.raw.json` 继续 |
| 归一化后 0 项（退出码 3） | 字段未校准 | 跑 `--probe-dump` 看真实键名 |
| HTTP 401/403 | Token 无效或过期 | 重新激活并更新环境变量 |
| 连接超时 | 网络不可达 | 用 `--offline` 继续 |
| 约束下无解（退出码 1） | 该约束在真实菜单上不存在 | 工具会打印放宽建议；或提高 `--kcal` |

## 七、服务规则

使用本 Skill 即表示遵守麦当劳 MCP 服务规则：
<https://cdn.mcd.cn/cms/pages/MCPServerRules.html>

