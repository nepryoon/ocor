#!/usr/bin/env python3
"""RED tests for the OCOR-DEV-REM-0068 current-evidence-head gate.

The reference selector in this module is the oracle. It uses the Python standard
library only and does not import production code. The production subject is
``scripts/validate_current_evidence_head.py``, which this RED commit does not add.
Tests that invoke it fail while the script is absent. Cell count is 3 entries by
17 classes (51). No cell outcome is a silent skip. OCOR-DEV-REM-0068-REDESIGN
(2026-11-28) option 1 adds 18 cells. Those cells call production directly and do
not alter the 51-cell oracle.

Contract: reports/assurance/OCOR-DEV-REM-0068-RCCAD/README.md, including
OCOR-DEV-REM-0068-PIN-INVENTORY (2026-11-27).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_current_evidence_head.py"
TASK = "OCOR-DEV-0099"
GATE = "G0"
CREATED = "2026-11-27T00:00:00Z"

CODES = frozenset(
    {
        "NOT_CURRENT_HEAD",
        "RECONCILIATION_ABSENT",
        "SELF_SUPERSEDES",
        "TWO_SUCCESSORS",
        "MULTIPLE_HEADS",
        "SUPERSEDES_UNRESOLVED",
        "CYCLE",
        "RECONCILIATION_UNLISTED",
        "MANIFEST_FIELD",
        "MANIFEST_MISSING",
        "MANIFEST_UNLISTED",
        "UNREADABLE_JSON",
        "OUTSIDE_EVIDENCE",
        "AMBIGUOUS_IDENTITY",
    }
)
ENTRIES = ("E1", "E2", "E3")
MUTATION_CHECKS = (
    "SELF_SUPERSEDES",
    "TWO_SUCCESSORS",
    "MULTIPLE_HEADS",
    "CYCLE",
    "RECONCILIATION_ABSENT",
    "RECONCILIATION_UNLISTED",
    "SUPERSEDES_UNRESOLVED",
    "NOT_CURRENT_HEAD",
    "MANIFEST_FIELD",
    "MANIFEST_MISSING",
    "MANIFEST_UNLISTED",
    "UNREADABLE_JSON",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lone_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in value)


@dataclass(frozen=True)
class Record:
    path: str
    record_id: str | None = None
    supersedes: str | None = None
    commit: str | None = None
    unreadable: bool = False
    non_utf8: bool = False
    nan_literal: bool = False
    broken: bool = False
    literal: bytes | None = None


@dataclass(frozen=True)
class Reconciliation:
    task_id: str
    remaining_head: str
    supersedes: tuple[str, ...]
    reconciles: tuple[tuple[str, str], ...]
    selected_path: str
    embedded_task_id: str | None = None
    unreadable: bool = False
    under_evidence: bool = False
    missing: bool = False
    literal: bytes | None = None
    reject: bool = False


@dataclass(frozen=True)
class ManifestEntry:
    path: object
    task_id: object


@dataclass(frozen=True)
class Manifest:
    relative_path: str
    entries: tuple[ManifestEntry, ...]
    unreadable: bool = False
    literal: bytes | None = None
    reject: bool = False


@dataclass(frozen=True)
class World:
    completed: tuple[str, ...]
    records: tuple[Record, ...]
    reconciliations: tuple[Reconciliation, ...]
    manifests: tuple[Manifest, ...]
    state_bytes: bytes | None = None
    state_unreadable: bool = False
    state_missing: bool = False


@dataclass(frozen=True)
class Finding:
    task_id: str
    code: str
    entry: str


@dataclass(frozen=True)
class Outcome:
    status: str
    findings: tuple[Finding, ...]
    validated_heads: tuple[tuple[str, str], ...]


def _record_payload(record: Record) -> dict[str, object]:
    payload: dict[str, object] = {"created_at": CREATED, "task_id": TASK}
    if record.commit is not None:
        payload["commit"] = record.commit
    if record.record_id is not None:
        payload["record_id"] = record.record_id
    if record.supersedes is not None:
        payload["supersedes"] = record.supersedes
    return payload


def record_bytes(record: Record) -> bytes:
    if record.literal is not None:
        return record.literal
    if record.non_utf8:
        return b"\xff\xfe not utf-8"
    if record.nan_literal:
        return b'{"task_id": "OCOR-DEV-0099", "score": NaN}\n'
    if record.unreadable:
        return b"{\n"
    return (json.dumps(_record_payload(record), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _rejected(record: Record) -> bool:
    return record.unreadable or record.non_utf8 or record.nan_literal or record.broken


def _path(name: str) -> str:
    return f"reports/evidence/{GATE}/{name}"


def _manifest_for(names: Sequence[str], extra: tuple[ManifestEntry, ...] = ()) -> Manifest:
    entries = tuple(ManifestEntry(name, TASK) for name in names) + extra
    return Manifest(f"reports/evidence/{GATE}/MANIFEST.json", entries)


def _listed_names(records: Sequence[Record]) -> tuple[str, ...]:
    return tuple(Path(record.path).name for record in records if not _rejected(record))


def _world(
    records: Sequence[Record],
    reconciliations: Sequence[Reconciliation] = (),
    manifest: Manifest | None = None,
) -> World:
    chosen = manifest if manifest is not None else _manifest_for(_listed_names(records))
    return World((TASK,), tuple(records), tuple(reconciliations), (chosen,))


def _historical(value: str, records: Sequence[Record]) -> bool:
    if any(value == record.path for record in records):
        return True
    if "@sha256:" in value:
        return True
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def _referenced(value: str, record: Record) -> bool:
    """True when a historical supersedes string names this listed record."""
    if value == record.path:
        return True
    if value == f"{record.path}@sha256:{_sha256(record_bytes(record))}":
        return True
    return record.commit is not None and value == record.commit


def _text_fields(record: Record) -> tuple[str, ...]:
    values = [record.path, TASK]
    for value in (record.record_id, record.supersedes, record.commit):
        if isinstance(value, str):
            values.append(value)
    return tuple(values)


def _canonical(record: Record, reconciles: Mapping[str, str]) -> str | None:
    if isinstance(record.record_id, str) and record.record_id:
        return record.record_id
    keys = [record.path, f"{record.path}@sha256:{_sha256(record_bytes(record))}"]
    if record.commit is not None:
        keys.append(record.commit)
    for key in keys:
        mapped = reconciles.get(key)
        if isinstance(mapped, str) and mapped:
            return mapped
    return None


def _graph(world: World, entry: str, focus: str | None) -> Outcome:
    findings: set[Finding] = set()
    records = [record for record in world.records if record.path.startswith("reports/evidence/")]
    if focus is not None:
        named = [record for record in records if record.path == focus]
        if not named or _rejected(named[0]):
            findings.add(Finding(TASK, "UNREADABLE_JSON", entry))
            return Outcome("FAIL", tuple(sorted(findings, key=_finding_key)), ())
    for record in records:
        if _rejected(record) or any(_lone_surrogate(value) for value in _text_fields(record)):
            findings.add(Finding(TASK, "UNREADABLE_JSON", entry))
    readable = [record for record in records if not _rejected(record)]
    recon = next((item for item in world.reconciliations if item.task_id == TASK), None)
    recon_unusable = (
        recon is None
        or recon.missing
        or recon.unreadable
        or recon.reject
        or recon.under_evidence
        or bool(recon.embedded_task_id)
    )
    reconciles: dict[str, str] = {}
    if recon is not None and not recon_unusable:
        reconciles = dict(recon.reconciles)
        if not recon.selected_path or any(_lone_surrogate(value) for value in [recon.remaining_head, recon.selected_path, *recon.supersedes]):
            findings.add(Finding(TASK, "RECONCILIATION_ABSENT", entry))
            recon_unusable = True
    identities = {record.path: _canonical(record, reconciles) for record in readable}
    listed_ids = {value for value in identities.values() if value}
    needs_recon = any(identities[record.path] is None for record in readable)
    resolved: dict[str, str | None] = {}
    for record in readable:
        raw = record.supersedes
        if raw is None:
            resolved[record.path] = None
            continue
        if _lone_surrogate(raw):
            continue
        identity = identities[record.path]
        mapped = reconciles.get(raw)
        mapped_listed = isinstance(mapped, str) and bool(mapped) and mapped in listed_ids
        if identity is not None and raw == identity:
            resolved[record.path] = raw
            findings.add(Finding(TASK, "SELF_SUPERSEDES", entry))
            continue
        if raw in listed_ids:
            resolved[record.path] = raw
            continue
        if _historical(raw, readable):
            if mapped_listed:
                resolved[record.path] = mapped
                if mapped == identity:
                    findings.add(Finding(TASK, "SELF_SUPERSEDES", entry))
            elif isinstance(mapped, str) and mapped:
                resolved[record.path] = None
                findings.add(Finding(TASK, "SUPERSEDES_UNRESOLVED", entry))
            else:
                needs_recon = True
                resolved[record.path] = None
            continue
        if mapped_listed:
            resolved[record.path] = mapped
            if mapped == identity:
                findings.add(Finding(TASK, "SELF_SUPERSEDES", entry))
            continue
        resolved[record.path] = None
        findings.add(Finding(TASK, "SUPERSEDES_UNRESOLVED", entry))
    if needs_recon:
        findings.add(Finding(TASK, "RECONCILIATION_ABSENT", entry))
    if recon is not None and (recon.unreadable or recon.reject or recon.under_evidence or bool(recon.embedded_task_id)):
        findings.add(Finding(TASK, "RECONCILIATION_ABSENT", entry))
    listed = listed_ids
    if recon is not None and not recon_unusable:
        listed_ok = recon.remaining_head in listed and recon.selected_path in identities and identities.get(recon.selected_path) == recon.remaining_head
        if recon.remaining_head in recon.supersedes or any(item not in listed for item in recon.supersedes) or not listed_ok:
            findings.add(Finding(TASK, "RECONCILIATION_UNLISTED", entry))
    unresolved_targets: set[str] = set()
    for record in readable:
        raw = record.supersedes
        if not isinstance(raw, str) or not _historical(raw, readable) or reconciles.get(raw):
            continue
        for other in readable:
            if other.path != record.path and _referenced(raw, other):
                unresolved_targets.add(other.path)
    edges: dict[str, set[str]] = {}
    retired: set[str] = set()
    for record in readable:
        source = identities[record.path]
        target = resolved.get(record.path)
        if source and target and target != source and target in listed:
            edges.setdefault(source, set()).add(target)
            retired.add(target)
    if recon is not None and not recon_unusable:
        for item in recon.supersedes:
            if item in listed and item != recon.remaining_head:
                retired.add(item)
    if _cyclic(edges):
        findings.add(Finding(TASK, "CYCLE", entry))
    current = [
        record
        for record in readable
        if identities[record.path] and identities[record.path] not in retired and record.path not in unresolved_targets
    ]
    groups: dict[str, list[Record]] = {}
    for record in current:
        target = resolved.get(record.path)
        if target:
            groups.setdefault(target, []).append(record)
    fork = any(len(group) >= 2 for group in groups.values())
    if fork:
        findings.add(Finding(TASK, "TWO_SUCCESSORS", entry))
    if len(current) >= 2 and not (fork and len(current) == sum(len(group) for group in groups.values() if len(group) >= 2)):
        findings.add(Finding(TASK, "MULTIPLE_HEADS", entry))
    if len(current) == 0 and not findings:
        findings.add(Finding(TASK, "RECONCILIATION_ABSENT", entry))
    if recon is not None and not recon_unusable and not findings:
        chain = {recon.remaining_head}
        growing = True
        while growing:
            growing = False
            for record in readable:
                source = identities[record.path]
                target = resolved.get(record.path)
                if source and target in chain and source not in chain:
                    chain.add(source)
                    growing = True
        if any(identities[record.path] not in chain for record in current):
            findings.add(Finding(TASK, "MULTIPLE_HEADS", entry))
    validated: tuple[tuple[str, str], ...] = ()
    if not findings and len(current) == 1:
        head = identities[current[0].path]
        if head is not None:
            validated = ((TASK, head),)
    if focus is not None and not any(item.code == "UNREADABLE_JSON" for item in findings):
        named_id = identities.get(focus)
        heads = {head for _, head in validated}
        if not findings and named_id not in heads:
            findings.add(Finding(TASK, "NOT_CURRENT_HEAD", entry))
            validated = ()
        elif findings and named_id and validated and named_id not in {head for _, head in validated}:
            validated = ()
    status = "PASS" if not findings else "FAIL"
    return Outcome(status, tuple(sorted(findings, key=_finding_key)), validated)


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


def _manifest_outcome(world: World, entry: str, manifest_path: str | None) -> Outcome:
    findings: set[Finding] = set()
    manifests = world.manifests
    if manifest_path is not None:
        manifests = tuple(item for item in manifests if item.relative_path == manifest_path)
        if not manifests:
            findings.add(Finding(TASK, "UNREADABLE_JSON", entry))
    for manifest in manifests:
        if manifest.unreadable or manifest.reject:
            findings.add(Finding(TASK, "UNREADABLE_JSON", entry))
            continue
        listed: set[str] = set()
        directory = str(Path(manifest.relative_path).parent)
        for item in manifest.entries:
            path_ok = isinstance(item.path, str) and bool(item.path)
            task_ok = isinstance(item.task_id, str) and bool(item.task_id)
            if not path_ok or not task_ok:
                findings.add(Finding(TASK, "MANIFEST_FIELD", entry))
                continue
            assert isinstance(item.path, str)
            listed.add(item.path)
            full = str(Path(directory) / item.path)
            present = any(record.path == full and not record.unreadable for record in world.records)
            if not present:
                findings.add(Finding(str(item.task_id), "MANIFEST_MISSING", entry))
        for record in world.records:
            if str(Path(record.path).parent) != directory:
                continue
            if _rejected(record):
                findings.add(Finding(TASK, "UNREADABLE_JSON", entry))
                continue
            if Path(record.path).name not in listed:
                findings.add(Finding(TASK, "MANIFEST_UNLISTED", entry))
    if manifest_path is None or manifests:
        covered = {str(Path(manifest.relative_path).parent) for manifest in manifests}
        for record in world.records:
            if not record.path.startswith("reports/evidence/") or _rejected(record):
                continue
            if str(Path(record.path).parent) not in covered:
                findings.add(Finding(TASK, "MANIFEST_UNLISTED", entry))
    status = "PASS" if not findings else "FAIL"
    return Outcome(status, tuple(sorted(findings, key=_finding_key)), ())


def _finding_key(finding: Finding) -> tuple[str, str, str]:
    return (finding.task_id, finding.code, finding.entry)


def evaluate(world: World, entry: str, focus: str | None = None, manifest_path: str | None = None) -> Outcome:
    """Return the reference outcome for one entry point. Never skips."""
    if entry not in ENTRIES:
        raise ValueError(entry)
    if world.state_unreadable or world.state_missing or _state_document_rejected(world.state_bytes):
        return Outcome("FAIL", (Finding("UNSCOPED", "UNREADABLE_JSON", entry),), ())
    if entry == "E3":
        return _manifest_outcome(world, entry, manifest_path)
    graph = _graph(world, entry, focus)
    if entry == "E2":
        return graph
    manifest = _manifest_outcome(world, entry, None)
    findings = tuple(sorted(set(graph.findings) | set(manifest.findings), key=_finding_key))
    validated = () if findings else graph.validated_heads
    return Outcome("PASS" if not findings else "FAIL", findings, validated)


def _state_document_rejected(raw: bytes | None) -> bool:
    """True when an explicit state document cannot name the completed-task set."""
    if raw is None:
        return False
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return True
    if not isinstance(data, dict) or "completed_evidence_tasks" not in data:
        return True
    tasks = data["completed_evidence_tasks"]
    return not isinstance(tasks, list) or any(not isinstance(item, str) or not item for item in tasks)


def _record(name: str, record_id: str | None, supersedes: str | None = None, commit: str | None = None) -> Record:
    return Record(_path(name), record_id, supersedes, commit)


def world_for(class_id: int, entry: str) -> tuple[World, str | None]:
    """Build the fixture for one matrix cell. The second item is the E2 record path."""
    head = _record("head.json", f"{TASK}-head")
    old = _record("old.json", f"{TASK}-old", commit="a" * 40)
    nxt = _record("next.json", f"{TASK}-next", old.record_id)
    if class_id == 1:
        return _world((head,)), head.path
    if class_id == 2:
        return _world((old, nxt)), nxt.path
    if class_id == 3:
        linked = _record("next.json", f"{TASK}-next", old.path)
        return _world((old, linked)), linked.path
    if class_id == 4:
        digest = _sha256(record_bytes(old))
        linked = _record("next.json", f"{TASK}-next", f"{old.path}@sha256:{digest}")
        return _world((old, linked)), linked.path
    if class_id == 5:
        linked = _record("next.json", f"{TASK}-next", old.commit)
        return _world((old, linked)), linked.path
    if class_id == 6:
        self_edge = _record("head.json", f"{TASK}-head", f"{TASK}-head")
        return _world((self_edge,)), self_edge.path
    if class_id == 7:
        left = _record("left.json", f"{TASK}-left", old.record_id)
        right = _record("right.json", f"{TASK}-right", old.record_id)
        return _world((old, left, right)), left.path
    if class_id == 8:
        other = _record("other.json", f"{TASK}-other")
        return _world((head, other)), head.path
    if class_id == 9:
        dangling = _record("head.json", f"{TASK}-head", f"{TASK}-missing")
        return _world((dangling,)), dangling.path
    if class_id == 10:
        first = _record("first.json", f"{TASK}-first", f"{TASK}-second")
        second = _record("second.json", f"{TASK}-second", f"{TASK}-first")
        return _world((first, second)), first.path
    if class_id == 11:
        bare = Record(old.path, None, None, old.commit)
        linked = _record("next.json", f"{TASK}-next", bare.path)
        recon = Reconciliation(TASK, f"{TASK}-next", (f"{TASK}-old",), ((bare.path, f"{TASK}-old"),), linked.path)
        return _world((bare, linked), (recon,)), linked.path
    if class_id == 12:
        bare = Record(old.path, None, None, old.commit)
        linked = _record("next.json", f"{TASK}-next", bare.path)
        return _world((bare, linked)), linked.path
    if class_id == 13:
        recon = Reconciliation(TASK, f"{TASK}-unlisted", (), (), head.path)
        return _world((head,), (recon,)), head.path
    if class_id == 14:
        manifest = _manifest_for(("head.json",), (ManifestEntry("", TASK),))
        return _world((head,), manifest=manifest), head.path
    if class_id == 15:
        manifest = _manifest_for(("head.json", "missing.json"))
        return _world((head,), manifest=manifest), head.path
    if class_id == 16:
        extra = _record("extra.json", f"{TASK}-extra")
        listed = _record("head.json", f"{TASK}-head", extra.record_id)
        manifest = _manifest_for(("head.json",))
        return _world((listed, extra), manifest=manifest), listed.path
    if class_id == 17 and entry == "E3":
        manifest = Manifest(_manifest_for(("head.json",)).relative_path, _manifest_for(("head.json",)).entries, True)
        return _world((head,), manifest=manifest), head.path
    if class_id == 17:
        broken = Record(_path("broken.json"), None, unreadable=True)
        return _world((head, broken)), broken.path
    raise ValueError(class_id)


def expected_codes(class_id: int, entry: str) -> frozenset[str]:
    """Contract codes for one cell. E3 does not select heads. E2 does not read manifests."""
    if class_id in {1, 2, 11} and entry in {"E1", "E2"}:
        return frozenset()
    if class_id in {1, 2, 11} and entry == "E3":
        return frozenset()
    graph = {
        3: "RECONCILIATION_ABSENT",
        4: "RECONCILIATION_ABSENT",
        5: "RECONCILIATION_ABSENT",
        6: "SELF_SUPERSEDES",
        7: "TWO_SUCCESSORS",
        8: "MULTIPLE_HEADS",
        9: "SUPERSEDES_UNRESOLVED",
        10: "CYCLE",
        12: "RECONCILIATION_ABSENT",
        13: "RECONCILIATION_UNLISTED",
    }
    if class_id in graph:
        if entry == "E3":
            return frozenset()
        return frozenset({graph[class_id]})
    manifest = {14: "MANIFEST_FIELD", 15: "MANIFEST_MISSING", 16: "MANIFEST_UNLISTED", 17: "UNREADABLE_JSON"}
    if entry == "E2" and class_id in {14, 15, 16}:
        return frozenset()
    if class_id == 17 and entry == "E2":
        return frozenset({"UNREADABLE_JSON"})
    return frozenset({manifest[class_id]})


def cell_disposition(class_id: int, entry: str) -> str:
    """Name how the cell is proved. Never ``SKIP``."""
    if class_id <= 13 and entry == "E3":
        return f"CARRIED_BY_E1:{','.join(sorted(expected_codes(class_id, 'E1'))) or 'PASS'}"
    if class_id in {14, 15, 16} and entry == "E2":
        carried = ",".join(sorted(expected_codes(class_id, "E1")))
        return f"CARRIED_BY_E1:{carried}"
    codes = expected_codes(class_id, entry)
    return "PASS" if not codes else ",".join(sorted(codes))


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def materialise(root: Path, world: World) -> None:
    if not world.state_missing:
        state = {"completed_evidence_tasks": list(world.completed)}
        state_bytes = world.state_bytes if world.state_bytes is not None else (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _write(root / "reports" / "development" / "EXECUTION_STATE.json", state_bytes)
    for record in world.records:
        _write(root / record.path, record_bytes(record))
    written_recons: set[Path] = set()
    for recon in world.reconciliations:
        if recon.missing:
            continue
        body: dict[str, object] = {
            "reconciles": dict(recon.reconciles),
            "remaining_head": recon.remaining_head,
            "selection_proof": {"base": "fixture", "selected_path": recon.selected_path, "selector": "select_most_recent"},
            "supersedes": list(recon.supersedes),
        }
        if recon.embedded_task_id is not None:
            body["task_id"] = recon.embedded_task_id
        target = root / "reports" / "assurance" / "OCOR-DEV-REM-0068-RCCAD" / "reconciliation" / f"{recon.task_id}.json"
        if recon.under_evidence:
            target = root / "reports" / "evidence" / GATE / f"{recon.task_id}.reconciliation.json"
        if recon.literal is not None:
            data = recon.literal
        elif recon.unreadable:
            data = b"{\n"
        else:
            data = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8")
        # The oracle keeps the first reconciliation of a task. A later file for the same path would hide it.
        if target in written_recons:
            continue
        written_recons.add(target)
        _write(target, data)
    for manifest in world.manifests:
        if manifest.literal is not None:
            _write(root / manifest.relative_path, manifest.literal)
            continue
        if manifest.unreadable:
            _write(root / manifest.relative_path, b"{\n")
            continue
        payload = {"artifacts": [{"path": item.path, "task_id": item.task_id} for item in manifest.entries]}
        _write(root / manifest.relative_path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _run(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root, text=True, capture_output=True, check=False)


def _production(world: World, entry: str, focus: str | None = None, script: Path | None = None) -> Outcome:
    subject = script or SCRIPT
    if not subject.is_file():
        raise AssertionError(f"production script missing: {SCRIPT.relative_to(ROOT)}")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        materialise(root, world)
        if entry == "E1":
            args = ["--root", str(root)]
        elif entry == "E2":
            if focus is None:
                raise AssertionError("E2 requires a record path")
            _commit(root)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            args = ["--root", str(root), "--execution-commit", commit, "--record", focus]
        else:
            if not world.manifests:
                raise AssertionError("E3 requires a manifest path")
            args = ["--root", str(root), "--manifest", world.manifests[0].relative_path]
        completed = subprocess.run([sys.executable, str(subject), *args], cwd=root, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(completed.stderr or completed.stdout) from exc
    findings = tuple(sorted((Finding(str(item["task_id"]), str(item["code"]), str(item["entry"])) for item in payload["findings"]), key=_finding_key))
    heads = tuple(sorted((str(key), str(value)) for key, value in payload["validated_heads"].items()))
    return Outcome(str(payload["status"]), findings, heads)


def _commit(root: Path) -> None:
    subprocess.check_call(["git", "init", "-q"], cwd=root)
    # Quote non-ASCII names, as Git does by default. Listing must not depend on quotepath=false.
    subprocess.check_call(["git", "config", "core.quotepath", "true"], cwd=root)
    subprocess.check_call(["git", "add", "-A"], cwd=root)
    subprocess.check_call(["git", "-c", "user.email=dev@example.com", "-c", "user.name=OCOR Test", "commit", "-q", "-m", "fixture"], cwd=root)


def _rewrite_alias(value: str | None, path_map: Mapping[str, str], id_map: Mapping[str, str]) -> str | None:
    if value is None:
        return None
    if value in id_map:
        return id_map[value]
    if value in path_map:
        return path_map[value]
    marker = "@sha256:"
    if marker in value:
        path, _sep, digest = value.partition(marker)
        if path in path_map:
            return f"{path_map[path]}{marker}{digest}"
    return value


def _suffix_world(world: World, suffix: str) -> World:
    """Disjoint copy so a combined graph keeps every record as its own file."""
    path_map = {
        record.path: str(Path(record.path).with_name(f"{Path(record.path).stem}-{suffix}{Path(record.path).suffix}"))
        for record in world.records
    }
    id_map = {record.record_id: f"{record.record_id}-{suffix}" for record in world.records if record.record_id}
    records = tuple(
        Record(
            path_map[record.path],
            id_map.get(record.record_id) if record.record_id else None,
            _rewrite_alias(record.supersedes, path_map, id_map),
            record.commit,
            record.unreadable,
            record.non_utf8,
            record.nan_literal,
            record.broken,
            record.literal,
        )
        for record in world.records
    )
    reconciliations = tuple(
        Reconciliation(
            recon.task_id,
            id_map.get(recon.remaining_head, recon.remaining_head),
            tuple(id_map.get(item, item) for item in recon.supersedes),
            tuple((_rewrite_alias(key, path_map, id_map) or key, id_map.get(value, value)) for key, value in recon.reconciles),
            path_map.get(recon.selected_path, recon.selected_path),
            recon.embedded_task_id,
            recon.unreadable,
            recon.under_evidence,
            recon.missing,
            recon.literal,
            recon.reject,
        )
        for recon in world.reconciliations
    )
    return World(world.completed, records, reconciliations, world.manifests, world.state_bytes, world.state_unreadable, world.state_missing)


def _combine(left: World, right: World) -> World:
    shifted = _suffix_world(right, "b")
    return World(left.completed, left.records + shifted.records, left.reconciliations + shifted.reconciliations, left.manifests)


def _random_world(seed: int) -> World:
    rng = random.Random(seed)
    count = rng.randint(1, 4)
    records = []
    for index in range(count):
        record_id = f"{TASK}-r{index}"
        supersedes = f"{TASK}-r{rng.randrange(count)}" if index and rng.random() < 0.7 else None
        records.append(_record(f"r{index}.json", record_id, supersedes))
    return _world(records)


class OracleTests(unittest.TestCase):
    def test_oracle_source_does_not_import_production(self) -> None:
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *[alias.name for alias in node.names]]
            else:
                continue
            for name in names:
                self.assertNotIn("validate_current_evidence_head", name)

    def test_cell_count_is_51_and_never_skips(self) -> None:
        cells = [(entry, class_id) for entry in ENTRIES for class_id in range(1, 18)]
        self.assertEqual(51, len(cells))
        for entry, class_id in cells:
            disposition = cell_disposition(class_id, entry)
            self.assertNotIn("SKIP", disposition)
            self.assertTrue(disposition)

    def test_each_class_matches_the_contract_code(self) -> None:
        for entry in ENTRIES:
            for class_id in range(1, 18):
                with self.subTest(entry=entry, class_id=class_id):
                    world, focus = world_for(class_id, entry)
                    record = focus if entry == "E2" and class_id not in {14, 15, 16} else None
                    if class_id == 2 and entry == "E2":
                        outcome = evaluate(world, entry, focus)
                        self.assertEqual(frozenset(), {item.code for item in outcome.findings})
                        superseded = evaluate(world, entry, _path("old.json"))
                        self.assertEqual(frozenset({"NOT_CURRENT_HEAD"}), {item.code for item in superseded.findings})
                        continue
                    if entry == "E2" and class_id in {14, 15, 16}:
                        carried = evaluate(world, "E1", None)
                        self.assertEqual(expected_codes(class_id, "E1"), {item.code for item in carried.findings})
                        continue
                    if entry == "E3" and class_id <= 13:
                        carried = evaluate(world, "E1", None)
                        self.assertEqual(expected_codes(class_id, "E1"), {item.code for item in carried.findings})
                        manifest = evaluate(world, "E3", None)
                        self.assertEqual((), manifest.validated_heads)
                        continue
                    outcome = evaluate(world, entry, record)
                    self.assertEqual(expected_codes(class_id, entry), {item.code for item in outcome.findings})
                    if outcome.status == "PASS":
                        self.assertEqual((), outcome.findings)
                        if entry != "E3":
                            self.assertEqual(1, len(outcome.validated_heads))

    def test_positive_example_validates_only_the_successor(self) -> None:
        world, focus = world_for(2, "E1")
        root = evaluate(world, "E1")
        self.assertEqual("PASS", root.status)
        self.assertEqual(((TASK, f"{TASK}-next"),), root.validated_heads)
        current = evaluate(world, "E2", focus)
        self.assertEqual("PASS", current.status)
        previous = evaluate(world, "E2", _path("old.json"))
        self.assertEqual("FAIL", previous.status)
        self.assertEqual("NOT_CURRENT_HEAD", previous.findings[0].code)

    def test_negative_example_rejects_two_successors(self) -> None:
        world, _focus = world_for(7, "E1")
        outcome = evaluate(world, "E1")
        self.assertEqual(frozenset({"TWO_SUCCESSORS"}), {item.code for item in outcome.findings})
        self.assertEqual((), outcome.validated_heads)
        for name in ("left.json", "right.json"):
            probed = evaluate(world, "E2", _path(name))
            self.assertNotEqual("PASS", probed.status)
            self.assertIn("TWO_SUCCESSORS", {item.code for item in probed.findings})

    def test_pairwise_oracle_is_deterministic_and_closed(self) -> None:
        for left in range(1, 18):
            for right in range(left + 1, 18):
                with self.subTest(left=left, right=right):
                    first, _focus = world_for(left, "E1")
                    second, _other = world_for(right, "E1")
                    merged = _combine(first, second)
                    once = evaluate(merged, "E1")
                    twice = evaluate(merged, "E1")
                    produced = _production(merged, "E1")
                    self.assertEqual(once, twice)
                    self.assertEqual(once.status, produced.status)
                    self.assertEqual(
                        tuple((item.task_id, item.code) for item in once.findings),
                        tuple((item.task_id, item.code) for item in produced.findings),
                    )
                    self.assertTrue({item.code for item in once.findings} <= CODES)
                    if once.status == "PASS":
                        self.assertEqual(once.validated_heads, produced.validated_heads)
                        self.assertEqual(1, len(once.validated_heads))
                        self.assertEqual((), once.findings)

    def test_seeded_random_graphs_stay_inside_the_outcome_function(self) -> None:
        for offset in range(40):
            world = _random_world(680068 + offset)
            once = evaluate(world, "E1")
            twice = evaluate(world, "E1")
            produced = _production(world, "E1")
            self.assertEqual(once, twice)
            self.assertEqual(once.status, produced.status)
            self.assertEqual(
                tuple((item.task_id, item.code) for item in once.findings),
                tuple((item.task_id, item.code) for item in produced.findings),
            )
            self.assertTrue({item.code for item in once.findings} <= CODES)
            if once.status == "PASS":
                self.assertEqual(once.validated_heads, produced.validated_heads)
                self.assertEqual(1, len(once.validated_heads))
                identity = once.validated_heads[0][1]
                focus = next(record.path for record in world.records if record.record_id == identity)
                self.assertEqual(evaluate(world, "E2", focus), _production(world, "E2", focus))
            else:
                self.assertGreaterEqual(len(once.findings), 1)

    def test_class_12_variants_are_reconciliation_absent(self) -> None:
        bare = Record(_path("old.json"), None, None, "b" * 40)
        linked = _record("next.json", f"{TASK}-next", bare.path)
        variants = (
            Reconciliation(TASK, f"{TASK}-next", (f"{TASK}-old",), ((bare.path, f"{TASK}-old"),), linked.path, unreadable=True),
            Reconciliation(TASK, f"{TASK}-next", (f"{TASK}-old",), ((bare.path, f"{TASK}-old"),), linked.path, embedded_task_id=TASK),
            Reconciliation(TASK, f"{TASK}-next", (f"{TASK}-old",), ((bare.path, f"{TASK}-old"),), linked.path, under_evidence=True),
        )
        for recon in variants:
            outcome = evaluate(_world((bare, linked), (recon,)), "E1")
            self.assertIn("RECONCILIATION_ABSENT", {item.code for item in outcome.findings})

    def test_nan_and_lone_surrogate_are_unreadable(self) -> None:
        nan = Record(_path("nan.json"), f"{TASK}-nan", nan_literal=True)
        surrogate = Record(_path("bad.json"), f"{TASK}-bad\ud800")
        for record in (nan, surrogate):
            outcome = evaluate(_world((record,)), "E1")
            self.assertEqual(frozenset({"UNREADABLE_JSON"}), {item.code for item in outcome.findings})

    def test_non_ascii_record_id_is_a_canonical_identity(self) -> None:
        record = _record("head.json", f"{TASK}-t\u00eate")
        outcome = evaluate(_world((record,)), "E1")
        self.assertEqual("PASS", outcome.status)
        self.assertEqual(((TASK, f"{TASK}-t\u00eate"),), outcome.validated_heads)


class ProductionTests(unittest.TestCase):
    def test_every_matrix_cell_matches_the_oracle(self) -> None:
        for entry in ENTRIES:
            for class_id in range(1, 18):
                with self.subTest(entry=entry, class_id=class_id):
                    world, focus = world_for(class_id, entry)
                    if entry == "E3" and class_id <= 13:
                        produced = _production(world, "E3")
                        self.assertEqual((), produced.validated_heads)
                        self.assertEqual(evaluate(world, "E1"), _production(world, "E1"))
                        continue
                    if entry == "E2" and class_id in {14, 15, 16}:
                        self.assertEqual(evaluate(world, "E1"), _production(world, "E1"))
                        continue
                    record = focus if entry == "E2" else None
                    self.assertEqual(evaluate(world, entry, record), _production(world, entry, record))

    def test_negative_record_of_a_passing_chain_is_not_current(self) -> None:
        world, _focus = world_for(2, "E2")
        expected = evaluate(world, "E2", _path("old.json"))
        self.assertEqual(expected, _production(world, "E2", _path("old.json")))

    def test_mutation_of_each_check_disagrees_with_the_oracle(self) -> None:
        """Each marked check is a function body. Replacing it with ``return []`` must drop that code."""
        if not SCRIPT.is_file():
            self.fail(f"production script missing: {SCRIPT.relative_to(ROOT)}")
        source = SCRIPT.read_text(encoding="utf-8")
        classes = {
            "SELF_SUPERSEDES": 6,
            "TWO_SUCCESSORS": 7,
            "MULTIPLE_HEADS": 8,
            "CYCLE": 10,
            "RECONCILIATION_ABSENT": 12,
            "RECONCILIATION_UNLISTED": 13,
            "SUPERSEDES_UNRESOLVED": 9,
            "NOT_CURRENT_HEAD": 2,
            "MANIFEST_FIELD": 14,
            "MANIFEST_MISSING": 15,
            "MANIFEST_UNLISTED": 16,
            "UNREADABLE_JSON": 17,
        }
        for name in MUTATION_CHECKS:
            with self.subTest(check=name):
                start = f"# CHECK {name}\n"
                end = f"# END CHECK {name}\n"
                self.assertIn(start, source)
                self.assertLess(source.index(start), source.index(end))
                block = source.split(start, 1)[1].split(end, 1)[0]
                mutated = source.replace(start + block + end, start + "    return []\n" + end, 1)
                with tempfile.TemporaryDirectory() as tmp:
                    script = Path(tmp) / "validate_current_evidence_head.py"
                    script.write_text(mutated, encoding="utf-8")
                    class_id = classes[name]
                    entry = "E2" if name == "NOT_CURRENT_HEAD" else "E1"
                    world, focus = world_for(class_id, entry)
                    record = _path("old.json") if name == "NOT_CURRENT_HEAD" else focus
                    expected = evaluate(world, entry, record if entry == "E2" else None)
                    produced = _production(world, entry, record if entry == "E2" else None, script)
                self.assertNotEqual(expected, produced)
                self.assertNotIn(name, {item.code for item in produced.findings})

    def test_strict_documents_match_the_oracle(self) -> None:
        """Non-RFC JSON and wrong types fail closed; finite wrong manifest fields do not."""
        head = _record("head.json", f"{TASK}-head")

        def evidence(raw: bytes) -> World:
            return _world((head, Record(_path("bad.json"), broken=True, literal=raw)))

        def recon(raw: bytes) -> World:
            item = Reconciliation(TASK, f"{TASK}-head", (), (), head.path, literal=raw, reject=True)
            return _world((head,), (item,))

        def state(raw: bytes) -> World:
            return World((TASK,), (head,), (), (_manifest_for(("head.json",)),), raw, True)

        def manifest(raw: bytes) -> World:
            chosen = Manifest(
                f"reports/evidence/{GATE}/MANIFEST.json",
                (ManifestEntry("head.json", TASK),),
                literal=raw,
                reject=True,
            )
            return _world((head,), manifest=chosen)

        valid = {
            "reconciles": {},
            "remaining_head": f"{TASK}-head",
            "selection_proof": {"base": "fixture", "selected_path": head.path, "selector": "select_most_recent"},
            "supersedes": [],
        }

        def patched(payload: dict[str, object], token: str, replacement: str) -> bytes:
            text = json.dumps(payload, indent=2, sort_keys=True).replace(f'"{token}"', replacement, 1)
            return (text + "\n").encode("utf-8")

        nan_recon = dict(valid)
        nan_recon["note"] = "NAN_TOKEN"
        number_recon = dict(valid)
        number_recon["reconciles"] = {"extra": "NUM_TOKEN"}
        embedded = dict(valid)
        embedded["task_id"] = "NUM_TOKEN"
        remaining = dict(valid)
        remaining["remaining_head"] = "NUM_TOKEN"
        selected = dict(valid)
        selected["selection_proof"] = {
            "base": "fixture",
            "selected_path": "NUM_TOKEN",
            "selector": "select_most_recent",
        }
        surrogate_note = dict(valid)
        surrogate_note["note"] = "SUR_TOKEN"
        lone_head = json.dumps(valid, indent=2, sort_keys=True).replace(f'"{TASK}-head"', '"\\ud800"', 1)

        cases: list[tuple[str, World, str, str | None]] = [
            ("nan", evidence(b'{"score": NaN, "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("infinity", evidence(b'{"score": Infinity, "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("negative-infinity", evidence(b'{"meta": {"bound": -Infinity}, "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("supersedes-list", evidence(b'{"record_id": "OCOR-DEV-0099-list", "supersedes": ["B"], "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("supersedes-null", evidence(b'{"record_id": "OCOR-DEV-0099-null", "supersedes": null, "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("task-id-number", evidence(b'{"record_id": "OCOR-DEV-0099-num", "task_id": 1}\n'), "E1", None),
            ("task-id-bool", evidence(b'{"record_id": "OCOR-DEV-0099-bool", "task_id": true}\n'), "E1", None),
            ("task-id-empty", evidence(b'{"record_id": "OCOR-DEV-0099-empty", "task_id": ""}\n'), "E1", None),
            ("record-id-number", evidence(b'{"record_id": 4, "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("record-id-null", evidence(b'{"record_id": null, "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("commit-number", evidence(b'{"commit": 1, "record_id": "OCOR-DEV-0099-c", "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("commit-null", evidence(b'{"commit": null, "record_id": "OCOR-DEV-0099-c", "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("nested-surrogate", evidence(b'{"note": {"k": "\\ud800"}, "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("key-surrogate", evidence(b'{"\\ud800": "x", "task_id": "OCOR-DEV-0099"}\n'), "E1", None),
            ("nan-e2", evidence(b'{"score": NaN, "task_id": "OCOR-DEV-0099"}\n'), "E2", _path("bad.json")),
            ("recon-nan", recon(patched(nan_recon, "NAN_TOKEN", "NaN")), "E1", None),
            ("recon-infinity", recon(patched(nan_recon, "NAN_TOKEN", "Infinity")), "E1", None),
            ("recon-number-value", recon(patched(number_recon, "NUM_TOKEN", "1")), "E1", None),
            ("recon-embedded-number", recon(patched(embedded, "NUM_TOKEN", "1")), "E1", None),
            ("recon-remaining-number", recon(patched(remaining, "NUM_TOKEN", "1")), "E1", None),
            ("recon-selected-number", recon(patched(selected, "NUM_TOKEN", "1")), "E1", None),
            ("recon-lone-remaining", recon((lone_head + "\n").encode("utf-8")), "E1", None),
            ("recon-nested-surrogate", recon(patched(surrogate_note, "SUR_TOKEN", '"\\ud800"')), "E1", None),
            ("state-nan", state(b'{"completed_evidence_tasks": ["OCOR-DEV-0099"], "score": NaN}\n'), "E1", None),
            ("state-infinity", state(b'{"completed_evidence_tasks": [Infinity]}\n'), "E1", None),
            ("state-number", state(b'{"completed_evidence_tasks": [1]}\n'), "E1", None),
            ("state-bool", state(b'{"completed_evidence_tasks": [true]}\n'), "E1", None),
            ("state-container", state(b'{"completed_evidence_tasks": {"task": "OCOR-DEV-0099"}}\n'), "E1", None),
            ("state-not-object", state(b"[1]\n"), "E1", None),
            ("state-non-utf8", state(b"\xff"), "E1", None),
            ("manifest-nan", manifest(b'{"artifacts": [{"n": NaN, "path": "head.json", "task_id": "OCOR-DEV-0099"}]}\n'), "E1", None),
            ("manifest-nan-e3", manifest(b'{"artifacts": [{"n": NaN, "path": "head.json", "task_id": "OCOR-DEV-0099"}]}\n'), "E3", None),
            ("manifest-surrogate", manifest(b'{"artifacts": [{"path": "\\ud800", "task_id": "OCOR-DEV-0099"}]}\n'), "E1", None),
            ("manifest-number", _world((head,), manifest=_manifest_for(("head.json",), (ManifestEntry(1, TASK),))), "E1", None),
            ("manifest-bool-task", _world((head,), manifest=_manifest_for(("head.json",), (ManifestEntry("also.json", True),))), "E1", None),
            ("empty-supersedes", _world((_record("head.json", f"{TASK}-head", ""),)), "E1", None),
            ("empty-record-id", _world((Record(_path("head.json"), None, literal=b'{"record_id": "", "task_id": "OCOR-DEV-0099"}\n'),)), "E1", None),
            ("emoji-pair", _world((_record("head.json", f"{TASK}-t\U0001f600"),)), "E1", None),
            ("duplicate-keys", _world((Record(_path("head.json"), f"{TASK}-dup", literal=b'{"record_id": "OCOR-DEV-0099-dup", "task_id": "OCOR-DEV-0099", "task_id": "OCOR-DEV-0099"}\n'),)), "E1", None),
        ]
        for name, world, entry, focus in cases:
            with self.subTest(name=name):
                self.assertEqual(evaluate(world, entry, focus), _production(world, entry, focus))


class RepairCycle1Tests(unittest.TestCase):
    """Negatives for OCOR-DEV-REM-0068-c6410c0c7c31-0. The oracle is the expected result."""

    def _assert_gate(self, world: World, entry: str, focus: str | None = None) -> Outcome:
        expected = evaluate(world, entry, focus)
        self.assertEqual(expected, _production(world, entry, focus))
        return expected

    def test_missing_execution_state_is_rejected(self) -> None:
        head = _record("head.json", f"{TASK}-head")
        world = World((TASK,), (head,), (), (_manifest_for(("head.json",)),), state_missing=True)
        outcome = self._assert_gate(world, "E1")
        self.assertEqual(frozenset({("UNSCOPED", "UNREADABLE_JSON")}), {(item.task_id, item.code) for item in outcome.findings})
        self.assertEqual((), outcome.validated_heads)

    def test_missing_completed_key_is_rejected(self) -> None:
        head = _record("head.json", f"{TASK}-head")
        world = World((TASK,), (head,), (), (_manifest_for(("head.json",)),), b'{"other": []}\n')
        outcome = self._assert_gate(world, "E1")
        self.assertEqual(frozenset({("UNSCOPED", "UNREADABLE_JSON")}), {(item.task_id, item.code) for item in outcome.findings})

    def test_completed_task_without_records_has_a_finding(self) -> None:
        world = World((TASK,), (), (), (_manifest_for(()),))
        outcome = self._assert_gate(world, "E1")
        self.assertEqual(frozenset({"RECONCILIATION_ABSENT"}), {item.code for item in outcome.findings})
        self.assertEqual(TASK, outcome.findings[0].task_id)
        self.assertEqual((), outcome.validated_heads)

    def test_positive_chain_still_validates_one_head(self) -> None:
        world, focus = world_for(2, "E1")
        root = self._assert_gate(world, "E1")
        self.assertEqual("PASS", root.status)
        self.assertEqual(((TASK, f"{TASK}-next"),), root.validated_heads)
        current = self._assert_gate(world, "E2", focus)
        self.assertEqual("PASS", current.status)
        manifest = self._assert_gate(world, "E3")
        self.assertEqual((), manifest.findings)

    def test_escaped_git_path_second_head_is_examined(self) -> None:
        first = _record("a.json", f"{TASK}-a")
        second = _record("t\u00eate.json", f"{TASK}-tete")
        world = _world((first, second))
        outcome = self._assert_gate(world, "E1")
        self.assertEqual(frozenset({"MULTIPLE_HEADS"}), {item.code for item in outcome.findings})
        probed = self._assert_gate(world, "E2", first.path)
        self.assertNotEqual("PASS", probed.status)
        self.assertIn("MULTIPLE_HEADS", {item.code for item in probed.findings})

    def test_non_utf8_git_path_second_head_is_examined(self) -> None:
        """A blob name Git cannot show as UTF-8 is still a second head under core.quotepath=true."""
        bad_name = os.fsdecode(b"bad\xff.json")
        self.assertIn(b"\xff", os.fsencode(bad_name))
        first = _record("a.json", f"{TASK}-a")
        second = _record(bad_name, f"{TASK}-b")
        world = _world((first, second))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            materialise(root, world)
            _commit(root)
            quoted = subprocess.check_output(["git", "config", "--get", "core.quotepath"], cwd=root, text=True).strip()
            self.assertEqual("true", quoted)
            listing = subprocess.check_output(["git", "ls-tree", "-r", "-z", "--name-only", "HEAD"], cwd=root)
            self.assertIn(os.fsencode(second.path), listing.split(b"\0"))
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(root), "--execution-commit", commit, "--record", first.path],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
        payload = json.loads(completed.stdout)
        self.assertNotEqual("PASS", payload["status"], payload)
        self.assertEqual({}, payload["validated_heads"])
        self.assertIn("MULTIPLE_HEADS", {item["code"] for item in payload["findings"]})

    def test_alias_must_name_a_listed_distinct_record(self) -> None:
        old = _record("a.json", f"{TASK}-a")
        nxt = _record("b.json", f"{TASK}-b", "old-string")
        valid = Reconciliation(TASK, f"{TASK}-b", (f"{TASK}-a",), (("old-string", f"{TASK}-a"),), nxt.path)
        accepted = self._assert_gate(_world((old, nxt), (valid,)), "E1")
        self.assertEqual("PASS", accepted.status)
        self.assertEqual(((TASK, f"{TASK}-b"),), accepted.validated_heads)
        self.assertEqual("PASS", self._assert_gate(_world((old, nxt), (valid,)), "E2", nxt.path).status)
        ghost = Reconciliation(TASK, f"{TASK}-b", (f"{TASK}-a",), (("old-string", "ghost"),), nxt.path)
        rejected = self._assert_gate(_world((old, nxt), (ghost,)), "E1")
        self.assertIn("SUPERSEDES_UNRESOLVED", {item.code for item in rejected.findings})
        self.assertNotEqual("PASS", rejected.status)
        self_record = _record("b.json", f"{TASK}-b", _path("b.json"))
        recon = Reconciliation(TASK, f"{TASK}-b", (), ((_path("b.json"), f"{TASK}-b"),), self_record.path)
        aliased = self._assert_gate(_world((self_record,), (recon,)), "E1")
        self.assertIn("SELF_SUPERSEDES", {item.code for item in aliased.findings})
        self.assertNotEqual("PASS", self._assert_gate(_world((self_record,), (recon,)), "E2", self_record.path).status)

    def test_reconciliation_rejects_an_extraneous_branch(self) -> None:
        chosen = _record("a.json", f"{TASK}-a")
        retired = _record("b.json", f"{TASK}-b", f"{TASK}-a")
        stray = _record("c.json", f"{TASK}-c")
        recon = Reconciliation(TASK, f"{TASK}-a", (f"{TASK}-b",), (), chosen.path)
        outcome = self._assert_gate(_world((chosen, retired, stray), (recon,)), "E1")
        self.assertIn("MULTIPLE_HEADS", {item.code for item in outcome.findings})
        self.assertNotEqual("PASS", outcome.status)
        self.assertEqual((), outcome.validated_heads)

    def test_reconciliation_accepts_a_successor_of_the_choice(self) -> None:
        chosen = _record("a.json", f"{TASK}-a")
        isolated = _record("b.json", f"{TASK}-b")
        successor = _record("c.json", f"{TASK}-c", f"{TASK}-a")
        recon = Reconciliation(TASK, f"{TASK}-a", (f"{TASK}-b",), (), chosen.path)
        outcome = self._assert_gate(_world((chosen, isolated, successor), (recon,)), "E1")
        self.assertEqual("PASS", outcome.status)
        self.assertEqual(((TASK, f"{TASK}-c"),), outcome.validated_heads)

    def test_missing_gate_manifest_is_unlisted(self) -> None:
        record = _record("a.json", f"{TASK}-a")
        world = World((TASK,), (record,), (), ())
        outcome = self._assert_gate(world, "E1")
        self.assertIn("MANIFEST_UNLISTED", {item.code for item in outcome.findings})
        self.assertNotEqual("PASS", outcome.status)
        self.assertEqual((), outcome.validated_heads)

    def test_incomplete_cli_pair_and_manifest_combination_are_rejected(self) -> None:
        world, focus = world_for(2, "E1")
        assert focus is not None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            materialise(root, world)
            _commit(root)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            manifest = world.manifests[0].relative_path
            refused = (
                ["--root", str(root), "--execution-commit", "0" * 40],
                ["--root", str(root), "--record", focus],
                ["--root", str(root), "--manifest", manifest, "--execution-commit", commit, "--record", focus],
                ["--root", str(root), "--manifest", manifest, "--execution-commit", commit],
            )
            for args in refused:
                with self.subTest(args=args[-2:]):
                    completed = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root, text=True, capture_output=True, check=False)
                    self.assertNotEqual(0, completed.returncode, completed.stdout)
                    payload = json.loads(completed.stdout)
                    self.assertEqual("FAIL", payload["status"])
                    self.assertNotEqual("E1", payload["entry"])
                    self.assertEqual([], payload["validated_heads"] if isinstance(payload["validated_heads"], list) else list(payload["validated_heads"]))
                    self.assertTrue(payload["findings"])
        self.assertEqual("PASS", self._assert_gate(world, "E1").status)
        self.assertEqual("PASS", self._assert_gate(world, "E2", focus).status)
        self.assertEqual((), self._assert_gate(world, "E3").findings)


def json_depth(value: object) -> int:
    """Contract depth: a scalar is 0; an empty container is 1; any other container is 1 plus its deepest child."""
    if isinstance(value, dict):
        if not value:
            return 1
        return 1 + max(json_depth(item) for item in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return 1 + max(json_depth(item) for item in value)
    return 0


def _document(task_id: str, record_id: str, supersedes: str | None = None, commit: str | None = None) -> bytes:
    payload: dict[str, object] = {"record_id": record_id, "task_id": task_id}
    if commit is not None:
        payload["commit"] = commit
    if supersedes is not None:
        payload["supersedes"] = supersedes
    return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


def document_at_depth(depth: int) -> bytes:
    """One evidence object whose contract depth is exactly ``depth``."""
    inner: object = "x"
    for _ in range(depth - 1):
        inner = {"k": inner}
    payload = {"nest": inner, "record_id": f"{TASK}-deep", "task_id": TASK}
    if json_depth(payload) != depth:
        raise AssertionError(json_depth(payload))
    return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


class RedesignOption1Tests(unittest.TestCase):
    """Eighteen cells of OCOR-DEV-REM-0068-REDESIGN (2026-11-28) option 1.

    The production script is the subject. This class does not remove or loosen a cycle-0 test.
    ``select_graph`` is the one pure function on the explicit graph. E1, E2, and E3 project it.
    """

    def _module(self):
        import importlib.util

        name = "validate_current_evidence_head_subject"
        spec = importlib.util.spec_from_file_location(name, SCRIPT)
        if spec is None or spec.loader is None:
            self.fail(f"production script missing: {SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        # dataclasses resolve the class module through sys.modules during exec.
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
        return module

    def _completed(self, world: World, entry: str, focus: str | None = None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            materialise(root, world)
            if entry == "E1":
                args = ["--root", str(root)]
            elif entry == "E2":
                if focus is None:
                    self.fail("E2 requires a record path")
                _commit(root)
                commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
                args = ["--root", str(root), "--execution-commit", commit, "--record", focus]
            else:
                if not world.manifests:
                    self.fail("E3 requires a manifest")
                args = ["--root", str(root), "--manifest", world.manifests[0].relative_path]
            return subprocess.run(
                [sys.executable, str(SCRIPT), *args],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

    def _payload(self, completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertTrue(completed.stdout.strip(), completed.stderr[-800:])
        self.assertNotIn("Traceback", completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIsInstance(payload, dict)
        return payload

    def _assert_codes(self, world: World, entry: str, focus: str | None, required: frozenset[str], *, passed: bool) -> None:
        payload = self._payload(self._completed(world, entry, focus))
        codes = {str(item["code"]) for item in payload["findings"]}  # type: ignore[index]
        self.assertTrue(codes <= CODES, codes)
        if passed:
            self.assertEqual("PASS", payload["status"])
            self.assertEqual(set(), codes)
            return
        self.assertNotEqual("PASS", payload["status"])
        self.assertTrue(required <= codes, payload)
        for item in payload["findings"]:  # type: ignore[union-attr]
            self.assertTrue(item["task_id"])
            self.assertEqual(entry, item["entry"])

    def _archive_world(self) -> tuple[World, str, str]:
        inside = _record("A.json", f"{TASK}-A")
        outside = Record("reports/evidence-archive/G0/B.json", f"{TASK}-B", f"{TASK}-A")
        world = _world((inside, outside), manifest=_manifest_for(("A.json",)))
        return world, inside.path, outside.path

    def _suffix_world(self) -> tuple[World, str]:
        first = _record("a.json", f"{TASK}-A")
        second = _record("b.json", f"{TASK}-B", f"{TASK}-A")
        extra = _record("second.reconciliation.json", f"{TASK}-D")
        manifest = _manifest_for(("a.json", "b.json", "second.reconciliation.json"))
        return _world((first, second, extra), manifest=manifest), second.path

    def _collision_world(self, include_new: bool) -> tuple[World, str]:
        """Cycle-1 VF-004. The commit key is not an identity. ``C`` shares A's execution commit."""
        shared = "4" * 40
        old = Record(_path("a.json"), None, None, shared)
        digest = _sha256(record_bytes(old))
        successor = Record(_path("b.json"), "B", "A")
        records = [old, successor]
        names = ["a.json", "b.json"]
        if include_new:
            fresh = Record(
                _path("c.json"),
                literal=(
                    json.dumps(
                        {"commit": shared, "created_at": "2026-11-28T03:00:00Z", "task_id": TASK},
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8"),
            )
            records.append(fresh)
            names.append("c.json")
        recon = Reconciliation(
            TASK,
            "A",
            (),
            ((old.path, "A"), (shared, "A"), (f"{old.path}@sha256:{digest}", "A")),
            old.path,
        )
        return _world(records, (recon,), _manifest_for(tuple(names))), successor.path

    def _ambiguous_world(self) -> tuple[World, str]:
        shared = "d" * 40
        left = Record(_path("a.json"), None, None, shared)
        right = Record(_path("b.json"), None, None, shared)
        recon = Reconciliation(TASK, "SHARED", (), ((shared, "SHARED"),), left.path)
        world = _world((left, right), (recon,), _manifest_for(("a.json", "b.json")))
        return world, left.path

    def _depth_world(self, raw: bytes) -> World:
        return _world((Record(_path("deep.json"), literal=raw),), manifest=_manifest_for(("deep.json",)))

    def _two_gates(self, *, state_missing: bool) -> World:
        other = "OCOR-DEV-0098"
        records = (
            Record("reports/evidence/G0/a.json", literal=_document(TASK, f"{TASK}-A")),
            Record("reports/evidence/G0/b.json", literal=_document(TASK, f"{TASK}-B", f"{TASK}-A")),
            Record("reports/evidence/G1/x.json", literal=_document(other, f"{other}-X")),
        )
        manifests = (
            Manifest(
                "reports/evidence/G0/MANIFEST.json",
                (ManifestEntry("a.json", TASK), ManifestEntry("b.json", TASK)),
            ),
            Manifest("reports/evidence/G1/MANIFEST.json", (ManifestEntry("x.json", other),)),
        )
        return World((TASK, other), records, (), manifests, state_missing=state_missing)

    def test_select_graph_projects_the_three_entries(self) -> None:
        """One pure function. The three entries on the same graph are its projections."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        old = _record("old.json", f"{TASK}-old")
        nxt = _record("next.json", f"{TASK}-next", old.record_id)
        manifest = _manifest_for(("old.json", "next.json"))
        manifest_bytes = (
            json.dumps(
                {"artifacts": [{"path": item.path, "task_id": item.task_id} for item in manifest.entries]},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        graph = {
            "completed": [TASK],
            "manifests": [{"path": manifest.relative_path, "raw": manifest_bytes}],
            "reconciliations": [],
            "records": [
                {"path": old.path, "raw": record_bytes(old)},
                {"path": nxt.path, "raw": record_bytes(nxt)},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                decision = select(graph)  # type: ignore[misc]
            finally:
                os.chdir(previous)
        self.assertEqual("PASS", decision["entries"]["E1"]["status"])
        self.assertEqual({TASK: f"{TASK}-next"}, decision["entries"]["E1"]["validated_heads"])
        self.assertEqual("FAIL", decision["entries"]["E2"][old.path]["status"])
        self.assertIn("NOT_CURRENT_HEAD", {item["code"] for item in decision["entries"]["E2"][old.path]["findings"]})
        self.assertEqual("PASS", decision["entries"]["E2"][nxt.path]["status"])
        self.assertEqual({TASK: f"{TASK}-next"}, decision["entries"]["E2"][nxt.path]["validated_heads"])
        self.assertEqual("PASS", decision["entries"]["E3"][manifest.relative_path]["status"])
        self.assertEqual([], decision["entries"]["E3"][manifest.relative_path]["findings"])
        world = _world((old, nxt), manifest=manifest)
        root = self._payload(self._completed(world, "E1"))
        current = self._payload(self._completed(world, "E2", nxt.path))
        retired = self._payload(self._completed(world, "E2", old.path))
        admitted = self._payload(self._completed(world, "E3"))
        self.assertEqual(decision["entries"]["E1"]["status"], root["status"])
        self.assertEqual(decision["entries"]["E1"]["validated_heads"], root["validated_heads"])
        self.assertEqual(decision["entries"]["E2"][nxt.path]["status"], current["status"])
        self.assertEqual(decision["entries"]["E2"][nxt.path]["validated_heads"], current["validated_heads"])
        self.assertEqual(decision["entries"]["E2"][old.path]["status"], retired["status"])
        self.assertEqual(
            {item["code"] for item in decision["entries"]["E2"][old.path]["findings"]},
            {item["code"] for item in retired["findings"]},
        )
        self.assertEqual(decision["entries"]["E3"][manifest.relative_path]["status"], admitted["status"])
        self.assertEqual(decision["entries"]["E3"][manifest.relative_path]["findings"], admitted["findings"])

    def test_select_graph_refuses_a_non_object(self) -> None:
        """A graph that is not an object is unreadable. It does not raise."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        decision = select("nope")  # type: ignore[misc]
        entry = decision["entries"]["E1"]
        self.assertEqual("FAIL", entry["status"])
        self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in entry["findings"]])
        self.assertEqual({}, entry["validated_heads"])
        self.assertEqual({}, decision["entries"]["E2"])
        self.assertEqual({}, decision["entries"]["E3"])

    def test_select_graph_refuses_a_non_json_completed_set(self) -> None:
        """A completed item that JSON cannot encode is unreadable. The record stays in E2."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        record = _record("kept.json", f"{TASK}-kept")
        graph = {
            "completed": [b"not-json"],
            "manifests": [],
            "reconciliations": [],
            "records": [{"path": record.path, "raw": record_bytes(record)}],
        }
        decision = select(graph)  # type: ignore[misc]
        self.assertEqual("FAIL", decision["entries"]["E1"]["status"])
        self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in decision["entries"]["E1"]["findings"]])
        self.assertEqual({}, decision["entries"]["E1"]["validated_heads"])
        self.assertIn(record.path, decision["entries"]["E2"])
        projected = decision["entries"]["E2"][record.path]
        self.assertEqual("FAIL", projected["status"])
        self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in projected["findings"]])
        self.assertEqual({}, projected["validated_heads"])

    def test_select_graph_refuses_each_non_object_graph(self) -> None:
        """None, a bool, a number and a list are the same unreadable graph."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        for graph in (None, True, 1, ["x"]):
            decision = select(graph)  # type: ignore[misc]
            entry = decision["entries"]["E1"]
            self.assertEqual("FAIL", entry["status"], graph)
            self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in entry["findings"]], graph)
            self.assertEqual({}, entry["validated_heads"], graph)
            self.assertEqual({}, decision["entries"]["E2"], graph)
            self.assertEqual({}, decision["entries"]["E3"], graph)

    def test_select_graph_refuses_each_non_json_completed_member(self) -> None:
        """A set, and NaN or Infinity, including nested, are unreadable."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        members = (
            set(),
            float("nan"),
            float("inf"),
            float("-inf"),
            {"nested": float("nan")},
            [float("inf")],
        )
        for member in members:
            decision = select(
                {"completed": [member], "manifests": [], "reconciliations": [], "records": []}
            )
            entry = decision["entries"]["E1"]
            self.assertEqual("FAIL", entry["status"], member)
            self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in entry["findings"]], member)
            self.assertEqual({}, entry["validated_heads"], member)

    def test_select_graph_completed_set_matches_the_json_oracle(self) -> None:
        """stdlib json is the oracle. The module is stricter only for a non-empty string."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        unencodable = (
            b"raw",
            set(),
            float("nan"),
            float("inf"),
            float("-inf"),
            {"nested": float("nan")},
            [float("-inf")],
        )
        # json.dumps coerces an int key to a string, so this object encodes.
        # _completed still refuses it: a completed item must be a non-empty string.
        stricter = (None, True, False, 0, 1.5, "", {1: "x"}, {"task": "x"}, ["nested"])
        usable = ("OCOR-DEV-0099", "\ud800\udc00")
        lone_surrogate = ("\ud800",)
        seen = 0
        for member in unencodable:
            with self.assertRaises((TypeError, ValueError)):
                json.dumps({"completed_evidence_tasks": [member]}, allow_nan=False)
            decision = select({"completed": [member], "records": [], "manifests": [], "reconciliations": []})
            entry = decision["entries"]["E1"]
            self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in entry["findings"]], member)
            seen += 1
        for member in stricter:
            json.dumps({"completed_evidence_tasks": [member]}, allow_nan=False)
            decision = select({"completed": [member], "records": [], "manifests": [], "reconciliations": []})
            entry = decision["entries"]["E1"]
            self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in entry["findings"]], member)
            seen += 1
        for member in usable:
            json.dumps({"completed_evidence_tasks": [member]}, allow_nan=False)
            decision = select({"completed": [member], "records": [], "manifests": [], "reconciliations": []})
            self.assertNotIn(
                "UNREADABLE_JSON",
                [item["code"] for item in decision["entries"]["E1"]["findings"]],
                member,
            )
            seen += 1
        for member in lone_surrogate:
            json.dumps({"completed_evidence_tasks": [member]}, allow_nan=False)
            decision = select({"completed": [member], "records": [], "manifests": [], "reconciliations": []})
            entry = decision["entries"]["E1"]
            self.assertEqual(["UNREADABLE_JSON"], [item["code"] for item in entry["findings"]], member)
            seen += 1
        empty = select({"completed": [], "records": [], "manifests": [], "reconciliations": []})
        self.assertEqual("PASS", empty["entries"]["E1"]["status"])
        seen += 1
        self.assertEqual(20, seen)

    def test_select_graph_ignores_a_collection_that_is_not_a_list(self) -> None:
        """A records, manifests, or reconciliations value that is not a list is absent."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        decision = select(
            {"completed": [], "records": "nope", "manifests": None, "reconciliations": {"a": 1}}
        )
        self.assertEqual("PASS", decision["entries"]["E1"]["status"])
        self.assertEqual({}, decision["entries"]["E1"]["validated_heads"])
        self.assertEqual({}, decision["entries"]["E2"])
        self.assertEqual({}, decision["entries"]["E3"])

    def test_select_graph_skips_a_record_whose_raw_is_not_bytes(self) -> None:
        """A node whose raw is not bytes is not a presented document."""
        module = self._module()
        select = getattr(module, "select_graph", None)
        self.assertTrue(callable(select), "production must expose select_graph")
        decision = select(
            {
                "completed": [],
                "manifests": [],
                "reconciliations": [],
                "records": [{"path": "reports/evidence/G0/x.json", "raw": "not-bytes"}],
            }
        )
        self.assertEqual("PASS", decision["entries"]["E1"]["status"])
        self.assertEqual({}, decision["entries"]["E2"])
        self.assertEqual({}, decision["entries"]["E3"])

    def test_evidence_archive_is_not_an_evidence_node_on_e1(self) -> None:
        world, _inside, _outside = self._archive_world()
        payload = self._payload(self._completed(world, "E1"))
        self.assertEqual("PASS", payload["status"])
        self.assertEqual({TASK: f"{TASK}-A"}, payload["validated_heads"])
        self.assertNotIn(f"{TASK}-B", set(payload["validated_heads"].values()))

    def test_evidence_archive_does_not_retire_the_evidence_head_on_e2(self) -> None:
        world, inside, _outside = self._archive_world()
        payload = self._payload(self._completed(world, "E2", inside))
        self.assertEqual("PASS", payload["status"], payload)
        self.assertEqual({TASK: f"{TASK}-A"}, payload["validated_heads"])

    def test_record_outside_the_evidence_directory_is_outside_evidence(self) -> None:
        world, _inside, outside = self._archive_world()
        self._assert_codes(world, "E2", outside, frozenset({"OUTSIDE_EVIDENCE"}), passed=False)

    def test_reconciliation_suffix_under_evidence_is_a_second_head_on_e1(self) -> None:
        world, _focus = self._suffix_world()
        self._assert_codes(world, "E1", None, frozenset({"MULTIPLE_HEADS"}), passed=False)

    def test_reconciliation_suffix_under_evidence_is_a_second_head_on_e2(self) -> None:
        world, focus = self._suffix_world()
        self._assert_codes(world, "E2", focus, frozenset({"MULTIPLE_HEADS"}), passed=False)

    def test_execution_commit_collision_is_reconciliation_absent_on_e1(self) -> None:
        base, _focus = self._collision_world(False)
        held = self._payload(self._completed(base, "E1"))
        self.assertEqual("PASS", held["status"], held)
        self.assertEqual({TASK: "B"}, held["validated_heads"])
        world, _focus = self._collision_world(True)
        self._assert_codes(world, "E1", None, frozenset({"RECONCILIATION_ABSENT"}), passed=False)

    def test_execution_commit_collision_is_reconciliation_absent_on_e2(self) -> None:
        world, focus = self._collision_world(True)
        self._assert_codes(world, "E2", focus, frozenset({"RECONCILIATION_ABSENT"}), passed=False)

    def test_one_historical_key_on_two_records_is_ambiguous_on_e1(self) -> None:
        world, _focus = self._ambiguous_world()
        self._assert_codes(world, "E1", None, frozenset({"AMBIGUOUS_IDENTITY"}), passed=False)

    def test_one_historical_key_on_two_records_is_ambiguous_on_e2(self) -> None:
        world, focus = self._ambiguous_world()
        self._assert_codes(world, "E2", focus, frozenset({"AMBIGUOUS_IDENTITY"}), passed=False)

    def _assert_depth_accepted(self, entry: str) -> None:
        raw = document_at_depth(11)
        world = self._depth_world(raw)
        focus = _path("deep.json") if entry == "E2" else None
        payload = self._payload(self._completed(world, entry, focus))
        self.assertEqual("PASS", payload["status"], payload)
        if entry == "E3":
            self.assertEqual({}, payload["validated_heads"])
        else:
            self.assertEqual({TASK: f"{TASK}-deep"}, payload["validated_heads"])

    def _assert_depth_rejected(self, entry: str) -> None:
        focus = _path("deep.json") if entry == "E2" else None
        with self.subTest(document="depth-12"):
            bounded = self._depth_world(document_at_depth(12))
            self._assert_codes(bounded, entry, focus, frozenset({"UNREADABLE_JSON"}), passed=False)
        with self.subTest(document="depth-600"):
            nested = '{"extension":' + ("[" * 600) + "0" + ("]" * 600)
            nested += ',"record_id":"' + TASK + '-deep","task_id":"' + TASK + '"}'
            crashed = self._depth_world(nested.encode("utf-8") + b"\n")
            self._assert_codes(crashed, entry, focus, frozenset({"UNREADABLE_JSON"}), passed=False)

    def test_depth_11_is_loaded_on_e1(self) -> None:
        self._assert_depth_accepted("E1")

    def test_depth_11_is_loaded_on_e2(self) -> None:
        self._assert_depth_accepted("E2")

    def test_depth_11_is_loaded_on_e3(self) -> None:
        self._assert_depth_accepted("E3")

    def test_depth_above_the_limit_is_unreadable_json_on_e1(self) -> None:
        self._assert_depth_rejected("E1")

    def test_depth_above_the_limit_is_unreadable_json_on_e2(self) -> None:
        self._assert_depth_rejected("E2")

    def test_depth_above_the_limit_is_unreadable_json_on_e3(self) -> None:
        self._assert_depth_rejected("E3")

    def test_e3_on_one_manifest_does_not_fail_for_another_gate(self) -> None:
        world = self._two_gates(state_missing=False)
        root = self._payload(self._completed(world, "E1"))
        self.assertEqual("PASS", root["status"], root)
        self.assertEqual({"OCOR-DEV-0098": "OCOR-DEV-0098-X", TASK: f"{TASK}-B"}, root["validated_heads"])
        admitted = self._payload(self._completed(world, "E3"))
        self.assertEqual("PASS", admitted["status"], admitted)
        self.assertEqual([], admitted["findings"])
        self.assertNotIn("MANIFEST_UNLISTED", {item["code"] for item in admitted["findings"]})

    def test_e3_without_execution_state_is_not_unreadable_json(self) -> None:
        world = self._two_gates(state_missing=True)
        # The requested manifest and its listed files are enough. The absent state file is not a record.
        admitted = self._payload(self._completed(world, "E3"))
        self.assertEqual("PASS", admitted["status"], admitted)
        self.assertNotIn("UNREADABLE_JSON", {item["code"] for item in admitted["findings"]})
        self.assertEqual([], admitted["findings"])

    def test_removing_each_new_check_changes_the_outcome(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for name, (entry, focus, world) in (
            ("OUTSIDE_EVIDENCE", ("E2", self._archive_world()[2], self._archive_world()[0])),
            ("AMBIGUOUS_IDENTITY", ("E1", None, self._ambiguous_world()[0])),
        ):
            with self.subTest(check=name):
                start = f"# CHECK {name}\n"
                end = f"# END CHECK {name}\n"
                if start not in source or end not in source or source.index(start) > source.index(end):
                    self.fail(f"production is missing the marked check {name}")
                block = source.split(start, 1)[1].split(end, 1)[0]
                mutated = source.replace(start + block + end, start + "    return []\n" + end, 1)
                with tempfile.TemporaryDirectory() as tmp:
                    script = Path(tmp) / "validate_current_evidence_head.py"
                    script.write_text(mutated, encoding="utf-8")
                    expected = self._payload(self._completed(world, entry, focus))
                    self.assertIn(name, {item["code"] for item in expected["findings"]})
                    produced = _production(world, entry, focus, script)
                self.assertNotIn(name, {item.code for item in produced.findings})


if __name__ == "__main__":
    unittest.main()
