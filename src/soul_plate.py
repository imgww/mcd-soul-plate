"""麦麦soul 搭子 · CLI 入口

用法
----
    # 列出全部人格与偏好画像
    python src/soul_plate.py --souls

    # 指定人格推荐（默认 650 kcal 基准）
    python src/soul_plate.py --soul miao

    # 调整基准热量
    python src/soul_plate.py --soul worker --kcal 800

    # 对比全部 16 人格在同一天给出的不同答案（本方案的核心证明）
    python src/soul_plate.py --compare

    # 离线复现（无需 Token）
    python src/soul_plate.py --soul mum --offline samples/nutrition-foods.raw.json

    # 自检：MCP 连通性与工具清单
    python src/soul_plate.py --list-tools

免责声明：输出仅供参考，不构成医疗、营养或其他专业建议。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nutrition import load_offline, fetch_foods, detect_unknown_fields
from composer import diagnose
from soul import SOULS, SOUL_ORDER, get, closest_key
from soul_engine import recommend, verify_divergence, build_constraints
from order_flow import BE_TYPES, OrderPlanner

DISCLAIMER = ("本项目为麦当劳程序员节创意开发大赛参赛作品，非麦当劳官方产品。"
              "输出仅供参考，不构成医疗、营养或其他专业建议；"
              "餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。")

BAR = "═" * 66
SUB = "─" * 66


def _load(args) -> tuple[list, object | None]:
    if args.offline:
        path = Path(args.offline)
        if not path.is_file():
            print(f"离线数据文件不存在：{args.offline}", file=sys.stderr)
            print("请确认路径；仓库自带样本位于 samples/nutrition-foods.raw.json，"
                  "也可配置 MCD_MCP_TOKEN 走联网模式。", file=sys.stderr)
            sys.exit(2)
        try:
            foods = load_offline(path)
        except (OSError, ValueError) as exc:
            print(f"离线数据无法解析：{exc}", file=sys.stderr)
            print("该文件应为 MCP list-nutrition-foods 的真实响应；"
                  "若来自 --probe-dump，请先确认拉取成功。", file=sys.stderr)
            sys.exit(3)
        if not foods:
            print("离线数据归一化后为 0 项，判定字段结构已变更。", file=sys.stderr)
            sys.exit(3)
        return foods, None
    from mcp_client import StreamableHTTPClient, mask_secret
    try:
        client = StreamableHTTPClient()
        foods, payload = fetch_foods(
            client, args.probe_dump if args.probe_dump else None)
        if not foods:
            print("归一化结果为 0 项，判定字段未校准。真实键名：",
                  file=sys.stderr)
            print(detect_unknown_fields(payload), file=sys.stderr)
            sys.exit(3)
        return foods, payload
    except SystemExit:
        raise
    except Exception as exc:                      # noqa: BLE001
        print(mask_secret(str(exc)), file=sys.stderr)
        sys.exit(2)


def _fmt_souls() -> None:
    print(BAR)
    print("  麦麦 soul 搭子 · 16 种人格的进食偏好画像".center(64))
    print(BAR)
    print(f"  {'人格':<10}{'key':<10}{'热量':<6}{'蛋白':<6}{'钠':<6}"
          f"{'多样':<6}{'放纵':<6}{'尝鲜':<6}")
    print(SUB)
    for k in SOUL_ORDER:
        s = SOULS[k]
        w = s.as_dict()["weights"]
        print(f"  {s.name:<10}{k:<10}"
              f"{w['heat']:<6.2f}{w['protein']:<6.2f}{w['sodium']:<6.2f}"
              f"{w['variety']:<6.2f}{w['indulgence']:<6.2f}{w['adventure']:<6.2f}")
    print(SUB)
    print("  取值 0~1，0.5 为中性；权重由人格短评推导，非官方数据。")
    print()
    for k in SOUL_ORDER:
        s = SOULS[k]
        print(f"  【{s.name}】{s.tagline}")
        print(f"     画像：{s.describe()}")
        print(f"     逻辑：{s.rationale}")
    print(BAR)


def _fmt_one(foods, sp, base_kcal: float, tolerance: float, top: int) -> None:
    r = recommend(foods, sp, base_kcal, tolerance)
    c = r["constraints"]

    print(BAR)
    print(f"  【{sp.name} · {sp.key}】{sp.tagline}")
    print(f"  “{sp.voice}”")
    print(BAR)
    print(f"  偏好画像  {sp.describe()}")
    print(f"  选餐逻辑  {sp.rationale}")
    print(SUB)
    print(f"  人格生效约束  热量预算 {c.target_kcal:.0f} kcal ±{tolerance:.0%}   "
          f"钠上限 {c.max_sodium:.0f} mg   同品类最多 {c.max_per_category} 件")
    pf = r["signature"].get("protein_floor") or 0
    if pf:
        print(f"                蛋白下限 {pf:.1f} g")
    print(f"  候选池      {r['pool_size']} / {r['total_size']} 项"
          f"（放纵 {sp.indulgence:.2f} · 尝鲜 {sp.adventure:.2f}）")
    print(SUB)

    for msg in r.get("relaxed") or []:
        print(f"  ⚠ 注意：{msg}")
    if r.get("relaxed"):
        print(SUB)

    if not r["plans"]:
        print("  当前约束下无解。")
        print("  " + diagnose(r["pool_size"] and foods or foods, c))
        print(SUB)
        print(DISCLAIMER)
        return

    for i, p in enumerate(r["plans"][:top], 1):
        print(f"  方案 {i}  得分 {p.score:.3f}   热量贴合 {p.kcal_fit_pct:.0%}")
        for f in sorted(p.items, key=lambda x: (-x.kcal, x.name)):
            tag = ""
            if f.category == "甜品":
                tag = "  ← 放纵位"
            elif "风味" in f.name or "柠萌" in f.name:
                tag = "  ← 限定款"
            print(f"     · {f.name:<30} [{f.category:<4}] "
                  f"{f.kcal:>5.0f} kcal  蛋白 {f.protein:>4.1f} g  "
                  f"钠 {f.sodium:>5.0f} mg{tag}")
        print(f"     合计 {p.kcal:.0f} kcal  蛋白 {p.protein:.1f} g  "
              f"脂肪 {p.fat:.1f} g  碳水 {p.carb:.1f} g  "
              f"钠 {p.sodium:.0f} mg  钙 {p.calcium:.0f} mg")
        print(SUB)

    print(f"  {sp.name}说：{sp.voice}")
    print(BAR)
    print(DISCLAIMER)


def _fmt_compare(foods, base_kcal: float, tolerance: float) -> None:
    souls = [SOULS[k] for k in SOUL_ORDER]
    v = verify_divergence(foods, souls, base_kcal)

    print(BAR)
    print("  16 人格同一天 · 同预算 · 不同答案".center(64))
    print(BAR)
    print(f"  {'人格':<8}{'方案':<5}{'热量':<8}{'蛋白':<8}{'钠':<8}  推荐组合")
    print(SUB)
    for k in SOUL_ORDER:
        d = v["detail"][k]
        if not d["plans"]:
            print(f"  {SOULS[k].name:<8}{'无解':<5}")
            continue
        items = " + ".join(n[:14] for n in d["top_items"])
        print(f"  {SOULS[k].name:<8}{d['plans']:<5}"
              f"{d['top_kcal']:<8.0f}{d['top_protein']:<8.1f}"
              f"{d['top_sodium']:<8.0f}  {items}")
    print(SUB)
    print(f"  实测人格数        {v['souls_tested']}")
    print(f"  出解人格数        {v['souls_with_plans']}")
    print(f"  不同首选方案数    {v['distinct_first_plans']}")
    print(f"  差异化是否成立    {'是' if v['diverged'] else '否 ← 方案失效'}")
    print(BAR)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="麦麦 soul 搭子：按 SOUL 人格推荐麦当劳搭配")
    ap.add_argument("--soul", "-s", help="人格 key 或中文名，不填则自动匹配")
    ap.add_argument("--kcal", type=float, default=650.0, help="基准热量预算")
    ap.add_argument("--tolerance", type=float, default=0.12, help="热量容差")
    ap.add_argument("--top", type=int, default=3, help="展示前 N 个方案")
    ap.add_argument("--souls", action="store_true", help="列出全部人格")
    ap.add_argument("--compare", action="store_true", help="对比全部人格")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--offline", help="离线数据路径，无需 Token")
    ap.add_argument("--probe-dump", help="落盘 MCP 原始响应（校准用）")
    ap.add_argument("--list-tools", action="store_true", help="MCP 自检")
    ap.add_argument("--pickup", default="pickup",
                    choices=sorted(BE_TYPES), help="取餐方式（默认到店自取）")
    ap.add_argument("--order-plan", action="store_true",
                    help="把推荐结果转成可下单清单（含缺口清单与引导，不下单）")
    ap.add_argument("--store-code", help="门店编码（有则可匹配菜单回填 productCode）")
    ap.add_argument("--be-code", help="业务编码（得来速/外送/团餐场景必填）")
    ap.add_argument("--quote", action="store_true",
                    help="调用 calculate-price 核价（只读，需联网与门店编码）")
    ap.add_argument("--allow-order", action="store_true",
                    help="开启下单能力（高风险，默认关闭；仍需 --confirm 才能执行）")
    ap.add_argument("--confirm", action="store_true",
                    help="确认本次下单已获用户授权（无 --allow-order 时无效）")
    args = ap.parse_args()

    if args.souls:
        _fmt_souls()
        return

    if args.list_tools:
        from mcp_client import StreamableHTTPClient, mask_secret
        try:
            tools = StreamableHTTPClient().list_tools()
        except Exception as exc:                  # noqa: BLE001
            print(mask_secret(str(exc)), file=sys.stderr)
            sys.exit(2)
        print(f"MCP 连通正常，共 {len(tools)} 个工具。")
        for t in tools:
            print("  -", t.get("name"))
        return

    foods, _ = _load(args)

    if args.compare:
        _fmt_compare(foods, args.kcal, args.tolerance)
        return

    if args.soul:
        try:
            sp = get(args.soul)
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        if args.order_plan or args.quote or args.allow_order:
            _run_order_flow(foods, sp, args)
            return

        if not args.json:
            _fmt_one(foods, sp, args.kcal, args.tolerance, args.top)
        else:
            r = recommend(foods, sp, args.kcal, args.tolerance)
            print(json.dumps({
                "soul": sp.as_dict(),
                "profile": sp.describe(),
                "constraints": {
                    "target_kcal": r["constraints"].target_kcal,
                    "max_sodium": r["constraints"].max_sodium,
                    "max_per_category": r["constraints"].max_per_category,
                },
                "pool": {"usable": r["pool_size"], "total": r["total_size"]},
                "plans": [p.as_dict() for p in r["plans"][:args.top]],
                "disclaimer": DISCLAIMER,
            }, ensure_ascii=False, indent=2))
        return

    key = closest_key(foods)
    sp = SOULS[key]
    print(f"未指定人格，按菜单特征自动匹配为【{sp.name}】（--soul 可指定其他）。\n")
    _fmt_one(foods, sp, args.kcal, args.tolerance, args.top)


def _run_order_flow(foods, sp, args) -> None:
    """下单引导流程：推荐 → 清单 → 缺口 → 可选核价 → 默认不下单。

    真实下单必须同时满足三个条件，缺一即拒绝：
      1. 命令行给了 --allow-order（显式开启能力）
      2. 命令行给了 --confirm（本次已获用户授权）
      3. 清单字段齐备（productCode / storeCode / takeWayCode 等）
    """
    r = recommend(foods, sp, args.kcal, args.tolerance)
    if not r["plans"]:
        print(f"当前人格约束下无可用方案，无法生成下单清单。", file=sys.stderr)
        sys.exit(1)

    top_plan = r["plans"][0]

    # 下单的确认校验必须前置于任何网络连接：
    # 否则缺 Token 时会先因连接失败报错，用户看不到「缺 --confirm」这条更关键的信息。
    if args.allow_order and not args.confirm:
        print("  已拒绝下单：本次未给出 --confirm。", file=sys.stderr)
        print("  下单会产生真实订单，属不可逆操作。", file=sys.stderr)
        print("  确认无误后请同时加 --allow-order 与 --confirm 重跑。", file=sys.stderr)
        print("  如只想看清单不打算下单，去掉 --allow-order 即可。", file=sys.stderr)
        sys.exit(4)

    client = None
    if args.quote or args.allow_order:
        from mcp_client import StreamableHTTPClient
        client = StreamableHTTPClient()

    planner = OrderPlanner(client, allow_create_order=args.allow_order)
    plan = planner.plan(foods, top_plan.items, sp.key, sp.name,
                        pickup=args.pickup,
                        store_code=args.store_code,
                        be_code=args.be_code)

    # 有门店编码时可拉菜单回填 productCode（只读）
    if args.store_code and client is not None:
        spec = BE_TYPES[args.pickup]
        menu = planner.match_menu(args.store_code, spec["orderType"],
                                  spec["beType"], args.be_code)
        if menu:
            hit, missed = planner.match_items(plan, menu)
            print(f"门店菜单匹配：命中 {hit}/{len(plan.items)} 项"
                  + (f"，未命中：{', '.join(missed)}" if missed else ""))
            if hit == len(plan.items):
                plan.gaps = [g for g in plan.gaps
                             if g.field not in ("items[].productCode",)]
        else:
            print("未能获取门店菜单（需联网且门店编码有效），productCode 保持待匹配。")

    # 可选核价（只读）
    if args.quote and client is not None and args.store_code:
        q = planner.quote(plan, args.store_code, args.be_code)
        if q is None:
            print("核价未完成：需已回填 productCode（缺少门店菜单时无法核价）。",
                  file=sys.stderr)

    if args.json:
        print(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2))
        return

    _fmt_order_plan(plan, r, args)

    # 真实下单：确认已在流程开头校验，此处只校验字段齐备性
    if not args.allow_order:
        return
    if not plan.is_ready():
        print("\n  已拒绝下单：字段未齐备，不做部分下单。", file=sys.stderr)
        for g in plan.blocking_gaps():
            print(f"     缺 {g.field} —— 由 {g.provided_by} 提供", file=sys.stderr)
        sys.exit(5)

    spec = BE_TYPES[args.pickup]
    try:
        result = planner.create_order(
            store_code=args.store_code, order_type=spec["orderType"],
            be_type=spec["beType"],
            items=[{"productCode": i.product_code, "quantity": i.quantity}
                   for i in plan.items],
            confirmed_by_user=True, be_code=args.be_code,
            take_way_code=(plan.quote or {}).get("takeWayCode")
            if isinstance(plan.quote, dict) else None,
            remark=None,
        )
    except (PermissionError, ValueError) as exc:
        print(f"\n  下单被拒绝：{exc}", file=sys.stderr)
        sys.exit(6)

    print(BAR)
    print("  下单已提交")
    print(BAR)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1200])
    print(BAR)
    print("  支付在麦当劳侧完成：可通过支付链接扫码或打开麦当劳 App。")
    print("  支付完成后回复「支付完成」，可用 query-order 回查订单状态。")
    print(BAR)
    print(DISCLAIMER)


def _fmt_order_plan(plan, r, args) -> None:
    """输出可下单清单：订单项、缺口、引导。"""
    spec = BE_TYPES[plan.pickup]
    print(BAR)
    print(f"  可下单清单 · {plan.soul_name} · {spec['label']}")
    print(BAR)
    print("  ⚠ 这是一份清单，不是已生成的订单。本 Skill 默认不下单。")
    print(SUB)
    print("  订单项")
    for it in plan.items:
        code = it.product_code or "待匹配"
        print(f"     · {it.name:<24} ×{it.quantity}  "
              f"{it.kcal:>5.0f} kcal   编码 {code}")
    print(f"     合计 {plan.total_kcal:.0f} kcal · {len(plan.items)} 项")
    print(SUB)

    print("  还缺什么")
    if plan.gaps:
        for g in plan.gaps:
            print(f"     · {g.field:<22} {g.why}")
            print(f"       来源：{g.provided_by}")
    else:
        print("     · 无 —— 字段已齐全")
    print(SUB)

    if plan.quote:
        print("  核价结果（calculate-price，只读）")
        print(f"     {json.dumps(plan.quote, ensure_ascii=False)[:300]}")
        print(SUB)

    print("  接下来怎么做")
    for line in plan.guidance:
        print(f"     {line}")
    print(SUB)

    if not plan.is_ready():
        print(f"  字段未齐备，当前不可下单。缺 {len(plan.blocking_gaps())} 项阻塞字段。")
    else:
        print("  字段已齐备。若确需由本 Skill 代下单，需同时加 --allow-order 与 --confirm。")
        print("  两道开关缺一不可，且 --confirm 每次都要重新给出。")
    print(BAR)
    print(DISCLAIMER)


if __name__ == "__main__":
    # 参数与约束的非法输入转为人话，不向终端吐调用栈。
    # 栈只对开发者调试有用，对 CLI 使用者只是噪音，且会掩盖真正的错误原因。
    try:
        main()
    except ValueError as exc:
        print(f"参数不合法：{exc}", file=sys.stderr)
        print("请用 --help 查看可用参数及其取值范围。", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        sys.exit(130)
