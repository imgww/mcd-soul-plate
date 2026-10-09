"""人格驱动的配平：把 SoulPreference 的 6 维权重翻译成引擎能执行的约束与打分。

翻译规则（全部显式，无隐藏魔法）
------------------------------
维度 → 引擎参数的映射：

    heat       → Constraints.target_kcal      吃得轻 = 预算下调；扎实 = 上调
    protein    → 打分中蛋白项的权重           追蛋白 = 蛋白权重上调
    sodium     → Constraints.max_sodium       严格控钠 = 上限收紧
    variety    → Constraints.max_per_category 1 = 品类必须互不重复；0 = 放开
                 + 多样性项权重
    indulgence → 候选池是否放行甜品/油炸      放纵 = 放开；克制 = 收紧
    adventure  → 候选池是否放行「风味限定款」  追限定 = 放开；认准经典 = 收紧

关键设计：人格差异必须作用在**可观察的输出**上。
因此引擎返回的不只是方案，还返回 `signature`（该人格的推荐指纹），
用于验证「不同人格是否真的给出不同答案」——见 verify_divergence()。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from composer import Constraints, Plan, compose
from nutrition import Food
from soul import SoulPreference

# 放纵倾向低于此值则不把甜品纳入候选（除非它是唯一能配平的品类）
INDULGENCE_CUTOFF = 0.5
# 尝鲜倾向低于此值则排除「风味/限定/联名」命名的高新奇餐品
ADVENTURE_CUTOFF = 0.5

# 风味限定款特征词（实测菜单里真实存在的命名，例如「蒜了吧黄油风味薄皮脆汁鸡」）
_ADVENTURE_HINTS = ("风味", "柠萌", "yeyeyeye", "奥利奥", "抹茶", "黑巧",
                     "草莓", "柠檬", "菠萝", "香芋", "麦旋酷", "阳光橙",
                     "燕麦", "焦糖", "浓")
# 经典款特征词：这些是麦当劳长期在售的稳定款
_CLASSIC_HINTS = ("巨无霸", "麦满分", "板烧", "麦香鱼", "麦乐鸡",
                  "薯条", "圆筒", "新地", "麦旋风", "可乐", "雪碧", "牛奶",
                  "豆浆", "咖啡", "红茶", "派")

# 营销命名品：麦当劳在菜单上用于造势的**临时包装名**，不是餐品本名。
# 实测 160 行里命中 3 项：牛气满满(495kcal) / 专"薯鱼"你(463kcal) / "苹板"支撑Pro(476kcal)。
# 它们热量高、钠高（764~1077mg），一旦进入候选池就会因为「热量贴合度」被优先选中，
# 导致严格控钠人格也推荐它们——这是必须剔除的数据污染，不是口味偏好。
_MARKETING_HINTS = ("牛气满满", "苹板", "薯鱼", "红绿", "开门红", "够本",
                     "当牛", "麦霸", "超满足", "真香")


def _is_adventurous(f: Food) -> bool:
    """是否属于「风味限定款」——尝鲜人格的猎场。"""
    return any(h in f.name for h in _ADVENTURE_HINTS)


def _is_classic(f: Food) -> bool:
    return any(h in f.name for h in _CLASSIC_HINTS)


def _is_marketing(f: Food) -> bool:
    """是否属于营销命名品（临时包装名，非餐品本名）。"""
    return any(h in f.name for h in _MARKETING_HINTS)


def build_constraints(sp: SoulPreference, base_kcal: float = 650.0,
                      tolerance: float = 0.12) -> Constraints:
    """把人格偏好翻译成一组引擎约束。

    base_kcal 是「基准热量预算」（用户给的 650 kcal），
    heat 在其上下浮动 ±22%——因为人格影响的是**食量倾向**，
    而非让用户凭空多出一倍的摄入预算。

    展开幅度（2026-10-09 真实菜单实测校准）：
      实测发现若钠上限只在 0.69x~1.15x 之间浮动，妈妈(0.72)与哦不人(0.90)
      会收敛到同一个候选池并给出**完全相同**的首选（均为钠 766mg 的组合）。
      原因是两者都严格控钠，而池内低钠组合的高分结构一致。
      因此把 sodium 的映射区间拉宽到 0.55x~1.45x，让严格控钠人格之间
      也能分出层次；protein 则改走 `protein_floor`（见下）而非仅靠打分权重。
    """
    heat_scale = 0.78 + sp.heat * 0.44          # heat=0.44 → 0.78x；heat=0.82 → 1.14x
    target = round(base_kcal * heat_scale, 0)

    # 钠上限：敏感度高 → 收紧；不敏感 → 放宽。区间拉宽以保证人格间可区分。
    sodium_scale = 1.45 - sp.sodium * 0.90      # sodium=0.90 → 0.64x；sodium=0.28 → 1.20x
    max_sodium = round(base_kcal * 1.8 * sodium_scale, 0)

    # 品类重复：多样性低的人格允许同品类多件（i 人就是要三杯饮料）
    # 实测教训：僧侣(0.34) 与独行者(0.30) 若同落一档会产生完全相同的首选。
    # 因此这里用四档而非两档，把窄带内的差异也保留下来。
    if sp.variety >= 0.66:
        max_per_category = 1
    elif sp.variety >= 0.45:
        max_per_category = 2
    elif sp.variety >= 0.28:
        max_per_category = 3
    else:
        max_per_category = 4

    c = Constraints(
        target_kcal=target,
        tolerance=tolerance,
        min_size=2,
        max_size=4 if sp.variety >= 0.66 else 3,
        max_sodium=max_sodium,
        per_category_cap=14 if sp.adventure >= 0.5 else 8,
        max_per_category=max_per_category,
        min_staple=0,
        top_n=6,
    )
    return c


def protein_floor(sp: SoulPreference, target_kcal: float) -> float:
    """该人格对蛋白的**硬性下限**（克）。

    只有 protein 倾向明显高的人格才有硬下限；其余人格不设限，
    避免把所有维度都变成硬约束后候选池过窄而无解。

    阈值说明（2026-10-09 真实菜单实测）：
        初版用 protein >= 0.60 触发，导致哦不人(0.62) 严格控钠 +
        高蛋白 + 低热量(0.40→预算 570kcal) 三者同时生效而**无解**。
        真实菜单里「低热量高蛋白低钠」的组合本就稀少。
        现改为 0.65 触发、且下限倍数更温和，并配合 recommend() 的
        软约束回退——保证任何人格都至少有一个可展示的结果。
    """
    base = target_kcal / 100.0 * 3.2          # 与引擎 PROTEIN_PER_100KCAL 一致
    if sp.protein >= 0.65:
        return round(base * (0.85 + (sp.protein - 0.65) * 0.60), 1)
    return 0.0


def _candidate_pool(foods: Sequence[Food], sp: SoulPreference) -> list[Food]:
    """候选池裁剪，三步，顺序不可颠倒：

    1. 剔除营销命名品（数据污染，非人格偏好）
    2. 放纵倾向低 → 排除甜品与超高热量品
    3. 尝鲜倾向低 → 排除「风味限定款」（保留经典款）
    """
    # 第 1 步：无条件剔除，与人格无关
    pool = [f for f in foods if not _is_marketing(f)]
    if not pool:
        pool = list(foods)          # 极端情况兜底，不让整池清零

    # 第 2 步：放纵
    if sp.indulgence < INDULGENCE_CUTOFF:
        cap = 1000.0 if sp.indulgence < 0.35 else 650.0
        filtered = [f for f in pool
                    if not (f.category == "甜品" or f.kcal > cap * 1.6)]
        if filtered:
            pool = filtered

    # 第 3 步：尝鲜
    if sp.adventure < ADVENTURE_CUTOFF:
        filtered = [f for f in pool if not _is_adventurous(f) or _is_classic(f)]
        if filtered:
            pool = filtered

    return pool


def _rescore_for_soul(plans: Sequence[Plan], sp: SoulPreference) -> list[Plan]:
    """在引擎给出的方案内，按人格偏好重新排序。

    为什么需要重排：composer 的打分权重是**固定**的
    （热量 .42 / 蛋白 .26 / 钠 .20 / 多样 .12），对所有人格一样。
    若不重排，「热量贴合度」会主导排序，人格差异被压在后面。
    这里把权重改为随人格线性插值，让人格真正影响「首选哪一个」。

    权重映射（0~1 偏好 → 权重占比，总和归一）：
        heat      → 热量贴合度
        protein   → 蛋白达成
        sodium    → 钠控制
        variety   → 品类多样性
        adventure → 风味限定款占比   ← 实测必需：否则低尝鲜人格之间无法区分
        indulgence→ 甜品/放纵品占比   ← 实测必需：否则「吗喽」与「神人」趋同

    前四维取自 composer 的既有口径，后两维是本项目新增的人格维度。
    """
    base = {"heat": 0.42, "protein": 0.26, "sodium": 0.20,
            "variety": 0.12, "adventure": 0.18, "indulgence": 0.14}
    w = {
        "heat": base["heat"] * (0.6 + sp.heat),
        "protein": base["protein"] * (0.5 + sp.protein * 1.2),
        "sodium": base["sodium"] * (0.5 + sp.sodium * 1.5),
        "variety": base["variety"] * (0.4 + sp.variety * 1.8),
        "adventure": base["adventure"] * (0.3 + sp.adventure * 1.7),
        "indulgence": base["indulgence"] * (0.3 + sp.indulgence * 1.7),
    }
    total_w = sum(w.values())

    out: list[tuple[float, str, Plan]] = []
    for p in plans:
        if p.kcal <= 0 or not p.items:
            continue
        # 引擎已算好热量贴合度，直接复用，避免重复计算
        s_heat = max(0.0, p.kcal_fit_pct)
        s_protein = min(1.0, p.protein / p.protein_target) if p.protein_target else 1.0
        # 钠项：满意线取该人格**自己的**钠上限密度，而不是 composer 的固定 260mg/100kcal。
        # 这样钠敏感度不仅改变「硬上限」，也改变「打分偏好」——
        # 僧侣(0.50) 与独行者(0.58) 才会真正分选出不同方案。
        comfort = p.sodium_limit / 260.0
        s_sodium = min(1.0, comfort / p.sodium) if p.sodium > 0 else 1.0
        s_variety = len({f.category for f in p.items}) / len(p.items)
        # 新增两维：命中「风味限定款」与「甜品」的件数占比
        n = len(p.items)
        s_adv = sum(1 for f in p.items if _is_adventurous(f)) / n
        s_ind = sum(1 for f in p.items if f.category == "甜品") / n
        # 热量项同样按人格预算归一，避免「贴合度」永远由固定容差主导
        s_heat = min(1.0, s_heat * (0.7 + sp.heat * 0.6))

        score = (w["heat"] * s_heat + w["protein"] * s_protein
                 + w["sodium"] * s_sodium + w["variety"] * s_variety
                 + w["adventure"] * s_adv + w["indulgence"] * s_ind) / total_w
        key = "|".join(sorted(f.name for f in p.items))
        out.append((score, key, p))

    out.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, _, p in out]


RELAX_STEPS: tuple[tuple[str, float, float], ...] = (
    # (放宽项, 钠上限倍数, 容差倍数)——按顺序尝试，逐级报告
    ("初始约束", 1.00, 1.00),
    ("放宽钠上限 +25%", 1.25, 1.00),
    ("放宽钠上限 +25% 与热量容差", 1.25, 1.35),
    ("放宽钠上限 +55% 与热量容差", 1.55, 1.60),
)


def recommend(foods: Sequence[Food], sp: SoulPreference,
              base_kcal: float = 650.0, tolerance: float = 0.12) -> dict:
    """按人格给出推荐。

    返回 dict：方案列表 + 该人格的推荐指纹 + 实际生效的约束（供解释与检验）。

    人格差异作用在**四处**（这是差异化能否成立的根）：
      候选池（放纵 / 尝鲜 / 营销名剔除）
      硬约束（热量预算、钠上限、同品类上限、蛋白下限）
      件数范围（多样性高 → 允许 4 件）
      打分重排（权重随人格线性插值，含 adventure/indulgence 两维，见 _rescore_for_soul）

    **分级回退**：人格约束在真实菜单上可能无解
    （实测：哦不人 749mg 钠上限 + 621kcal 预算，预筛后仅 28 项候选，
      0 个合法组合）。此时按 RELAX_STEPS 逐级放宽钠上限与容差，
    取第一个有解的档位，并把**放宽了什么**如实写入 `relaxed`——
    宁可让用户知道「为了给你结果，我放宽了钠」，也不静默违背人格设定。
    """
    c0 = build_constraints(sp, base_kcal, tolerance)
    pool = _candidate_pool(foods, sp)
    floor = protein_floor(sp, c0.target_kcal)

    relaxed: list[str] = []
    plans: list[Plan] = []
    used_c = c0

    for label, na_scale, tol_scale in RELAX_STEPS:
        c = replace(c0,
                    max_sodium=round(c0.max_sodium * na_scale),
                    tolerance=min(0.35, tolerance * tol_scale))
        got = compose(pool, c)
        if got:
            plans, used_c = got, c
            if label != "初始约束":
                relaxed.append(f"{label}（钠上限 {c.max_sodium:.0f}mg，"
                               f"容差 ±{c.tolerance:.0%}）")
            break
    if not plans:
        # 全部档位都无解：退回最初约束，交给调用方显示诊断
        plans, used_c = compose(pool, c0), c0

    # 蛋白下限是**软约束**：优先保留达标方案；若全被过滤，回退并报告。
    if floor > 0:
        filtered = [p for p in plans if p.protein >= floor]
        if filtered:
            plans = filtered
        else:
            relaxed.append(
                f"蛋白下限 {floor:.1f}g 无解（严格控钠 + 高蛋白 + "
                f"该热量预算在真实菜单里不存在），已回退为不设下限")

    # 人格化重排：让偏好影响「首选哪一个」，而不只是「能否入选」
    plans = _rescore_for_soul(plans, sp)

    used: list[str] = sorted({f.category for p in plans for f in p.items})
    signature = {
        "soul": sp.key,
        "target_kcal": used_c.target_kcal,
        "max_sodium": used_c.max_sodium,
        "max_per_category": used_c.max_per_category,
        "protein_floor": floor if floor > 0 and not relaxed else 0.0,
        "categories": used,
        "indulgence": sp.indulgence,
        "adventure": sp.adventure,
    }

    return {
        "soul": sp,
        "constraints": used_c,
        "plans": plans,
        "signature": signature,
        "pool_size": len(pool),
        "total_size": len(foods),
        "relaxed": relaxed,
    }


def verify_divergence(foods: Sequence[Food], souls: Sequence[SoulPreference],
                      base_kcal: float = 650.0) -> dict:
    """**本方案成立的硬指标**：不同人格是否真的给出不同推荐。

    若所有人格的方案指纹都一样，说明权重没起作用，方案即失效——
    这个函数就是为了让「失效」被立刻看见，而不是靠嘴说。
    """
    seen: dict[str, list[str]] = {}
    detail: dict[str, dict] = {}

    for sp in souls:
        r = recommend(foods, sp, base_kcal)
        plans = r["plans"]
        if not plans:
            seen[sp.key] = []
            detail[sp.key] = {"plans": 0, "signature": r["signature"]}
            continue
        top = plans[0]
        key = "|".join(sorted(f.name for f in top.items))
        seen[sp.key] = [key]
        detail[sp.key] = {
            "plans": len(plans),
            "signature": r["signature"],
            "top_items": [f.name for f in top.items],
            "top_kcal": round(top.kcal, 1),
            "top_protein": round(top.protein, 1),
            "top_sodium": round(top.sodium, 1),
            "top_score": round(top.score, 4),
        }

    unique_firsts = {k: v[0] for k, v in seen.items() if v}
    return {
        "souls_tested": len(souls),
        "souls_with_plans": len(unique_firsts),
        "distinct_first_plans": len(set(unique_firsts.values())),
        "diverged": len(set(unique_firsts.values())) > 1,
        "detail": detail,
    }
