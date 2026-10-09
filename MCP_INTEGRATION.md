# MCP_INTEGRATION.md · 麦当劳 MCP 集成说明

本文档只描述**代码里真实发生的调用**，不含设想中未接入的能力。

---

## 一、使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| Server 版本 | `1.0.0` |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输方式 | streamable HTTP（JSON-RPC 2.0 over HTTP POST） |
| 协议版本 | `2025-06-18` |
| 鉴权 | 请求头 `Authorization: Bearer <MCP Token>`，Token 在 <https://open.mcd.cn/mcp> 控制台激活后获取 |
| 会话特性 | 服务端为**无状态**：`initialize` 响应头不下发 `mcp-session-id`。客户端仍会透传该头，以便将来有状态时无需改动 |
| 声明的能力 | `tools`（未提供 `resources` 与 `prompts`） |
| 服务端工具总数 | 35 个（经 `tools/list` 实测，单页返回、无分页游标） |
| 客户端实现 | `src/mcp_client.py`，纯 Python 标准库自研，不依赖 MCP SDK |
| 服务规则 | 遵守麦当劳 MCP 服务规则 <https://cdn.mcd.cn/cms/pages/MCPServerRules.html> |

配置样例见 [`mcp-config.example.json`](./mcp-config.example.json)（脱敏，仅环境变量占位符）。

---

## 二、实际调用的 Tool

### 2.1 业务数据工具（1 个）

#### `list-nutrition-foods`

| 项 | 说明 |
|---|---|
| 作用 | 获取麦当劳常见餐品的营养成分数据 |
| 入参 | **无必填参数**，本项目以 `{}` 调用 |
| 调用点 | `src/nutrition.py` → `fetch_foods()`，常量 `TOOL_NAME` |
| 调用时机 | 每次 CLI 运行开始时调用 1 次；`--offline` 模式下不调用 |
| 副作用 | 无（只读查询） |
| 是否依赖登录会员态 | 否，仅需有效 Token |
| 是否依赖门店/地理位置 | 否 |

**为什么选它作为唯一数据源**：35 个工具里，`list-nutrition-foods` 与 `now-time-info` 是仅有的两个「零必填参数 + 纯只读 + 不依赖门店与登录态」的工具。任何评审者拿到仓库、配上自己的 Token 就能完整复现，不需要人在北京、不需要账户里有券有积分有订单。可复现性是这个 Skill 的设计底线。

#### 真实返回结构（2026-10-09 实测校准）

外层是业务信封，**`data` 不是数组也不是对象，而是一段带表头的字符串表格**：

```json
{"success": true, "code": 200, "message": "请求成功",
 "datetime": "2026-10-09 15:44:08", "traceId": "...",
 "data": "[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n  猪柳麦满分,null,1288,308,16,16,24,781,213\n  ..."}
```

首行 `[N]{列名...}:` 声明行数与列名，其后每行一条记录、两空格缩进、逗号分隔、缺失值为字面量 `null`。实测 160 行，朴素 split 安全，但代码仍按表头列数严格校验。

**归一化后的字段映射（实测真实键名）**

| 逻辑字段 | 归一化属性 | 真实键名 | 单位 | 备注 |
|---|---|---|---|---|
| 餐品名 | `Food.name` | `productName` | — | |
| 能量（千焦） | `Food.energy_kj` | `energyKj` | kJ | 实测 160 行全部为 `null` |
| 能量（千卡） | `Food.kcal` | `energyKcal` | kcal | **注意列名带大写 K** |
| 蛋白质 | `Food.protein` | `protein` | g | |
| 脂肪 | `Food.fat` | `fat` | g | |
| 碳水化合物 | `Food.carb` | `carbohydrate` | g | |
| 钠 | `Food.sodium` | `sodium` | mg | |
| 钙 | `Food.calcium` | `calcium` | mg | |
| 营养说明 | `Food.desc` | `nutritionDescription` | — | 实测全部为 `null` |
| 品类 | `Food.category` | **无此字段** | — | **本项目按商品名关键词推断**，见下 |

**两条影响设计的实测结论**

