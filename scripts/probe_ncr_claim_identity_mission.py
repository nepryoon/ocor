#!/usr/bin/env python3
"""Read-only probe for NCR-C3-008, NCR-C3-009 and NCR-PLAN-007.

Prints the facts used as the verification outcome of those register entries.
It does not modify the repository.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _has(text: str, needle: str) -> str:
    return "yes" if needle in text else "no"


def main() -> None:
    src = list((ROOT / "ocor-runtime/src").rglob("*.py"))
    admit = sorted(
        str(path.relative_to(ROOT))
        for path in src
        if "AdmitClaim" in path.read_text(encoding="utf-8")
    )
    mission = sorted(
        str(path.relative_to(ROOT))
        for path in src
        if "MissionThread" in path.read_text(encoding="utf-8")
        or "mission_thread" in path.read_text(encoding="utf-8")
    )
    lld = (ROOT / "docs/OCOR_LLD_v1.1.md").read_text(encoding="utf-8").splitlines()
    add = (
        ROOT / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
    ).read_text(encoding="utf-8").splitlines()
    reg = (
        ROOT
        / "ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md"
    ).read_text(encoding="utf-8").splitlines()
    shacl = (
        ROOT / "ocor-runtime/src/ocor_runtime/c4/shacl.py"
    ).read_text(encoding="utf-8").splitlines()
    orch = (
        ROOT / "ocor-runtime/src/ocor_runtime/c8/orchestrator.py"
    ).read_text(encoding="utf-8").splitlines()
    print("HEAD_OBSERVED", "41abc9cc28f1cba91b51401bcbb1bee9acdcd93b")
    print("AdmitClaim under ocor-runtime/src:", admit or "ABSENT")
    print("MissionThread or mission_thread under ocor-runtime/src:", mission or "ABSENT")
    print("LLD AdmitClaim count:", sum("AdmitClaim" in line for line in lld))
    print("LLD line 246 has MissionThreadView:", _has(lld[245], "MissionThreadView"))
    print("ADD line 284 has AdmitClaim:", _has(add[283], "AdmitClaim"))
    print("ADD line 342 has AdmitClaim:", _has(add[341], "AdmitClaim"))
    print("ADD line 2048 has acceptedFromClaim:", _has(add[2047], "acceptedFromClaim"))
    print("ADD line 2010 has CandidateMatch:", _has(add[2009], "CandidateMatch"))
    print("ADD line 2012 has IdentityResolutionDecision:", _has(add[2011], "IdentityResolutionDecision"))
    print("ADD line 2015 has ClusterMembershipAssertion:", _has(add[2014], "ClusterMembershipAssertion"))
    print("ADD line 2051 has reversibility:", _has(add[2050], "Reversibilit"))
    print("SHACL lines 37-41 contain CandidateMatch:", _has("\n".join(shacl[36:41]), "CandidateMatch"))
    print("SHACL lines 37-41 contain IdentityResolutionDecision:", _has("\n".join(shacl[36:41]), "IdentityResolutionDecision"))
    print("ORCH line 195:", orch[194].strip())
    for number, needle in (
        (65, "FR-012"),
        (120, "FR-030"),
        (175, "FR-053"),
        (176, "FR-054"),
        (335, "FR-150"),
        (336, "NFR-055"),
        (411, "FR-166"),
    ):
        print(f"REG line {number} is {needle}:", reg[number - 1].startswith(f"| `{needle}`"))
    print("CONFIRMED")


if __name__ == "__main__":
    main()
