#!/usr/bin/env python3
"""Fail-closed DR-FORMATO-OPZIONI check for one pull-request decision file.

CI-STATO-RAPIDA (2026-11-14) keeps this check on the fast path. The files
examined are the decision-request Markdown files added or modified in the
three-dot diff from the unique merge-base of ``--base`` and ``--head`` to
the pinned head. A state-only diff with no such file passes. ``--path``
checks one file and fails when that file is missing. Classification of the
route stays path-only: a malformed file is not redirected to full CI here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

DECISION_PREFIX = "reports/development/decision_requests/"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_STATUS_TOKEN = re.compile(r"^(?:[AMDTUXB]|[RC][0-9]{1,3})$")
_OPTION = re.compile(r"^([A-Z])?([0-9]{1,2})\. \*\*(.+)\*\*(.*)$")
_LOOSE = re.compile(r"^[A-Z]?[0-9]{1,2}\. ")
_GREP = re.compile(r"^[A-Z]?[0-9]{1,2}\. \*\*")
_QUESITO = re.compile(r"^### Opzioni del quesito ([A-Z])$")
_PRIORITY = (
    "empty_options",
    "plain_list",
    "wrong_letter",
    "numbering_gap",
    "option_outside_heading",
    "option_only_in_fence",
    "repeated_question",
    "repeated_identifier",
)


def _decode(blob: bytes) -> str | None:
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _git_bytes(root: Path, args: Sequence[str]) -> bytes | None:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def _rev_parse(root: Path, rev: str) -> str | None:
    blob = _git_bytes(root, ["rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"])
    if blob is None:
        return None
    text = _decode(blob)
    if text is None:
        return None
    sha = text.strip()
    if _SHA.fullmatch(sha) is None:
        return None
    return sha


def _unique_merge_base(root: Path, base_sha: str, head_sha: str) -> str | None:
    blob = _git_bytes(root, ["merge-base", "--all", "--end-of-options", base_sha, head_sha])
    if blob is None:
        return None
    text = _decode(blob)
    if text is None:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or _SHA.fullmatch(lines[0]) is None:
        return None
    return lines[0]


def _read_field(blob: bytes, pos: int) -> tuple[bytes, int] | None:
    end = blob.find(b"\0", pos)
    if end < 0:
        return None
    return blob[pos:end], end + 1


def _is_direct_decision_request(path: str) -> bool:
    if path.startswith("/") or path.startswith("\\") or ".." in path.split("/"):
        return False
    if not path.startswith(DECISION_PREFIX):
        return False
    name = path[len(DECISION_PREFIX) :]
    return bool(name) and "/" not in name and name.endswith(".md") and name != ".md"


def _changed_decision_requests(root: Path, merge_base: str, head_sha: str) -> list[str] | None:
    blob = _git_bytes(
        root,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "-M",
            "--name-status",
            "-z",
            "--end-of-options",
            merge_base,
            head_sha,
        ],
    )
    if blob is None:
        return None
    paths: list[str] = []
    pos = 0
    while pos < len(blob):
        status_field = _read_field(blob, pos)
        if status_field is None:
            return None
        status_bytes, pos = status_field
        status = _decode(status_bytes)
        if status is None or _STATUS_TOKEN.fullmatch(status) is None:
            return None
        path_field = _read_field(blob, pos)
        if path_field is None:
            return None
        path_bytes, pos = path_field
        path = _decode(path_bytes)
        if path is None:
            return None
        if status[:1] in {"R", "C"}:
            new_field = _read_field(blob, pos)
            if new_field is None:
                return None
            new_bytes, pos = new_field
            new_path = _decode(new_bytes)
            if new_path is None:
                return None
            path = new_path
        if status[:1] in {"A", "M", "R", "C", "T"} and _is_direct_decision_request(path):
            paths.append(path)
    return sorted(set(paths))


def _show(root: Path, sha: str, path: str) -> bytes | None:
    return _git_bytes(root, ["show", "--no-textconv", "--end-of-options", f"{sha}:{path}"])


def _first_nonspace_run(line: str) -> str:
    stripped = line.lstrip(" \t")
    end = 0
    while end < len(stripped) and not stripped[end].isspace():
        end += 1
    return stripped[:end]


def _opening_fence(line: str) -> tuple[str, int] | None:
    """A fence opens when the first non-space run is only backticks or tildes."""
    token = _first_nonspace_run(line)
    if len(token) >= 3 and set(token) == {"`"}:
        return "`", len(token)
    if len(token) >= 3 and set(token) == {"~"}:
        return "~", len(token)
    return None


def _closing_fence(line: str, character: str, length: int) -> bool:
    stripped = line.strip(" \t")
    return bool(stripped) and len(stripped) >= length and set(stripped) == {character}


def _fence_hidden(lines: Sequence[str]) -> list[bool]:
    """Mark fence markers and every line until the closer, or through EOF."""
    hidden = [False] * len(lines)
    index = 0
    limit = len(lines)
    while index < limit:
        opener = _opening_fence(lines[index])
        if opener is None:
            index += 1
            continue
        character, length = opener
        hidden[index] = True
        index += 1
        while index < limit:
            hidden[index] = True
            closed = _closing_fence(lines[index], character, length)
            index += 1
            if closed:
                break
    return hidden


def _line_is_option(line: str) -> bool:
    return bool(_OPTION.fullmatch(line) or _LOOSE.match(line) or _GREP.match(line))


def _next_heading(lines: Sequence[str], start: int, limit: int, hidden: Sequence[bool]) -> int:
    for index in range(start, limit):
        if hidden[index]:
            continue
        if lines[index].startswith("#"):
            return index
    return limit


def _gap_has_option(
    lines: Sequence[str], start: int, end: int, hidden: Sequence[bool]
) -> bool:
    for index in range(start, end):
        if hidden[index]:
            continue
        if _line_is_option(lines[index]):
            return True
    return False


def _take_options(
    lines: Sequence[str],
    start: int,
    end: int,
    expect: str | None,
    problems: list[str],
    accepted: list[int],
    hidden: Sequence[bool],
    seen: set[str],
) -> None:
    found: list[tuple[str | None, int]] = []
    malformed = False
    fenced_option = False
    for index in range(start, end):
        if hidden[index]:
            if _line_is_option(lines[index]):
                fenced_option = True
            continue
        line = lines[index]
        if line.startswith("#"):
            continue
        matched = _OPTION.fullmatch(line)
        if matched is not None:
            found.append((matched.group(1), int(matched.group(2))))
            accepted.append(index)
            continue
        if _LOOSE.match(line) or _GREP.match(line):
            malformed = True
            problems.append("plain_list")
    if not found:
        if not malformed:
            if fenced_option:
                problems.append("option_only_in_fence")
            else:
                problems.append("empty_options")
        return
    for prefix, number in found:
        if prefix != expect:
            problems.append("wrong_letter")
        identifier = f"{prefix or ''}{number}"
        if identifier in seen:
            problems.append("repeated_identifier")
        seen.add(identifier)
    numbers = [number for _prefix, number in found]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append("numbering_gap")


def validate_text(text: str) -> str:
    """Return ``ok`` or the first violated option-format property."""
    lines = text.splitlines()
    hidden = _fence_hidden(lines)
    grep_hits = [
        index
        for index, line in enumerate(lines)
        if not hidden[index] and _GREP.match(line)
    ]
    h2_at = [
        index
        for index, line in enumerate(lines)
        if not hidden[index] and line == "## Opzioni"
    ]
    quesiti = [
        (index, matched.group(1))
        for index, line in enumerate(lines)
        if not hidden[index] and (matched := _QUESITO.fullmatch(line)) is not None
    ]
    seen: set[str] = set()
    if not h2_at and not quesiti:
        return "no_options_heading"
    problems: list[str] = []
    letters = [letter for _index, letter in quesiti]
    if len(letters) != len(set(letters)):
        problems.append("repeated_question")
    accepted: list[int] = []
    consumed: set[int] = set()
    for start in h2_at:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if hidden[index]:
                continue
            if lines[index].startswith("## ") and not lines[index].startswith("### "):
                end = index
                break
        children = [(index, letter) for index, letter in quesiti if start < index < end]
        for index, _letter in children:
            consumed.add(index)
        if children:
            cursor = start + 1
            for child_at, letter in children:
                if _gap_has_option(lines, cursor, child_at, hidden):
                    problems.append("option_outside_heading")
                child_end = _next_heading(lines, child_at + 1, end, hidden)
                _take_options(
                    lines, child_at + 1, child_end, letter, problems, accepted, hidden, seen
                )
                cursor = child_end
            if _gap_has_option(lines, cursor, end, hidden):
                problems.append("option_outside_heading")
            continue
        _take_options(lines, start + 1, end, None, problems, accepted, hidden, seen)
    for index, letter in quesiti:
        if index in consumed:
            continue
        end = _next_heading(lines, index + 1, len(lines), hidden)
        _take_options(lines, index + 1, end, letter, problems, accepted, hidden, seen)
    if len(accepted) != len(grep_hits) or any(index not in accepted for index in grep_hits):
        problems.append("option_outside_heading")
    for reason in _PRIORITY:
        if reason in problems:
            return reason
    return "ok"


def _payload(reason: str, path: str = "", checked: Sequence[str] = ()) -> dict[str, object]:
    return {"checked": list(checked), "path": path, "reason": reason}


def _emit(reason: str, path: str = "", checked: Sequence[str] = ()) -> int:
    sys.stdout.write(json.dumps(_payload(reason, path, checked), indent=2, sort_keys=True) + "\n")
    return 0 if reason == "ok" else 1


def _check_bytes(blob: bytes) -> str:
    text = _decode(blob)
    if text is None:
        return "not_utf8"
    return validate_text(text)


def _path_under_root(root: Path, raw: str) -> Path | None:
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return root / candidate


def check_path(root: Path, raw: str) -> int:
    """Validate one filesystem path. A missing file fails closed."""
    target = _path_under_root(root, raw)
    if target is None or not target.is_file():
        return _emit("missing_file", raw)
    try:
        blob = target.read_bytes()
    except OSError:
        return _emit("missing_file", raw)
    reason = _check_bytes(blob)
    checked = [raw] if reason == "ok" else []
    return _emit(reason, "" if reason == "ok" else raw, checked)


def check_diff(root: Path, base: str, head: str) -> int:
    """Validate decision-request files added or modified by the pull request."""
    if not base.strip() or not head.strip():
        return _emit("git_error")
    base_sha = _rev_parse(root, base)
    head_sha = _rev_parse(root, head)
    if base_sha is None or head_sha is None:
        return _emit("git_error")
    merge_base = _unique_merge_base(root, base_sha, head_sha)
    if merge_base is None:
        return _emit("git_error")
    paths = _changed_decision_requests(root, merge_base, head_sha)
    if paths is None:
        return _emit("git_error")
    for path in paths:
        blob = _show(root, head_sha, path)
        if blob is None:
            return _emit("missing_file", path, paths)
        reason = _check_bytes(blob)
        if reason != "ok":
            return _emit(reason, path, paths)
    return _emit("ok", "", paths)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None)
    parser.add_argument("--head", default=None)
    parser.add_argument("--path", default=None)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = Path(str(args.root))
    raw_path = None if args.path is None else str(args.path)
    base = None if args.base is None else str(args.base)
    head = None if args.head is None else str(args.head)
    if raw_path is not None and (base is not None or head is not None):
        return _emit("usage")
    if raw_path is not None:
        return check_path(root, raw_path)
    if base is None or head is None:
        return _emit("usage")
    return check_diff(root, base, head)


if __name__ == "__main__":
    raise SystemExit(main())
