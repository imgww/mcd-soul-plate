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

from nutrition import load_offline, fetch_foods, detect_unknown_fields
from composer import diagnose
from soul import SOULS, SOUL_ORDER, get, closest_key
from soul_engine import recommend, verify_divergence, build_constraints

DISCLAIMER = ("本项目为麦当劳程序员节创意开发大赛参赛作品，非麦当劳官方产品。"
              "输出仅供参考，不构成医疗、营养或其他专业建议；"
              "餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。")

BAR = "═" * 66
SUB = "─" * 66


def _load(args) -> tuple[list, object | None]:
    if args.offline:
        return load_offline(args.offline), None
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


if __name__ == "__main__":
    main()
