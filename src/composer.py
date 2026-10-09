"""配平引擎：在给定热量预算下，从麦当劳餐品里搜出一餐「蛋白够、钠不超、品类不重复」的组合。

算法说明（可解释、确定性、无随机）
----------------------------------
1. 预筛：剔除单项热量已超预算 1.05 倍的餐品；按品类各保留若干最低热量候选，
   把组合规模压到可穷举的量级。
2. 穷举：对 size ∈ [min_size, max_size] 做 itertools.combinations 全枚举。
3. 打分：四项加权（热量贴合度 / 蛋白达成 / 钠控制 / 品类多样性），
   超钠直接淘汰。
4. 排序：分数降序，同分按名称字典序，保证同一输入必得同一输出。

这不是「最优解保证」，而是「可解释的近似穷举」——餐品数被预筛限制后，
实际就是在候选集内取全局最优，便于向用户解释「为什么推荐这几个」。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable, Sequence

from nutrition import Food

# 权重：热量贴合 > 蛋白达成 > 控钠 > 多样性
W_KCAL_FIT = 0.42
W_PROTEIN = 0.26
W_SODIUM = 0.20
W_VARIETY = 0.12

# 每 100 kcal 期望的蛋白质克数（用于把热量预算换算成蛋白目标）
PROTEIN_PER_100KCAL = 3.2
# 每 100 kcal 的钠「满意线」，低于此值得满分
SODIUM_COMFORT_PER_100KCAL = 260.0
# 被视为正餐主体的品类名（与 nutrition._CATEGORY_RULES 保持一致）
STAPLE_CATEGORY = "主食"


@dataclass
class Plan:
    items: tuple[Food, ...]
    kcal: float
    protein: float
    fat: float
    carb: float
    sodium: float
    calcium: float
    score: float
    kcal_fit_pct: float
    protein_target: float
    sodium_limit: float

    def as_dict(self) -> dict:
        return {
            "items": [{"name": f.name, "category": f.category, "kcal": f.kcal,
                       "protein": f.protein, "sodium": f.sodium} for f in self.items],
            "totals": {"kcal": round(self.kcal, 1), "protein": round(self.protein, 1),
                       "fat": round(self.fat, 1), "carb": round(self.carb, 1),
                       "sodium": round(self.sodium, 1), "calcium": round(self.calcium, 1)},
            "target_kcal": None,  # 由调用方填充
            "kcal_fit_pct": round(self.kcal_fit_pct, 3),
            "protein_target": round(self.protein_target, 1),
            "sodium_limit": round(self.sodium_limit, 1),
            "score": round(self.score, 4),
        }


@dataclass
class Constraints:
    target_kcal: float = 650.0
    tolerance: float = 0.10          # 允许 ±10% 热量偏差
    min_size: int = 2
    max_size: int = 4
    max_sodium: float | None = None  # 默认按 180mg/100kcal 推导
    per_category_cap: int = 10       # 预筛时每个品类保留的候选数
    max_per_category: int = 1        # 同一品类最多选几件（一餐不点两份主食）
    min_staple: int = 0              # 每餐至少几件「主食」；0=不强制
    top_n: int = 5

    def __post_init__(self) -> None:
        if self.target_kcal <= 0:
            raise ValueError("target_kcal 必须为正数")
        if self.min_size < 1 or self.max_size < self.min_size:
            raise ValueError("要求 min_size >= 1 且 max_size >= min_size")
        if self.max_sodium is None:
            self.max_sodium = round(self.target_kcal * 1.8, 0)  # 180 mg / 100 kcal


def _prefilter(foods: Sequence[Food], c: Constraints) -> list[Food]:
    ceiling = c.target_kcal * 1.05
    pool = [f for f in foods if 0 < f.kcal <= ceiling]
    by_cat: dict[str, list[Food]] = {}
    for f in pool:
        by_cat.setdefault(f.category, []).append(f)
    kept: list[Food] = []
    for cat in sorted(by_cat):
        # 同品类内按「蛋白密度高、钠负荷低」优先保留，而不是随便截断
        ranked = sorted(by_cat[cat], key=lambda f: (-f.macro_pdr(), f.sodium_load(), f.name))
        kept.extend(ranked[: c.per_category_cap])
    return kept


def _enforce_category_cap(pool: Sequence[Food], c: Constraints) -> bool:
    """仅当品类维度真的有区分度时才启用「同品类不重复」。

    实测 `list-nutrition-foods` **不返回品类字段**，category 由本项目按商品名关键词
    推断（见 nutrition.infer_category）。少数营销名会落到「其他」，因此这里保留
    区分度判定：万一推断整体失效（上游改了命名习惯），去重不会把方案空间清零。
    """
    distinct = {f.category for f in pool}
    return len(distinct) >= 3 and c.max_per_category >= 1


def _staple_requirement(pool: Sequence[Food], c: Constraints) -> int:
    """主食下限同样只在品类可区分时生效，否则一律返回 0。"""
    if c.min_staple <= 0:
        return 0
    return c.min_staple if STAPLE_CATEGORY in {f.category for f in pool} else 0


def _score(items: tuple[Food, ...], c: Constraints, cap_cat: bool = False,
           staple_min: int = 0) -> tuple[float, float] | None:
    kcal = sum(f.kcal for f in items)
    if kcal <= 0:
        return None
    if cap_cat and len({f.category for f in items}) != len(items):
        return None                                   # 同品类重复，淘汰
    if staple_min and sum(1 for f in items if f.category == STAPLE_CATEGORY) < staple_min:
        return None                                   # 缺主食，淘汰
    protein = sum(f.protein for f in items)
    sodium = sum(f.sodium for f in items)
    if sodium > c.max_sodium:
        return None                                   # 超钠直接淘汰

    dev = abs(kcal - c.target_kcal) / c.target_kcal
    if dev > c.tolerance:
        return None                                   # 超出热量容差
    s_kcal = 1.0 - dev / c.tolerance

    protein_target = c.target_kcal / 100.0 * PROTEIN_PER_100KCAL
    s_protein = min(1.0, protein / protein_target) if protein_target else 1.0

    comfort = c.target_kcal / 100.0 * SODIUM_COMFORT_PER_100KCAL
    s_sodium = min(1.0, comfort / sodium) if sodium > 0 else 1.0

    cats = {f.category for f in items}
    s_variety = len(cats) / len(items)

    total = (W_KCAL_FIT * s_kcal + W_PROTEIN * s_protein
             + W_SODIUM * s_sodium + W_VARIETY * s_variety)
    return total, 1.0 - dev


def compose(foods: Sequence[Food], c: Constraints | None = None) -> list[Plan]:
    """返回按分数降序的方案列表；无解时返回空列表。"""
    c = c or Constraints()
    pool = _prefilter(foods, c)
    if not pool:
        return []
    cap_cat = _enforce_category_cap(pool, c)
    staple_min = _staple_requirement(pool, c)

    scored: list[tuple[float, str, tuple[Food, ...]]] = []
    for size in range(c.min_size, c.max_size + 1):
        if len(pool) < size:
            break
        for combo in itertools.combinations(pool, size):
            res = _score(combo, c, cap_cat, staple_min)
            if res is None:
                continue
            total, fit = res
            key = "|".join(sorted(f.name for f in combo))
            scored.append((total, key, combo))

        # 性能护栏：候选已远超所需时不再枚举更大件数组合。
        # 真实菜单 154 项时，size=4 一层就要算约 48 万个组合，而前面几层通常
        # 已攒下上千个有效方案。提前跳出可把周模式从几十秒压到秒级，
        # 代价是极大件数组合不参与排序——这是有意的取舍，不是遗漏。
        if len(scored) >= max(c.top_n * 8, 400):
            break

    if not scored:
        return []
    scored.sort(key=lambda x: (-x[0], x[1]))

    protein_target = c.target_kcal / 100.0 * PROTEIN_PER_100KCAL
    plans: list[Plan] = []
    seen: set[str] = set()
    for total, key, combo in scored:
        if key in seen:
            continue
        seen.add(key)
        kcal = sum(f.kcal for f in combo)
        _, fit = _score(combo, c, cap_cat, staple_min)
        plans.append(Plan(
            items=combo,
            kcal=kcal,
            protein=sum(f.protein for f in combo),
            fat=sum(f.fat for f in combo),
            carb=sum(f.carb for f in combo),
            sodium=sum(f.sodium for f in combo),
            calcium=sum(f.calcium for f in combo),
            score=total,
            kcal_fit_pct=fit,
            protein_target=protein_target,
            sodium_limit=c.max_sodium,
        ))
        if len(plans) >= c.top_n:
            break
    return plans


def diagnose(foods: Sequence[Food], c: Constraints) -> str:
    """无解时给出人话解释，帮助用户放宽约束。"""
    if not foods:
        return "没有可用餐品：营养数据为空或字段未校准（见 src/nutrition.py 的 TODO(实测)）。"
    pool = _prefilter(foods, c)
    if not pool:
        return (f"预筛后无候选：所有餐品单项热量都超过预算上限 "
                f"{c.target_kcal * 1.05:.0f} kcal，请提高 --kcal。")
    return (f"候选 {len(pool)} 项（共 {len(foods)} 项）在 "
            f"±{c.tolerance:.0%} 热量容差 / 钠 ≤{c.max_sodium:.0f}mg / "
            f"{c.min_size}-{c.max_size} 件 的约束下无解，"
            f"试试放宽 --tolerance 或提高 --max-sodium。")


def format_plan(plan: Plan, target_kcal: float, idx: int) -> str:
    bar = "─" * 58
    rows = []
    for f in sorted(plan.items, key=lambda x: (-x.kcal, x.name)):
        rows.append(f"     · {f.name:<16} [{f.category:<6}] "
                    f"{f.kcal:>6.0f} kcal | 蛋白 {f.protein:>5.1f} g | 钠 {f.sodium:>6.0f} mg")
    head = (f"  方案 {idx}  得分 {plan.score:.3f}   "
            f"热量贴合 {plan.kcal_fit_pct:.0%}   "
            f"蛋白 {plan.protein:.1f}/{plan.protein_target:.1f} g   "
            f"钠 {plan.sodium:.0f}/{plan.sodium_limit:.0f} mg")
    body = "\n".join(rows)
    total = (f"     合计  {plan.kcal:.0f} kcal（目标 {target_kcal:.0f}±10%）  "
             f"蛋白 {plan.protein:.1f} g  脂肪 {plan.fat:.1f} g  "
             f"碳水 {plan.carb:.1f} g  钠 {plan.sodium:.0f} mg  钙 {plan.calcium:.0f} mg")
    return f"{head}\n{body}\n{total}\n{bar}"


def iter_categories(foods: Iterable[Food]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in foods:
        out[f.category] = out.get(f.category, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
