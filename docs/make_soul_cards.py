"""生成 README 用的 16 人格总览卡片（SVG → 由 Chrome headless 渲染为 PNG）。

从 src/soul.py 读取真实人格数据，保证图与代码永不脱节。
用法：
    python docs/make_soul_cards.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from soul import SOUL_ORDER, SOULS, DIM_LABELS   # noqa: E402

# Economist/FT 编辑风配色（与 banner.svg 一致）
BG = "#F5F1E8"
CARD = "#FBF8F1"
RULE = "#CFC5AC"
INK = "#2C2C2A"
SUB = "#5F5E5A"
FAINT = "#A89F8C"
ACCENT = "#8C2F24"
GOLD = "#C9A227"

W, H = 1400, 1090
COLS, ROWS = 4, 4
CW, CH = 316, 208
GX, GY = 18, 16
X0, Y0 = 40, 128

TONE = ["#B5453A", "#C9A227", "#7C8B5E", "#6B7B8C",
        "#C08A8A", "#A8703C", "#8C6D9B", "#4E7A7A",
        "#B07C3C", "#9B6B6B", "#5F6E96", "#A64B5F",
        "#6E8B4A", "#8C7B4A", "#4F7B8C", "#8A5A7A"]


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def bars(sp) -> str:
    """六维偏好横向条。"""
    out = []
    y = 0
    for d in ("heat", "protein", "sodium", "variety", "indulgence", "adventure"):
        v = getattr(sp, d)
        w = v * 92
        color = ACCENT if v >= 0.66 else (GOLD if v >= 0.34 else "#AFA395")
        out.append(
            f'<text x="16" y="{y + 8}" font-size="9.5" fill="{SUB}" '
            f'font-family="system-ui, sans-serif">{DIM_LABELS[d]}</text>'
            f'<rect x="66" y="{y + 2}" width="92" height="6" rx="3" fill="#E6DEC9"/>'
            f'<rect x="66" y="{y + 2}" width="{w:.1f}" height="6" rx="3" fill="{color}"/>'
            f'<text x="164" y="{y + 8}" font-size="9" fill="{FAINT}" '
            f'font-family="Consolas, monospace">{v:.2f}</text>'
        )
        y += 13
    return "".join(out)


def build() -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        f'<rect x="0" y="0" width="{W}" height="5" fill="{ACCENT}"/>',
        # 标题区
        f'<text x="{X0}" y="46" font-size="13" letter-spacing="4" '
        f'font-family="Georgia, serif" fill="{ACCENT}">THE 16 SOULS</text>',
        f'<text x="{X0}" y="82" font-size="34" font-weight="bold" '
        f'font-family="Georgia, \'Songti SC\', serif" fill="{INK}">16 种人格，16 套进食偏好</text>',
        f'<text x="{X0}" y="108" font-size="14" '
        f'font-family="Georgia, \'Songti SC\', serif" fill="{SUB}">'
        f'每张卡下方六条即为该人格的六维权重，由人格短评推导，可手工修改后复跑对比</text>',
    ]

    for i, key in enumerate(SOUL_ORDER):
        sp = SOULS[key]
        r, c = divmod(i, COLS)
        x = X0 + c * (CW + GX)
        y = Y0 + r * (CH + GY)
        tone = TONE[i % len(TONE)]

        parts.append(
            f'<g transform="translate({x},{y})">'
            # 卡底
            f'<rect x="0" y="0" width="{CW}" height="{CH}" rx="7" '
            f'fill="{CARD}" stroke="{RULE}" stroke-width="1"/>'
            # 顶部色条
            f'<rect x="0" y="0" width="{CW}" height="4" rx="2" fill="{tone}"/>'
            # 序号圆点
            f'<circle cx="24" cy="30" r="11" fill="{tone}"/>'
            f'<text x="24" y="34" text-anchor="middle" font-size="11" '
            f'font-weight="bold" font-family="Georgia, serif" fill="#FBF8F1">{i + 1}</text>'
            # 人格名
            f'<text x="44" y="27" font-size="17" font-weight="bold" '
            f'font-family="Georgia, \'Songti SC\', serif" fill="{INK}">{esc(sp.name)}</text>'
            f'<text x="44" y="42" font-size="10" font-family="Consolas, monospace" '
            f'fill="{FAINT}">{sp.key}</text>'
            # 短评
            f'<text x="16" y="62" font-size="10.5" fill="{SUB}" '
            f'font-family="Georgia, \'Songti SC\', serif">{esc(sp.tagline[:26])}</text>'
            f'<line x1="16" y1="72" x2="{CW - 16}" y2="72" stroke="{RULE}" stroke-width="0.6"/>'
            # 六维条
            f'<g transform="translate(0,82)">{bars(sp)}</g>'
            # 口吻
            f'<text x="16" y="{CH - 30}" font-size="10.5" font-style="italic" '
            f'fill="{tone}" font-family="Georgia, \'Songti SC\', serif">'
            f'“{esc(sp.voice[:17])}”</text>'
            # 约束摘要
            f'<text x="16" y="{CH - 12}" font-size="9" fill="{FAINT}" '
            f'font-family="Consolas, monospace">钠上限 {round(650 * 1.8 * (1.45 - sp.sodium * 0.90))}mg'
            f' · 预算 {round(650 * (0.78 + sp.heat * 0.44))}kcal</text>'
            f'</g>'
        )

    # 页脚
    fy = Y0 + ROWS * CH + (ROWS - 1) * GY + 34
    parts.append(
        f'<text x="{X0}" y="{fy}" font-size="11" fill="{FAINT}" '
        f'font-family="Georgia, \'Songti SC\', serif">'
        f'权重为本项目自建，非官方数据 · 全部维度可在 src/soul.py 手工修改并复跑 '
        f'python src/soul_plate.py --compare 验证</text>'
    )
    parts.append(
        f'<text x="{W - X0}" y="{fy}" text-anchor="end" font-size="11" fill="{FAINT}" '
        f'font-family="Georgia, \'Songti SC\', serif">'
        f'数据源：麦当劳 MCP list-nutrition-foods · 154 项真实餐品</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "soul_cards.svg"
    out.write_text(build(), encoding="utf-8")
    print(f"已生成 {out}")
    print(f"人格数 {len(SOUL_ORDER)} · 画布 {W}x{H}")
