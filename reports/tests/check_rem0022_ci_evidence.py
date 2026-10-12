"""Reconstruct candidate case identities, hashes, supersession and history."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT / "reports/tests"))
from test_rem0022_case_identity import verify_index  # noqa: E402

BASE = "355490ecd5fc28db999b1374c9adeddf95c64e23"
CONFIGS = [
    ("G2", "OCOR-DEV-REM-0022.ci-evidence-supersession"),
    ("G2", "OCOR-DEV-0019.requalified-rem0022-ci"),
    ("G4", "OCOR-DEV-0040.requalified-rem0022-ci"),
    ("G5", "OCOR-DEV-0050.requalified-rem0022-ci"),
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(ref: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", ref + ":" + path], cwd=ROOT)


records = []
for gate, name in CONFIGS:
    folder = ROOT / "reports/evidence" / gate
    record = json.loads((folder / (name + ".json")).read_text())
    records.append(record)
    raw = (folder / (name + ".log")).read_bytes()
    assert digest(raw) == record["raw_output_sha256"]
    entries = [json.loads(line) for line in raw.decode().splitlines()]
    labels = {entry["label"]: entry for entry in entries}
    assert len(labels) == len(entries)
    for entry in entries:
        assert digest(entry["output"].encode()) == entry["sha256"]
    for command in record["commands"]:
        assert command["exit_code"] == 0 and command["status"] == "PASS"
        assert command["head_sha"] == record["commit"]
        assert command["raw_sha256"] == labels[command["label"]]["sha256"]
        if "counts" in command:
            assert all(command["counts"][key] == 0 for key in ("failures", "errors", "skipped"))
    for path, value in record["inputs"].items():
        if path == "inputs_tree":
            assert value == subprocess.check_output(["git", "rev-parse", "HEAD:inputs"], cwd=ROOT, text=True).strip()
        else:
            assert value == digest((ROOT / path).read_bytes()) == digest(git_blob(record["commit"], path))
    nodes = json.loads(labels["artifact:collected.json"]["output"])
    full_xml = labels["artifact:full.xml"]["output"].encode()
    task_xml = labels["artifact:task.xml"]["output"].encode()
    index = record["case_identity_index"]
    verify_index(index["full"], nodes, full_xml)
    wanted = {row["node_id_sha256"] for row in index["task"]}
    task_nodes = [node for node in nodes if digest(node.encode()) in wanted]
    verify_index(index["task"], task_nodes, task_xml)
    full_map = {row["node_id_sha256"]: row for row in index["full"]}
    assert len(full_map) == len(nodes)
    for case in record["requirement_results"]:
        identities = case["test_case_sha256"]
        assert len(set(identities)) == len(identities) == case["result"]["passed"]
        assert all(value in full_map for value in identities)
        assert case["tests"] == list(dict.fromkeys(full_map[value]["test"].split("::")[-1] for value in identities))
        assert all(case["result"][key] == 0 for key in ("failed", "skipped", "not_executed"))
    superseded = record["superseded_record"]
    previous = git_blob(superseded["commit"], superseded["path"])
    assert digest(previous) == superseded["sha256"]
    assert json.loads(previous)["record_id"] == record["supersedes"]
    assert record["independent_verification"]["sealed"] is False
    assert record["claims"]["E1"] == record["claims"]["E2"] == record["claims"]["Verified"] == 0
    for prefix in ("task", "full"):
        assert labels["artifact:" + prefix + "-resources-before.json"]["output"] == labels["artifact:" + prefix + "-resources-after.json"]["output"]
    assert json.loads(labels["artifact:session-resource-union.json"]["output"])["status"] == "PASS"
    manifest = json.loads((folder / "MANIFEST.json").read_text())
    for task, suffix in ((record["task_id"], ".json"), (record["task_id"] + "-RAW", ".log")):
        entry = next(e for e in manifest["artifacts"] if e["task_id"] == task)
        assert entry["path"] == name + suffix and entry["sha256"] == digest((folder / (name + suffix)).read_bytes())
    for path in record["metadata_repair"]["source_equivalence_paths"]:
        assert (ROOT / path).read_bytes() == git_blob(record["metadata_repair"]["source_equivalence_commit"], path)
    assert digest((ROOT / ".github/workflows/ocor-supply-chain.yml").read_bytes()) == record["metadata_repair"]["scanner_sha256"]
# Every preexisting evidence artifact remains byte-identical to main.
for path in subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE, "reports/evidence"], cwd=ROOT, text=True).splitlines():
    if not path.endswith("/MANIFEST.json"):
        assert (ROOT / path).read_bytes() == git_blob(BASE, path), path
changed_tasks = {r["task_id"] for r in records} | {r["task_id"] + "-RAW" for r in records}
for gate in ("G2", "G4", "G5"):
    path = "reports/evidence/" + gate + "/MANIFEST.json"
    before = json.loads(git_blob(BASE, path))
    after = json.loads((ROOT / path).read_text())
    assert [e for e in before["artifacts"] if e["task_id"] not in changed_tasks] == [e for e in after["artifacts"] if e["task_id"] not in changed_tasks]
print(json.dumps({"status": "PASS", "records": len(records), "full_cases": len(nodes), "task_cases": len(task_nodes), "sealed_history_unchanged": True}, sort_keys=True))