1. **响应里没有品类/分类字段。** `category` 由 `nutrition._CATEGORY_RULES` 按商品名关键词推断得到，属于**本项目派生字段**而非麦当劳返回数据。实测 154 项归一化结果的品类分布：饮品 69、主食 34、小食 23、甜品 21、果蔬 4、其他 3。
2. **存在同名重复行**（160 行 / 158 个唯一名，「小杯玉米杯」与「纯牛奶（盒装）」各重复一次且数值完全相同）。配平引擎以商品名为唯一键，故按整行去重，最终得到 154 项。
3. **实测菜单含 3 项「营销命名品」**：`牛气满满`(495kcal/钠764)、`专"薯鱼"你`(463kcal/钠652)、`"苹板"支撑Pro`(476kcal/钠1077)。它们是菜单上的临时包装名而非餐品本名，热量高钠高，一旦进入候选池会因「热量贴合度」被严格控钠人格优先选中。本项目在 `soul_engine._is_marketing()` 中无条件剔除。

### 2.2 协议与自检工具（不承载业务）

| Tool | 用途 | 调用点 |
|---|---|---|
| `tools/list` | `--list-tools` 自检模式，确认 Token 有效、连通正常、可查工具总数 | `src/mcp_client.py` → `list_tools()` |

`initialize` 与 `notifications/initialized` 是 MCP 协议握手，所有调用前自动完成，不属业务工具。

### 2.3 明确**不使用**的工具及理由

35 个工具中其余 33 个本项目刻意不接入：

| 类别 | 代表工具 | 不接入的理由 |
|---|---|---|
| 下单与取消 | `create-order`、`cancel-order`、`calculate-price` | 产生真实订单与支付链路，Demo 与评审复算有资损风险 |
| 券与积分写操作 | `auto-bind-coupons`、`draw-lottery`、`mall-create-order` | 改变用户券资产、原子扣减积分；`draw-lottery` 自身描述即要求先展示扣减并经用户确认 |
| 个人资产查询 | `query-my-account`、`query-my-coupons`、`order-list`、`query-my-prizes` | 依赖登录会员态，评审无法复现，且涉及个人信息 |
| 门店/地址上下文 | `query-nearby-stores`、`query-meals`、`query-store-coupons`、`delivery-*` | 需要 `storeCode`/`addressId`，把结果绑死在特定地理位置与配送地址上 |
| 派对预约链路 | `query-party-*`、`party-order-create` | 多级下钻依赖 `spuId`，与「配餐」无关 |
| 活动日历 | `campaign-calendar` | 输出随时间漂移，与营养配平无因果关系 |

**这条边界是有意为之的设计声明**：本 Skill 的价值主张是「只读数据 + 本地算法」，不代用户做任何有资产后果的动作。

---

## 三、调用流程

### 3.1 时序

```
用户 CLI 命令
    │
    ├─(A) --offline 分支 ─────────────────────────┐
    │                                             │
    └─(B) 在线分支                                 │
         │                                        │
         1. POST initialize                       │
         2. POST notifications/initialized  → 202 │
         3. POST tools/call                       │
              {name:"list-nutrition-foods",        │
               arguments:{}}                      │
            ← result.content[].text 或             │
              result.structuredContent            │
                                                    ▼
                                        4. 字符串表格解析 + 字段归一化
                                           parse_foods()
                                        5. 营销命名品剔除 + 人格候选池裁剪
                                           _candidate_pool()
                                        6. 人格偏好 → 硬约束 build_constraints()
                                        7. 穷举 + 打分 + 约束过滤 compose()
                                        8. 人格化重排（6 维权重）  │
                                           _rescore_for_soul()     │
                                        9. 约束无解则分级回退     │
                                           RELAX_STEPS ←───────────┘
                                       10. 输出方案 + 放宽告警 + 免责声明
```

### 3.2 代码路径

