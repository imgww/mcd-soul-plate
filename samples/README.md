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

`nutrition-foods.raw.json` —— 2026-10-09 实测拉取，含 160 行餐品记录、
归一化后 154 项。已在入库前逐字段检查：确认无个人信息、无凭证、无会员相关内容。

## 为什么默认不入库

`.gitignore` 忽略 `samples/*.raw.json`。原因有两条：

1. 拉取动作依赖个人 MCP Token 与会员身份，产物可能夹带与账户相关的上下文字段；
   入库前必须**人工逐字段检查**，确认无个人信息、无凭证后才手动 `git add -f`。
2. 营养数据以官方实时结果为准，仓库里固化一份快照容易过期误导。

本仓库的该文件已完成上述人工检查，故公开留档，便于评审离线复现。

## 数据真实性约定

本目录只接受 MCP 真实响应。算法逻辑的测试夹具在 `tests/fixtures/`，
那些是**人为构造的合成数据，不是麦当劳餐品数据**，两者不得混用。
README 首屏的对比输出即来自本目录的真实数据。
