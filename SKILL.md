---
name: mcd-soul-plate
description: 按 SOUL 人格偏好从麦当劳真实营养数据解出符合该人格约束的搭配。适用于「我是哦不人/社恐/牛马，帮我配一顿麦当劳」「按我的人格点餐」「16 种人格分别吃什么」这类请求。把人格短评翻译成可执行的营养约束（钠上限、热量预算、蛋白下限、品类与放纵度），用确定性搜索求解并校验约束。只读麦当劳 MCP 的 list-nutrition-foods，不下单不领券不改账户；离线模式无需 Token 与网络。
version: 1.2.0
agent_created: true
---

# 麦麦 soul 搭子

## 这个 Skill 做什么

按 SOUL 人格偏好，从麦当劳真实营养数据里解出一顿**符合该人格约束**的搭配。

用户说「我是哦不人，帮我配一顿麦当劳」，它把「哦不人 = 风险雷达 = 严格控钠」这条定性描述，
翻译成可执行的数值约束（钠上限 749mg、候选池裁掉甜品与油炸），再用确定性搜索求解，
输出带约束校验的组合与营养拆解。

**它不是给推荐套文案壳。** 人格差异必须改变约束、进而改变答案——
这是与同类作品的核心区别，也是本 Skill 唯一的技术主张。

## 什么时候用

用户表达以下任一意图时触发：

- 「按我的人格/性格/口味配一顿麦当劳」「我是 XX 人，帮我点」
- 「我是社恐 / 牛马 / 佛系，午饭吃什么好」
- 「帮我在麦当劳里按某个约束配餐」（会被翻译成对应人格）
- 「16 种人格分别吃什么」「对比所有人格」

**不触发**的情况：

- 用户要减重方案或临床营养处方 → 本 Skill 只回答「按这个人格该吃什么」，
  不回答「你应该吃多少」
- 用户只是问别家吃什么 → 数据源仅麦当劳自有营养库

## 从推荐到下单

推荐结果可以转成**可下单清单**，但**本 Skill 默认不下单**。

这不是能力缺失，是实测得出的事实：`create-order` 的四个必需字段里
**三个不在营养表中**——

| 必需字段 | 来源 |
|---|---|
| `storeCode` | `query-nearby-stores` / `delivery-query-stores` |
| `items[].productCode` | `query-meals`（门店菜单）|
| `takeWayCode` | `calculate-price` 的返回 |
| `orderType` / `beType` | 可由用户选择 |

`list-nutrition-foods` 只给中文菜名，不给商品编码。所以推荐结果**无法直接**
构造合法下单调用——必须由用户补齐门店与编码。

### 用法

```bash
# 生成可下单清单（只读，不下单）
python src/soul_plate.py --soul mum --order-plan

# 外送场景
python src/soul_plate.py --soul mum --order-plan --pickup delivery

# 有门店编码时，拉菜单回填 productCode 并核价（只读，需联网）
python src/soul_plate.py --soul mum --order-plan \
    --store-code 12345 --be-code ABC --quote

# 机器可读
python src/soul_plate.py --soul mum --order-plan --json
```

### 真实下单：三重校验，缺一即拒绝

```bash
python src/soul_plate.py --soul mum --order-plan \
    --store-code 12345 --be-code ABC \
    --allow-order --confirm
```

1. 必须显式加 `--allow-order`（开启下单能力，默认关闭）
2. 必须显式加 `--confirm`（本次已获用户授权，**每次都要重新给出**）
3. 字段必须齐备（`productCode` / `storeCode` / `takeWayCode` / `beCode`）

任一不满足即拒绝执行，**不做部分下单**。退出码：`4` 缺确认、`5` 字段未齐备、
`6` 参数被拒。

### 支付不归本 Skill 管

下单后由用户在麦当劳侧完成支付（支付链接扫码或 App）。支付完成后可用
`query-order` 回查订单状态。本 Skill **不接入任何支付能力**。

### 下单与内容合规

比赛规则全文**未禁止下单**，且第 6 行明确把「业务处理、任务执行」列为官方认可的能力形态，
第 21 行只要求「真实使用麦当劳 MCP 能力」。因此下单功能本身合规。

但外送链路会接触手机号与收货地址 —— 按规则「个人信息」条款，这些信息
**仅用于用户自己的下单**，不得留存、不得写入任何文件或样本。

另需注意内容合规 d 项：下单失败、缺货、价格波动等负面场景**不得归因或暗示品牌**。

## 数据来源

唯一数据源是麦当劳 MCP 的 `list-nutrition-foods`：35 个工具里仅有的两个
「零必填参数 + 纯只读 + 不依赖门店与登录态」之一。

这条边界是刻意选的：**任何人 clone 后配自己的 Token 就能完整复现**，
不需要人在北京、不需要账户里有券有积分有订单。

## 六维偏好怎么来的

16 种人格，每种带一组六维权重（热量 / 蛋白 / 钠 / 多样 / 放纵 / 尝鲜，0~1）。

权重由**公开人格短评推导**，不是从数据集学出来的，也不是从 SOUL 原文计算的
（SkillHub 未开放 SOUL 全文 API，页面为 SPA 无服务端渲染，抓不到正文）。
每维在 `soul.py` 的 `provenance` 字段写明推导依据，可手工改后复跑对比。

**不宣称这是官方人格的官方营养建议。** 主张只有一条：给定一组透明可审计的权重，
引擎能产出人格之间明显不同的推荐，且这种差异可被复现与检验。

## 人格差异作用在四处

缺一层人格就会趋同——这是实测出来的，不是设计出来的：