| 步骤 | 文件 | 函数 |
|---|---|---|
| 读 Token（仅环境变量） | `src/mcp_client.py` | `StreamableHTTPClient.__init__` |
| 握手 | `src/mcp_client.py` | `initialize()` |
| 工具调用与响应解包 | `src/mcp_client.py` | `call_tool()` |
| SSE 分帧还原 | `src/mcp_client.py` | `_unwrap()` |
| 拉营养数据 | `src/nutrition.py` | `fetch_foods()` |
| 字符串表格解析 | `src/nutrition.py` | `_parse_string_table()` |
| 字段归一化 | `src/nutrition.py` | `parse_foods()` |
| 品类推断 | `src/nutrition.py` | `infer_category()` |
| **人格偏好向量** | `src/soul.py` | `SOULS` / `get()` |
| **人格 → 硬约束** | `src/soul_engine.py` | `build_constraints()` |
| **候选池裁剪** | `src/soul_engine.py` | `_candidate_pool()` / `_is_marketing()` |
| **蛋白下限** | `src/soul_engine.py` | `protein_floor()` |
| 单日组合穷举与打分 | `src/composer.py` | `compose()` |
| **人格化重排（6 维）** | `src/soul_engine.py` | `_rescore_for_soul()` |
| **分级回退** | `src/soul_engine.py` | `RELAX_STEPS` + `recommend()` |
| **差异化验证** | `src/soul_engine.py` | `verify_divergence()` |
| 输出与免责 | `src/soul_plate.py` | `main()` |

### 3.3 异常与重试策略

| 情况 | 处理 |
|---|---|
| 未设 Token | 立即抛 `MCPError`，提示设置 `MCD_MCP_TOKEN`，不发网络请求 |
| 网络不可达 / TLS 失败 | 包装为 `MCPError`，退出码 2 |
| HTTP 4xx/5xx | 保留状态码与响应片段进错误消息，退出码 2 |
| JSON-RPC `error` 字段 | 提取 `code` + `message` 抛出，退出码 2 |
| 工具返回 `isError: true` | 抛 `MCPError` 并附 `content` 摘要，退出码 2 |
| 归一化后 0 项 | 判定为字段未校准，打印真实键名，退出码 3（与网络故障区分） |
| 人格约束无解 | **分级回退**（放宽钠上限与容差），并把放宽事实写入输出 |

**不做静默重试。** 所有失败都带原因抛给终端用户，避免用假数据或缓存数据冒充 MCP 实时结果。任何异常消息经 `mask_secret()` 兜底，确保 Token 不会出现在日志或报错里。

### 3.4 调用强度

单次运行 3 个 HTTP 请求（2 次握手 + 1 次工具调用）。无轮询、无并发、无批量写。`--offline` 模式 0 请求。

---

## 四、SOUL 人格数据的来源与边界（重要）

本项目的「人格偏好」是**本项目自建数据**，不是麦当劳数据，也不是 SkillHub 官方营养建议。必须说清楚三件事：

1. **SkillHub 的 SOUL 是表达风格设定**（语气、思考逻辑、说话方式），不含任何营养知识。
2. 本项目做的是一次**有损但可解释的降维映射**：人格短评的语义信号 → 6 维营养偏好权重（0~1）→ 引擎约束与打分。每维权重的推导依据记录在 `soul.py` 的 `provenance` 字段，可逐条审阅与手工修正。
3. **SkillHub 未开放 SOUL 全文 API，页面为 SPA 无服务端渲染**（2026-10-09 实测 `skillhub.cn/api/soul/list` 等路径均返回前端外壳 HTML）。因此权重由设计者依公开的人格短评推导，**不宣称是官方人格的官方营养建议**。

`src/soul.py` 内置 16 个人格。其中 15 个取自 SkillHub SOUL 广场的公开人格名与短评（YYDS 神人、MIAO 喵之人、MUM 妈妈、OH-NO 哦不人、WHY 疑问者、GRASS 草人、MONK 僧侣、SOLO 独行者、GOOD 好人、MALO 吗喽、FAKE 假面人、LOVE-R 情种、ZZZZ 装睡者、WORK-er 工作者、GOGO 行人）；第 16 个「卷王 / jushi」为本项目为补齐 16 档而自建，其人格名**不宣称取自 SkillHub**，已在 `provenance` 中显式标注。

---

## 五、业务价值

### 5.1 它替代了什么人工动作

