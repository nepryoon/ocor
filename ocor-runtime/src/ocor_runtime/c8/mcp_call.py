"""C8 boundary for one MCP tool call that carries its own governed context.

FABLE52-POST-POC-PROGRAMME (2026-11-11) point 1 and ADD v1.3 line 382. There is no
protocol session and no ``initialize`` handshake. Every call supplies
``governed_context_ref``. A call that omits it, or an argument object that tries to
carry the same field, is refused with ``CAPABILITY_DENIED``. The referenced record
is immutable. This module is not an MCP server, does not speak MCP ``_meta``, and
is not the production capability broker in ``tool_runtime.py``. A successful
return checks the transport ref required by point 1(c). It does not admit a tool
for execution.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

_CONTEXT_REF = re.compile(r"urn:sha256:[0-9a-f]{64}\Z")
_CONTEXT_FIELD = "governed_context_ref"
# Deep payloads are walked on an explicit stack. Past this depth the call is
# refused; the interpreter recursion limit is not the bound.
_MAX_ARGUMENT_DEPTH = 4096


class McpCallError(ValueError):
    """A caller-controlled MCP call was refused with a closed reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        if reason_code != "CAPABILITY_DENIED":
            raise ValueError("the MCP call boundary refuses only with CAPABILITY_DENIED")
        if not isinstance(message, str) or not message or len(message) > 512:
            raise ValueError("MCP call message must be bounded and non-empty")
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _deny(message: str) -> McpCallError:
    return McpCallError("CAPABILITY_DENIED", message)


class GovernedContextRegistry:
    """Immutable map from a governed-context digest to the record it names."""

    def __init__(self) -> None:
        self._records: dict[str, Mapping[str, Any]] = {}

    def register(self, governed_context_ref: str, record: object) -> None:
        ref = _require_ref(governed_context_ref)
        if ref in self._records:
            raise _deny("a governed context ref cannot be registered twice")
        if not isinstance(record, Mapping):
            raise _deny("a governed context record must be a JSON object")
        self._records[ref] = _freeze(record)

    def resolve(self, governed_context_ref: str) -> Mapping[str, Any]:
        ref = _require_ref(governed_context_ref)
        try:
            return self._records[ref]
        except KeyError:
            raise _deny("the governed context ref is unknown") from None


def call_tool(
    *,
    tool_name: str,
    arguments: object,
    governed_context_ref: str | None = None,
    registry: object,
) -> Mapping[str, Any]:
    """Call ``tool_name`` with arguments and the transport's governed context ref.

    The first call needs no handshake. ``registry`` resolves the ref to the frozen
    record registered for it. The returned mapping is frozen.
    """

    if not isinstance(registry, GovernedContextRegistry):
        raise _deny("a governed context registry is required")
    if not isinstance(tool_name, str) or not tool_name:
        raise _deny("a tool name is required")
    if not isinstance(arguments, Mapping):
        raise _deny("tool arguments must be an object")
    if _contains_context_field(arguments):
        raise _deny("governed_context_ref is transport-origin and cannot be supplied in arguments")
    if governed_context_ref is None or governed_context_ref == "":
        raise _deny("a tool call requires its own governed_context_ref")
    record = registry.resolve(governed_context_ref)
    frozen_arguments = _freeze(arguments)
    if not isinstance(frozen_arguments, Mapping):
        raise _deny("tool arguments must be an object")
    return MappingProxyType(
        {
            "arguments": frozen_arguments,
            "governed_context": record,
            "governed_context_ref": _require_ref(governed_context_ref),
            "origin": "TRANSPORT",
            "tool_name": tool_name,
        }
    )


def _require_ref(value: object) -> str:
    if not isinstance(value, str) or _CONTEXT_REF.fullmatch(value) is None:
        raise _deny("governed_context_ref must be a lowercase SHA-256 URN")
    return value


def _contains_context_field(value: object) -> bool:
    stack: list[tuple[object, int, tuple[int, ...]]] = [(value, 0, ())]
    while stack:
        current, depth, path = stack.pop()
        if depth > _MAX_ARGUMENT_DEPTH:
            raise _deny("decoded arguments exceed the depth bound")
        if isinstance(current, str) or current is None or isinstance(current, (bool, int, float)):
            continue
        if isinstance(current, (bytes, bytearray, memoryview)):
            continue
        identity = id(current)
        if identity in path:
            raise _deny("decoded arguments contain a cycle")
        if isinstance(current, Mapping):
            if _CONTEXT_FIELD in current:
                return True
            child_path = path + (identity,)
            for item in current.values():
                stack.append((item, depth + 1, child_path))
            continue
        if isinstance(current, Sequence):
            child_path = path + (identity,)
            for item in current:
                stack.append((item, depth + 1, child_path))
    return False


def _reject_surrogate(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _deny("a governed context record contains a lone surrogate")


def _freeze(root: object) -> Any:
    stack: list[dict[str, Any]] = [{"node": root, "depth": 0, "path": (), "phase": "enter"}]
    results: list[Any] = []
    while stack:
        frame = stack[-1]
        node = frame["node"]
        depth = frame["depth"]
        if depth > _MAX_ARGUMENT_DEPTH:
            raise _deny("decoded arguments exceed the depth bound")
        if frame["phase"] != "enter":
            if frame["phase"] == "exit-map":
                frozen_keys = frame["keys"]
                count = len(frozen_keys)
                values = results[-count:] if count else []
                if count:
                    del results[-count:]
                results.append(MappingProxyType(dict(zip(frozen_keys, values, strict=True))))
            else:
                count = frame["count"]
                values = results[-count:] if count else []
                if count:
                    del results[-count:]
                results.append(tuple(values))
            stack.pop()
            continue
        if isinstance(node, str):
            _reject_surrogate(node)
            results.append(node)
            stack.pop()
            continue
        if isinstance(node, bool) or node is None or isinstance(node, int):
            results.append(node)
            stack.pop()
            continue
        if isinstance(node, float):
            if not math.isfinite(node):
                raise _deny("a governed context record contains a non-finite number")
            results.append(node)
            stack.pop()
            continue
        if isinstance(node, (bytes, bytearray, memoryview)):
            raise _deny("a governed context record must be JSON")
        identity = id(node)
        if identity in frame["path"]:
            raise _deny("decoded arguments contain a cycle")
        child_path = frame["path"] + (identity,)
        if isinstance(node, Mapping):
            keys: list[str] = []
            for key in node:
                if not isinstance(key, str):
                    raise _deny("a governed context record must be JSON")
                _reject_surrogate(key)
                keys.append(key)
            frame["phase"] = "exit-map"
            frame["keys"] = keys
            for key in reversed(keys):
                stack.append({"node": node[key], "depth": depth + 1, "path": child_path, "phase": "enter"})
            continue
        if isinstance(node, Sequence):
            frame["phase"] = "exit-seq"
            frame["count"] = len(node)
            for item in reversed(tuple(node)):
                stack.append({"node": item, "depth": depth + 1, "path": child_path, "phase": "enter"})
            continue
        raise _deny("a governed context record must be JSON")
    if len(results) != 1:
        raise _deny("a governed context record must be JSON")
    return results[0]
