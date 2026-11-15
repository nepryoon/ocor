#!/usr/bin/env python3
"""Classify a pull request as state-only CI or full CI.

CI-STATO-RAPIDA (2026-11-14). A pull request is state-only only when every
diff entry is an add or a modify of one closed path: the three development
state files and ``TERMINAL_BLOCKED_REPORT.json`` from
``state_sync_ci_observation_contract``, or exactly one Markdown file placed
directly under ``reports/development/decision_requests/``.

``git diff --name-status`` does not show mode changes, symlinks or binary
files. The command also reads ``git diff -M --raw -z`` and
``git diff -M --numstat -z``. Paths are compared as exact strings. A ``..``
segment is never normalised onto the allowlist. Missing data, a git error,
an empty diff and any disallowed entry select full CI.

No pinned library implements this policy. The property oracle is in
``reports/tests/test_classify_pull_request_ci_route.py``: the same entries in
any order return the same result, and adding a disallowed entry never yields
``state_only``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

STATE_FILES = frozenset(
    {
        "reports/development/EXECUTION_STATE.json",
        "reports/development/MODEL_HANDOFF.json",
        "reports/development/ITERATION_LOG.md",
        "reports/development/TERMINAL_BLOCKED_REPORT.json",
    }
)
DECISION_PREFIX = "reports/development/decision_requests/"
ROUTE_STATE_ONLY = "state_only"
ROUTE_FULL = "full"
_RAW_METADATA = re.compile(r"^:(\d{6}) (\d{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z][0-9]*)$")


class DiffEntry:
    """One changed path, with the mode and binary facts ``--name-status`` omits.

    A plain class keeps ``importlib`` loading working when the caller has not
    inserted the module into ``sys.modules`` yet. ``dataclass`` on Python 3.12
    looks that entry up while the class body is executing.
    """

    def __init__(
        self,
        status: str,
        path: str,
        old_path: str | None = None,
        old_mode: str | None = None,
        new_mode: str | None = None,
        binary: bool = False,
    ) -> None:
        self.status = status
        self.path = path
        self.old_path = old_path
        self.old_mode = old_mode
        self.new_mode = new_mode
        self.binary = binary


def _path_bucket(path: str) -> tuple[str | None, str]:
    """Return ``(bucket, reason)``. ``bucket`` is set only for an allowlisted path."""
    if path.startswith("/") or path.startswith("\\"):
        return None, "absolute_path"
    if ".." in path.split("/"):
        return None, "path_escape"
    if path in STATE_FILES:
        return "state", "state_files"
    if path.startswith(DECISION_PREFIX):
        name = path[len(DECISION_PREFIX) :]
        if name == "" or "/" in name or name in {".", ".."}:
            return None, "decision_request_not_direct"
        if not name.endswith(".md") or name == ".md":
            return None, "decision_request_not_markdown"
        return "decision", "single_decision_request"
    return None, "outside_closed_list"


def _structural_failure(entry: DiffEntry) -> str | None:
    status = entry.status
    kind = status[:1]
    if entry.old_mode == "160000" or entry.new_mode == "160000":
        return "submodule"
    if entry.old_mode == "120000" or entry.new_mode == "120000":
        return "symlink"
    if kind == "U":
        return "unmerged"
    if kind == "D":
        return "deletion"
    if kind == "R":
        return "rename"
    if kind == "C":
        return "copy"
    if kind == "T":
        return "type_change"
    if (
        entry.old_mode is not None
        and entry.new_mode is not None
        and entry.old_mode != entry.new_mode
        and entry.old_mode != "000000"
    ):
        return "mode_change"
    if entry.binary:
        return "binary"
    if status not in {"A", "M"}:
        return "git_error"
    return None


def classify_entries(entries: Sequence[DiffEntry]) -> tuple[str, str]:
    """Return ``(route, reason)``. Any disallowed entry forces ``full``."""
    if not entries:
        return ROUTE_FULL, "empty_diff"
    buckets: list[str] = []
    for entry in entries:
        failure = _structural_failure(entry)
        if failure is not None:
            return ROUTE_FULL, failure
        for candidate in (entry.path, entry.old_path):
            if candidate is None:
                continue
            bucket, reason = _path_bucket(candidate)
            if bucket is None:
                return ROUTE_FULL, reason
        bucket, _reason = _path_bucket(entry.path)
        if bucket is None:
            return ROUTE_FULL, "outside_closed_list"
        buckets.append(bucket)
    if all(bucket == "state" for bucket in buckets):
        return ROUTE_STATE_ONLY, "state_files"
    if all(bucket == "decision" for bucket in buckets):
        if len(buckets) == 1:
            return ROUTE_STATE_ONLY, "single_decision_request"
        return ROUTE_FULL, "multiple_decision_requests"
    if "state" in buckets and "decision" in buckets:
        return ROUTE_FULL, "mixed_state_and_decision_request"
    return ROUTE_FULL, "outside_closed_list"


def _decode(blob: bytes) -> str | None:
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _read_field(blob: bytes, pos: int) -> tuple[bytes, int] | None:
    end = blob.find(b"\0", pos)
    if end < 0:
        return None
    return blob[pos:end], end + 1


def _parse_raw(blob: bytes) -> list[DiffEntry] | None:
    entries: list[DiffEntry] = []
    pos = 0
    while pos < len(blob):
        field = _read_field(blob, pos)
        if field is None:
            return None
        meta_bytes, pos = field
        meta = _decode(meta_bytes)
        if meta is None:
            return None
        matched = _RAW_METADATA.fullmatch(meta)
        if matched is None:
            return None
        old_mode, new_mode, _old_sha, _new_sha, status = matched.groups()
        path_field = _read_field(blob, pos)
        if path_field is None:
            return None
        path_bytes, pos = path_field
        path = _decode(path_bytes)
        if path is None:
            return None
        old_path: str | None = None
        if status[:1] in {"R", "C"}:
            new_field = _read_field(blob, pos)
            if new_field is None:
                return None
            new_bytes, pos = new_field
            new_path = _decode(new_bytes)
            if new_path is None:
                return None
            old_path = path
            path = new_path
        entries.append(
            DiffEntry(
                status=status,
                path=path,
                old_path=old_path,
                old_mode=old_mode,
                new_mode=new_mode,
            )
        )
    return entries


def _parse_name_status(blob: bytes) -> list[tuple[str, str, str | None]] | None:
    records: list[tuple[str, str, str | None]] = []
    pos = 0
    while pos < len(blob):
        status_field = _read_field(blob, pos)
        if status_field is None:
            return None
        status_bytes, pos = status_field
        status = _decode(status_bytes)
        if status is None or not status:
            return None
        path_field = _read_field(blob, pos)
        if path_field is None:
            return None
        path_bytes, pos = path_field
        path = _decode(path_bytes)
        if path is None:
            return None
        old_path: str | None = None
        if status[:1] in {"R", "C"}:
            new_field = _read_field(blob, pos)
            if new_field is None:
                return None
            new_bytes, pos = new_field
            new_path = _decode(new_bytes)
            if new_path is None:
                return None
            old_path = path
            path = new_path
        records.append((status, path, old_path))
    return records


def _parse_numstat(blob: bytes) -> list[tuple[str, str | None, bool]] | None:
    records: list[tuple[str, str | None, bool]] = []
    pos = 0
    while pos < len(blob):
        header_field = _read_field(blob, pos)
        if header_field is None:
            return None
        header, pos = header_field
        pieces = header.split(b"\t")
        if len(pieces) < 3:
            return None
        binary = pieces[0] == b"-" and pieces[1] == b"-"
        embedded = b"\t".join(pieces[2:])
        if embedded == b"":
            old_field = _read_field(blob, pos)
            if old_field is None:
                return None
            old_bytes, pos = old_field
            new_field = _read_field(blob, pos)
            if new_field is None:
                return None
            new_bytes, pos = new_field
            old_path = _decode(old_bytes)
            new_path = _decode(new_bytes)
            if old_path is None or new_path is None:
                return None
            records.append((new_path, old_path, binary))
            continue
        path = _decode(embedded)
        if path is None:
            return None
        records.append((path, None, binary))
    return records


def _align(
    raw_entries: list[DiffEntry],
    named: list[tuple[str, str, str | None]],
    counted: list[tuple[str, str | None, bool]],
) -> list[DiffEntry] | None:
    if not (len(raw_entries) == len(named) == len(counted)):
        return None
    aligned: list[DiffEntry] = []
    for raw, name, count in zip(raw_entries, named, counted, strict=True):
        status, path, old_path = name
        count_path, count_old, binary = count
        if status != raw.status or path != raw.path or old_path != raw.old_path:
            return None
        if count_path != raw.path or count_old != raw.old_path:
            return None
        aligned.append(
            DiffEntry(
                status=raw.status,
                path=raw.path,
                old_path=raw.old_path,
                old_mode=raw.old_mode,
                new_mode=raw.new_mode,
                binary=binary,
            )
        )
    return aligned


def _git_bytes(root: Path, args: Sequence[str]) -> bytes | None:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def entries_from_git(root: Path, base: str, head: str) -> list[DiffEntry] | None:
    """Return aligned entries, or ``None`` when git fails or the views disagree."""
    common = ["diff", "--no-ext-diff", "--no-textconv", "-M"]
    raw_blob = _git_bytes(root, [*common, "--raw", "-z", "--no-abbrev", base, head])
    numstat_blob = _git_bytes(root, [*common, "--numstat", "-z", base, head])
    named_blob = _git_bytes(root, [*common, "--name-status", "-z", base, head])
    if raw_blob is None or numstat_blob is None or named_blob is None:
        return None
    raw_entries = _parse_raw(raw_blob)
    named = _parse_name_status(named_blob)
    counted = _parse_numstat(numstat_blob)
    if raw_entries is None or named is None or counted is None:
        return None
    return _align(raw_entries, named, counted)


def decide(root: Path, base: str, head: str) -> dict[str, str]:
    """Return the route payload. Git failures stay on the full route."""
    if not base.strip() or not head.strip():
        return {"base": base, "head": head, "reason": "missing_base_or_head", "route": ROUTE_FULL}
    entries = entries_from_git(root, base, head)
    if entries is None:
        return {"base": base, "head": head, "reason": "git_error", "route": ROUTE_FULL}
    route, reason = classify_entries(entries)
    return {"base": base, "head": head, "reason": reason, "route": route}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--github-output", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = decide(Path(args.root), str(args.base), str(args.head))
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if args.github_output is not None:
        Path(str(args.github_output)).write_text(
            f"route={payload['route']}\n",
            encoding="utf-8",
            newline="\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
