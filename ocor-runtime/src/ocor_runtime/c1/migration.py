"""C1 -- semantic diff, migration planning and the release change gate.

Realises FR-045 (Requirement Register v1.1 :141): changes are classified as
``compatible``, ``conditional``, ``breaking``, ``destructive`` or ``causal-breaking``
and every plan carries migration, backfill, alias, deprecation, dry-run and recovery
parts; a destructive change without a backup and replay plan is rejected. LLD v1.1
§2.1 (docs/OCOR_LLD_v1.1.md :107): a breaking change requires a migration plan, dual
control and a new major version. Where LLD names fewer classes, the Register
prevails (LLD v1.1 :16-18). FR-046 (:142): the plan is content-addressed and bound
to the exact pair of releases it was computed for. In the PoC profile the dry-run is
a plan-only simulation (FR-045 release column).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from ..kernel.canonical import canonical_digest
from .ir import malformed_core_rejected, parse_core, require_core_shape, semver_major, semver_precedence
from .ports import C1Diagnostic, C1Error, CanonicalIrRelease, DiagnosticCode


class ChangeClass(StrEnum):
    COMPATIBLE = "compatible"
    CONDITIONAL = "conditional"
    BREAKING = "breaking"
    DESTRUCTIVE = "destructive"
    CAUSAL_BREAKING = "causal-breaking"


# Dominance order used for the overall classification of a release pair; the gate
# enforces the obligations of every class present, not only of the dominant one.
_RANK = {ChangeClass.COMPATIBLE: 0, ChangeClass.CONDITIONAL: 1, ChangeClass.BREAKING: 2,
         ChangeClass.CAUSAL_BREAKING: 3, ChangeClass.DESTRUCTIVE: 4}
_MAJOR = frozenset({ChangeClass.BREAKING, ChangeClass.DESTRUCTIVE, ChangeClass.CAUSAL_BREAKING})
# (collection, identifier field, class when added, class when removed, class when changed)
_COLLECTIONS: tuple[tuple[str, str, ChangeClass, ChangeClass, ChangeClass], ...] = (
    ("namespaces", "namespace_id", ChangeClass.COMPATIBLE, ChangeClass.DESTRUCTIVE, ChangeClass.BREAKING),
    ("links", "link_id", ChangeClass.COMPATIBLE, ChangeClass.DESTRUCTIVE, ChangeClass.BREAKING),
    ("constraints", "constraint_id", ChangeClass.CONDITIONAL, ChangeClass.COMPATIBLE, ChangeClass.CONDITIONAL),
    ("temporal_semantics", "owner_ref", ChangeClass.CONDITIONAL, ChangeClass.DESTRUCTIVE, ChangeClass.BREAKING),
    ("derived_definitions", "derived_id", ChangeClass.COMPATIBLE, ChangeClass.BREAKING, ChangeClass.BREAKING),
    ("named_contracts", "contract_id", ChangeClass.COMPATIBLE, ChangeClass.BREAKING, ChangeClass.BREAKING),
    ("causal_manifests", "type_id", ChangeClass.COMPATIBLE, ChangeClass.CAUSAL_BREAKING,
     ChangeClass.CAUSAL_BREAKING),
    ("security_profiles", "security_profile_id", ChangeClass.COMPATIBLE, ChangeClass.BREAKING,
     ChangeClass.BREAKING),
    ("capability_matrix", "semantic_capability_id", ChangeClass.COMPATIBLE, ChangeClass.CONDITIONAL,
     ChangeClass.CONDITIONAL),
    ("artifact_plan", "artifact_kind", ChangeClass.COMPATIBLE, ChangeClass.BREAKING, ChangeClass.BREAKING),
)


def _reject(path: str, message: str) -> C1Error:
    return C1Error((C1Diagnostic(DiagnosticCode.RELEASE_REJECTED, path, message),))


def _index(entries: Iterable[Mapping[str, Any]], key: str) -> dict[str, Mapping[str, Any]]:
    if key == "semantic_capability_id":
        return {f"{e['semantic_capability_id']}@{e['adapter_role']}": e for e in entries}
    return {str(e[key]): e for e in entries}


def _change(path: str, op: str, klass: ChangeClass, symbol: str) -> dict[str, str]:
    return {"path": path, "op": op, "class": klass.value, "symbol": symbol}


def _property_change(before: Mapping[str, Any], after: Mapping[str, Any]) -> ChangeClass:
    if before["value_type"] != after["value_type"] or before["cardinality"] != after["cardinality"]:
        return ChangeClass.BREAKING
    if before.get("unit_ref") != after.get("unit_ref"):
        return ChangeClass.BREAKING
    if before["nullable"] and not after["nullable"]:
        return ChangeClass.CONDITIONAL
    if not before["nullable"] and after["nullable"]:
        return ChangeClass.BREAKING
    if before.get("constraint_refs") != after.get("constraint_refs"):
        return ChangeClass.CONDITIONAL
    return ChangeClass.BREAKING if before != after else ChangeClass.COMPATIBLE


def _type_changes(before: Mapping[str, Any], after: Mapping[str, Any], causal: bool) -> list[dict[str, str]]:
    type_id = str(after["type_id"])
    base = f"types/{type_id}"
    changes: list[dict[str, str]] = []
    if before["kind"] != after["kind"]:
        changes.append(_change(f"{base}/kind", "changed", ChangeClass.BREAKING, type_id))
    for field in ("keys", "interfaces", "security_profile_ref", "lifecycle_ref", "values"):
        if before.get(field) != after.get(field):
            changes.append(_change(f"{base}/{field}", "changed", ChangeClass.BREAKING, type_id))
    if before.get("label") != after.get("label"):
        changes.append(_change(f"{base}/label", "changed", ChangeClass.COMPATIBLE, type_id))
    old = {p["property_id"]: p for p in before["properties"]}
    new = {p["property_id"]: p for p in after["properties"]}
    for prop_id in sorted(set(new) - set(old)):
        prop = new[prop_id]
        klass = ChangeClass.COMPATIBLE if prop["nullable"] or "default" in prop else ChangeClass.CONDITIONAL
        changes.append(_change(f"{base}/properties/{prop_id}", "added", klass, prop_id))
    for prop_id in sorted(set(old) - set(new)):
        changes.append(_change(f"{base}/properties/{prop_id}", "removed", ChangeClass.DESTRUCTIVE, prop_id))
    for prop_id in sorted(set(old) & set(new)):
        if old[prop_id] != new[prop_id]:
            changes.append(_change(f"{base}/properties/{prop_id}", "changed",
                                   _property_change(old[prop_id], new[prop_id]), prop_id))
    if causal and before != after:
        # NCP-U01-RETAINED-C1-BUILDERS point 3: a change of a CAUSAL type is
        # causal-breaking (with the obligations of breaking); the conditional and
        # destructive changes it contains keep their own class, so the gate applies
        # backfill, backup and replay too ("ogni classe presente").
        kept = (ChangeClass.CONDITIONAL.value, ChangeClass.DESTRUCTIVE.value)
        changes = [_change(base, "changed", ChangeClass.CAUSAL_BREAKING, type_id)] + [
            change if change["class"] in kept else {**change, "class": ChangeClass.CAUSAL_BREAKING.value}
            for change in changes]
    return changes


# Module fields (ADD v1.3 :446) and their class when changed, by the criterion of
# NCP-U01-RETAINED-C1-BUILDERS point 3 for changes the FR-045 table does not name.
_MODULE_FIELDS: Mapping[str, ChangeClass] = {
    "namespace_ref": ChangeClass.BREAKING,      # every exported symbol changes namespace
    "imports": ChangeClass.CONDITIONAL,         # resolved by the dependency lock, as lock_digest
    "owner": ChangeClass.COMPATIBLE,            # governance metadata: no effect on data or consumers
    "steward": ChangeClass.COMPATIBLE,
    "reviewer": ChangeClass.COMPATIBLE,
    "review_date": ChangeClass.COMPATIBLE,
    "version": ChangeClass.COMPATIBLE,          # the release version is gated separately
}
# definition_refs is derived from the definitions, each classified in its own collection
# (a definition moved between modules is classified through the symbol table).


def _module_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, str]]:
    module_id = str(after["module_id"])
    base = f"modules/{module_id}"
    changes = [_change(f"{base}/{field}", "changed", klass, module_id)
               for field, klass in sorted(_MODULE_FIELDS.items()) if before[field] != after[field]]
    # A removed export breaks the consumers that import it; an added export does not.
    changes += [_change(f"{base}/exports/{symbol}", "removed", ChangeClass.BREAKING, symbol)
                for symbol in sorted(set(before["exports"]) - set(after["exports"]))]
    changes += [_change(f"{base}/exports/{symbol}", "added", ChangeClass.COMPATIBLE, symbol)
                for symbol in sorted(set(after["exports"]) - set(before["exports"]))]
    if before["status"] != after["status"]:
        # Deprecation announces the removal to consumers: it carries the deprecation
        # plan, dual control and a new major. The review states before it are metadata.
        deprecated = "DEPRECATED" in {before["status"], after["status"]}
        changes.append(_change(f"{base}/status", "changed",
                               ChangeClass.BREAKING if deprecated else ChangeClass.COMPATIBLE, module_id))
    return changes


def _symbol_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, str]]:
    """A symbol that moves to another module, or changes kind, breaks the importers of the old one."""
    old = {str(e["symbol_id"]): e for e in before["symbol_table"]}
    new = {str(e["symbol_id"]): e for e in after["symbol_table"]}
    return [_change(f"symbol_table/{symbol}", "changed", ChangeClass.BREAKING, symbol)
            for symbol in sorted(set(old) & set(new))
            if (old[symbol]["module_ref"], old[symbol]["kind"]) != (new[symbol]["module_ref"], new[symbol]["kind"])]


def semantic_changes(previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> list[dict[str, str]]:
    """The classified, ordered list of semantic changes between two releases."""
    before, after = parse_core(previous.canonical_bytes), parse_core(candidate.canonical_bytes)
    require_core_shape(before)
    require_core_shape(after)
    with malformed_core_rejected():
        return _semantic_changes(before, after)


def _semantic_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for field in ("lock_digest", "mapping_version"):
        if before["release"][field] != after["release"][field]:
            changes.append(_change(f"release/{field}", "changed", ChangeClass.CONDITIONAL, field))
    if before["release"]["package_id"] != after["release"]["package_id"]:
        changes.append(_change("release/package_id", "changed", ChangeClass.BREAKING, "package_id"))
    old_types, new_types = _index(before["types"], "type_id"), _index(after["types"], "type_id")
    for type_id in sorted(set(new_types) - set(old_types)):
        changes.append(_change(f"types/{type_id}", "added", ChangeClass.COMPATIBLE, type_id))
    for type_id in sorted(set(old_types) - set(new_types)):
        changes.append(_change(f"types/{type_id}", "removed", ChangeClass.DESTRUCTIVE, type_id))
        if old_types[type_id]["kind"] == "CAUSAL":
            changes.append(_change(f"types/{type_id}", "removed", ChangeClass.CAUSAL_BREAKING, type_id))
    for type_id in sorted(set(old_types) & set(new_types)):
        causal = "CAUSAL" in {old_types[type_id]["kind"], new_types[type_id]["kind"]}
        changes += _type_changes(old_types[type_id], new_types[type_id], causal)
    old_modules, new_modules = _index(before["modules"], "module_id"), _index(after["modules"], "module_id")
    changes += [_change(f"modules/{i}", "added", ChangeClass.COMPATIBLE, i)
                for i in sorted(set(new_modules) - set(old_modules))]
    # Removing a module removes what its importers resolve; its definitions are
    # classified in their own collections (a removed type stays destructive).
    changes += [_change(f"modules/{i}", "removed", ChangeClass.BREAKING, i)
                for i in sorted(set(old_modules) - set(new_modules))]
    for module_id in sorted(set(old_modules) & set(new_modules)):
        changes += _module_changes(old_modules[module_id], new_modules[module_id])
    changes += _symbol_changes(before, after)
    for collection, key, added, removed, changed in _COLLECTIONS:
        old, new = _index(before[collection], key), _index(after[collection], key)
        changes += [_change(f"{collection}/{i}", "added", added, i) for i in sorted(set(new) - set(old))]
        changes += [_change(f"{collection}/{i}", "removed", removed, i) for i in sorted(set(old) - set(new))]
        changes += [_change(f"{collection}/{i}", "changed", changed, i)
                    for i in sorted(set(old) & set(new)) if old[i] != new[i]]
    return sorted(changes, key=lambda c: (c["path"], c["op"], c["class"]))


def _classify(changes: Sequence[Mapping[str, str]]) -> ChangeClass:
    classes = [ChangeClass(c["class"]) for c in changes] or [ChangeClass.COMPATIBLE]
    return max(classes, key=lambda klass: _RANK[klass])


class IrSemanticDiffEngine:
    """SemanticDiffEngine over CanonicalIRCore; ``compare`` returns the diff digest."""

    def changes(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> list[dict[str, str]]:
        return semantic_changes(previous, candidate)

    def classify(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> ChangeClass:
        return _classify(semantic_changes(previous, candidate))

    def compare(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease) -> str:
        return canonical_digest({"previous_ir_digest": previous.ir_digest, "candidate_ir_digest": candidate.ir_digest,
                                 "changes": semantic_changes(previous, candidate)})


class IrMigrationPlanner:
    """MigrationPlanner: migration, backfill, alias, deprecation, dry-run and recovery parts."""

    def __init__(self, diff_engine: IrSemanticDiffEngine | None = None) -> None:
        self._engine = diff_engine or IrSemanticDiffEngine()

    def plan(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease, *,
             backup_ref: str | None = None, replay_plan_ref: str | None = None) -> dict[str, Any]:
        changes = self._engine.changes(previous, candidate)
        classes = sorted({c["class"] for c in changes} or {ChangeClass.COMPATIBLE.value})
        with malformed_core_rejected():
            before = parse_core(previous.canonical_bytes)["release"]
            after = parse_core(candidate.canonical_bytes)["release"]
        migration = [{"op": {"added": "expand", "changed": "expand-migrate-contract", "removed": "contract"}[c["op"]],
                      "path": c["path"], "class": c["class"]}
                     for c in changes if c["class"] != ChangeClass.COMPATIBLE.value]
        backfill = [{"path": c["path"], "symbol": c["symbol"], "strategy": "BACKFILL_BEFORE_ACTIVATION"}
                    for c in changes if c["class"] == ChangeClass.CONDITIONAL.value]
        deprecated = [c for c in changes if c["op"] in {"removed", "changed"}
                      and c["class"] in {k.value for k in _MAJOR}]
        destructive = ChangeClass.DESTRUCTIVE.value in classes
        body: dict[str, Any] = {
            "previous_ir_digest": previous.ir_digest,
            "candidate_ir_digest": candidate.ir_digest,
            "previous_version": before["semantic_version"],
            "candidate_version": after["semantic_version"],
            "diff_digest": self._engine.compare(previous, candidate),
            "classification": _classify(changes).value,
            "change_classes": classes,
            "changes": changes,
            "migration": migration,
            "backfill": backfill,
            "alias": [{"symbol": c["symbol"], "alias_of_version": before["semantic_version"],
                       "until_version": after["semantic_version"]} for c in deprecated if c["op"] == "changed"],
            "deprecation": [{"symbol": c["symbol"], "deprecated_in": before["semantic_version"],
                             "removed_in": after["semantic_version"]} for c in deprecated],
            "dry_run": {"mode": "PLAN_ONLY", "required": bool(migration),
                        "steps": [step["path"] for step in migration]},
            "recovery": {"backup_required": destructive, "backup_ref": backup_ref, "replay_plan_ref": replay_plan_ref,
                         "strategy": "RESTORE_BACKUP_AND_REPLAY" if destructive else "REVERSE_MIGRATION"},
        }
        return {**body, "plan_digest": canonical_digest(body)}


class ReleaseChangeGate:
    """Admits a candidate against its predecessor only with the obligations of FR-045 and LLD :107."""

    def __init__(self, planner: IrMigrationPlanner | None = None) -> None:
        self._planner = planner or IrMigrationPlanner()

    def admit(self, previous: CanonicalIrRelease, candidate: CanonicalIrRelease, *,
              plan: Mapping[str, Any] | None, approvals: Sequence[str]) -> dict[str, Any]:
        path = "release_change"
        expected = self._planner.plan(previous, candidate)
        classes = {ChangeClass(value) for value in expected["change_classes"]}
        identical = previous.ir_digest == candidate.ir_digest
        before_version, after_version = expected["previous_version"], expected["candidate_version"]
        if not identical and semver_precedence(after_version) <= semver_precedence(before_version):
            raise _reject(path, "a changed release needs a higher semantic version")
        if plan is None:
            if classes != {ChangeClass.COMPATIBLE}:
                raise _reject(path, "a non-compatible change needs a migration plan")
            return {"classification": expected["classification"], "plan_digest": None, "approvals": []}
        body = {key: value for key, value in plan.items() if key != "plan_digest"}
        if plan.get("plan_digest") != canonical_digest(body):
            raise _reject(path, "the plan digest does not bind the plan")
        bound = {key: expected[key] for key in ("previous_ir_digest", "candidate_ir_digest", "diff_digest",
                                                "classification", "change_classes", "changes")}
        if any(plan.get(key) != value for key, value in bound.items()):
            raise _reject(path, "the plan does not belong to this pair of releases")
        if ChangeClass.CONDITIONAL in classes and not plan.get("backfill"):
            raise _reject(path, "a conditional change needs a backfill plan")
        distinct = {item for item in approvals if isinstance(item, str) and item}
        if classes & _MAJOR:
            if not plan.get("migration"):
                raise _reject(path, "a breaking change needs a migration plan")
            if len(distinct) < 2 or len(distinct) != len(tuple(approvals)):
                raise _reject(path, "a breaking change needs dual control by two distinct principals")
            if semver_major(after_version) <= semver_major(before_version):
                raise _reject(path, "a breaking change needs a new major version")
        if ChangeClass.DESTRUCTIVE in classes:
            recovery = plan.get("recovery")
            if not isinstance(recovery, Mapping) or not recovery.get("backup_ref") or not recovery.get(
                "replay_plan_ref"
            ):
                raise _reject(path, "a destructive change needs a backup and a replay plan")
        return {"classification": expected["classification"], "plan_digest": plan["plan_digest"],
                "approvals": sorted(distinct)}
