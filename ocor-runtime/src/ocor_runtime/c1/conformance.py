"""C1 -- IR conformance suite (ConformanceSuitePort of LLD v1.1 §2.1, :105).

Checks a release against ADD v1.3 §3.1 (OCOR_ADD_v1.3_APPROVED_BASELINE.md):
CanonicalIRCore structure (:441-462), symbol resolution (:440 step 6), set-like
arrays sorted and duplicate-free with collections ordered by stable identifier
(LLD v1.1 :39, ADD :436), Unicode NFC (:435), capability coverage for every used
capability and adapter role (:438-439, FR-024) and the RFC 8785 digest (:464). A
failing check is reported as ``FAIL``; nothing is passed silently.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..kernel.canonical import canonical_digest
from .ir import CORE_KEYS, IR_FORMAT, RELEASE_KEYS, core_references, is_nfc, parse_core, used_capabilities
from .ports import C1Error, CanonicalIrRelease

_MIN_ONE = ("namespaces", "modules", "symbol_table", "security_profiles", "capability_matrix", "artifact_plan")
_ORDERED = (("namespaces", "namespace_id"), ("modules", "module_id"), ("types", "type_id"), ("links", "link_id"),
            ("constraints", "constraint_id"), ("derived_definitions", "derived_id"),
            ("named_contracts", "contract_id"), ("security_profiles", "security_profile_id"),
            ("artifact_plan", "artifact_kind"))


def _sorted_unique(values: Sequence[Any]) -> bool:
    return list(values) == sorted(set(values))


def _core_structure(core: Mapping[str, Any]) -> str | None:
    if set(core) != set(CORE_KEYS) or core.get("format") != IR_FORMAT:
        return "core keys or format differ from CanonicalIRCore"
    if set(core["release"]) != set(RELEASE_KEYS):
        return "release block differs from CanonicalIRCore"
    empty = [key for key in _MIN_ONE if not core[key]]
    return f"empty collections: {empty}" if empty else None


def _symbol_resolution(core: Mapping[str, Any]) -> str | None:
    symbols = {entry["symbol_id"] for entry in core["symbol_table"]}
    missing = sorted({ref for _, ref in core_references(core) if ref not in symbols})
    return f"unresolved: {missing[:5]}" if missing else None


def _set_ordering(core: Mapping[str, Any]) -> str | None:
    for collection, key in _ORDERED:
        if not _sorted_unique([str(entry[key]) for entry in core[collection]]):
            return f"{collection} is not ordered by {key}"
    for type_ir in core["types"]:
        for field in ("interfaces", "keys"):
            if not _sorted_unique(type_ir[field]):
                return f"{type_ir['type_id']}/{field} is not sorted and duplicate-free"
        if not _sorted_unique([p["property_id"] for p in type_ir["properties"]]):
            return f"{type_ir['type_id']}/properties are not ordered"
    pairs = [(e["semantic_capability_id"], e["adapter_role"]) for e in core["capability_matrix"]]
    return None if pairs == sorted(set(pairs)) else "capability_matrix is not ordered"


def _nfc(core: Mapping[str, Any]) -> str | None:
    return None if is_nfc(core) else "a string is not in Unicode NFC"


def _capability_coverage(core: Mapping[str, Any]) -> str | None:
    matrix = {(e["semantic_capability_id"], e["adapter_role"]): e for e in core["capability_matrix"]}
    roles = sorted({role for _, role in matrix})
    for capability in sorted(used_capabilities(core)):
        for role in roles:
            entry = matrix.get((capability, role))
            if entry is None:
                return f"{capability} has no disposition for {role}"
            if entry["disposition"] == "unsupported" and entry.get("approved_exception") is not True:
                return f"{capability} is unsupported on {role} without an approved exception"
    return None


class IrConformanceSuite:
    """ConformanceSuitePort: returns a PASS/FAIL report with one entry per check."""

    CHECKS: tuple[tuple[str, Callable[[Mapping[str, Any]], str | None]], ...] = (
        ("core_structure", _core_structure),
        ("symbol_resolution", _symbol_resolution),
        ("set_ordering", _set_ordering),
        ("nfc", _nfc),
        ("capability_coverage", _capability_coverage),
    )

    def run(self, release: CanonicalIrRelease) -> dict[str, object]:
        checks: list[dict[str, str]] = []
        try:
            core = parse_core(release.canonical_bytes)
            digest_ok = canonical_digest(core) == release.ir_digest
        except (C1Error, ValueError) as error:
            return {"status": "FAIL", "ir_digest": release.ir_digest,
                    "checks": [{"check": "digest", "status": "FAIL", "detail": str(error)[:200]}]}
        checks.append({"check": "digest", "status": "PASS" if digest_ok else "FAIL",
                       "detail": "" if digest_ok else "ir_digest does not bind the core"})
        structure_ok = _core_structure(core) is None
        for name, check in self.CHECKS:
            if name != "core_structure" and not structure_ok:
                checks.append({"check": name, "status": "FAIL", "detail": "not evaluated: core structure invalid"})
                continue
            try:
                problem = check(core)
            except (KeyError, TypeError) as error:
                problem = f"malformed core: {error!r}"[:200]
            checks.append({"check": name, "status": "FAIL" if problem else "PASS", "detail": problem or ""})
        status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
        return {"status": status, "ir_digest": release.ir_digest, "checks": checks}
