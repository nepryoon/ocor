#!/usr/bin/env python3
"""Fail-closed gate: one current evidence head per completed task.

The reference selector in ``reports/tests/test_validate_current_evidence_head.py``
is the oracle. This script is the subject. It does not import that module.
``scripts/validate_evidence_input_drift.py`` stays byte-identical; CI runs both.

Stdout is one strict UTF-8 JSON object. Exit 0 only when status is PASS and
findings are empty. A presented input is never skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

EXCLUDED_PARTS = {"blockers", "local-gates"}
RECON_DIR = "reports/assurance/OCOR-DEV-REM-0068-RCCAD/reconciliation"
JSON_DEPTH_LIMIT = 11
CODES = (
    "AMBIGUOUS_IDENTITY",
    "CYCLE",
    "MANIFEST_FIELD",
    "MANIFEST_MISSING",
    "MANIFEST_UNLISTED",
    "MULTIPLE_HEADS",
    "NOT_CURRENT_HEAD",
    "OUTSIDE_EVIDENCE",
    "RECONCILIATION_ABSENT",
    "RECONCILIATION_UNLISTED",
    "SELF_SUPERSEDES",
    "SUPERSEDES_UNRESOLVED",
    "TWO_SUCCESSORS",
    "UNREADABLE_JSON",
)


@dataclass(frozen=True)
class Rec:
    """One evidence JSON file, readable or not."""

    path: str
    task_id: str
    record_id: str | None
    supersedes: str | None
    commit: str | None
    raw: bytes
    unreadable: bool


@dataclass(frozen=True)
class Recon:
    """One reconciliation file. A non-empty task_id makes it unusable."""

    task_id: str
    remaining_head: str
    supersedes: tuple[str, ...]
    reconciles: tuple[tuple[str, str], ...]
    selected_path: str
    embedded_task_id: str | None
    unreadable: bool
    under_evidence: bool
    missing: bool


@dataclass(frozen=True)
class ManifestEntry:
    path: object
    task_id: object


@dataclass(frozen=True)
class Manifest:
    relative_path: str
    entries: tuple[ManifestEntry, ...]
    unreadable: bool


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lone(value: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _refuse_constant(value: str) -> Any:
    raise ValueError(value)


def _lone_tree(value: object) -> bool:
    """Walk a decoded JSON value on an explicit stack. Depth 11 never recurses."""
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            if _lone(current):
                return True
            continue
        if isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
            continue
        if isinstance(current, list):
            stack.extend(current)
    return False


def _json_container_depth(raw: bytes) -> int:
    """Container nesting of one JSON text. Strings do not count. No call recursion."""
    text = raw.decode("utf-8")
    maximum = 0
    depth = 0
    in_string = False
    escape = False
    for char in text:
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in "{[":
            depth += 1
            if depth > maximum:
                maximum = depth
            if maximum > JSON_DEPTH_LIMIT:
                return maximum
            continue
        if char in "}]" and depth:
            depth -= 1
    return maximum


def _loads(raw: bytes) -> object:
    """RFC 8259 document. NaN, Infinity, a lone surrogate, or depth above 11 raise ValueError.

    The depth walk uses an explicit index. ``json.loads`` runs only at or below the limit,
    so a document of several hundred containers cannot raise ``RecursionError``.
    """
    if _json_container_depth(raw) > JSON_DEPTH_LIMIT:
        raise ValueError("json depth")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_refuse_constant)
    except RecursionError as exc:
        raise ValueError("json depth") from exc
    if _lone_tree(data):
        raise ValueError("lone surrogate")
    return data


def _unreadable_record(relative: str, raw: bytes, fallback_task: str) -> Rec:
    return Rec(relative, fallback_task, None, None, None, raw, True)


def _bad_recon(task_id: str, under_evidence: bool) -> Recon:
    return Recon(task_id, "", (), (), "", None, True, under_evidence, False)


def _finding(task_id: str, code: str, entry: str) -> dict[str, str]:
    if code not in CODES:
        raise ValueError(code)
    return {"code": code, "entry": entry, "task_id": task_id}


def _historical(value: str, records: Sequence[Rec]) -> bool:
    if any(value == record.path for record in records):
        return True
    if "@sha256:" in value:
        return True
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def _referenced(value: str, record: Rec) -> bool:
    """True when a historical supersedes string names this listed record."""
    if value == record.path:
        return True
    if value == f"{record.path}@sha256:{_sha256(record.raw)}":
        return True
    return record.commit is not None and value == record.commit


def _historical_keys(record: Rec) -> list[str]:
    keys = [record.path, f"{record.path}@sha256:{_sha256(record.raw)}"]
    if record.commit is not None:
        keys.append(record.commit)
    return keys


def _ambiguous_keys(readable: Sequence[Rec], reconciles: Mapping[str, str]) -> set[str]:
    """Historical keys that more than one record without ``record_id`` receives.

    The execution commit is a key only when reconciliation names it. A shared commit is
    not an identity: the key is ambiguous and neither record takes it.
    """
    receivers: dict[str, set[str]] = {}
    for record in readable:
        if isinstance(record.record_id, str) and record.record_id:
            continue
        for key in _historical_keys(record):
            mapped = reconciles.get(key)
            if isinstance(mapped, str) and mapped:
                receivers.setdefault(key, set()).add(record.path)
    return {key for key, paths in receivers.items() if len(paths) > 1}


def _canonical(
    record: Rec,
    reconciles: Mapping[str, str],
    ambiguous: set[str] | None = None,
) -> str | None:
    if isinstance(record.record_id, str) and record.record_id:
        return record.record_id
    blocked = ambiguous or set()
    for key in _historical_keys(record):
        if key in blocked:
            continue
        mapped = reconciles.get(key)
        if isinstance(mapped, str) and mapped:
            return mapped
    return None


def _is_evidence_path(relative: str) -> bool:
    """True only for a descendant of the ``reports/evidence`` directory, by components."""
    parts = PurePosixPath(relative).parts
    return len(parts) >= 3 and parts[0] == "reports" and parts[1] == "evidence"


def _below(path: str, prefix: str) -> bool:
    """Path equality or a real child. ``reports/evidence-archive`` is not under ``reports/evidence``."""
    return path == prefix or path.startswith(prefix + "/")


def _cyclic(edges: Mapping[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for target in edges.get(node, ()):
            if walk(target):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(walk(node) for node in list(edges))


def check_outside_evidence(
    relative: str,
    raw: bytes | None,
    entry: str,
    fallback_task: str,
) -> list[dict[str, str]]:
# CHECK OUTSIDE_EVIDENCE
    if _is_evidence_path(relative):
        return []
    task_id = relative
    if raw:
        try:
            data = _loads(raw)
        except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
            data = None
        if isinstance(data, dict):
            carried = data.get("task_id")
            if isinstance(carried, str) and carried:
                task_id = carried
    if not task_id:
        task_id = fallback_task or relative
    return [_finding(task_id, "OUTSIDE_EVIDENCE", entry)]
# END CHECK OUTSIDE_EVIDENCE


def check_ambiguous_identity(
    readable: Sequence[Rec],
    reconciles: Mapping[str, str],
    entry: str,
    task_id: str,
) -> list[dict[str, str]]:
# CHECK AMBIGUOUS_IDENTITY
    if not _ambiguous_keys(readable, reconciles):
        return []
    return [_finding(task_id, "AMBIGUOUS_IDENTITY", entry)]
# END CHECK AMBIGUOUS_IDENTITY


def check_unreadable_json(
    records: Sequence[Rec],
    task_id: str,
    entry: str,
    focus: str | None,
    manifests: Sequence[Manifest] = (),
) -> list[dict[str, str]]:
# CHECK UNREADABLE_JSON
    findings: list[dict[str, str]] = []
    if focus is not None:
        named = [record for record in records if record.path == focus]
        if not named or named[0].unreadable or _text_broken(named[0]):
            findings.append(_finding(task_id, "UNREADABLE_JSON", entry))
            return findings
    for record in records:
        if record.unreadable or _text_broken(record):
            findings.append(_finding(record.task_id or task_id, "UNREADABLE_JSON", entry))
    for manifest in manifests:
        if manifest.unreadable:
            findings.append(_finding(task_id, "UNREADABLE_JSON", entry))
        directory = str(Path(manifest.relative_path).parent)
        for record in records:
            if str(Path(record.path).parent) != directory:
                continue
            if record.unreadable or _text_broken(record):
                findings.append(_finding(record.task_id or task_id, "UNREADABLE_JSON", entry))
    return findings
# END CHECK UNREADABLE_JSON


def _text_broken(record: Rec) -> bool:
    if record.unreadable:
        return False
    # The blob name is not document text. A non-UTF-8 path stays a readable record.
    values = [record.task_id]
    for value in (record.record_id, record.supersedes, record.commit):
        if isinstance(value, str):
            values.append(value)
    return any(_lone(value) for value in values)


def check_self_supersedes(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    entry: str,
) -> list[dict[str, str]]:
# CHECK SELF_SUPERSEDES
    findings: list[dict[str, str]] = []
    listed = {value for value in identities.values() if value}
    for record in readable:
        raw = record.supersedes
        identity = identities.get(record.path)
        if not isinstance(raw, str) or identity is None or _lone(raw):
            continue
        if raw == identity:
            findings.append(_finding(record.task_id, "SELF_SUPERSEDES", entry))
            continue
        if raw in listed:
            continue
        mapped = reconciles.get(raw)
        if isinstance(mapped, str) and mapped in listed and mapped == identity:
            findings.append(_finding(record.task_id, "SELF_SUPERSEDES", entry))
    return findings
# END CHECK SELF_SUPERSEDES


def check_supersedes_unresolved(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    entry: str,
) -> list[dict[str, str]]:
# CHECK SUPERSEDES_UNRESOLVED
    findings: list[dict[str, str]] = []
    listed = {value for value in identities.values() if value}
    for record in readable:
        raw = record.supersedes
        if not isinstance(raw, str) or _lone(raw):
            continue
        identity = identities.get(record.path)
        if identity is not None and raw == identity:
            continue
        if raw in listed:
            continue
        mapped = reconciles.get(raw)
        mapped_listed = isinstance(mapped, str) and bool(mapped) and mapped in listed
        if _historical(raw, readable):
            if mapped_listed or not (isinstance(mapped, str) and mapped):
                continue
            findings.append(_finding(record.task_id, "SUPERSEDES_UNRESOLVED", entry))
            continue
        if mapped_listed:
            continue
        findings.append(_finding(record.task_id, "SUPERSEDES_UNRESOLVED", entry))
    return findings
# END CHECK SUPERSEDES_UNRESOLVED


def check_reconciliation_absent(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    other_findings: Sequence[Mapping[str, str]],
    entry: str,
    task_id: str,
) -> list[dict[str, str]]:
# CHECK RECONCILIATION_ABSENT
    findings: list[dict[str, str]] = []
    needs = any(identities.get(record.path) is None for record in readable)
    for record in readable:
        raw = record.supersedes
        if not isinstance(raw, str) or _lone(raw):
            continue
        identity = identities.get(record.path)
        if identity is not None and raw == identity:
            continue
        listed = {value for value in identities.values() if value}
        if raw in listed:
            continue
        if _historical(raw, readable) and not reconciles.get(raw):
            needs = True
    if needs:
        findings.append(_finding(task_id, "RECONCILIATION_ABSENT", entry))
    if recon is not None and (recon.unreadable or recon.under_evidence or bool(recon.embedded_task_id)):
        findings.append(_finding(task_id, "RECONCILIATION_ABSENT", entry))
    if recon is not None and not recon.missing and not recon_unusable:
        values = [recon.remaining_head, recon.selected_path, *recon.supersedes]
        if not recon.selected_path or any(_lone(value) for value in values if isinstance(value, str)):
            findings.append(_finding(task_id, "RECONCILIATION_ABSENT", entry))
    retired, unresolved = _retired(readable, identities, resolved, reconciles, recon, recon_unusable)
    current = [
        record
        for record in readable
        if identities.get(record.path) and identities.get(record.path) not in retired and record.path not in unresolved
    ]
    blocked = list(other_findings) + findings
    if len(current) == 0 and not blocked:
        findings.append(_finding(task_id, "RECONCILIATION_ABSENT", entry))
    return findings
# END CHECK RECONCILIATION_ABSENT


def check_reconciliation_unlisted(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    recon: Recon | None,
    recon_unusable: bool,
    entry: str,
) -> list[dict[str, str]]:
# CHECK RECONCILIATION_UNLISTED
    findings: list[dict[str, str]] = []
    if recon is None or recon_unusable:
        return findings
    listed = {value for value in identities.values() if value}
    selected_ok = (
        recon.remaining_head in listed
        and recon.selected_path in identities
        and identities.get(recon.selected_path) == recon.remaining_head
    )
    bad_list = recon.remaining_head in recon.supersedes or any(item not in listed for item in recon.supersedes)
    if bad_list or not selected_ok:
        task_id = readable[0].task_id if readable else recon.task_id
        findings.append(_finding(task_id, "RECONCILIATION_UNLISTED", entry))
    return findings
# END CHECK RECONCILIATION_UNLISTED


def check_cycle(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    entry: str,
    task_id: str,
) -> list[dict[str, str]]:
# CHECK CYCLE
    findings: list[dict[str, str]] = []
    edges: dict[str, set[str]] = {}
    listed = {value for value in identities.values() if value}
    for record in readable:
        source = identities.get(record.path)
        target = resolved.get(record.path)
        if source and target and target != source and target in listed:
            edges.setdefault(source, set()).add(target)
    if _cyclic(edges):
        findings.append(_finding(task_id, "CYCLE", entry))
    return findings
# END CHECK CYCLE


def check_two_successors(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    entry: str,
    task_id: str,
) -> list[dict[str, str]]:
# CHECK TWO_SUCCESSORS
    findings: list[dict[str, str]] = []
    retired, unresolved = _retired(readable, identities, resolved, reconciles, recon, recon_unusable)
    current = [
        record
        for record in readable
        if identities.get(record.path) and identities.get(record.path) not in retired and record.path not in unresolved
    ]
    groups: dict[str, list[Rec]] = {}
    for record in current:
        target = resolved.get(record.path)
        if target:
            groups.setdefault(target, []).append(record)
    if any(len(group) >= 2 for group in groups.values()):
        findings.append(_finding(task_id, "TWO_SUCCESSORS", entry))
    return findings
# END CHECK TWO_SUCCESSORS


def check_multiple_heads(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    entry: str,
    task_id: str,
) -> list[dict[str, str]]:
# CHECK MULTIPLE_HEADS
    findings: list[dict[str, str]] = []
    retired, unresolved = _retired(readable, identities, resolved, reconciles, recon, recon_unusable)
    current = [
        record
        for record in readable
        if identities.get(record.path) and identities.get(record.path) not in retired and record.path not in unresolved
    ]
    groups: dict[str, list[Rec]] = {}
    for record in current:
        target = resolved.get(record.path)
        if target:
            groups.setdefault(target, []).append(record)
    fork = any(len(group) >= 2 for group in groups.values())
    fork_members = sum(len(group) for group in groups.values() if len(group) >= 2)
    if len(current) >= 2 and not (fork and len(current) == fork_members):
        findings.append(_finding(task_id, "MULTIPLE_HEADS", entry))
    return findings
# END CHECK MULTIPLE_HEADS


def check_not_current_head(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    other_findings: Sequence[Mapping[str, str]],
    focus: str | None,
    entry: str,
) -> list[dict[str, str]]:
# CHECK NOT_CURRENT_HEAD
    findings: list[dict[str, str]] = []
    if focus is None or any(item.get("code") == "UNREADABLE_JSON" for item in other_findings):
        return findings
    if other_findings:
        return findings
    retired, unresolved = _retired(readable, identities, resolved, reconciles, recon, recon_unusable)
    current = [
        record
        for record in readable
        if identities.get(record.path) and identities.get(record.path) not in retired and record.path not in unresolved
    ]
    heads = {identities.get(record.path) for record in current if identities.get(record.path)}
    named = identities.get(focus)
    if named not in heads:
        task_id = next((record.task_id for record in readable if record.path == focus), "")
        if not task_id and readable:
            task_id = readable[0].task_id
        findings.append(_finding(task_id or "UNSCOPED", "NOT_CURRENT_HEAD", entry))
    return findings
# END CHECK NOT_CURRENT_HEAD


def check_manifest_field(manifests: Sequence[Manifest], entry: str, fallback_task: str) -> list[dict[str, str]]:
# CHECK MANIFEST_FIELD
    findings: list[dict[str, str]] = []
    for manifest in manifests:
        if manifest.unreadable:
            continue
        for item in manifest.entries:
            path_ok = isinstance(item.path, str) and bool(item.path)
            task_ok = isinstance(item.task_id, str) and bool(item.task_id)
            if not path_ok or not task_ok:
                task_id = item.task_id if isinstance(item.task_id, str) and item.task_id else fallback_task
                findings.append(_finding(task_id, "MANIFEST_FIELD", entry))
    return findings
# END CHECK MANIFEST_FIELD


def check_manifest_missing(manifests: Sequence[Manifest], present: set[str], entry: str) -> list[dict[str, str]]:
# CHECK MANIFEST_MISSING
    findings: list[dict[str, str]] = []
    for manifest in manifests:
        if manifest.unreadable:
            continue
        directory = str(Path(manifest.relative_path).parent)
        for item in manifest.entries:
            if not isinstance(item.path, str) or not item.path:
                continue
            if not isinstance(item.task_id, str) or not item.task_id:
                continue
            full = str(Path(directory) / item.path)
            if full not in present:
                findings.append(_finding(item.task_id, "MANIFEST_MISSING", entry))
    return findings
# END CHECK MANIFEST_MISSING


def check_manifest_unlisted(
    manifests: Sequence[Manifest],
    records: Sequence[Rec],
    entry: str,
    fallback_task: str,
    scan_uncovered: bool = False,
) -> list[dict[str, str]]:
# CHECK MANIFEST_UNLISTED
    findings: list[dict[str, str]] = []
    for manifest in manifests:
        if manifest.unreadable:
            continue
        directory = str(Path(manifest.relative_path).parent)
        listed: set[str] = set()
        for item in manifest.entries:
            if isinstance(item.path, str) and item.path:
                listed.add(item.path)
        for record in records:
            if str(Path(record.path).parent) != directory or record.unreadable or _text_broken(record):
                continue
            if Path(record.path).name not in listed:
                findings.append(_finding(record.task_id or fallback_task, "MANIFEST_UNLISTED", entry))
    if scan_uncovered:
        covered = {str(Path(manifest.relative_path).parent) for manifest in manifests}
        for record in records:
            if not record.path.startswith("reports/evidence/"):
                continue
            if record.unreadable or _text_broken(record):
                continue
            if str(Path(record.path).parent) not in covered:
                findings.append(_finding(record.task_id or fallback_task, "MANIFEST_UNLISTED", entry))
    return findings
# END CHECK MANIFEST_UNLISTED


def _resolve(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    reconciles: Mapping[str, str],
) -> dict[str, str | None]:
    listed = {value for value in identities.values() if value}
    resolved: dict[str, str | None] = {}
    for record in readable:
        raw = record.supersedes
        if raw is None or _lone(raw):
            resolved[record.path] = None
            continue
        identity = identities.get(record.path)
        if identity is not None and raw == identity:
            resolved[record.path] = raw
            continue
        if raw in listed:
            resolved[record.path] = raw
            continue
        mapped = reconciles.get(raw)
        mapped_listed = isinstance(mapped, str) and bool(mapped) and mapped in listed
        resolved[record.path] = mapped if mapped_listed else None
    return resolved


def _retired(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
) -> tuple[set[str], set[str]]:
    del reconciles
    listed = {value for value in identities.values() if value}
    unresolved: set[str] = set()
    # Recomputed by the caller for historical targets. Kept here so each check
    # that receives reconciles can pass the same pair without a second policy.
    retired: set[str] = set()
    for record in readable:
        source = identities.get(record.path)
        target = resolved.get(record.path)
        if source and target and target != source and target in listed:
            retired.add(target)
    if recon is not None and not recon_unusable:
        for item in recon.supersedes:
            if item in listed and item != recon.remaining_head:
                retired.add(item)
    return retired, unresolved


def _unresolved_targets(readable: Sequence[Rec], reconciles: Mapping[str, str]) -> set[str]:
    targets: set[str] = set()
    for record in readable:
        raw = record.supersedes
        if not isinstance(raw, str) or not _historical(raw, readable) or reconciles.get(raw):
            continue
        for other in readable:
            if other.path != record.path and _referenced(raw, other):
                targets.add(other.path)
    return targets


def _graph_findings(records: Sequence[Rec], recon: Recon | None, entry: str, focus: str | None, task_id: str) -> tuple[list[dict[str, str]], str | None]:
    readable = [record for record in records if not record.unreadable and not _text_broken(record)]
    unread = check_unreadable_json(records, task_id, entry, focus, ())
    if focus is not None and any(item["code"] == "UNREADABLE_JSON" for item in unread):
        return _dedupe(unread), None
    recon_unusable = recon is None or recon.missing or recon.unreadable or recon.under_evidence or bool(recon.embedded_task_id)
    reconciles: dict[str, str] = {}
    if recon is not None and not recon_unusable:
        reconciles = dict(recon.reconciles)
        values = [recon.remaining_head, recon.selected_path, *recon.supersedes]
        if not recon.selected_path or any(_lone(value) for value in values):
            recon_unusable = True
            reconciles = {}
    ambiguous = _ambiguous_keys(readable, reconciles)
    identities = {record.path: _canonical(record, reconciles, ambiguous) for record in readable}
    resolved = _resolve(readable, identities, reconciles)
    unresolved = _unresolved_targets(readable, reconciles)
    findings: list[dict[str, str]] = list(unread)
    findings.extend(check_ambiguous_identity(readable, reconciles, entry, task_id))
    findings.extend(check_self_supersedes(readable, identities, reconciles, entry))
    findings.extend(check_supersedes_unresolved(readable, identities, reconciles, entry))
    findings.extend(check_reconciliation_unlisted(readable, identities, recon, recon_unusable, entry))
    findings.extend(check_cycle(readable, identities, resolved, entry, task_id))
    findings.extend(check_two_successors(readable, identities, resolved, reconciles, recon, recon_unusable, entry, task_id))
    findings.extend(check_multiple_heads(readable, identities, resolved, reconciles, recon, recon_unusable, entry, task_id))
    # The retired set used by the successor checks must include unresolved targets.
    # Those checks call _retired, which does not know unresolved targets, so the
    # current-set filter is repeated with the targets folded into retirement by
    # dropping those paths inside the checks via identities. See _current_with.
    findings = _apply_unresolved(findings, readable, identities, resolved, reconciles, recon, recon_unusable, unresolved, entry, task_id)
    absent = check_reconciliation_absent(
        readable, identities, resolved, reconciles, recon, recon_unusable, findings, entry, task_id,
    )
    findings.extend(absent)
    blocked = _dedupe(findings)
    if not blocked:
        blocked.extend(
            _off_chain_multiple_heads(
                readable, identities, resolved, reconciles, recon, recon_unusable, unresolved, entry, task_id,
            )
        )
        blocked = _dedupe(blocked)
    head = _validated_head(readable, identities, resolved, reconciles, recon, recon_unusable, unresolved, blocked)
    focus_findings = check_not_current_head(
        readable, identities, resolved, reconciles, recon, recon_unusable, blocked, focus, entry,
    )
    blocked.extend(focus_findings)
    if focus_findings:
        head = None
    return _dedupe(blocked), head


def _current_paths(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    unresolved: set[str],
) -> list[Rec]:
    retired, _ignored = _retired(readable, identities, resolved, reconciles, recon, recon_unusable)
    return [
        record
        for record in readable
        if identities.get(record.path)
        and identities.get(record.path) not in retired
        and record.path not in unresolved
    ]


def _apply_unresolved(
    findings: list[dict[str, str]],
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    unresolved: set[str],
    entry: str,
    task_id: str,
) -> list[dict[str, str]]:
    """Replace successor findings with the same checks on the filtered current set.

    ``_retired`` does not see unresolved historical targets. The oracle removes
    those paths from the current set before the fork test. Re-running the two
    checks with those paths already dropped keeps each code inside its function.
    """
    kept = [item for item in findings if item["code"] not in {"TWO_SUCCESSORS", "MULTIPLE_HEADS"}]
    visible = [record for record in readable if record.path not in unresolved]
    kept.extend(check_two_successors(visible, identities, resolved, reconciles, recon, recon_unusable, entry, task_id))
    kept.extend(check_multiple_heads(visible, identities, resolved, reconciles, recon, recon_unusable, entry, task_id))
    return kept


def _off_chain_multiple_heads(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    unresolved: set[str],
    entry: str,
    task_id: str,
) -> list[dict[str, str]]:
    """A usable reconciliation admits only the chain that starts at ``remaining_head``.

    The chain grows by resolved supersedes edges whose target is already on it.
    A current identity outside that chain is another head (``MULTIPLE_HEADS``).
    """
    if recon is None or recon_unusable:
        return []
    current = _current_paths(readable, identities, resolved, reconciles, recon, recon_unusable, unresolved)
    chain = {recon.remaining_head}
    growing = True
    while growing:
        growing = False
        for record in readable:
            source = identities.get(record.path)
            target = resolved.get(record.path)
            if source and target in chain and source not in chain:
                chain.add(source)
                growing = True
    if any(identities.get(record.path) not in chain for record in current):
        return [_finding(task_id, "MULTIPLE_HEADS", entry)]
    return []


def _validated_head(
    readable: Sequence[Rec],
    identities: Mapping[str, str | None],
    resolved: Mapping[str, str | None],
    reconciles: Mapping[str, str],
    recon: Recon | None,
    recon_unusable: bool,
    unresolved: set[str],
    findings: Sequence[Mapping[str, str]],
) -> str | None:
    if findings:
        return None
    current = _current_paths(readable, identities, resolved, reconciles, recon, recon_unusable, unresolved)
    if len(current) != 1:
        return None
    return identities.get(current[0].path)


def _dedupe(findings: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    chosen: list[dict[str, str]] = []
    for item in findings:
        key = (item["task_id"], item["code"], item["entry"])
        if key in seen:
            continue
        seen.add(key)
        chosen.append({"code": item["code"], "entry": item["entry"], "task_id": item["task_id"]})
    chosen.sort(key=lambda item: (item["task_id"], item["code"], item["entry"]))
    return chosen


class Store:
    """Bytes of one tree: the worktree, one git commit, or an explicit graph."""

    def __init__(self, root: Path, commit: str | None, files: Mapping[str, bytes] | None = None) -> None:
        self.root = root
        self.commit = commit
        self._memory = None if files is None else dict(files)

    def read(self, relative: str) -> bytes | None:
        if self._memory is not None:
            return self._memory.get(relative)
        if self.commit is None:
            path = self.root / relative
            if not path.is_file():
                return None
            return path.read_bytes()
        probe = subprocess.run(
            ["git", "cat-file", "blob", f"{self.commit}:{relative}"],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        if probe.returncode != 0:
            return None
        return probe.stdout

    def files(self, prefix: str) -> list[str]:
        if self._memory is not None:
            return sorted(path for path in self._memory if _below(path, prefix))
        if self.commit is None:
            base = self.root / prefix
            if not base.exists():
                return []
            found: list[str] = []
            for path in base.rglob("*"):
                if path.is_file():
                    found.append(path.relative_to(self.root).as_posix())
            return sorted(found)
        # Without -z, git quotes non-ASCII paths and the quoted line fails the prefix test.
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "--name-only", self.commit],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        if listing.returncode != 0:
            return []
        names: list[str] = []
        for raw_name in listing.stdout.split(b"\0"):
            if not raw_name:
                continue
            # Git blob names are raw bytes. surrogateescape keeps a non-UTF-8 name until read.
            line = raw_name.decode("utf-8", "surrogateescape")
            if _below(line, prefix):
                names.append(line)
        return sorted(names)


def _load_record(relative: str, raw: bytes, fallback_task: str) -> Rec:
    try:
        data = _loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return _unreadable_record(relative, raw, fallback_task)
    if not isinstance(data, dict):
        return _unreadable_record(relative, raw, fallback_task)
    if "task_id" not in data:
        task_id = fallback_task
    else:
        raw_task = data["task_id"]
        if not isinstance(raw_task, str) or not raw_task:
            return _unreadable_record(relative, raw, fallback_task)
        task_id = raw_task
    if "record_id" not in data:
        record_id: str | None = None
    else:
        raw_id = data["record_id"]
        if not isinstance(raw_id, str):
            return _unreadable_record(relative, raw, fallback_task)
        record_id = raw_id or None
    if "supersedes" not in data:
        supersedes: str | None = None
    else:
        raw_sup = data["supersedes"]
        if not isinstance(raw_sup, str):
            return _unreadable_record(relative, raw, fallback_task)
        supersedes = raw_sup
    if "commit" not in data:
        commit: str | None = None
    else:
        raw_commit = data["commit"]
        if not isinstance(raw_commit, str):
            return _unreadable_record(relative, raw, fallback_task)
        commit = raw_commit or None
    record = Rec(relative, task_id, record_id, supersedes, commit, raw, False)
    if _text_broken(record):
        return Rec(relative, task_id, record_id, supersedes, commit, raw, True)
    return record


def _load_recon(task_id: str, store: Store) -> Recon:
    """Reconciliation is only the exact directory and the exact ``<task>.json`` name."""
    relative = f"{RECON_DIR}/{task_id}.json"
    raw = store.read(relative)
    if raw is None:
        return Recon(task_id, "", (), (), "", None, False, False, True)
    return _parse_recon(task_id, raw, under_evidence=False, unreadable=False)


def _parse_recon(task_id: str, raw: bytes, *, under_evidence: bool, unreadable: bool) -> Recon:
    if unreadable:
        return _bad_recon(task_id, under_evidence)
    try:
        data = _loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return _bad_recon(task_id, under_evidence)
    if not isinstance(data, dict):
        return _bad_recon(task_id, under_evidence)
    if "task_id" not in data:
        embedded_task: str | None = None
    else:
        embedded = data["task_id"]
        if not isinstance(embedded, str):
            return _bad_recon(task_id, under_evidence)
        embedded_task = embedded or None
    if "remaining_head" not in data:
        remaining = ""
    else:
        remaining_raw = data["remaining_head"]
        if not isinstance(remaining_raw, str):
            return _bad_recon(task_id, under_evidence)
        remaining = remaining_raw
    selected = ""
    if "selection_proof" in data:
        proof = data["selection_proof"]
        if not isinstance(proof, dict):
            return _bad_recon(task_id, under_evidence)
        if "selected_path" in proof:
            selected_raw = proof["selected_path"]
            if not isinstance(selected_raw, str):
                return _bad_recon(task_id, under_evidence)
            selected = selected_raw
    supersedes_raw = data.get("supersedes")
    if not isinstance(supersedes_raw, list) or not all(isinstance(item, str) for item in supersedes_raw):
        return _bad_recon(task_id, under_evidence)
    supersedes: tuple[str, ...] = tuple(supersedes_raw)
    reconciles_raw = data.get("reconciles")
    if not isinstance(reconciles_raw, dict):
        return _bad_recon(task_id, under_evidence)
    pairs: list[tuple[str, str]] = []
    for key, value in reconciles_raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            return _bad_recon(task_id, under_evidence)
        if key and value:
            pairs.append((key, value))
    return Recon(task_id, remaining, supersedes, tuple(pairs), selected, embedded_task, False, under_evidence, False)


def _load_manifest(relative: str, store: Store) -> Manifest:
    raw = store.read(relative)
    if raw is None:
        return Manifest(relative, (), True)
    try:
        data = _loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return Manifest(relative, (), True)
    if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list):
        return Manifest(relative, (), True)
    entries: list[ManifestEntry] = []
    for item in data["artifacts"]:
        if not isinstance(item, dict):
            entries.append(ManifestEntry(None, None))
            continue
        entries.append(ManifestEntry(item.get("path"), item.get("task_id")))
    return Manifest(relative, tuple(entries), False)


def _completed(store: Store) -> list[str] | None:
    """Completed task ids, or None when the state document cannot name that set.

    A missing file, a missing ``completed_evidence_tasks`` key, a non-object
    document, a non-list value, or a non-string item is unreadable. An empty
    list is a usable set.
    """
    raw = store.read("reports/development/EXECUTION_STATE.json")
    if raw is None:
        return None
    try:
        data = _loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if "completed_evidence_tasks" not in data:
        return None
    tasks = data["completed_evidence_tasks"]
    if not isinstance(tasks, list):
        return None
    chosen: list[str] = []
    for item in tasks:
        if not isinstance(item, str) or not item:
            return None
        chosen.append(item)
    return sorted(set(chosen))


def _evidence_records(store: Store, fallback_task: str) -> list[Rec]:
    records: list[Rec] = []
    for relative in store.files("reports/evidence"):
        if not relative.endswith(".json"):
            continue
        name = Path(relative).name
        # A name ending in ``.reconciliation.json`` under evidence is an evidence record.
        if name == "MANIFEST.json":
            continue
        if EXCLUDED_PARTS & set(Path(relative).parts):
            continue
        raw = store.read(relative)
        if raw is None:
            records.append(_unreadable_record(relative, b"", fallback_task))
            continue
        records.append(_load_record(relative, raw, fallback_task))
    return records


def _manifests(store: Store) -> list[Manifest]:
    return [_load_manifest(relative, store) for relative in store.files("reports/evidence") if relative.endswith("/MANIFEST.json") or relative.endswith("MANIFEST.json")]


def _present_paths(records: Sequence[Rec]) -> set[str]:
    return {record.path for record in records if not record.unreadable and not _text_broken(record)}


def _manifest_findings(
    manifests: Sequence[Manifest],
    records: Sequence[Rec],
    entry: str,
    fallback_task: str,
    files: set[str],
    scan_uncovered: bool,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    # Class 15 is a listed file absent from the tree. Logs and other non-record
    # artifacts are files. Readable JSON records stay in the set for the oracle.
    present = set(files) | _present_paths(records)
    findings.extend(check_manifest_field(manifests, entry, fallback_task))
    findings.extend(check_manifest_missing(manifests, present, entry))
    findings.extend(check_manifest_unlisted(manifests, records, entry, fallback_task, scan_uncovered))
    findings.extend(check_unreadable_json(records, fallback_task, entry, None, manifests))
    return findings


def _task_records(records: Sequence[Rec], task_id: str) -> list[Rec]:
    return [record for record in records if record.task_id == task_id or (record.unreadable and record.task_id == task_id)]


def evaluate(store: Store, entry: str, focus: str | None, manifest_path: str | None) -> tuple[str, list[dict[str, str]], dict[str, str]]:
    completed = _completed(store)
    # E3 admits one manifest. A missing state file is not a record and is not UNREADABLE_JSON.
    if completed is None and entry != "E3":
        return "FAIL", [_finding("UNSCOPED", "UNREADABLE_JSON", entry)], {}
    if completed is None:
        completed = []
    fallback = completed[0] if len(completed) == 1 else "UNSCOPED"
    if entry == "E2" and focus is not None:
        outside = check_outside_evidence(focus, store.read(focus), entry, fallback)
        if outside:
            return "FAIL", _dedupe(outside), {}
    records = _evidence_records(store, fallback)
    # A lone completed task owns unreadable files that carry no task_id of their own.
    if len(completed) == 1:
        records = [_retag(record, completed[0]) if record.unreadable and record.task_id == fallback else record for record in records]
    findings: list[dict[str, str]] = []
    heads: dict[str, str] = {}
    if entry in {"E1", "E2"}:
        tasks = completed
        if entry == "E2" and focus is not None:
            named = next((record for record in records if record.path == focus), None)
            task_id = named.task_id if named is not None and not named.unreadable else fallback
            if named is not None and named.unreadable and len(completed) == 1:
                task_id = completed[0]
            tasks = [task_id]
        for task_id in tasks:
            group = _task_records(records, task_id)
            if entry == "E2" and focus is not None and not any(record.path == focus for record in group):
                raw = store.read(focus)
                if raw is None or _load_record(focus, raw, task_id).unreadable:
                    group = [Rec(focus, task_id, None, None, None, raw or b"", True), *group]
            recon = _load_recon(task_id, store)
            task_findings, head = _graph_findings(group, recon, entry, focus if entry == "E2" else None, task_id)
            findings.extend(task_findings)
            if head is not None:
                heads[task_id] = head
    manifest_findings: list[dict[str, str]] = []
    if entry in {"E1", "E3"}:
        manifests = _manifests(store)
        if manifest_path is not None:
            manifests = [item for item in manifests if item.relative_path == manifest_path]
            if not manifests:
                manifest_findings.append(_finding(fallback, "UNREADABLE_JSON", entry))
        # A named manifest that is absent is UNREADABLE_JSON only. Do not also
        # mark every canonical record MANIFEST_UNLISTED for that missing file.
        # E3 does not scan another gate: class 16 stays inside the requested directory.
        scan_uncovered = manifest_path is None
        manifest_records = records
        if entry == "E3":
            directories = {str(Path(item.relative_path).parent) for item in manifests}
            manifest_records = [
                record for record in records if str(Path(record.path).parent) in directories
            ]
        manifest_findings.extend(
            _manifest_findings(
                manifests,
                manifest_records,
                entry,
                fallback,
                set(store.files("reports/evidence")),
                scan_uncovered,
            )
        )
    if entry == "E3":
        findings = manifest_findings
        heads = {}
    elif entry == "E1":
        findings.extend(manifest_findings)
    findings = _dedupe(findings)
    if findings:
        heads = {}
    status = "PASS" if not findings else "FAIL"
    return status, findings, heads


def _retag(record: Rec, task_id: str) -> Rec:
    return Rec(record.path, task_id, record.record_id, record.supersedes, record.commit, record.raw, record.unreadable)


def _emit(status: str, entry: str, findings: Sequence[Mapping[str, str]], heads: Mapping[str, str]) -> int:
    payload = {
        "entry": entry,
        "findings": [dict(item) for item in findings],
        "status": status,
        "validated_heads": dict(sorted(heads.items())),
    }
    encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    sys.stdout.buffer.write(encoded)
    return 0 if status == "PASS" and not findings else 1


def _invocation_refused(commit: str | None, record: str | None, manifest: str | None) -> bool:
    """E2 is only the pair. A presented commit or record is never dropped, including next to E3."""
    presented_pair = commit is not None or record is not None
    complete_pair = commit is not None and record is not None
    if manifest is not None and presented_pair:
        return True
    return presented_pair and not complete_pair


def _pack(status: str, findings: Sequence[Mapping[str, str]], heads: Mapping[str, str]) -> dict[str, object]:
    return {
        "findings": [dict(item) for item in findings],
        "status": status,
        "validated_heads": dict(sorted(heads.items())),
    }


def select_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    """One pure decision on an explicit graph. E1, E2, and E3 are projections of it.

    The graph carries bytes. This function does not read the worktree or a git commit.
    """
    completed = graph.get("completed")
    tasks = [item for item in completed] if isinstance(completed, list) else []
    files: dict[str, bytes] = {}
    records = graph.get("records") if isinstance(graph.get("records"), list) else []
    manifests = graph.get("manifests") if isinstance(graph.get("manifests"), list) else []
    reconciliations = graph.get("reconciliations") if isinstance(graph.get("reconciliations"), list) else []
    for item in [*records, *manifests, *reconciliations]:
        if isinstance(item, Mapping) and isinstance(item.get("path"), str) and isinstance(item.get("raw"), bytes):
            files[item["path"]] = item["raw"]
    state = {"completed_evidence_tasks": tasks}
    files["reports/development/EXECUTION_STATE.json"] = (
        json.dumps(state, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    store = Store(Path("."), None, files)
    root_status, root_findings, root_heads = evaluate(store, "E1", None, None)
    by_record: dict[str, dict[str, object]] = {}
    for item in records:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            continue
        path = item["path"]
        status, findings, heads = evaluate(store, "E2", path, None)
        by_record[path] = _pack(status, findings, heads)
    by_manifest: dict[str, dict[str, object]] = {}
    for item in manifests:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            continue
        path = item["path"]
        status, findings, heads = evaluate(store, "E3", None, path)
        by_manifest[path] = _pack(status, findings, heads)
    return {
        "entries": {
            "E1": _pack(root_status, root_findings, root_heads),
            "E2": by_record,
            "E3": by_manifest,
        }
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--execution-commit", default=None)
    parser.add_argument("--record", default=None)
    parser.add_argument("--manifest", default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if _invocation_refused(args.execution_commit, args.record, args.manifest):
        return _emit("FAIL", "E2", [_finding("UNSCOPED", "UNREADABLE_JSON", "E2")], {})
    if args.manifest is not None:
        entry = "E3"
        commit = None
    elif args.execution_commit is not None and args.record is not None:
        entry = "E2"
        commit = args.execution_commit
    else:
        entry = "E1"
        commit = None
    store = Store(root, commit)
    status, findings, heads = evaluate(store, entry, args.record, args.manifest)
    return _emit(status, entry, findings, heads)


if __name__ == "__main__":
    raise SystemExit(main())
