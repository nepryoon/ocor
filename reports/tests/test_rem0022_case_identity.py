"""Content-addressed parameter-case traceability, with fail-closed JUnit union."""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter

import pytest


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def junit_identity(node: str) -> tuple[str, str]:
    path, *parts = node.removeprefix("ocor-runtime/").split("::")
    if not path.endswith(".py") or not parts:
        raise ValueError("invalid collected node")
    return ".".join([path[:-3].replace("/", "."), *parts[:-1]]), parts[-1]


def case_index(nodes: list[str], junit: bytes) -> list[dict[str, str]]:
    cases = list(ET.fromstring(junit).iter("testcase"))
    expected = Counter(junit_identity(node) for node in nodes)
    actual = Counter((c.get("classname"), c.get("name")) for c in cases)
    if not nodes or len(set(nodes)) != len(nodes) or any(n != 1 for n in expected.values()):
        raise ValueError("missing or duplicated collected identity")
    if expected != actual:
        raise ValueError("collection/JUnit identity mismatch")
    if any(c.find(tag) is not None for c in cases for tag in ("failure", "error", "skipped")):
        raise ValueError("non-qualifying JUnit result")
    return [
        {
            "node_id_sha256": sha(node.encode()),
            "junit_identity_sha256": sha(json.dumps(junit_identity(node), separators=(",", ":")).encode()),
            "test": node.split("[", 1)[0],
            "junit_sha256": sha(junit),
        }
        for node in nodes
    ]


def verify_index(index: list[dict[str, str]], nodes: list[str], junit: bytes) -> None:
    if index != case_index(nodes, junit):
        raise ValueError("case index does not bind to exact raw JUnit and collection")


def fixture_xml(names: list[str], outcome: str = "") -> bytes:
    root = ET.Element("testsuite")
    for name in names:
        case = ET.SubElement(root, "testcase", classname="tests.tasks.test_example", name=name)
        if outcome:
            ET.SubElement(case, outcome)
    return ET.tostring(root)


NODES = ["ocor-runtime/tests/tasks/test_example.py::test_rule[left]", "ocor-runtime/tests/tasks/test_example.py::test_rule[right]"]


def test_parameter_cases_keep_distinct_hashes_and_one_base_name():
    raw = fixture_xml(["test_rule[left]", "test_rule[right]"])
    index = case_index(NODES, raw)
    assert len(index) == 2
    assert len({row["node_id_sha256"] for row in index}) == 2
    assert len({row["test"] for row in index}) == 1
    assert "[" not in json.dumps(index)
    verify_index(index, NODES, raw)


@pytest.mark.parametrize("names", [["test_rule[left]"], ["test_rule[left]", "test_rule[left]"], ["test_rule[left]", "test_rule[other]"], ["test_rule[left]", "test_rule[right]", "test_extra"]])
def test_missing_duplicate_substituted_and_extra_cases_are_rejected(names):
    with pytest.raises(ValueError, match="identity mismatch"):
        case_index(NODES, fixture_xml(names))


@pytest.mark.parametrize("outcome", ["failure", "error", "skipped"])
def test_nonqualifying_results_are_rejected(outcome):
    with pytest.raises(ValueError, match="non-qualifying"):
        case_index(NODES, fixture_xml(["test_rule[left]", "test_rule[right]"], outcome))


def test_tampered_mapping_or_raw_digest_is_rejected():
    raw = fixture_xml(["test_rule[left]", "test_rule[right]"])
    index = case_index(NODES, raw)
    index[0]["node_id_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="exact raw"):
        verify_index(index, NODES, raw)
    index = case_index(NODES, raw)
    with pytest.raises(ValueError, match="exact raw"):
        verify_index(index, NODES, raw + b"\n")


def test_duplicate_collection_and_malformed_node_are_rejected():
    with pytest.raises(ValueError, match="duplicated"):
        case_index([NODES[0], NODES[0]], fixture_xml(["test_rule[left]", "test_rule[left]"]))
    with pytest.raises(ValueError, match="invalid"):
        junit_identity("unqualified")
