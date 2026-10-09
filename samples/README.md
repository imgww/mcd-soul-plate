# samples/

本目录存放**从麦当劳 MCP 实时拉取的原始响应样本**，用途是让评审在不配置 Token 的情况下
离线复现全部推荐结果与差异化对比。

## 生成方式

```bash
export MCD_MCP_TOKEN=你的Token
python src/soul_plate.py --probe-dump samples/nutrition-foods.raw.json
```

该命令只做一次 `tools/call` 调用 `list-nutrition-foods`，把服务端返回的 JSON 原样落盘，不做任何加工。

## 当前内容

`nutrition-foods.raw.json` —— 2026-10-09 15:44 实测拉取，含 160 行餐品记录、
归一化后 154 项。**已公开入库**，评审 clone 后可直接运行：

```bash
python src/soul_plate.py --compare --offline samples/nutrition-foods.raw.json
python tests/test_soul.py      # 36 项断言全绿，无需 Token、无需网络
```

## 入库前的安全审查（已完成）

该响应为 `list-nutrition-foods` 的**纯营养数据**。入库前用 `docs/sanitize_sample.py`
逐项检查，结果：

| 检查项 | 结果 |
|:---|:---|
| Token / 密钥 / 密码 字段 | 无 |
| 手机号 / 身份证 / 邮箱 | 无 |
| openId / unionId / 会员号 | 无 |
| `traceId`（会话追踪标识） | **已脱敏**为 `<REDACTED_TRACE_ID>` |
| `datetime`（可证明数据新鲜度） | 保留 |

审查结论：可公开。`.gitignore` 已就**这一个文件**开白名单
（`!samples/nutrition-foods.raw.json`），其余 `.raw.json` 仍默认拦截。

## 新增样本前必须先脱敏

```bash
# 先跑检查（只读，不修改）
python docs/sanitize_sample.py --check

# 确认无命中后再脱敏写入
python docs/sanitize_sample.py
```

**不要**直接把新拉取的 `.raw.json` 用 `git add -f` 塞进仓库——
它可能夹带你个人的会话上下文。

## 样本缺失时的行为

若本文件缺失，`tests/test_soul.py` **不会崩溃**：自动改用
`tests/fixtures/` 合成夹具运行核心逻辑，把依赖真实菜单的 8 项断言**显式标记为跳过**，
并打印提示。跳过数会写进汇总，不会伪装成通过。

## 数据真实性约定

本目录只接受 MCP 真实响应。算法逻辑的测试夹具在 `tests/fixtures/`，
那些是**人为构造的合成数据，不是麦当劳餐品数据**，两者不得混用。
README 首屏的对比输出即来自本目录的真实数据。
