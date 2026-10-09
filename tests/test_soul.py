"""麦麦 soul 搭子 · 回归测试（离线，无需 Token 与网络）

运行：
    python tests/test_soul.py

覆盖：
  A 人格向量层：取值域、基线人格、查表
  B 翻译层：约束映射是否符合人格方向（单调性）
  C 引擎层：营销名剔除、分级回退、约束遵守
  D 方案层：确定性、差异化、JSON 可序列化
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from nutrition import load_offline                       # noqa: E402
from soul import SOULS, SOUL_ORDER, get, closest_key     # noqa: E402
from soul_engine import (                                # noqa: E402
    recommend, verify_divergence, build_constraints, protein_floor,
    _candidate_pool, _is_marketing, _is_adventurous, RELAX_STEPS,
)

FOODS = load_offline(ROOT / "samples" / "nutrition-foods.raw.json")
FIXTURE = load_offline(ROOT / "tests" / "fixtures" / "synthetic_nutrition_week.json")

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  [PASS] {label}" + (f"  {detail}" if detail else ""))
    else:
        _failed += 1
        print(f"  [FAIL] {label}  {detail}")


def main() -> int:
    print("=" * 66)
    print("  麦麦 soul 搭子 · 回归测试")
    print("=" * 66)

    print("\n--- A · 人格向量层 ---")
    check("共 16 个人格", len(SOUL_ORDER) == 16, f"实际 {len(SOUL_ORDER)}")
    check("key 唯一无重复", len(set(SOUL_ORDER)) == len(SOUL_ORDER))
    dims = ("heat", "protein", "sodium", "variety", "indulgence", "adventure")
    bad = []
    for k in SOUL_ORDER:
        for d in dims:
            v = getattr(SOULS[k], d)
            if not (0.0 <= v <= 1.0):
                bad.append(f"{k}.{d}={v}")
    check("六维权重均在 [0,1]", not bad, "越界: " + ",".join(bad) if bad else "")
    check("每个维度都有差异（不塌缩）",
          all(len({getattr(SOULS[k], d) for k in SOUL_ORDER}) >= 8 for d in dims))
    check("基线人格「好人」六维接近中性",
          all(abs(getattr(SOULS["good"], d) - 0.5) <= 0.12 for d in dims),
          str({d: SOULS["good"].as_dict()["weights"][d] for d in dims}))
    check("按 key 可查", get("mum").name == "妈妈")
    check("按中文名可查", get("妈妈").key == "mum")
    try:
        get("不存在的人格")
        check("未知人格抛错", False)
    except KeyError:
        check("未知人格抛 KeyError", True)
    check("每人都有推荐口吻与选餐逻辑",
          all(SOULS[k].voice and SOULS[k].rationale for k in SOUL_ORDER))
    check("每人都有 provenance 溯源",
          all(SOULS[k].provenance for k in SOUL_ORDER))

    print("\n--- B · 翻译层：人格→约束方向正确 ---")
    # 热量单调性：heat 越高，预算越高
    heat_pairs = sorted(((SOULS[k].heat, k) for k in SOUL_ORDER))
    budgets = [build_constraints(SOULS[k], 650).target_kcal for _, k in heat_pairs]
    check("热量预算随 heat 单调不减",
          all(a <= b for a, b in zip(budgets, budgets[1:])),
          f"{heat_pairs[0][1]}:{budgets[0]} → {heat_pairs[-1][1]}:{budgets[-1]}")
    # 钠单调性：sodium 越高，上限越低
    na_pairs = sorted(((SOULS[k].sodium, k) for k in SOUL_ORDER))
    nas = [build_constraints(SOULS[k], 650).max_sodium for _, k in na_pairs]
    check("钠上限随 sodium 单调递减",
          all(a >= b for a, b in zip(nas, nas[1:])),
          f"{na_pairs[0][1]}:{nas[0]} → {na_pairs[-1][1]}:{nas[-1]}")
    # variety 与同品类上限负相关：variety 升序 → max_per_category 应单调不增
    va_pairs = sorted(((SOULS[k].variety, k) for k in SOUL_ORDER))
    caps = [build_constraints(SOULS[k], 650).max_per_category for _, k in va_pairs]
    check("多样性低 → 同品类上限更宽松（单调不增）",
          all(a >= b for a, b in zip(caps, caps[1:])),
          str(list(zip([p[1] for p in va_pairs], caps))))
    check("最高多样性人格严格禁止同品类重复",
          build_constraints(SOULS["miao"], 650).max_per_category == 1)
    check("最低多样性人格允许同品类多件",
          build_constraints(SOULS["zzzz"], 650).max_per_category >= 3)
    # 蛋白下限只给高蛋白人格（阈值 0.65）
    hi = [k for k in SOUL_ORDER if protein_floor(SOULS[k], 650) > 0]
    check("蛋白下限仅对高蛋白人格生效",
          all(SOULS[k].protein >= 0.65 for k in hi),
          "生效: " + ",".join(hi))
    check("高蛋白人格数量合理（2~6 个）", 2 <= len(hi) <= 6, f"{len(hi)} 个")
    check("低蛋白人格无下限",
          all(protein_floor(SOULS[k], 650) == 0
              for k in SOUL_ORDER if SOULS[k].protein < 0.65))

    print("\n--- C · 引擎层：数据清洗与回退 ---")
    mkt = [f.name for f in FOODS if _is_marketing(f)]
    check("营销命名品已被识别", len(mkt) >= 3, f"命中 {mkt}")
    for name in ("牛气满满", "专“薯鱼”你", "“苹板”支撑Pro"):
        in_pool = any(f.name == name for f in _candidate_pool(FOODS, SOULS["worker"]))
        check(f"「{name}」不在任何候选池", not in_pool)
    check("严格控钠人格候选池 ≤ 放纵人格",
          len(_candidate_pool(FOODS, SOULS["ohno"]))
          <= len(_candidate_pool(FOODS, SOULS["malo"])))
    check("高多样性人格允许 4 件",
          build_constraints(SOULS["miao"], 650).max_size == 4)
    check("低多样性人格限 3 件",
          build_constraints(SOULS["solo"], 650).max_size == 3)
    check("回退档位表非空且单调放宽",
          len(RELAX_STEPS) >= 3
          and RELAX_STEPS[0][1] == 1.0
          and all(RELAX_STEPS[i][1] <= RELAX_STEPS[i+1][1]
                  for i in range(len(RELAX_STEPS)-1)))

    print("\n--- D · 方案层：确定性 / 差异化 / 合规 ---")
    souls = [SOULS[k] for k in SOUL_ORDER]
    v = verify_divergence(FOODS, souls, 650)
    check("16 人格全部出解", v["souls_with_plans"] == 16,
          f"仅 {v['souls_with_plans']} 个出解")
    check("差异化成立（首选不唯一）", v["diverged"], f"{v['distinct_first_plans']} 种不同首选")
    check("差异化覆盖过半", v["distinct_first_plans"] >= 8,
          f"{v['distinct_first_plans']}/16")

    # 确定性：同输入必得同输出
    a = recommend(FOODS, SOULS["mum"], 650)["plans"]
    b = recommend(FOODS, SOULS["mum"], 650)["plans"]
    ka = ["|".join(sorted(f.name for f in p.items)) for p in a]
    kb = ["|".join(sorted(f.name for f in p.items)) for p in b]
    check("同输入结果完全一致（无随机）", ka == kb, f"{len(ka)} 个方案")

    # 约束遵守：所有方案都不得超钠上限与热量容差
    violations = []
    for k in SOUL_ORDER:
        r = recommend(FOODS, SOULS[k], 650)
        c = r["constraints"]
        for p in r["plans"]:
            if p.sodium > c.max_sodium:
                violations.append(f"{k} 钠{p.sodium:.0f}>{c.max_sodium:.0f}")
            if abs(p.kcal - c.target_kcal) / c.target_kcal > c.tolerance + 1e-9:
                violations.append(f"{k} 热量{p.kcal:.0f}偏离{c.target_kcal:.0f}")
    check("所有方案不违反其人格约束", not violations,
          "; ".join(violations[:3]) if violations else "")

    # 报告机制：放宽必须被如实记录
    ohno = recommend(FOODS, SOULS["ohno"], 650)
    check("无解人格经回退后有结果", len(ohno["plans"]) > 0)
    check("回退事实被如实记录（不静默放宽）", bool(ohno["relaxed"]),
          ohno["relaxed"][0][:60] if ohno["relaxed"] else "未记录")

    # 合成夹具下也能跑（证明不依赖真实菜单结构）
    r_fix = recommend(FIXTURE, SOULS["worker"], 650)
    check("合成夹具下同样可运行", True,
          f"出解 {len(r_fix['plans'])} 个")

    # JSON 可序列化
    payload = json.dumps(
        [{"soul": k, "signature": recommend(FOODS, SOULS[k], 650)["signature"]}
         for k in SOUL_ORDER], ensure_ascii=False)
    check("签名可 JSON 序列化", len(payload) > 0, f"{len(payload)} 字符")

    # 合规：不得出现品牌对比表述
    blob = " ".join(SOULS[k].rationale + SOULS[k].voice for k in SOUL_ORDER)
    banned = ["肯德基", "汉堡王", "必胜客", "更健康", "比其它", "减肥", "减脂", "掉秤"]
    hit = [b for b in banned if b in blob]
    check("人格文案无跨品牌对比与减重承诺", not hit, "命中: " + ",".join(hit) if hit else "")

    print("\n" + "=" * 66)
    total = _passed + _failed
    if _failed == 0:
        print(f"  ✓ 全部通过（{total} 项）")
    else:
        print(f"  ✗ {_failed} 项失败 / 共 {total} 项")
    print("=" * 66)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
