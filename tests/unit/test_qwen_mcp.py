"""The Claude Code <-> Qwen MCP dev tool: real stdio MCP handshake, read-only safety, graceful failure."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _params(base_url: str = "http://127.0.0.1:9/v1") -> StdioServerParameters:
    # port 9 (discard) on loopback: nothing listens there, so the LLM is "down"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "pitwall.devtools.qwen_mcp"],
        env={"QWEN_BASE_URL": base_url, "CLAUDE_PROJECT_DIR": str(ROOT), "PITWALL_URL": "http://127.0.0.1:9"},
        cwd=str(ROOT),
    )


def _text(result: object) -> str:
    return " ".join(getattr(c, "text", "") for c in getattr(result, "content", []))


async def test_mcp_server_lists_read_only_tools_and_fails_gracefully() -> None:
    async with stdio_client(_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == {"qwen_status", "qwen_ask", "qwen_review_code", "qwen_generate_tests"}
        for t in tools.values():
            assert t.annotations is not None and t.annotations.read_only_hint is True
            assert t.annotations.destructive_hint is False

        status = await session.call_tool("qwen_status", {})
        assert "unreachable" in _text(status)

        down = await session.call_tool("qwen_ask", {"question": "hi"})
        assert down.is_error and "unavailable" in _text(down)

        escape = await session.call_tool("qwen_review_code", {"paths": ["../../etc/hosts"]})
        assert escape.is_error and "outside the project" in _text(escape)

        secret = await session.call_tool("qwen_review_code", {"paths": [".env"]})
        assert secret.is_error and "deny-listed" in _text(secret)

        data = await session.call_tool("qwen_review_code", {"paths": ["data/pitwall.sqlite3"]})
        assert data.is_error and "deny-listed" in _text(data)


def test_non_loopback_endpoint_is_refused() -> None:
    import os
    import subprocess

    env = {"QWEN_BASE_URL": "http://example.com/v1", "PATH": "/usr/bin:/bin"}
    if sys.platform == "win32":  # a Windows process needs SYSTEMROOT (and its own PATH) to start Python at all
        env.update(PATH=os.environ.get("PATH", ""), SYSTEMROOT=os.environ.get("SYSTEMROOT", r"C:\Windows"))
    r = subprocess.run(
        [sys.executable, "-m", "pitwall.devtools.qwen_mcp"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode != 0 and "loopback" in r.stderr
