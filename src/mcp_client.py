"""极简麦当劳 MCP 客户端：streamable HTTP + JSON-RPC 2.0，仅用 Python 标准库。

设计约束
--------
* Token 只从环境变量读取，绝不写入源码、日志或异常信息。
* 只做本 Skill 需要的最小调用面：initialize -> tools/list -> tools/call。
* 服务端为无状态模式（响应头不下发 mcp-session-id），因此不维护会话，
  但会正确透传服务端返回的 session id（若将来有状态）。

环境变量
--------
MCD_MCP_TOKEN   必填。在 https://open.mcd.cn/mcp 控制台「激活」后获取。
MCD_MCP_URL     选填。默认 https://mcp.mcd.cn
MCD_MCP_TIMEOUT 选填。单次请求超时秒数，默认 60。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "mcd-weekly-plate"
CLIENT_VERSION = "0.1.0"


class MCPError(RuntimeError):
    """MCP 协议或传输层错误。消息中不包含 Token。"""


class StreamableHTTPClient:
    def __init__(self, url: str | None = None, token: str | None = None,
                 timeout: float | None = None) -> None:
        self.url = (url or os.environ.get("MCD_MCP_URL") or DEFAULT_URL).rstrip("/")
        self.token = token or os.environ.get("MCD_MCP_TOKEN") or ""
        if not self.token:
            raise MCPError(
                "缺少 MCP Token。请设置环境变量 MCD_MCP_TOKEN，"
                "或参考 mcp-config.example.json 在客户端中配置连接器。"
            )
        try:
            self.timeout = float(timeout or os.environ.get("MCD_MCP_TIMEOUT") or 60)
        except ValueError as exc:
            raise MCPError(f"MCD_MCP_TIMEOUT 不是合法数字：{exc}") from exc
        self._req_id = 0
        self._session_id: str | None = None
        self._initialized = False

    # ---------------- 传输 ----------------

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": f"{CLIENT_NAME}/{CLIENT_VERSION}",
        }
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    def _post(self, payload: dict[str, Any]) -> tuple[int, str, str | None]:
        """返回 (http_status, 解析出的 JSON 文本, content-type)。"""
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status, ctype = resp.status, (resp.headers.get("content-type") or "")
                sid = resp.headers.get("mcp-session-id")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            status, ctype = exc.code, (exc.headers.get("content-type") or "")
            sid = exc.headers.get("mcp-session-id")
        except urllib.error.URLError as exc:
            raise MCPError(f"无法连接 {self.url}：{exc.reason}") from exc

        if sid:
            self._session_id = sid
        return status, self._unwrap(raw, ctype), ctype

    @staticmethod
    def _unwrap(raw: str, ctype: str) -> str:
        """streamable HTTP 可能以 SSE 分帧返回，抽出 data: 行拼成 JSON 文本。"""
        if "text/event-stream" not in ctype and not raw.lstrip()[:5] in ("event", "data:"):
            return raw
        datas = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
        return "\n".join(datas) if datas else raw

    def _rpc(self, method: str, params: dict[str, Any] | None = None,
             notification: bool = False) -> Any:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            self._req_id += 1
            payload["id"] = self._req_id

        status, body, _ = self._post(payload)

        if notification:
            if status >= 400:
                raise MCPError(f"{method} 通知被拒绝：HTTP {status} {body[:200]}")
            return None

        try:
            msg = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError as exc:
            raise MCPError(f"{method} 响应不是合法 JSON（HTTP {status}）：{body[:200]}") from exc

        if isinstance(msg, dict) and "error" in msg:
            err = msg["error"]
            raise MCPError(f"{method} 失败：[{err.get('code')}] {err.get('message')}")
        return msg.get("result", msg) if isinstance(msg, dict) else msg

    # ---------------- MCP 语义 ----------------

    def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return {}
        result = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        })
        self._rpc("notifications/initialized", notification=True)
        self._initialized = True
        return result if isinstance(result, dict) else {}

    def list_tools(self) -> list[dict[str, Any]]:
        """返回全部工具定义（自动翻页）。"""
        self.initialize()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params) or {}
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """调用工具，返回解包后的业务数据。

        优先取 structuredContent；否则把 content[].text 尝试 JSON 解析。
        isError=true 时抛 MCPError。
        """
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        if result.get("isError"):
            raise MCPError(f"工具 {name} 返回业务错误：{_flatten_content(result)[:400]}")
        if isinstance(result.get("structuredContent"), (dict, list)):
            return result["structuredContent"]
        text = _flatten_content(result)
        if not text:
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


def _flatten_content(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(parts)


def mask_secret(text: str) -> str:
    """兜底脱敏：任何异常信息里若混入 Token 值，替换为占位符。"""
    tok = os.environ.get("MCD_MCP_TOKEN") or ""
    if tok and len(tok) >= 8:
        text = text.replace(tok, "<REDACTED_TOKEN>")
    return re.sub(r"Bearer\s+[A-Za-z0-9._\-]{12,}", "Bearer <REDACTED_TOKEN>", text)
