"""Windows regression: the role-gated MCP gateway must import.

Root cause of the P0 issue: mcp 2.x removed ``mcp.server.fastmcp`` while
``danus.gateway`` (and the write-paper / human-summary MCP services) import it.
The dependency must stay pinned to the 1.x line until the code is migrated.
"""
from __future__ import annotations


def test_gateway_importable() -> None:
    import danus.gateway  # noqa: F401  (import must not raise)


def test_gateway_builds_mcp_app() -> None:
    from danus.gateway.server import build_app

    app = build_app()
    assert app is not None