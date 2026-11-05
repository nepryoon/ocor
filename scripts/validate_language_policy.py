#!/usr/bin/env python3
"""Fail-closed gate for docs/development_methodology/OCOR_LANGUAGE_POLICY.md (DEC-212).

Rejects any tracked file whose extension is a monitored implementation-language
extension found outside the area(s) authorized for that extension by the language
policy table. Extensions that are not part of the policy's "linguaggio autorizzato"
column (plain data/doc formats such as .md, .json, .txt, .csv, .mmd, .toml, .lock)
are out of scope for this gate; declarative-contract semantic checks (OpenAPI/proto3
version, JSON Schema draft) remain the job of scripts/verify.py.

Default is deny: an extension present in MONITORED_EXTENSIONS but with no
authorization rule anywhere in AUTHORIZATIONS is rejected wherever it occurs.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable
from pathlib import Path


def under(path: str, prefix: str) -> bool:
    return path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")


def is_openapi_contract(path: str) -> bool:
    return path.endswith(".openapi.yaml") or path.endswith(".openapi.yml")


def is_declarative_contract_location(path: str) -> bool:
    return any(
        under(path, prefix)
        for prefix in (
            "ocor-runtime/schemas",
            "ocor-runtime/docs/governance_dossier/contracts",
            "reports/contracts",
        )
    )


# One authorization predicate per monitored extension. A file is ALLOWED if any
# predicate for its extension returns True; otherwise it is REJECTED. An
# extension with an empty tuple is authorized nowhere in the project (any
# occurrence fails) -- this is the "alternative vietate" enforcement for every
# language not selected by the policy table for any area.
AUTHORIZATIONS: dict[str, tuple[Callable[[str], bool], ...]] = {
    ".py": (
        lambda p: under(p, "ocor-runtime"),
        lambda p: under(p, "scripts"),
        lambda p: under(p, "reports/tests"),
        lambda p: under(p, "deploy/bootstrap/services"),
        lambda p: under(p, "deploy/bootstrap/init"),
        lambda p: under(p, "deploy/bootstrap/fixtures"),
        lambda p: under(p, "spikes"),
    ),
    ".ts": (lambda p: under(p, "ocor-runtime/sdk/typescript"),),
    ".tsx": (lambda p: under(p, "ocor-runtime/sdk/typescript"),),
    ".rego": (lambda p: under(p, "policy"), lambda p: under(p, "deploy/bootstrap/init")),
    ".yaml": (
        lambda p: under(p, ".github/workflows"),
        lambda p: under(p, "deploy"),
        is_openapi_contract,
    ),
    ".yml": (
        lambda p: under(p, ".github/workflows"),
        lambda p: under(p, "deploy"),
        is_openapi_contract,
    ),
    ".proto": (is_declarative_contract_location,),
    ".ttl": (
        is_declarative_contract_location,
        lambda p: p == "deploy/bootstrap/fuseki/config.ttl",
    ),
    # Alternative implementation languages authorized nowhere in the project.
    ".js": (),
    ".jsx": (),
    ".go": (),
    ".rs": (),
    ".java": (),
    ".rb": (),
    ".php": (),
    ".c": (),
    ".cpp": (),
    ".cs": (),
    ".kt": (),
    ".sh": (),
    ".ps1": (),
    ".lua": (),
}

DOCKERFILE_AUTHORIZED_PREFIXES = ("infra",)


def is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.")


def extension_of(name: str) -> str:
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def evaluate(paths: list[str]) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if is_dockerfile(name):
            if not any(under(path, prefix) for prefix in DOCKERFILE_AUTHORIZED_PREFIXES):
                violations.append(
                    {
                        "path": path,
                        "extension": "Dockerfile",
                        "reason": "Dockerfile is authorized only under infra/ (OCOR_LANGUAGE_POLICY.md row 10)",
                    }
                )
            continue
        suffix = extension_of(name)
        rules = AUTHORIZATIONS.get(suffix)
        if rules is None:
            continue  # not a monitored extension
        if not any(rule(path) for rule in rules):
            violations.append(
                {
                    "path": path,
                    "extension": suffix,
                    "reason": f"extension '{suffix}' has no authorized area for this path in OCOR_LANGUAGE_POLICY.md",
                }
            )
    return violations


def tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    violations = evaluate(tracked_files(args.root))
    if violations:
        for item in violations:
            print(f"FAIL: {item['path']}: {item['reason']}")
        print(f"FAIL: {len(violations)} language-policy violation(s)")
        return 1
    print("PASS: no tracked file uses a monitored extension outside its authorized area")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
