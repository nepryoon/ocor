"""C2 admission of an MCP tool call.

ADD v1.3 line 382 names the C2 tool boundary as an enforcement point for
``governed_context_ref``. This function delegates to the C8 call so the two
surfaces cannot drift. It does not open a session, run a handshake, or speak an
MCP transport. Query admission stays on the named-query gateway.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..c8.mcp_call import call_tool


def admit_mcp_tool_call(
    *,
    tool_name: str,
    arguments: object,
    governed_context_ref: str | None = None,
    registry: object,
) -> Mapping[str, Any]:
    """Admit one MCP tool call. The decision is the C8 call, unchanged."""

    return call_tool(
        tool_name=tool_name,
        arguments=arguments,
        governed_context_ref=governed_context_ref,
        registry=registry,
    )
