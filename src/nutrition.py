"""`list-nutrition-foods` 返回结果的取数与字段归一化。

真实响应格式（2026-10-09 实测校准，见 samples/nutrition-foods.raw.json）
--------------------------------------------------------------------
外层是标准业务信封：

    {"success": true, "code": 200, "message": "请求成功",
     "datetime": "2026-10-09 15:44:08", "traceId": "...",
     "data": "<字符串表格>"}

**关键坑：`data` 不是数组，也不是对象，而是一段带表头的字符串表格**——

    [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,
          carbohydrate,sodium,calcium}:
      猪柳麦满分,null,1288,308,16,16,24,781,213
      ...

首行 `[N]{列名...}:` 声明行数与列名，其后每行一条记录、两空格缩进、逗号分隔、
缺失值用字面量 `null`。实测 160 行每行恰好 8 个逗号（9 字段），无引号包裹、
字段内无逗号，因此朴素 split 是安全的；但仍按表头列数严格校验，不匹配的行跳过。

单位与字段：energyKcal=kcal、energyKj=kJ、protein/fat/carbohydrate=g、
sodium/calcium=mg，全部为整数值。

另两条实测结论（会影响其他模块的行为，改动前请先读）：

1. **响应里没有品类/分类字段。** 因此 `category` 由商品名关键词推断得到
   （见 `_CATEGORY_RULES`），属于本项目派生字段而非麦当劳返回数据。
   `composer._enforce_category_cap` 依赖品类区分度，若日后上游补上真实分类字段，
   应优先用上游值、把推断降为兜底。
2. **存在同名重复行**（实测 160 行 / 158 个唯一名，「小杯玉米杯」与「纯牛奶（盒装）」
   各重复一次且数值完全相同）。配平引擎以商品名为唯一键，故此处按整行去重。

同时保留对「字典列表」结构的兼容，`tests/fixtures/` 里的合成夹具走的就是那条路径。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

TOOL_NAME = "list-nutrition-foods"

# 逻辑字段 -> 可能出现的键名。前 8 项为实测真实键名，其余为兼容别名。
# 比对前会做归一化（转小写、去括号内单位、去分隔符）。
_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("productName", "name", "foodname", "itemname", "title",
             "餐品名称", "名称", "品名", "商品名称"),
    "kcal": ("energyKcal", "energy", "kcal", "calorie", "calories", "heat",
             "能量", "热量", "能量kcal", "热量kcal"),
    "energy_kj": ("energyKj", "energykj", "能量kj", "能量千焦"),
    "protein": ("protein", "proteing", "proteincontent", "蛋白质", "蛋白质g"),
    "fat": ("fat", "fatg", "totalfat", "脂肪", "总脂肪", "脂肪g"),
    "carb": ("carbohydrate", "carb", "carbs", "totalcarbohydrate",
             "碳水化合物", "碳水", "糖", "碳水化合物g"),
    "sodium": ("sodium", "na", "salt", "sodiumcontent", "钠", "钠mg", "盐"),
    "calcium": ("calcium", "ca", "钙", "钙mg"),
    "category": ("category", "type", "foodtype", "classification", "cate",
                 "分类", "品类", "类别", "餐品分类"),
    "desc": ("nutritionDescription", "description", "营养说明", "说明"),
}

# 明确不可单点的周边/耗材。注意：**不能**放「杯」「盒装」——
# 实测真实菜单里「大杯玉米杯」「可乐中杯」「纯牛奶（盒装）」都是正常在售餐品。
_EXCLUDE_HINTS = ("玩具", "周边", "纸巾", "酱包", "餐具", "手提袋", "贴纸", "徽章")

# 品类由商品名关键词推断（上游无该字段）。规则按顺序命中，先匹配者胜，
# 因此把「更像正餐」的词放在前面，避免「鲜蔬蛋沙拉叠叠卷」被判成果蔬。
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("主食", ("麦满分", "堡", "营养卷", "叠叠卷", "多笋卷", "早安卷", "粥",
             "板烧", "巨无霸", "安格斯", "麦香")),
    ("果蔬", ("玉米杯", "苹果片", "蔬菜", "沙拉", "多肉")),
    ("甜品", ("冰淇淋", "圆筒", "新地", "麦旋风", "拉明顿", "奶冻", "雪冰",
             "阿芙佳朵", "香芋派", "菠萝派", "爆珠", "派")),
    ("饮品", ("可乐", "雪碧", "咖啡", "红茶", "豆浆", "美式", "奶铁", "燕麦奶",
             "牛奶", "苹果汁", "阳光橙", "黑巧", "抹茶", "卡布奇诺", "玛奇朵",
             "朱古力", "纯悦", "怡泉", "橙", "浓缩")),
    ("小食", ("薯条", "薯饼", "麦乐鸡", "鸡翅", "V翅", "双翅", "鸡排", "脆汁鸡",
             "鸡球", "鱼排", "油条", "脆鸡扒", "香肠", "图林根", "薄皮", "蜜汁",
             "趣鸡", "麦辣")),
)


@dataclass
class Food:
    name: str
    kcal: float = 0.0
    protein: float = 0.0
    fat: float = 0.0
    carb: float = 0.0
    sodium: float = 0.0
    calcium: float = 0.0
    category: str = "其他"
    category_derived: bool = False          # True = 本项目推断，非 MCP 返回
    desc: str = ""
    energy_kj: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def macro_pdr(self) -> float:
        """简易蛋白密度：每 100 kcal 含多少克蛋白质。"""
        return (self.protein / self.kcal * 100.0) if self.kcal > 0 else 0.0

    def sodium_load(self) -> float:
        """每 100 kcal 携带多少毫克钠（越低越好）。"""
        return (self.sodium / self.kcal * 100.0) if self.kcal > 0 else 0.0


def _norm_key(k: str) -> str:
    s = str(k).strip().lower()
    s = re.sub(r"[（(].*?[)）]", "", s)          # 去括号内单位说明
    s = re.sub(r"[\s_\-/·、，,。.]", "", s)       # 去分隔符
    return s


def _pick(obj: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    normed = {_norm_key(k): v for k, v in obj.items() if isinstance(k, str)}
    for a in aliases:
        na = _norm_key(a)
        if na in normed and normed[na] not in (None, ""):
            return normed[na]
    for k, v in normed.items():                    # 再退一步做包含匹配
        for a in aliases:
            na = _norm_key(a)
            if na and v not in (None, "") and (na in k or k in na):
                return v
    return None


def _num(v: Any) -> float:
    """把 308 / '253千卡' / '12.5g' / '≈80' / '1,200' 抽成 float。"""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", "").replace("，", ""))
    return float(m.group()) if m else 0.0


_TABLE_HEADER = re.compile(r"^\[(\d+)\]\{(.+)\}:\s*$")


def _parse_string_table(text: str) -> list[dict[str, Any]]:
    """解析麦当劳真实返回的 `[N]{cols}:` + 逐行 CSV 字符串表格。"""
    lines = text.splitlines()
    start = -1
    cols: list[str] = []
    for i, ln in enumerate(lines):
        m = _TABLE_HEADER.match(ln.strip())
        if m:
            cols = [c.strip() for c in m.group(2).split(",")]
            start = i + 1
            break
    if start < 0 or not cols:
        return []
    recs: list[dict[str, Any]] = []
    for ln in lines[start:]:
        row = ln.strip()
        if not row:
            continue
        vals = [v.strip() for v in ln.split(",")]   # 不 strip 前导缩进以外的部分
        if len(vals) != len(cols):
            continue                                 # 结构异常行，跳过而非猜
        recs.append({c: (None if v in ("null", "") else v)
                     for c, v in zip(cols, vals)})
    return recs


def _iter_records(payload: Any) -> list[dict[str, Any]]:
    """从工具返回里挖出「餐品记录列表」，兼容真实字符串表格与字典/列表结构。"""
    if isinstance(payload, str):
        return _parse_string_table(payload)
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    # 真实响应的 data 是字符串表格，优先走这条
    for key in ("data", "result", "list", "items", "foods", "nutritionFoods",
                "records", "rows", "content", "foodList", "nutritionList"):
        if key not in payload:
            continue
        val = payload[key]
        if isinstance(val, str):
            recs = _parse_string_table(val)
            if recs:
                return recs
            continue
        sub = _iter_records(val)
        if sub:
            return sub
    out: list[dict[str, Any]] = []
    for v in payload.values():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            out.extend(v)
    return out


def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按整行内容去重（实测存在同名同值的重复行）。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in records:
        key = json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def infer_category(name: str) -> tuple[str, bool]:
    """返回 (品类, 是否为推断值)。上游无品类字段，故全部为推断。"""
    for cat, kws in _CATEGORY_RULES:
        for kw in kws:
            if kw.lower() in name.lower():
                return cat, True
    return "其他", True


def parse_foods(payload: Any) -> list[Food]:
    """归一化为 Food 列表。

    丢弃规则：无名称、命中周边耗材词、能量缺失或为 0（无法参与热量配平）。
    """
    foods: list[Food] = []
    for rec in _dedupe(_iter_records(payload)):
        name = _pick(rec, _FIELDS["name"])
        if not name:
            continue
        name = str(name).strip()          # 只去首尾空白：品名里的全角引号是官方命名的一部分
        if not name or any(h in name for h in _EXCLUDE_HINTS):
            continue
        kcal = _num(_pick(rec, _FIELDS["kcal"]))
        if kcal <= 0:
            continue
        upstream_cat = _pick(rec, _FIELDS["category"])
        if upstream_cat and str(upstream_cat).strip():
            category, derived = str(upstream_cat).strip(), False
        else:
            category, derived = infer_category(name)
        foods.append(Food(
            name=name,
            kcal=kcal,
            protein=_num(_pick(rec, _FIELDS["protein"])),
            fat=_num(_pick(rec, _FIELDS["fat"])),
            carb=_num(_pick(rec, _FIELDS["carb"])),
            sodium=_num(_pick(rec, _FIELDS["sodium"])),
            calcium=_num(_pick(rec, _FIELDS["calcium"])),
            category=category,
            category_derived=derived,
            desc=str(_pick(rec, _FIELDS["desc"]) or "").strip(),
            energy_kj=_num(_pick(rec, _FIELDS["energy_kj"])),
            raw=rec,
        ))
    foods.sort(key=lambda f: f.kcal)
    return foods


def fetch_foods(client, dump_path: str | None = None) -> tuple[list[Food], Any]:
    """调用 MCP 拉取营养数据。返回 (归一化餐品, 原始 payload)。"""
    payload = client.call_tool(TOOL_NAME, {})
    if dump_path:
        with open(dump_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    return parse_foods(payload), payload


def load_offline(path: str) -> list[Food]:
    """从已留存的样本 JSON 读取，便于无 Token 复现。"""
    with open(path, encoding="utf-8") as fh:
        return parse_foods(json.load(fh))


def detect_unknown_fields(payload: Any) -> list[str]:
    """当归一化结果为空时，打印真实键名帮助校准。"""
    recs = _iter_records(payload)
    if not recs:
        kind = type(payload).__name__
        hint = ""
        if isinstance(payload, dict):
            hint = f"，顶层键={list(payload.keys())}"
            d = payload.get("data")
            if isinstance(d, str):
                hint += f"，data 为字符串（前 80 字符）={d[:80]!r}"
        return [f"(未识别到记录列表，顶层类型={kind}){hint}"]
    return sorted({k for r in recs[:5] if isinstance(r, dict) for k in r.keys()})
