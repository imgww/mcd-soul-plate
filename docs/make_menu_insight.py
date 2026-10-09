"""生成「真实菜单结构」图：从 MCP 实时样本统计，SVG → Chrome headless 渲染 PNG。

为什么需要这张图：154 项餐品里饮品 69 项（44.8%）多于主食 34 项，
这个反常识的结构事实是整个项目的数据起点，值得一张图说清。

用法：
    python docs/make_menu_insight.py
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from nutrition import load_offline   # noqa: E402

BG = "#F5F1E8"
CARD = "#FBF8F1"
RULE = "#CFC5AC"
INK = "#2C2C2A"
SUB = "#5F5E5A"
FAINT = "#A89F8C"
ACCENT = "#8C2F24"
GOLD = "#C9A227"

TONE = {"饮品": "#6B4A32", "主食": "#C9A227", "小食": "#A8703C",
        "甜品": "#C08A8A", "果蔬": "#7C8B5E", "其他": "#A89F8C"}

W, H = 1400, 720


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(foods) -> str:
    total = len(foods)
    cat = collections.Counter(f.category for f in foods)
    order = sorted(cat.items(), key=lambda kv: -kv[1])

    # 热量分档
    bands = [("0-99", 0, 100), ("100-199", 100, 200), ("200-299", 200, 300),
             ("300-399", 300, 400), ("400-499", 400, 500),
             ("500-699", 500, 700), ("700+", 700, 10 ** 9)]
    band_cnt = [sum(1 for f in foods if lo <= f.kcal < hi) for _, lo, hi in bands]
    band_max = max(band_cnt) or 1

    p = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        f'<rect x="0" y="0" width="{W}" height="5" fill="{ACCENT}"/>',
        f'<text x="40" y="46" font-size="13" letter-spacing="4" '
        f'font-family="Georgia, serif" fill="{ACCENT}">WHAT THE DATA ACTUALLY SAYS</text>',
        f'<text x="40" y="82" font-size="34" font-weight="bold" '
        f'font-family="Georgia, \'Songti SC\', serif" fill="{INK}">'
        f'菜单的重心不是饭，是喝的</text>',
        f'<text x="40" y="108" font-size="14" '
        f'font-family="Georgia, \'Songti SC\', serif" fill="{SUB}">'
        f'数据源：麦当劳 MCP list-nutrition-foods 实时响应，160 行 → 去重归一化 '
        f'{total} 项真实餐品</text>',
    ]

    # ---- 左：品类占比条 ----
    cx, cy, cw = 40, 150, 620
    p.append(f'<rect x="{cx}" y="{cy}" width="{cw}" height="300" rx="7" '
             f'fill="{CARD}" stroke="{RULE}" stroke-width="1"/>')
    p.append(f'<text x="{cx + 20}" y="{cy + 30}" font-size="15" font-weight="bold" '
             f'font-family="Georgia, \'Songti SC\', serif" fill="{INK}">'
             f'品类分布 · 饮品占 {cat["饮品"] / total:.1%}</text>')

    by = cy + 52
    for name, cnt in order:
        color = TONE.get(name, "#A89F8C")
        w = cnt / total * 330
        p.append(
            f'<text x="{cx + 20}" y="{by + 13}" font-size="12" fill="{SUB}" '
            f'font-family="Georgia, \'Songti SC\', serif">{name}</text>'
            f'<rect x="{cx + 84}" y="{by + 4}" width="330" height="14" rx="7" fill="#E9E1CE"/>'
            f'<rect x="{cx + 84}" y="{by + 4}" width="{w:.1f}" height="14" rx="7" fill="{color}"/>'
            f'<text x="{cx + 424}" y="{by + 15}" font-size="12" fill="{INK}" '
            f'font-family="Consolas, monospace">{cnt}</text>'
            f'<text x="{cx + 466}" y="{by + 15}" font-size="11" fill="{FAINT}" '
            f'font-family="Consolas, monospace">{cnt / total:.1%}</text>'
        )
        by += 32

    # ---- 右：热量分布 ----
    rx, ry, rw = 686, 150, 674
    p.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="300" rx="7" '
             f'fill="{CARD}" stroke="{RULE}" stroke-width="1"/>')
    p.append(f'<text x="{rx + 20}" y="{ry + 30}" font-size="15" font-weight="bold" '
             f'font-family="Georgia, \'Songti SC\', serif" fill="{INK}">'
             f'热量分布 · 半数在 300 kcal 以下</text>')

    gx0, gy0, gw, gh = rx + 70, ry + 60, 560, 180
    n = len(bands)
    slot = gw / n
    for i, ((label, _, _), cnt) in enumerate(zip(bands, band_cnt)):
        h = cnt / band_max * gh
        bx = gx0 + i * slot + slot * 0.18
        bw = slot * 0.64
        color = ACCENT if i >= 4 else (GOLD if i >= 2 else "#8FA9A0")
        p.append(
            f'<rect x="{bx:.1f}" y="{gy0 + gh - h:.1f}" width="{bw:.1f}" '
            f'height="{h:.1f}" rx="3" fill="{color}"/>'
            f'<text x="{bx + bw / 2:.1f}" y="{gy0 + gh - h - 6:.1f}" '
            f'text-anchor="middle" font-size="12" fill="{INK}" '
            f'font-family="Consolas, monospace">{cnt}</text>'
            f'<text x="{bx + bw / 2:.1f}" y="{gy0 + gh + 18:.1f}" '
            f'text-anchor="middle" font-size="10.5" fill="{FAINT}" '
            f'font-family="Consolas, monospace">{label}</text>'
        )
    p.append(f'<line x1="{gx0}" y1="{gy0 + gh}" x2="{gx0 + gw}" y2="{gy0 + gh}" '
             f'stroke="{RULE}" stroke-width="1"/>')
    p.append(f'<text x="{rx + 20}" y="{gy0 + gh + 46}" font-size="11" fill="{FAINT}" '
             f'font-family="Georgia, \'Songti SC\', serif">'
             f'单位 kcal · 高热量项（≥500）仅 {sum(band_cnt[5:])} 个，'
             f'说明「配一顿控卡餐」的约束空间其实很大</text>')

    # ---- 下：三条实测结论 ----
    by2 = 480
    notes = [
        ("没有品类字段", "响应里不存在 category/分类 字段，品类由商品名关键词推断得出（派生字段）"),
        ("有 3 项营销命名品", "牛气满满 / 专“薯鱼”你 / “苹板”支撑Pro —— 热量高钠高，必须无条件剔除"),
        ("data 是字符串表格", "形如 [160]{productName,energyKcal,...}: 不是 JSON 数组，需按表头解析"),
    ]
    bw3 = 424
    for i, (t, d) in enumerate(notes):
        x = 40 + i * (bw3 + 24)
        p.append(
            f'<rect x="{x}" y="{by2}" width="{bw3}" height="112" rx="7" '
            f'fill="{CARD}" stroke="{RULE}" stroke-width="1"/>'
            f'<rect x="{x}" y="{by2}" width="4" height="112" rx="2" fill="{ACCENT}"/>'
            f'<text x="{x + 20}" y="{by2 + 30}" font-size="14" font-weight="bold" '
            f'font-family="Georgia, \'Songti SC\', serif" fill="{INK}">{esc(t)}</text>'
        )
        # 手动折行
        words, line, lines = d, "", []
        for ch in words:
            line += ch
            if len(line) >= 26:
                lines.append(line)
                line = ""
        if line:
            lines.append(line)
        for j, ln in enumerate(lines[:3]):
            p.append(
                f'<text x="{x + 20}" y="{by2 + 54 + j * 19}" font-size="11.5" '
                f'fill="{SUB}" font-family="Georgia, \'Songti SC\', serif">{esc(ln)}</text>'
            )

    p.append(f'<text x="40" y="{H - 26}" font-size="11" fill="{FAINT}" '
             f'font-family="Georgia, \'Songti SC\', serif">'
             f'全部数字可复现：python src/soul_plate.py --compare --offline samples/nutrition-foods.raw.json'
             f'</text>')
    p.append(f'<text x="{W - 40}" y="{H - 26}" text-anchor="end" font-size="11" '
             f'fill="{FAINT}" font-family="Georgia, \'Songti SC\', serif">'
             f'参赛作品 · 非麦当劳官方产品</text>')
    p.append("</svg>")
    return "".join(p)


if __name__ == "__main__":
    foods = load_offline(ROOT / "samples" / "nutrition-foods.raw.json")
    out = Path(__file__).resolve().parent / "menu_insight.svg"
    out.write_text(build(foods), encoding="utf-8")
    print(f"已生成 {out}")
    print(f"餐品 {len(foods)} 项")
