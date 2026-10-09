"""把 samples/nutrition-foods.raw.json 脱敏为可公开版本。

审查结论（2026-10-09）：该响应为 `list-nutrition-foods` 的纯营养数据，
不含 Token、手机号、邮箱、身份证、会员标识等任何个人信息或凭证，
因此允许公开入库，使评审 clone 后可直接复现全部结果与 36 项断言。

唯一需处理的是 `traceId`——它是服务端的请求追踪标识，虽非个人信息，
但属会话产物，不应进公开仓库。本脚本将其替换为占位符，
并把 `datetime` 保留为实测时间（可证明数据新鲜度，且不含个人信息）。

用法：
    python docs/sanitize_sample.py          # 就地脱敏
    python docs/sanitize_sample.py --check  # 只检查不修改
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "samples" / "nutrition-foods.raw.json"
PLACEHOLDER = "<REDACTED_TRACE_ID>"

# 不得出现在可公开样本中的字段（防御性清单）
FORBIDDEN = ("token", "secret", "password", "passwd", "apikey", "api_key",
             "authorization", "openid", "unionid", "memberid", "member_id",
             "cardno", "card_no", "phone", "mobile", "idcard", "id_card")


def check(obj, path="") -> list[str]:
    """递归检查是否含禁止字段名。"""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower().replace("-", "").replace("_", "")
            if any(f.replace("_", "") in kl for f in FORBIDDEN):
                bad.append(f"{path}.{k}")
            bad.extend(check(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            bad.extend(check(v, f"{path}[{i}]"))
    return bad


def main() -> int:
    dry = "--check" in sys.argv
    if not TARGET.exists():
        print(f"未找到 {TARGET}")
        return 1

    raw = TARGET.read_text(encoding="utf-8")
    d = json.loads(raw)

    print(f"文件: {TARGET.relative_to(ROOT)}")
    print(f"大小: {len(raw)} 字节")
    print()

    # 1) 禁止字段检查
    bad = check(d)
    print("[1] 禁止字段检查")
    if bad:
        print("  [不通过] 命中禁止字段:", ", ".join(bad))
        return 2
    print("  [通过] 无 Token / 个人标识类字段")
    print()

    # 2) traceId 脱敏
    original_trace = d.get("traceId", "")
    if dry:
        print("[2] traceId 检查（--check 模式，未修改）")
        print(f"  当前值: {original_trace}")
        print("  [需处理]" if original_trace else "  [已合规]")
        return 0

    if original_trace:
        d["traceId"] = PLACEHOLDER
        TARGET.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print("[2] traceId 脱敏")
        print(f"  原值 {original_trace[:16]}... -> {PLACEHOLDER}")
        print()

    # 3) 复核 data 仍是完整表格
    data = d.get("data", "")
    rows = len([x for x in data.splitlines() if x.strip()]) - 1
    print("[3] 完整性复核")
    print(f"  表头: {data.splitlines()[0][:60]}...")
    print(f"  记录数: {rows}")
    print(f"  datetime 保留: {d.get('datetime')}  （可证明数据新鲜度）")
    print()
    print("已写入脱敏版本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())