#!/usr/bin/env python3
"""Read-only probe for NCR-C3-008, NCR-C3-009 and NCR-PLAN-007.

Prints the facts used as the verification outcome of those register entries.
It does not modify the repository. HEAD_OBSERVED is ``git rev-parse HEAD``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_HEX = frozenset("0123456789abcdef")


def accept_head(text: str) -> str:
    """Reject a head that is not 40 lowercase hex digits before it is printed."""
    if len(text) != 40 or any(char not in _HEX for char in text):
        raise SystemExit("HEAD_OBSERVED_INVALID")
    return text


def read_repository_text(path: Path) -> str:
    """Read one repository file as strict UTF-8, or stop."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise SystemExit("TEXT_DECODE_REJECTED") from exc


def line_text(lines: list[str], number: int) -> str:
    """Return one 1-based line. A bool or an out-of-range index stops first."""
    if isinstance(number, bool) or not isinstance(number, int):
        raise SystemExit("LINE_INDEX_REJECTED")
    if number < 1 or number > len(lines):
        raise SystemExit("LINE_INDEX_REJECTED")
    return lines[number - 1]


def observed_head(root: Path = ROOT) -> str:
    """Return the git HEAD of ``root``. A missing or malformed head stops."""
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit("HEAD_OBSERVED_UNAVAILABLE")
    return accept_head(proc.stdout.strip())


def _has(text: str, needle: str) -> str:
    return "yes" if needle in text else "no"


def _py_text(path: Path) -> str:
    return read_repository_text(path)


def main() -> None:
    src = list((ROOT / "ocor-runtime/src").rglob("*.py"))
    texts = {path: _py_text(path) for path in src}
    admit = sorted(
        str(path.relative_to(ROOT))
        for path, text in texts.items()
        if "AdmitClaim" in text
    )
    mission = sorted(
        str(path.relative_to(ROOT))
        for path, text in texts.items()
        if "MissionThread" in text or "mission_thread" in text
    )
    lld = read_repository_text(ROOT / "docs/OCOR_LLD_v1.1.md").splitlines()
    add = read_repository_text(
        ROOT / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
    ).splitlines()
    reg = read_repository_text(
        ROOT
        / "ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md"
    ).splitlines()
    shacl = read_repository_text(
        ROOT / "ocor-runtime/src/ocor_runtime/c4/shacl.py"
    ).splitlines()
    orch = read_repository_text(
        ROOT / "ocor-runtime/src/ocor_runtime/c8/orchestrator.py"
    ).splitlines()
    print("HEAD_OBSERVED", observed_head())
    print("AdmitClaim under ocor-runtime/src:", admit or "ABSENT")
    print("MissionThread or mission_thread under ocor-runtime/src:", mission or "ABSENT")
    print("LLD AdmitClaim count:", sum("AdmitClaim" in line for line in lld))
    print("LLD line 246 has MissionThreadView:", _has(line_text(lld, 246), "MissionThreadView"))
    print("ADD line 284 has AdmitClaim:", _has(line_text(add, 284), "AdmitClaim"))
    print("ADD line 342 has AdmitClaim:", _has(line_text(add, 342), "AdmitClaim"))
    print("ADD line 2048 has acceptedFromClaim:", _has(line_text(add, 2048), "acceptedFromClaim"))
    print("ADD line 2010 has CandidateMatch:", _has(line_text(add, 2010), "CandidateMatch"))
    print(
        "ADD line 2012 has IdentityResolutionDecision:",
        _has(line_text(add, 2012), "IdentityResolutionDecision"),
    )
    print(
        "ADD line 2015 has ClusterMembershipAssertion:",
        _has(line_text(add, 2015), "ClusterMembershipAssertion"),
    )
    print("ADD line 2051 has reversibility:", _has(line_text(add, 2051), "Reversibilit"))
    shacl_window = "\n".join(line_text(shacl, number) for number in range(37, 42))
    print("SHACL lines 37-41 contain CandidateMatch:", _has(shacl_window, "CandidateMatch"))
    print(
        "SHACL lines 37-41 contain IdentityResolutionDecision:",
        _has(shacl_window, "IdentityResolutionDecision"),
    )
    print("ORCH line 195:", line_text(orch, 195).strip())
    for number, needle in (
        (65, "FR-012"),
        (120, "FR-030"),
        (175, "FR-053"),
        (176, "FR-054"),
        (335, "FR-150"),
        (336, "NFR-055"),
        (411, "FR-166"),
    ):
        print(
            f"REG line {number} is {needle}:",
            line_text(reg, number).startswith(f"| `{needle}`"),
        )
    print("CONFIRMED")


if __name__ == "__main__":
    main()