| # | 作用点 | 做法 | 缺了会怎样 |
|---|---|---|---|
| 1 | 候选池 | 放纵 / 尝鲜裁剪 + 营销命名品剔除 | 严格控钠人格会选中「牛气满满」 |
| 2 | 硬约束 | 钠 / 热量 / 蛋白下限 / 品类上限 | 人格只剩软偏好，硬约束失效 |
| 3 | 打分重排 | 四项权重插值 + 限定款 / 甜品两维 | 低尝鲜人格之间完全无法区分 |
| 4 | 分级回退 | 无解则逐级放宽，**放宽事实强制打印** | 严格控钠人格直接返回空 |

## 运行

### 前提

Python 3.10 及以上，**无需 pip install**（仅标准库）。
联网模式需要麦当劳 MCP Token；从 <https://open.mcd.cn/mcp> 登录 → 控制台 → 激活 → 复制。

运行前先查环境：

```bash
python scripts/check_environment.py
```

### 离线模式（无需 Token，推荐先跑这个）

```bash
python src/soul_plate.py --compare --offline samples/nutrition-foods.raw.json
python src/soul_plate.py --soul 哦不人 --offline samples/nutrition-foods.raw.json
python src/soul_plate.py --souls --offline samples/nutrition-foods.raw.json
```

### 联网模式

```bash
export MCD_MCP_TOKEN="你的Token"      # Windows: $env:MCD_MCP_TOKEN="..."
python src/soul_plate.py --list-tools
python src/soul_plate.py --soul mum
python src/soul_plate.py --compare
```

Token 只从环境变量读取，异常信息经 `mask_secret()` 兜底脱敏。

## 诚实边界

工具不静默违背自己设的约束。做不到就说做不到：

- **严格不重样 / 严格控钠可能真的无解**。此时按 `RELAX_STEPS` 逐级放宽，
  并把放宽了什么打印出来（例：`放宽钠上限 +25%（钠上限 936mg，容差 ±12%）`）。
- **16 个人格产出 14 种不同首选，不是 16 种**。妈妈≈哦不人、僧侣≈独行者
  在真实菜单上收敛——严格控钠区间的低钠组合本来就少。这是数据的结构性事实，
  写进输出而不是藏起来。
- **受体克制**：严格控钠 + 高蛋白 + 低热量在真实菜单上可能三者不可兼得，
  工具会明确报告而非编造一个假装达标的方案。

## 边界与不做的事

- **默认不下单**：下单能力默认关闭，需显式开启且逐次确认，字段不齐则拒绝
- **不接入支付**：支付在麦当劳侧完成，本 Skill 只引导
- **不做券与积分写操作**：不调用 `auto-bind-coupons`、`draw-lottery`、
  `mall-create-order`，不改变用户券资产
- **不留存个人信息**：外送链路的手机号与地址仅用于当次下单，不写文件、不入样本
- **不做医疗或营养建议**：每次输出固定附免责声明
- **不做减重承诺**：定位是均衡搭配，输出不含节食方案
- **不跨品牌对比**：数据源仅麦当劳自有营养库
- **不猜商品编码**：菜单匹配不上就如实报告未命中，不用近似编码凑
- **停止条件**：归一化后 0 项（字段未校准，退出码 3）、网络不可达（退出码 2）、
  约束无解（退出码 1）、缺下单确认（退出码 4）、下单字段未齐（退出码 5）——
  均如实报错，不用缓存或假数据顶替

## 可验证性

```bash
python tests/test_soul.py     # 36 项断言，离线，无需 Token 与网络
```

| 主张 | 怎么证 |
|---|---|
| 人格差异是真的 | `verify_divergence()` 统计不同首选数；真实数据实测 16 → 14 |
| 约束没被偷偷违背 | 测试逐一人格逐方案校验钠上限与热量容差，违规即失败 |
| 没有随机性 | 同输入连续两次运行，输出 md5 完全一致 |
| 权重不是黑箱 | 每维带 `provenance`，可手工改后复跑对比 |
| 妥协被如实报告 | 分级回退必须写入 `relaxed`，测试断言其非空 |

样本缺失时测试不会崩溃：自动改用合成夹具，把依赖真实菜单的断言显式标记为
**跳过**，不伪装成通过。

## 目录

```
src/
  soul.py           16 人格六维权重 + provenance 溯源
  soul_engine.py    人格 → 硬约束 / 候选池 / 重排 / 分级回退
  soul_plate.py     CLI 入口
  order_flow.py     下单引导：清单 / 缺口 / 菜单匹配 / 三重下单锁
  nutrition.py      营养取数与字段归一化
  composer.py       单日组合穷举与打分
  mcp_client.py     极简 streamable HTTP MCP 客户端（零依赖）
scripts/
  check_environment.py  环境就绪检查
references/
  setup-guide.md        Token 获取与配置指引
tests/
  test_soul.py          94 项断言
samples/                MCP 实时响应样本（已脱敏公开，供离线复现）
```

## 环境降级

`scripts/check_environment.py` 返回四种状态：

| 状态 | 含义 | 本 Skill 的行为 |
|---|---|---|
| `ready` | Python 与样本齐备 | 跳过引导，直接执行 |
| `partial` | 可选能力缺失（如无联网） | 继续离线核心流程，标注受限范围 |
| `needs_setup` | 必需配置缺失（无 Token 且无样本） | 只展示缺失项的准确获取步骤 |
| `unavailable` | 认证失效 / 服务不可达 / 网络被拦 | 区分原因给恢复步骤，能降级则降级 |

无可靠降级时停止受影响流程，不用猜测结果顶替真实输出。

## 合规

参赛作品，非麦当劳官方产品。输出仅供参考，不构成医疗、营养或其他专业建议；
餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准。

SOUL 人格设定名取自 SkillHub 公开页面；六维营养偏好权重为本项目自建，
不构成对该平台的任何官方关联或背书。仓库不含任何真实 Token、密钥或个人信息。
