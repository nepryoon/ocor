"""OCOR-DEV-REM-0051 (NCP-U06) repair cycle 1: regression class in
``ocor-runtime/tools/evidence_manifest.py validate``.

Decision NCP-U06-0004-REGRESSION-MANIFEST-VALIDATION (2026-11-04), option 1
(reports/development/decision_requests/NCP-U06-0004-REGRESSION-MANIFEST-VALIDATION.md at
0b41db1bcc9c, sha256 fa6c4af1c69f): when the first artifact of the task is a record with
``requalification_kind: "regression"`` the validator applies to it the checks that do not
concern requirements (record and raw-log digests, required fields except
``requirement_results``, every command ``PASS``, ``result`` ``PASS``, no
``requirement_results``, no ledger row naming it, ``qualifies_requirements`` exactly
``false``, ``supersedes`` equal to ``previous_record.record_id`` and a superseded record of
the same task with the declared digest), then follows the ``supersedes`` chain to the latest
non-regression record and applies to it every current check unchanged, ledger cardinality and
paths included (REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30) points 1 and 3). A
non-regression record is validated exactly as before.

Positive and negative cases for each branch; negative cases match the specific refusal, so a
rejection for the wrong reason fails.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "ocor-runtime" / "tools"
sys.path.insert(0, str(TOOLS))

from evidence_manifest import (  # noqa: E402
    ManifestError,
    record_task_evidence,
    validate_manifest,
)

TASK = "OCOR-DEV-0004"
GATE_DIR = ("reports", "evidence", "G0")
QUALIFYING = "OCOR-DEV-0004.requalified-q.json"
REGRESSION = "OCOR-DEV-0004.requalified-r.json"
REGRESSION_R1 = "OCOR-DEV-0004.requalified-r1.json"
QUALIFYING_ID = "OCOR-DEV-0004-requalified-q"
REGRESSION_ID = "OCOR-DEV-0004-requalified-r"
REGRESSION_R1_ID = "OCOR-DEV-0004-requalified-r1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def raw_name(name: str) -> str:
    return name.removesuffix(".json") + ".log"


class Gate:
    """A G0-like evidence directory with a MANIFEST, built by hand like the sealed records."""

    def __init__(self, root: Path) -> None:
        self.dir = root.joinpath(*GATE_DIR)
        self.dir.mkdir(parents=True)
        self.manifest_path = self.dir / "MANIFEST.json"
        self.manifest: dict[str, Any] = {
            "artifacts": [],
            "created_at": "2026-11-04T00:00:00Z",
            "gate": "G0",
            "requirement_results": [],
            "schema_version": "1.0",
        }
        self.save()

    def save(self) -> None:
        write_json(self.manifest_path, self.manifest)

    def write_raw(self, name: str, text: str) -> str:
        path = self.dir / raw_name(name)
        path.write_text(text, encoding="utf-8")
        return sha256(path)

    def write_record(self, name: str, record: dict[str, Any]) -> str:
        path = self.dir / name
        write_json(path, record)
        return sha256(path)

    def add_pair(self, name: str, *, first: bool) -> None:
        pair = [
            {"path": name, "sha256": sha256(self.dir / name), "task_id": TASK},
            {"path": raw_name(name), "sha256": sha256(self.dir / raw_name(name)), "task_id": f"{TASK}-RAW"},
        ]
        artifacts = self.manifest["artifacts"]
        self.manifest["artifacts"] = pair + artifacts if first else artifacts + pair
        self.save()

    def refresh(self, name: str) -> None:
        """Rewrite the artifact digests of ``name`` and of its raw log after an edit."""
        for item in self.manifest["artifacts"]:
            if item["path"] in {name, raw_name(name)}:
                item["sha256"] = sha256(self.dir / item["path"])
        self.save()

    def record(self, name: str) -> dict[str, Any]:
        value: dict[str, Any] = json.loads((self.dir / name).read_text(encoding="utf-8"))
        return value

    def edit(self, name: str, change: Callable[[dict[str, Any]], None]) -> None:
        record = self.record(name)
        change(record)
        self.write_record(name, record)
        self.refresh(name)

    def validate(self, *, non_skipped: bool = True) -> bool:
        return validate_manifest(self.manifest_path, task_id=TASK, non_skipped=non_skipped)


def qualifying_record(raw_digest: str) -> dict[str, Any]:
    case = {
        "case_id": "OCOR-DEV-0004-REQUALIFIED-Q",
        "command": "labels regression of the shared campaign, all PASS",
        "requirement_id": "BR-003",
        "result": {"failed": 0, "not_executed": 0, "passed": 13, "skipped": 0},
        "status": "PASS",
    }
    return {
        "commands": [{"command": case["command"], "result": case["result"], "status": "PASS"}],
        "commit": "a" * 40,
        "created_at": "2026-10-27T00:00:00Z",
        "environment": {"python": "3.12.11", "uv": "0.12.5"},
        "inputs": {"ocor-runtime/uv.lock": "b" * 64},
        "raw_output_sha256": raw_digest,
        "record_id": QUALIFYING_ID,
        "requirement_results": [case],
        "result": "PASS",
        "schema_version": "1.0",
        "task_id": TASK,
    }


def regression_record(raw_digest: str, *, record_id: str, superseded: str, superseded_id: str, digest: str) -> dict[str, Any]:
    return {
        "commands": [
            {"command": "pytest tests/tasks/test_ocor_dev_0004.py", "exit_code": 0, "label": "task", "status": "PASS"},
            {"command": "pytest -n 2 tests/", "exit_code": 0, "label": "two-lane-full", "status": "PASS"},
        ],
        "commit": "c" * 40,
        "created_at": "2026-11-04T00:00:00Z",
        "environment": {"python": "3.12.11", "uv": "0.12.5"},
        "inputs": {"ocor-runtime/uv.lock": "d" * 64},
        "previous_record": {
            "record_id": superseded_id,
            "record_path": "/".join((*GATE_DIR, superseded)),
            "record_sha256": digest,
            "status": "SEALED",
        },
        "qualifies_requirements": False,
        "raw_output_sha256": raw_digest,
        "record_id": record_id,
        "requalification_kind": "regression",
        "result": "PASS",
        "schema_version": "1.0",
        "status": "SEALED",
        "supersedes": superseded_id,
        "task_id": TASK,
    }


def add_qualifying(gate: Gate) -> None:
    raw = gate.write_raw(QUALIFYING, "13 passed\n")
    gate.write_record(QUALIFYING, qualifying_record(raw))
    gate.add_pair(QUALIFYING, first=False)
    gate.manifest["requirement_results"].append(
        {
            "case_id": "OCOR-DEV-0004-REQUALIFIED-Q",
            "command": "labels regression of the shared campaign, all PASS",
            "evidence_path": QUALIFYING,
            "raw_output_path": raw_name(QUALIFYING),
            "requirement_id": "BR-003",
            "status": "PASS",
            "task_id": TASK,
        }
    )
    gate.save()


def add_regression(gate: Gate, name: str, record_id: str, superseded: str, superseded_id: str) -> None:
    raw = gate.write_raw(name, f"regression campaign of {record_id}: all PASS\n")
    record = regression_record(
        raw, record_id=record_id, superseded=superseded, superseded_id=superseded_id, digest=sha256(gate.dir / superseded)
    )
    gate.write_record(name, record)
    gate.add_pair(name, first=True)


@pytest.fixture
def chain(tmp_path: Path) -> Gate:
    """MANIFEST with a regression head superseding the latest qualifying record, head first."""
    gate = Gate(tmp_path)
    add_qualifying(gate)
    add_regression(gate, REGRESSION, REGRESSION_ID, QUALIFYING, QUALIFYING_ID)
    return gate


@pytest.fixture
def chain2(chain: Gate) -> Gate:
    """Two regression records (the repair-cycle shape r1 -> r -> q), newest first."""
    add_regression(chain, REGRESSION_R1, REGRESSION_R1_ID, REGRESSION, REGRESSION_ID)
    return chain


def refused(gate: Gate, pattern: str, *, non_skipped: bool = True) -> None:
    with pytest.raises(ManifestError, match=pattern):
        gate.validate(non_skipped=non_skipped)


# --- unchanged qualifying path -------------------------------------------------------


def test_qualifying_first_artifact_is_validated_as_before(tmp_path: Path) -> None:
    manifest = tmp_path / "MANIFEST.json"
    record_task_evidence(
        manifest_path=manifest,
        gate="G0",
        task_id=TASK,
        commit="a" * 40,
        environment={"python": "3.12.11"},
        inputs={"uv.lock": "b" * 64},
        cases=[
            {
                "requirement_id": "BR-003",
                "case_id": "OCOR-DEV-0004-POSITIVE",
                "command": "pytest -q test_ocor_dev_0004.py",
                "status": "PASS",
                "result": {"passed": 1, "failed": 0, "skipped": 0, "not_executed": 0},
            }
        ],
        raw_output="1 passed\n",
        created_at="2026-11-04T00:00:00Z",
    )
    assert validate_manifest(manifest, task_id=TASK, non_skipped=True) is True


def test_qualifying_only_manifest_passes(tmp_path: Path) -> None:
    gate = Gate(tmp_path)
    add_qualifying(gate)
    assert gate.validate() is True


def test_non_regression_first_artifact_without_requirement_results_is_still_refused(tmp_path: Path) -> None:
    gate = Gate(tmp_path)
    add_qualifying(gate)
    gate.edit(QUALIFYING, lambda record: record.pop("requirement_results"))
    refused(gate, "^evidence fields missing: requirement_results$")


@pytest.mark.parametrize("kind", [None, "qualifying", "Regression", "regression "])
def test_other_requalification_kinds_take_the_qualifying_path(chain: Gate, kind: str | None) -> None:
    def change(record: dict[str, Any]) -> None:
        if kind is None:
            record.pop("requalification_kind")
        else:
            record["requalification_kind"] = kind

    chain.edit(REGRESSION, change)
    refused(chain, "^evidence fields missing: requirement_results$")


def test_qualifying_first_with_ledger_on_another_record_is_refused(tmp_path: Path) -> None:
    gate = Gate(tmp_path)
    add_qualifying(gate)
    gate.manifest["requirement_results"][0]["evidence_path"] = "OCOR-DEV-0004.other.json"
    gate.save()
    refused(gate, "^requirement-result ledger path mismatch$")


# --- regression head, positive -------------------------------------------------------


def test_regression_head_then_latest_qualifying_record_passes(chain: Gate) -> None:
    assert chain.manifest["artifacts"][0]["path"] == REGRESSION
    assert chain.validate() is True


def test_two_regression_records_then_latest_qualifying_record_pass(chain2: Gate) -> None:
    assert [item["path"] for item in chain2.manifest["artifacts"][::2]] == [REGRESSION_R1, REGRESSION, QUALIFYING]
    assert chain2.validate() is True


def test_cli_reports_pass_for_a_regression_head(chain: Gate) -> None:
    run = subprocess.run(
        [sys.executable, str(TOOLS / "evidence_manifest.py"), "validate", "--task", TASK, "--non-skipped",
         "--manifest", str(chain.manifest_path)],
        capture_output=True, text=True, check=False,
    )
    assert (run.returncode, run.stdout) == (0, f"PASS: qualifying manifest and requirement ledger for {TASK}\n")


def test_regression_head_without_non_skipped_passes(chain: Gate) -> None:
    assert chain.validate(non_skipped=False) is True


# --- regression head, negative: checks that do not concern requirements --------------


@pytest.mark.parametrize(
    "field", ["task_id", "commit", "environment", "inputs", "commands", "raw_output_sha256", "result", "created_at"]
)
def test_regression_head_missing_required_field_is_refused(chain: Gate, field: str) -> None:
    chain.edit(REGRESSION, lambda record: record.pop(field))
    refused(chain, f"^evidence fields missing: {field}$")


@pytest.mark.parametrize("value", [[], [{"case_id": "X"}], None])
def test_regression_head_with_requirement_results_is_refused(chain: Gate, value: Any) -> None:
    chain.edit(REGRESSION, lambda record: record.__setitem__("requirement_results", value))
    refused(chain, "^regression requalification record binds a case to a requirement$")


@pytest.mark.parametrize("key", ["evidence_path", "raw_output_path"])
def test_regression_head_named_by_a_ledger_row_is_refused(chain: Gate, key: str) -> None:
    row = dict(chain.manifest["requirement_results"][0])
    row[key] = REGRESSION if key == "evidence_path" else raw_name(REGRESSION)
    row["case_id"] = "OCOR-DEV-0004-REGRESSION-ROW"
    chain.manifest["requirement_results"].append(row)
    chain.save()
    refused(chain, "^regression requalification record binds a case to a requirement$")


def test_regression_head_named_by_a_ledger_row_of_another_task_is_refused(chain: Gate) -> None:
    row = dict(chain.manifest["requirement_results"][0], task_id="OCOR-DEV-0005", evidence_path=REGRESSION)
    chain.manifest["requirement_results"].append(row)
    chain.save()
    refused(chain, "^regression requalification record binds a case to a requirement$")


def test_regression_head_with_non_list_ledger_is_refused(chain: Gate) -> None:
    chain.manifest["requirement_results"] = {"rows": []}
    chain.save()
    refused(chain, "^manifest requirement_results must be an array$")


@pytest.mark.parametrize("value", [True, "false", 0, None, "absent"])
def test_regression_head_qualifies_requirements_not_exactly_false_is_refused(chain: Gate, value: Any) -> None:
    def change(record: dict[str, Any]) -> None:
        if value == "absent":
            record.pop("qualifies_requirements")
        else:
            record["qualifies_requirements"] = value

    chain.edit(REGRESSION, change)
    refused(chain, "^regression requalification record: qualifies_requirements is not false$")


@pytest.mark.parametrize("commands", [[], {"label": "PASS"}, "PASS", [None], ["PASS"]])
def test_regression_head_malformed_or_empty_commands_are_refused(chain: Gate, commands: Any) -> None:
    chain.edit(REGRESSION, lambda record: record.__setitem__("commands", commands))
    refused(chain, "^regression requalification record has no well-formed executed command$")


@pytest.mark.parametrize("status", ["SKIPPED", "NOT_EXECUTED", "XFAIL", "UNAVAILABLE"])
def test_regression_head_non_qualifying_command_is_refused(chain: Gate, status: str) -> None:
    chain.edit(REGRESSION, lambda record: record["commands"][1].__setitem__("status", status))
    refused(chain, r"^non-qualifying result present: \['" + status + r"'\]$")


@pytest.mark.parametrize("status", ["FAIL", "", None, "pass "])
def test_regression_head_failing_command_is_refused(chain: Gate, status: Any) -> None:
    chain.edit(REGRESSION, lambda record: record["commands"][0].__setitem__("status", status))
    refused(chain, "^mandatory evidence is not all PASS$")


def test_regression_head_skipped_command_is_refused_without_non_skipped(chain: Gate) -> None:
    chain.edit(REGRESSION, lambda record: record["commands"][0].__setitem__("status", "SKIPPED"))
    refused(chain, "^mandatory evidence is not all PASS$", non_skipped=False)


@pytest.mark.parametrize("result", ["FAIL", "pass", None])
def test_regression_head_result_not_pass_is_refused(chain: Gate, result: Any) -> None:
    chain.edit(REGRESSION, lambda record: record.__setitem__("result", result))
    refused(chain, "^mandatory evidence is not all PASS$")


@pytest.mark.parametrize(
    ("field", "value"), [("task_id", "OCOR-DEV-0005"), ("commit", "c" * 39), ("commit", "C" * 40), ("commit", None)]
)
def test_regression_head_identifier_mismatch_is_refused(chain: Gate, field: str, value: Any) -> None:
    chain.edit(REGRESSION, lambda record: record.__setitem__(field, value))
    refused(chain, "^task or commit identifier mismatch$")


def test_regression_head_record_digest_mismatch_is_refused(chain: Gate) -> None:
    chain.manifest["artifacts"][0]["sha256"] = "0" * 64
    chain.save()
    refused(chain, "^evidence digest mismatch$")


def test_regression_head_raw_digest_mismatch_is_refused(chain: Gate) -> None:
    (chain.dir / raw_name(REGRESSION)).write_text("tampered\n", encoding="utf-8")
    refused(chain, "^raw evidence digest mismatch$")


def test_regression_head_record_raw_output_digest_mismatch_is_refused(chain: Gate) -> None:
    chain.edit(REGRESSION, lambda record: record.__setitem__("raw_output_sha256", "0" * 64))
    refused(chain, "^record raw-output digest mismatch$")


# --- regression head, negative: supersession -----------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        lambda record: record.pop("supersedes"),
        lambda record: record.__setitem__("supersedes", ""),
        lambda record: record.__setitem__("supersedes", ["OCOR-DEV-0004-requalified-q"]),
        lambda record: record.__setitem__("supersedes", "OCOR-DEV-0004-requalified-other"),
        lambda record: record.pop("previous_record"),
        lambda record: record.__setitem__("previous_record", "OCOR-DEV-0004-requalified-q"),
        lambda record: record["previous_record"].pop("record_id"),
    ],
    ids=["absent", "empty", "list", "other-id", "no-previous", "previous-not-object", "previous-without-id"],
)
def test_regression_head_without_matching_supersession_is_refused(chain: Gate, change: Callable[[dict[str, Any]], None]) -> None:
    chain.edit(REGRESSION, change)
    refused(chain, "^regression requalification record does not supersede a record$")


@pytest.mark.parametrize(
    "path",
    [
        None,
        "",
        "reports/evidence/G1/OCOR-DEV-0004.requalified-q.json",
        "reports/evidence/G0/../G0/OCOR-DEV-0004.requalified-q.json",
        "/reports/evidence/G0/OCOR-DEV-0004.requalified-q.json",
        "OCOR-DEV-0004.requalified-q.json",
        "reports/evidence/G0/OCOR-DEV-0004.requalified-q.log",
    ],
    ids=["none", "empty", "other-gate", "dot-dot", "absolute", "bare-name", "not-a-record"],
)
def test_superseded_record_outside_the_manifest_directory_is_refused(chain: Gate, path: Any) -> None:
    chain.edit(REGRESSION, lambda record: record["previous_record"].__setitem__("record_path", path))
    refused(chain, "^superseded record is not an evidence record of this manifest directory$")


def test_superseded_record_not_listed_in_the_manifest_is_refused(chain: Gate) -> None:
    chain.manifest["artifacts"] = [item for item in chain.manifest["artifacts"] if item["path"] != QUALIFYING]
    chain.save()
    refused(chain, f"^manifest has no evidence entry for superseded record {QUALIFYING}$")


def test_superseded_record_listed_for_another_task_is_refused(chain: Gate) -> None:
    for item in chain.manifest["artifacts"]:
        if item["path"] == QUALIFYING:
            item["task_id"] = "OCOR-DEV-0005"
    chain.save()
    refused(chain, f"^manifest has no evidence entry for superseded record {QUALIFYING}$")


def test_superseded_record_without_raw_artifact_is_refused(chain: Gate) -> None:
    chain.manifest["artifacts"] = [item for item in chain.manifest["artifacts"] if item["path"] != raw_name(QUALIFYING)]
    chain.save()
    refused(chain, f"^manifest has no raw evidence entry for superseded record {QUALIFYING}$")


def test_superseded_record_file_missing_is_refused(chain: Gate) -> None:
    (chain.dir / QUALIFYING).unlink()
    refused(chain, "^evidence record is missing$")


def test_superseded_record_artifact_digest_mismatch_is_refused(chain: Gate) -> None:
    for item in chain.manifest["artifacts"]:
        if item["path"] == QUALIFYING:
            item["sha256"] = "0" * 64
    chain.save()
    refused(chain, "^evidence digest mismatch$")


def test_superseded_record_declared_digest_mismatch_is_refused(chain: Gate) -> None:
    chain.edit(REGRESSION, lambda record: record["previous_record"].__setitem__("record_sha256", "0" * 64))
    refused(chain, "^superseded record digest mismatch$")


def test_superseded_record_with_another_record_id_is_refused(chain: Gate) -> None:
    chain.edit(QUALIFYING, lambda record: record.__setitem__("record_id", "OCOR-DEV-0004-requalified-other"))
    chain.edit(REGRESSION, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(chain.dir / QUALIFYING)))
    refused(chain, "^superseded record identifier mismatch$")


def test_superseded_record_of_another_task_is_refused(chain: Gate) -> None:
    chain.edit(QUALIFYING, lambda record: record.__setitem__("task_id", "OCOR-DEV-0005"))
    chain.edit(REGRESSION, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(chain.dir / QUALIFYING)))
    refused(chain, "^superseded record belongs to another task$")


def test_cyclic_supersedes_chain_is_refused(chain2: Gate) -> None:
    """r -> r1 -> r: the middle record is rewritten to supersede the head."""

    def point_back(record: dict[str, Any]) -> None:
        record["supersedes"] = REGRESSION_R1_ID
        record["previous_record"].update(
            record_id=REGRESSION_R1_ID,
            record_path="/".join((*GATE_DIR, REGRESSION_R1)),
            record_sha256=sha256(chain2.dir / REGRESSION_R1),
        )

    chain2.edit(REGRESSION, point_back)
    # the head's declared digest of the middle record is refreshed, so only the cycle remains
    chain2.edit(REGRESSION_R1, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(chain2.dir / REGRESSION)))
    refused(chain2, "^supersedes chain is cyclic$")


def test_self_superseding_regression_record_is_refused(chain: Gate) -> None:
    def point_to_itself(record: dict[str, Any]) -> None:
        record["supersedes"] = REGRESSION_ID
        record["previous_record"].update(record_id=REGRESSION_ID, record_path="/".join((*GATE_DIR, REGRESSION)))

    chain.edit(REGRESSION, point_to_itself)
    chain.edit(REGRESSION, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(chain.dir / REGRESSION)))
    refused(chain, "^supersedes chain is cyclic$")


# --- intermediate regression record and latest qualifying record ---------------------


def test_intermediate_regression_record_gets_the_regression_checks(chain2: Gate) -> None:
    chain2.edit(REGRESSION, lambda record: record.__setitem__("qualifies_requirements", True))
    chain2.edit(REGRESSION_R1, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(chain2.dir / REGRESSION)))
    refused(chain2, "^regression requalification record: qualifies_requirements is not false$")


def test_intermediate_regression_record_raw_digest_is_checked(chain2: Gate) -> None:
    (chain2.dir / raw_name(REGRESSION)).write_text("tampered\n", encoding="utf-8")
    refused(chain2, "^raw evidence digest mismatch$")


def test_latest_qualifying_record_without_requirement_results_is_refused(chain: Gate) -> None:
    chain.edit(QUALIFYING, lambda record: record.pop("requirement_results"))
    chain.edit(REGRESSION, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(chain.dir / QUALIFYING)))
    refused(chain, "^evidence fields missing: requirement_results$")


def test_latest_qualifying_record_ledger_cardinality_is_checked(chain: Gate) -> None:
    chain.manifest["requirement_results"].append(
        dict(chain.manifest["requirement_results"][0], case_id="OCOR-DEV-0004-EXTRA")
    )
    chain.save()
    refused(chain, "^requirement-result ledger cardinality mismatch$")


def test_latest_qualifying_record_ledger_paths_are_checked(chain: Gate) -> None:
    chain.manifest["requirement_results"][0]["raw_output_path"] = raw_name(REGRESSION_R1)
    chain.save()
    refused(chain, "^requirement-result ledger path mismatch$")


def test_latest_qualifying_record_raw_digest_is_checked(chain: Gate) -> None:
    (chain.dir / raw_name(QUALIFYING)).write_text("tampered\n", encoding="utf-8")
    refused(chain, "^raw evidence digest mismatch$")


def test_latest_qualifying_record_failing_case_is_refused(chain: Gate) -> None:
    chain.edit(QUALIFYING, lambda record: record["requirement_results"][0].__setitem__("status", "FAIL"))
    chain.edit(REGRESSION, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(chain.dir / QUALIFYING)))
    refused(chain, "^mandatory case is not PASS: OCOR-DEV-0004-REQUALIFIED-Q=FAIL$")


# --- the repository MANIFEST ---------------------------------------------------------


def test_repository_g0_manifest_validates_ocor_dev_0004() -> None:
    """The command of the required evidence job (.github/workflows/ocor-poc-ci.yml)."""
    run = subprocess.run(
        [sys.executable, "ocor-runtime/tools/evidence_manifest.py", "validate", "--task", TASK, "--non-skipped",
         "--manifest", "reports/evidence/G0/MANIFEST.json"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert (run.returncode, run.stdout) == (0, f"PASS: qualifying manifest and requirement ledger for {TASK}\n")


# --- repair cycle 2: VF-001 of OCOR-DEV-REM-0051-69bffc6b0f90-1 ----------------------
# The regression checklist, ``qualifies_requirements`` exactly ``false`` included, applies to
# the first artifact only. A later ``regression`` hop is followed through its supersession link
# (digests, identifier, same task, manifest directory, no cycle) even when, like the records
# sealed before REM-0046, it has no ``qualifies_requirements`` field; a value that is present and
# not ``false`` is still refused. The latest non-regression record receives every qualifying
# check unchanged.

LEGACY = "OCOR-DEV-0004.requalified-legacy.json"
LEGACY_ID = "OCOR-DEV-0004-requalified-legacy"


def legacy_shape(record: dict[str, Any]) -> None:
    """A regression record sealed before REM-0046: no qualifies_requirements, own cases."""
    record.pop("qualifies_requirements")
    record["requirement_results"] = [
        {
            "case_id": "OCOR-DEV-0004-REQUALIFIED-LEGACY",
            "command": "labels regression of the shared campaign, all PASS",
            "requirement_id": "BR-003",
            "result": {"failed": 0, "not_executed": 0, "passed": 13, "skipped": 0},
            "status": "PASS",
        }
    ]


@pytest.fixture
def legacy(tmp_path: Path) -> Gate:
    """head r1 (REM-0046 shape) -> legacy regression record -> latest qualifying record."""
    gate = Gate(tmp_path)
    add_qualifying(gate)
    add_regression(gate, LEGACY, LEGACY_ID, QUALIFYING, QUALIFYING_ID)
    gate.edit(LEGACY, legacy_shape)
    add_regression(gate, REGRESSION_R1, REGRESSION_R1_ID, LEGACY, LEGACY_ID)
    return gate


def relink(gate: Gate, head: str, superseded: str) -> None:
    gate.edit(head, lambda record: record["previous_record"].__setitem__("record_sha256", sha256(gate.dir / superseded)))


def test_legacy_regression_hop_without_the_field_is_followed_to_the_qualifying_record(legacy: Gate) -> None:
    assert "qualifies_requirements" not in legacy.record(LEGACY)
    assert legacy.validate() is True


@pytest.mark.parametrize(
    "change",
    [
        lambda record: record.pop("requirement_results"),
        lambda record: record["commands"].append({"command": "pytest -q", "status": "PASS"}),
        lambda record: record.__setitem__("requirement_results", []),
    ],
    ids=["field-only", "more-commands-than-cases", "empty-cases"],
)
def test_legacy_regression_hop_shapes_are_followed(legacy: Gate, change: Callable[[dict[str, Any]], None]) -> None:
    legacy.edit(LEGACY, change)
    relink(legacy, REGRESSION_R1, LEGACY)
    assert legacy.validate() is True


def test_legacy_regression_hop_named_by_the_ledger_reaches_the_unchanged_qualifying_checks(legacy: Gate) -> None:
    """The shape of the sealed OCOR-DEV-0005/0050/0082 chains: rows of older records stay in the ledger."""
    row = dict(
        legacy.manifest["requirement_results"][0],
        case_id="OCOR-DEV-0004-REQUALIFIED-LEGACY",
        evidence_path=LEGACY,
        raw_output_path=raw_name(LEGACY),
    )
    legacy.manifest["requirement_results"].append(row)
    legacy.save()
    refused(legacy, "^requirement-result ledger cardinality mismatch$")


@pytest.mark.parametrize("value", [True, "false", 0, None, []])
def test_legacy_regression_hop_with_a_present_non_false_field_is_refused(legacy: Gate, value: Any) -> None:
    legacy.edit(LEGACY, lambda record: record.__setitem__("qualifies_requirements", value))
    relink(legacy, REGRESSION_R1, LEGACY)
    refused(legacy, "^regression requalification record: qualifies_requirements is not false$")


def test_head_without_the_field_is_still_refused_when_the_hop_is_legacy(legacy: Gate) -> None:
    legacy.edit(REGRESSION_R1, lambda record: record.pop("qualifies_requirements"))
    refused(legacy, "^regression requalification record: qualifies_requirements is not false$")


def test_legacy_regression_hop_supersession_is_checked(legacy: Gate) -> None:
    legacy.edit(LEGACY, lambda record: record.__setitem__("supersedes", "OCOR-DEV-0004-requalified-other"))
    relink(legacy, REGRESSION_R1, LEGACY)
    refused(legacy, "^regression requalification record does not supersede a record$")


def test_legacy_regression_hop_declared_digest_is_checked(legacy: Gate) -> None:
    legacy.edit(LEGACY, lambda record: record["previous_record"].__setitem__("record_sha256", "0" * 64))
    relink(legacy, REGRESSION_R1, LEGACY)
    refused(legacy, "^superseded record digest mismatch$")


def test_legacy_regression_hop_directory_is_checked(legacy: Gate) -> None:
    legacy.edit(
        LEGACY,
        lambda record: record["previous_record"].__setitem__("record_path", "reports/evidence/G1/" + QUALIFYING),
    )
    relink(legacy, REGRESSION_R1, LEGACY)
    refused(legacy, "^superseded record is not an evidence record of this manifest directory$")


def test_legacy_regression_hop_raw_digest_is_checked(legacy: Gate) -> None:
    (legacy.dir / raw_name(LEGACY)).write_text("tampered\n", encoding="utf-8")
    refused(legacy, "^raw evidence digest mismatch$")


def test_legacy_regression_hop_of_another_task_is_refused(legacy: Gate) -> None:
    legacy.edit(LEGACY, lambda record: record.__setitem__("task_id", "OCOR-DEV-0005"))
    relink(legacy, REGRESSION_R1, LEGACY)
    refused(legacy, "^superseded record belongs to another task$")


def test_legacy_regression_hop_cycle_is_refused(legacy: Gate) -> None:
    def point_back(record: dict[str, Any]) -> None:
        record["supersedes"] = REGRESSION_R1_ID
        record["previous_record"].update(
            record_id=REGRESSION_R1_ID,
            record_path="/".join((*GATE_DIR, REGRESSION_R1)),
            record_sha256=sha256(legacy.dir / REGRESSION_R1),
        )

    legacy.edit(LEGACY, point_back)
    relink(legacy, REGRESSION_R1, LEGACY)
    refused(legacy, "^supersedes chain is cyclic$")


def test_latest_qualifying_record_after_a_legacy_hop_gets_the_qualifying_checks(legacy: Gate) -> None:
    legacy.edit(QUALIFYING, lambda record: record["commands"].append({"command": "pytest -q", "status": "PASS"}))
    relink(legacy, LEGACY, QUALIFYING)
    relink(legacy, REGRESSION_R1, LEGACY)
    refused(legacy, "^executed command/result cardinality mismatch$")


# --- the repository MANIFESTs: where the walk ends -----------------------------------


@pytest.mark.parametrize(
    ("gate", "task", "latest_non_regression"),
    [
        ("G0", "OCOR-DEV-0004", "OCOR-DEV-0004.requalified-rem0039.json"),
        ("G0", "OCOR-DEV-0005", "OCOR-DEV-0005.requalified-rem0039.json"),
        ("G5", "OCOR-DEV-0050", "OCOR-DEV-0050.requalified-rem0037.json"),
        ("G2", "OCOR-DEV-0082", "OCOR-DEV-0082.requalified-rem0039.json"),
    ],
)
def test_repository_walk_reaches_the_latest_non_regression_record(
    monkeypatch: pytest.MonkeyPatch, gate: str, task: str, latest_non_regression: str
) -> None:
    """The walk passes every regression hop and stops on the first non-regression record, where
    the unchanged qualifying checks run: OCOR-DEV-0004 passes on rem0039; the sealed multi-command
    records of OCOR-DEV-0005, 0050 and 0082 are refused there by the unchanged cardinality check."""
    import evidence_manifest

    visited: list[str] = []
    original = evidence_manifest._superseded

    def recording(*args: Any, **kwargs: Any) -> tuple[Path, Path, str, dict[str, Any]]:
        result = original(*args, **kwargs)
        visited.append(result[0].name)
        return result

    monkeypatch.setattr(evidence_manifest, "_superseded", recording)
    manifest = ROOT / "reports" / "evidence" / gate / "MANIFEST.json"
    try:
        outcome = str(validate_manifest(manifest, task_id=task, non_skipped=True))
    except ManifestError as exc:
        outcome = str(exc)
    directory = manifest.parent
    kinds = [json.loads((directory / name).read_text(encoding="utf-8")).get("requalification_kind") for name in visited]
    assert visited and visited[-1] == latest_non_regression
    assert kinds[:-1] == ["regression"] * (len(kinds) - 1) and kinds[-1] != "regression"
    expected = "True" if task == "OCOR-DEV-0004" else "executed command/result cardinality mismatch"
    assert outcome == expected
