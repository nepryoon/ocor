"""Library-only probe for the cycle 11 realignment.

referencing 0.37.0 and Draft202012Validator on the tool schema alone.
This file does not import ocor_runtime.
"""

from __future__ import annotations

import json
import platform
from importlib.metadata import version
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import PointerToNowhere, Unresolvable
from referencing.jsonschema import DRAFT202012

BASE = "urn:ocor:embedded-tool:0:inputSchema"

PLANTED = (
    ("truncated-percent", "#/$defs/%", {"%": {"type": "string"}}),
    ("truncated-digit", "#/$defs/%2", {"%2": {"type": "string"}}),
    ("non-hex", "#/$defs/%ZZ", {"%ZZ": {"type": "string"}}),
    ("non-hex-digit", "#/$defs/%2G", {"%2G": {"type": "string"}}),
    ("trailing-percent", "#/$defs/a%", {"a%": {"type": "string"}}),
    ("embedded-non-hex", "#/$defs/a%ZZb", {"a%ZZb": {"type": "string"}}),
    ("incomplete-utf8", "#/$defs/%C3", {"%C3": {"type": "string"}}),
    ("incomplete-utf8-lower", "#/$defs/%c3", {"%c3": {"type": "string"}}),
    ("bad-continuation", "#/$defs/%C3%28", {"%C3%28": {"type": "string"}}),
    ("overlong", "#/$defs/%C0%80", {"%C0%80": {"type": "string"}}),
    ("surrogate", "#/$defs/%ED%A0%80", {"%ED%A0%80": {"type": "string"}}),
    ("surrogate-lower", "#/$defs/%ed%a0%80", {"%ed%a0%80": {"type": "string"}}),
    ("lone-continuation", "#/$defs/%80", {"%80": {"type": "string"}}),
    ("embedded-continuation", "#/$defs/a%80b", {"a%80b": {"type": "string"}}),
    ("after-valid-encoding", "#/$defs/a%20b/%", {"a%20b": {"%": {"type": "string"}}}),
    (
        "non-final-segment",
        "#/$defs/%ZZ/properties/name",
        {"%ZZ": {"type": "object", "properties": {"name": {"type": "string"}}}},
    ),
)

TILDE = (
    ("verdict-tilde-two", "~2", "~2"),
    ("verdict-lone-tilde", "~", "~"),
    ("verdict-embedded", "a~3b", "a~3b"),
    ("tilde-three", "~3", "~3"),
    ("tilde-letter", "~a", "~a"),
    ("double-tilde", "~~", "~~"),
    ("trailing-tilde", "abc~", "abc~"),
    ("after-valid-escape", "~0~2", "~~2"),
    ("encoded-tilde-two", "%7E2", "~2"),
    ("encoded-lone-tilde", "%7E", "~"),
    ("non-final", "~2/type", "~2"),
)

FIELDS = ("inputSchema", "outputSchema")
POSITIONS = ("properties", "$defs", "allOf", "const", "default", "examples")
KEYS = ("a/b", "a~b", "café", "2")


def _schema(definitions: dict[str, Any], ref: str) -> dict[str, Any]:
    return {"type": "object", "$defs": definitions, "properties": {"name": {"$ref": ref}}}


def _place(holder: dict[str, Any], position: str, target: dict[str, Any]) -> str:
    if position == "examples":
        holder[position] = [{"target": target}]
        return "examples/0/target"
    if position == "allOf":
        holder[position] = [target]
        return "allOf/0"
    if position in ("properties", "$defs"):
        holder.setdefault(position, {})["target"] = target
    else:
        holder[position] = {"target": target}
    return position + "/target"


def _pair(schema: dict[str, Any], ref: str) -> dict[str, str]:
    schema_error = ""
    try:
        Draft202012Validator.check_schema(schema)
        schema_status = "accept"
    except SchemaError as exc:
        schema_status = "reject"
        schema_error = exc.__class__.__name__
    resource = DRAFT202012.create_resource(schema)
    resolver = Registry().with_resource(BASE, resource).resolver(BASE)
    lookup_error = ""
    try:
        resolver.lookup(ref)
        lookup_status = "resolved"
    except (PointerToNowhere, Unresolvable) as exc:
        lookup_status = "unresolved"
        lookup_error = exc.__class__.__name__
    pair = "accept" if schema_status == "accept" and lookup_status == "resolved" else "reject"
    return {
        "check_schema": schema_status,
        "lookup": lookup_status,
        "lookup_error": lookup_error,
        "pair": pair,
        "schema_error": schema_error,
    }


def _rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for case_id, ref, definitions in PLANTED:
        result = _pair(_schema(dict(definitions), ref), ref)
        rows.append({"case_id": case_id, "function": "planted", "ref": ref, **result})
    for case_id, token, key in TILDE:
        if "/" in token:
            schema = {
                "type": "object",
                "$defs": {key: {"type": {"type": "string"}}},
                "properties": {"name": {"$ref": "#/$defs/" + token}},
            }
        else:
            schema = _schema({key: {"type": "string"}}, "#/$defs/" + token)
        result = _pair(schema, "#/$defs/" + token)
        rows.append({"case_id": case_id, "function": "tilde", "ref": "#/$defs/" + token, **result})
    for field in FIELDS:
        for position in POSITIONS:
            for key in KEYS:
                token = "bad~2"
                schema: dict[str, Any] = {"type": "object", "$defs": {key: {"type": "object"}}}
                if key != "2":
                    schema["$defs"]["bad~2"] = {"type": "object"}
                    reference = "#/$defs/" + token
                else:
                    schema["x-cycle10-array"] = [0, 1, {"type": "object"}]
                    reference = "#/x-cycle10-array/02"
                pointer = "#/" + _place(schema, position, {"$ref": reference})
                schema.setdefault("properties", {})["entry"] = {"$ref": pointer}
                result = _pair(schema, reference)
                rows.append(
                    {
                        "case_id": f"{field}-{position}-{key}-malformed-escape",
                        "function": "cycle10-pointer",
                        "ref": reference,
                        **result,
                    }
                )
    return rows


def main() -> None:
    payload = {
        "jsonschema": version("jsonschema"),
        "python": platform.python_version(),
        "referencing": version("referencing"),
        "rows": _rows(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