麦当劳的营养信息**按单品分页呈现**，而且——这是实测数据揭示的关键事实——**154 项餐品里 69 项是饮品**（占 44.8%），远超主食（34 项）。菜单的真实重心是饮料，但没有任何界面会告诉你「今天的你，该喝哪一杯、吃哪一样」。

而**更难的是排一周**：天天吃的人要的是「这周别吃重、别哪天离谱、平均别超」，这是一道跨天的组合分配题。

本 Skill 把「逐个看」变成「给一个人格，出一顿有性格的饭」：**信息展示 → 决策辅助 → 个性化表达**。

### 5.2 价值落点

| 对象 | 价值 |
|---|---|
| 用户 | 同一份菜单，16 种人格得到 14 种不同推荐（真实数据实测），且每个推荐都能说清「为什么是你这个」 |
| 麦当劳 | 把营养透明这项合规资产转化为**可分享的人格化内容**。「今天我是哦不人」天然是社交话题，比营养数字更适合传播 |
| MCP 生态 | 示范一个**只用只读工具、零写操作**的 Skill 形态。把 35 个工具里最干净的那一个用透，比堆一堆有资损风险的写操作更适合被复用 |
| 后续开发者 | `src/mcp_client.py` 是可直接摘走的无依赖 MCP 客户端；`src/soul_engine.py` 示范如何把**定性人格设定**翻译成**可执行约束**（含单调性设计、分级回退、差异化自检） |

### 5.3 可验证性

- **36 项离线回归断言**（`tests/test_soul.py`），不依赖网络与 Token，实测全部通过：
  - **A 人格向量层（10 项）**：取值域、维度不塌缩、基线人格中性、key/中文名/别名三路可查、provenance 完备。
  - **B 翻译层（6 项）**：三条**单调性**检验——热量预算随 `heat` 单调不减、钠上限随 `sodium` 单调递减、同品类上限随 `variety` 单调不增；蛋白下限仅对高蛋白人格生效。
  - **C 引擎层（8 项）**：营销命名品识别与剔除、候选池方向、件数范围、回退档位单调放宽。
  - **D 方案层（12 项）**：16 人格全部出解、差异化成立、确定性（同输入两次 md5 完全一致）、**所有方案不违反其人格约束**、回退如实报告、合成夹具下可运行、JSON 可序列化、文案无跨品牌对比与减重承诺。
- **差异化不是自述而是实测**：`verify_divergence()` 用真实菜单统计不同首选方案数。真实数据实测：**16 人格全部出解，产生 14 种不同首选**。若权重失效导致所有人格趋同，该函数会立刻报 `diverged=False`——方案失效能被看见，而不是靠嘴说。
- **约束遵守是被测试的，不是被承诺的**：测试逐一人格逐方案校验钠上限与热量容差，违规即失败。
- 合成夹具与真实数据物理隔离：夹具在 `tests/fixtures/`，真实 MCP 响应在 `samples/` 且默认被 `.gitignore` 拦在仓库外。

---

## 六、合规对照

| 规则要求 | 本项目落实 |
|---|---|
| 真实使用麦当劳 MCP 能力 | 主链路 `list-nutrition-foods` 实时取数，无内置兜底营养表；离线模式仅用于测试且明确标注数据来源 |
| 配置仅用环境变量占位符 | `mcp-config.example.json` 全占位符；`.gitignore` 拦截 `.env`、`*token*`、`*secret*` |
| 不含真实 Token / 个人信息 | 代码与文档零凭证；不接入任何返回个人资产的 `query-my-*` 工具 |
| 不宣扬不健康饮食方式 | 定位为「均衡搭配」，输出不含减重承诺、不含节食方案，尾部固定打印免责声明；测试断言禁止文案出现「减肥/减脂/掉秤」 |
| 不与其他品牌产品对比 | 数据源仅麦当劳自有营养库，输出仅在麦当劳餐品之间做组合；测试断言禁止出现其他快餐品牌名 |
| 不构成医疗/营养专业建议 | CLI 每次输出打印该声明；README 明确「不适合当减重方案或临床营养处方」 |
| 不损害麦当劳名声 | 人格画像均为正向（妈妈=照顾、僧侣=克制），无贬低表述；严格控钠人格的存在反而展示麦当劳营养透明度 |
