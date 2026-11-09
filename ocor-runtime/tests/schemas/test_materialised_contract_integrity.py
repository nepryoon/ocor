"""Integrity of the contracts materialised by LLD v1.1 §0.2 (OCOR-DEV-REM-0060, NCP-U12, NCR-TESTS-003).

LLD v1.1 §0.2 (docs/OCOR_LLD_v1.1.md:20-31) names six contracts under
``ocor-runtime/docs/governance_dossier/contracts/``; their digests are fixed in the governed
approval manifest (``OCOR_IRB_ADD_LLD_AUTHORITY_SEAL_SHA256SUMS``) and "generation and fixtures start
exclusively from the manifested files" (:31). This module checks that set, not the legacy-slice
artefacts of ``ocor-runtime/schemas``: the table of §0.2 and the seal name the same six files, the bytes
match the sealed digests, the contract generator pins exactly those digests and refuses any other
source set, and every contract is well formed (JSON Schema 2020-12 meta-schema, OpenAPI 3.1, Proto3).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "ocor-runtime/docs/governance_dossier/contracts"
LLD = ROOT / "docs/OCOR_LLD_v1.1.md"
AUTHORITY_SEAL = ROOT / "ocor-runtime/docs/governance_dossier/OCOR_IRB_ADD_LLD_AUTHORITY_SEAL_SHA256SUMS"
GENERATOR = ROOT / "ocor-runtime/tools/generate_contracts.py"
CONTRACT_PREFIX = "ocor-runtime/docs/governance_dossier/contracts/"
MATERIALISED = (
    "capability-lease.schema.json",
    "governed-context.schema.json",
    "governed-memory-item.schema.json",
    "ocor-governed-memory.openapi.yaml",
    "ocor-named-query-gateway.openapi.yaml",
    "ocor_registry.proto",
)


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("ocor_generate_contracts_integrity", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lld_table() -> tuple[str, ...]:
    lines = LLD.read_text(encoding="utf-8").split("\n")
    start = lines.index("### 0.2 Artefatti contrattuali materializzati")
    end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("## "))
    section = "\n".join(lines[start:end])
    return tuple(sorted(re.findall(r"`" + re.escape(CONTRACT_PREFIX) + r"([^`]+)`", section)))


def _sealed() -> dict[str, str]:
    sealed: dict[str, str] = {}
    for line in AUTHORITY_SEAL.read_text(encoding="utf-8").splitlines():
        digest, separator, path = line.partition("  ")
        assert separator and re.fullmatch(r"[0-9a-f]{64}", digest), f"malformed seal line {line!r}"
        if path.startswith(CONTRACT_PREFIX):
            sealed[path[len(CONTRACT_PREFIX) :]] = digest
    return sealed


def test_lld_table_and_authority_seal_name_the_same_six_contracts():
    assert _lld_table() == MATERIALISED
    assert tuple(sorted(_sealed())) == MATERIALISED
    assert tuple(sorted(path.name for path in CONTRACTS.iterdir() if path.is_file())) == MATERIALISED


@pytest.mark.parametrize("name", MATERIALISED)
def test_contract_bytes_match_the_sealed_digest(name: str):
    assert hashlib.sha256((CONTRACTS / name).read_bytes()).hexdigest() == _sealed()[name]


def test_generator_pins_exactly_the_sealed_digests():
    assert _generator().PINNED_SOURCE_HASHES == _sealed()


def test_generator_validates_the_manifested_contracts():
    validated = _generator().validate_contracts(CONTRACTS)
    assert sorted(validated["json"]) == [name for name in MATERIALISED if name.endswith(".schema.json")]
    assert sorted(validated["openapi"]) == [name for name in MATERIALISED if name.endswith(".openapi.yaml")]
    assert [file.package for file in validated["proto"].file if file.name == "ocor_registry.proto"] == ["ocor.registry.v1"]


def _copy(tmp_path: Path) -> Path:
    source = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, source)
    return source


@pytest.mark.parametrize("name", MATERIALISED)
def test_generator_refuses_a_contract_that_differs_from_the_seal(tmp_path: Path, name: str):
    generator = _generator()
    source = _copy(tmp_path)
    (source / name).write_bytes((source / name).read_bytes() + b"\n")
    with pytest.raises(generator.ContractGenerationError, match="source digest mismatch for " + re.escape(name)):
        generator.validate_contracts(source)


def test_generator_refuses_a_source_set_with_an_unmanifested_or_missing_file(tmp_path: Path):
    generator = _generator()
    extra = _copy(tmp_path / "extra")
    (extra / "legacy.schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    with pytest.raises(generator.ContractGenerationError, match="inventory differs"):
        generator.validate_contracts(extra)
    missing = _copy(tmp_path / "missing")
    (missing / "ocor_registry.proto").unlink()
    with pytest.raises(generator.ContractGenerationError, match="inventory differs"):
        generator.validate_contracts(missing)


@pytest.mark.parametrize("name", [name for name in MATERIALISED if name.endswith(".schema.json")])
def test_json_schema_contracts_are_draft_2020_12_closed_and_uniquely_identified(name: str):
    schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    identifiers = [json.loads((CONTRACTS / other).read_text(encoding="utf-8"))["$id"] for other in MATERIALISED if other.endswith(".schema.json")]
    assert len(set(identifiers)) == len(identifiers)


@pytest.mark.parametrize("name", [name for name in MATERIALISED if name.endswith(".openapi.yaml")])
def test_openapi_contracts_are_3_1_with_resolvable_references(name: str):
    document = yaml.safe_load((CONTRACTS / name).read_text(encoding="utf-8"))
    assert re.fullmatch(r"3\.1\.\d+", document["openapi"])

    def walk(node: Any):
        if isinstance(node, dict):
            yield node
            for child in node.values():
                yield from walk(child)
        elif isinstance(node, list):
            for child in node:
                yield from walk(child)

    references = [node["$ref"] for node in walk(document) if isinstance(node.get("$ref"), str)]
    assert references
    for reference in references:
        target, _, pointer = reference.partition("#")
        base: Any = document
        if target:
            target = target.removeprefix("./")
            assert "/" not in target and target in MATERIALISED, f"{name} references the unmanifested file {target}"
            base = json.loads((CONTRACTS / target).read_text(encoding="utf-8")) if target.endswith(".json") else yaml.safe_load((CONTRACTS / target).read_text(encoding="utf-8"))
        for part in [segment for segment in pointer.split("/") if segment]:
            base = base[part.replace("~1", "/").replace("~0", "~")]
        assert base is not None
