"""环境就绪检查：判定本 Skill 当前能否执行，以及能执行到哪一步。

只读，不安装、不登录、不授权、不修改配置，不输出任何凭据值。

用法：
    python scripts/check_environment.py           # 人类可读报告
    python scripts/check_environment.py --json    # 机器可读

退出码：
    0 ready / partial   可执行（partial 表示功能受限）
    1 needs_setup       缺必需配置
    2 unavailable       认证或服务不可用
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "nutrition-foods.raw.json"
DEFAULTS = ("MCP_URL", "MCP_TOKEN", "MCP_TIMEOUT")

TOKEN_DOC = "https://open.mcd.cn/mcp → 登录 → 控制台 → 激活 → 同意服务协议 → 复制"
MIN_PY = (3, 10)


def _py_ok() -> tuple[bool, str]:
    if sys.version_info < MIN_PY:
        return False, (f"Python {sys.version_info.major}.{sys.version_info.minor} "
                       f"低于要求的 {MIN_PY[0]}.{MIN_PY[1]}；"
                       f"源码使用 `X | None` 注解，需改写为 Optional[X]")
    return True, f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.minor} OK"


def _sample_state() -> tuple[bool, str]:
    if not SAMPLE.exists():
        return False, "samples/nutrition-foods.raw.json 不存在"
    size = SAMPLE.stat().st_size
    if size < 1000:
        return False, f"样本文件过小（{size} 字节），可能未完整拉取"
    return True, f"样本已就绪（{size:,} 字节），离线模式可用"


def _token_state() -> tuple[bool, str, bool]:
    """返回 (是否有 token, 描述, 是否可能是占位符)。"""
    tok = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not tok:
        return False, "环境变量 MCD_MCP_TOKEN 未设置", False
    if len(tok) < 16:
        return False, f"MCD_MCP_TOKEN 长度仅 {len(tok)}，疑似无效", True
    placeholder = any(m in tok.upper() for m in
                      ("YOUR_", "TOKEN_HERE", "PLACEHOLDER", "XXXX", "<"))
    return True, f"MCD_MCP_TOKEN 已设置（长度 {len(tok)}，不回显内容）", placeholder


def _net_state() -> tuple[bool, str]:
    """只做 DNS 与 TCP 探测，不发起业务调用、不携带凭据。"""
    url = os.environ.get("MCD_MCP_URL", "https://mcp.mcd.cn").rstrip("/")
    host = url.split("//", 1)[-1].split("/", 1)[0]
    try:
        import socket
        socket.create_connection((host, 443), timeout=5).close()
        return True, f"{host}:443 可连接（未发起业务调用，未携带凭据）"
    except Exception as exc:                          # noqa: BLE001
        return False, f"{host}:443 不可达（{type(exc).__name__}）—— 离线模式不受影响"


def _probe_online() -> tuple[bool, str]:
    """仅在明确允许时，用最小代价验证 Token（tools/list，零业务副作用）。"""
    if os.environ.get("MCD_ALLOW_ONLINE_PROBE", "").strip() != "1":
        return True, "已跳过在线探测（设 MCD_ALLOW_ONLINE_PROBE=1 可开启，仅调用 tools/list）"
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from mcp_client import StreamableHTTPClient, mask_secret
        tools = StreamableHTTPClient().list_tools()
        return True, f"在线探测成功，可见 {len(tools)} 个工具"
    except Exception as exc:                          # noqa: BLE001
        return False, mask_secret(str(exc))


def assess(online_probe: bool = False) -> dict:
    py_ok, py_msg = _py_ok()
    sm_ok, sm_msg = _sample_state()
    tk_ok, tk_msg, tk_placeholder = _token_state()
    net_ok, net_msg = _net_state()
    if online_probe and py_ok and tk_ok and net_ok:
        probe_ok, probe_msg = _probe_online()
    else:
        probe_ok, probe_msg = True, "未触发（需 Python + Token + 网络齐备）"

    can_offline = py_ok and sm_ok
    can_online = py_ok and tk_ok and net_ok and not tk_placeholder

    if not py_ok:
        status, action = "unavailable", "升级 Python 或改写类型注解"
    elif can_offline:
        status = "ready" if can_online else "partial"
        action = ("全部功能可用" if can_online
                  else "离线功能可用；联网取数不可用，输出会标注数据来源为仓库样本")
    elif can_online:
        status, action = "partial", "联网可用；缺样本，离线复现路径不可用"
    else:
        status = "needs_setup"
        action = "补齐下列必需配置后重试"

    return {
        "status": status,
        "action": action,
        "capabilities": {
            "offline_replay": can_offline,
            "online_fetch": can_online,
        },
        "checks": {
            "python": {"ok": py_ok, "detail": py_msg},
            "sample": {"ok": sm_ok, "detail": sm_msg},
            "token": {"ok": tk_ok, "detail": tk_msg,
                      "suspicious_placeholder": tk_placeholder},
            "network": {"ok": net_ok, "detail": net_msg},
            "online_probe": {"ok": probe_ok, "detail": probe_msg},
        },
        "missing": [name for name, ok in (
            ("MCD_MCP_TOKEN", tk_ok), ("samples/nutrition-foods.raw.json", sm_ok),
        ) if not ok],
        "token_help": TOKEN_DOC,
        "env_vars": {
            "MCD_MCP_TOKEN": "必需（仅联网模式）。仅从环境变量读取，绝不写入文件",
            "MCD_MCP_URL": f"选填，默认 https://mcp.mcd.cn",
            "MCD_MCP_TIMEOUT": "选填，默认 60 秒",
            "MCD_ALLOW_ONLINE_PROBE": "设为 1 才允许在线探测 tools/list",
        },
        "note": "本检查不安装、不登录、不授权、不修改配置，且不回显任何凭据值",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="环境就绪检查")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    r = assess(online_probe=os.environ.get("MCD_ALLOW_ONLINE_PROBE") == "1")

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("=" * 62)
        print("  麦麦 soul 搭子 · 环境就绪检查")
        print("=" * 62)
        print(f"  状态: {r['status'].upper()}")
        print(f"  结论: {r['action']}")
        print("-" * 62)
        for name, c in r["checks"].items():
            print(f"  [{'OK' if c['ok'] else '--'}] {name:14} {c['detail']}")
        print("-" * 62)
        print(f"  离线复现  : {'可用' if r['capabilities']['offline_replay'] else '不可用'}")
        print(f"  联网取数  : {'可用' if r['capabilities']['online_fetch'] else '不可用'}")
        if r["missing"]:
            print(f"  缺失项    : {', '.join(r['missing'])}")
            print(f"  Token 获取: {r['token_help']}")
        print(f"  说明      : {r['note']}")
        print("=" * 62)
        if r["status"] == "partial" and not r["capabilities"]["online_fetch"]:
            print("  降级提示：联网不可用时，加 --offline samples/nutrition-foods.raw.json")
            print("            仍可完成全部人格推荐与对比，输出会标注数据来源。")

    return {"ready": 0, "partial": 0, "needs_setup": 1, "unavailable": 2}[r["status"]]


if __name__ == "__main__":
    sys.exit(main())
