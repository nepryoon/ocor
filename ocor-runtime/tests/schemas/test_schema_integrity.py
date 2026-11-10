"""Schema integrity and Anti-RV-01 regression checks of the legacy-slice schemas.

The schemas of ``ocor-runtime/schemas`` are artefacts of the legacy slice, not normative contracts:
the normative contracts are the six files materialised under
``ocor-runtime/docs/governance_dossier/contracts`` that LLD v1.1 §0.2 lists (docs/OCOR_LLD_v1.1.md:20-31),
whose integrity ``test_materialised_contract_integrity.py`` proves (NCP-U12-TEST-REALIGNMENT-SCOPE
(2026-11-10) option C1; the checks of this module are unchanged).
"""

from __future__ import annotations

import json
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas"
JSON_SCHEMA_FILES = tuple(sorted(SCHEMA_DIR.glob("*.schema.json")))


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _walk(value: Any, path: str = "$"):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}/{index}")


def _registry(schemas: list[dict[str, Any]]) -> Registry:
    resources = [
        (schema["$id"], Resource.from_contents(schema))
        for schema in schemas
    ]
    return Registry().with_resources(resources)


def test_all_normative_json_schemas_are_draft_2020_12_and_metaschema_valid():
    assert JSON_SCHEMA_FILES, "no legacy-slice JSON schemas found (non-normative; LLD v1.1 :20-31)"
    ids: set[str] = set()
    for path in JSON_SCHEMA_FILES:
        schema = _load(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] not in ids
        ids.add(schema["$id"])
        Draft202012Validator.check_schema(schema)


def test_anti_rv_01_required_fields_are_declared_locally_in_properties():
    """No conditional may rely on a required property declared elsewhere."""

    documents = [(path.name, _load(path)) for path in JSON_SCHEMA_FILES]
    openapi_path = SCHEMA_DIR / "ocor.openapi.yaml"
    documents.append(
        (openapi_path.name, yaml.safe_load(openapi_path.read_text(encoding="utf-8")))
    )
    for schema_name, schema in documents:
        for location, node in _walk(schema):
            if (
                not isinstance(node, dict)
                or "required" not in node
                or not isinstance(node["required"], list)
            ):
                continue
            required = set(node["required"])
            properties = set(node.get("properties", {}))
            assert required <= properties, (
                f"Anti-RV-01: {schema_name}{location} requires "
                f"{sorted(required - properties)} without local properties declarations"
            )


def test_conditional_keywords_are_structurally_explicit():
    for schema_path in JSON_SCHEMA_FILES:
        schema = _load(schema_path)
        for location, node in _walk(schema):
            if not isinstance(node, dict):
                continue
            if "if" in node:
                assert "then" in node, f"{schema_path.name}{location} has if without then"
                for keyword in ("if", "then"):
                    branch = node[keyword]
                    if isinstance(branch, dict) and branch.get("required"):
                        assert "properties" in branch
            if "allOf" in node:
                assert isinstance(node["allOf"], list) and node["allOf"]


def test_external_json_schema_references_resolve_and_validate_instances():
    schemas = [_load(path) for path in JSON_SCHEMA_FILES]
    by_name = {path.name: schema for path, schema in zip(JSON_SCHEMA_FILES, schemas)}
    registry = _registry(schemas)
    envelope = {
        "schemaVersion": "1.2",
        "kind": "Identity",
        "objectId": "identity-envelope-1",
        "payload": {
            "canonicalId": "urn:ocor:identity:alice",
            "aliases": ["alice@example.invalid"]
        },
        "markings": {"classification": "INTERNAL"}
    }
    validator = Draft202012Validator(
        by_name["semantic-envelope.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )
    assert not list(validator.iter_errors(envelope))


def test_normative_conditionals_reject_incomplete_instances():
    schemas = {path.name: _load(path) for path in JSON_SCHEMA_FILES}
    action_validator = Draft202012Validator(
        schemas["action.schema.json"], format_checker=FormatChecker()
    )
    assert list(
        action_validator.iter_errors(
            {"actionId": "a-1", "state": "READY", "version": 3}
        )
    )
    agent_validator = Draft202012Validator(schemas["agent-response.schema.json"])
    assert list(
        agent_validator.iter_errors(
            {
                "decision": "IDENTIFY",
                "identityId": None,
                "confidence": 0.99,
                "reason": "unsupported assertion",
            }
        )
    )


def test_openapi_31_document_and_references_are_well_formed():
    path = SCHEMA_DIR / "ocor.openapi.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert re.fullmatch(r"3\.1\.\d+", document["openapi"])
    assert document["jsonSchemaDialect"].endswith("draft/2020-12/schema")
    assert document["paths"]
    for _, node in _walk(document):
        if not isinstance(node, dict) or "$ref" not in node:
            continue
        reference = node["$ref"]
        if reference.startswith("#/"):
            target: Any = document
            for component in reference[2:].split("/"):
                target = target[component.replace("~1", "/").replace("~0", "~")]
            assert target is not None
        else:
            assert (SCHEMA_DIR / reference).is_file(), f"missing OpenAPI ref {reference}"

    if importlib.util.find_spec("openapi_spec_validator") is not None:
        from openapi_spec_validator import validate
        from openapi_spec_validator.readers import read_from_filename

        specification, base_uri = read_from_filename(str(path))
        validate(specification, base_uri=base_uri)


def test_proto3_contract_is_syntactically_compilable_when_protoc_is_available(tmp_path):
    proto = SCHEMA_DIR / "ocor_runtime.proto"
    text = proto.read_text(encoding="utf-8")
    assert text.startswith('syntax = "proto3";')
    assert "package ocor.runtime.v1;" in text
    assert all(
        service in text
        for service in (
            "service CompilerService",
            "service IdentityService",
            "service ActionService",
            "service EmissionService",
        )
    )
    protoc = shutil.which("protoc")
    grpc_tools_available = importlib.util.find_spec("grpc_tools") is not None
    if protoc is None and not grpc_tools_available:
        # The CI image need not ship protoc.  The assertions above plus balanced
        # declarations keep this test executable; release verification also runs
        # grpc_tools.protoc in an isolated tool environment.
        assert text.count("{") == text.count("}")
        assert len(re.findall(r"^message\s+\w+\s*\{", text, re.MULTILINE)) >= 10
        return
    if protoc is not None:
        subprocess.run(
            [
                protoc,
                f"--proto_path={SCHEMA_DIR}",
                f"--descriptor_set_out={tmp_path / 'ocor.pb'}",
                str(proto),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        import grpc_tools
        from grpc_tools import protoc as grpc_protoc

        include = Path(grpc_tools.__file__).resolve().parent / "_proto"
        result = grpc_protoc.main(
            [
                "grpc_tools.protoc",
                f"-I{SCHEMA_DIR}",
                f"-I{include}",
                f"--descriptor_set_out={tmp_path / 'ocor.pb'}",
                str(proto),
            ]
        )
        assert result == 0
    assert (tmp_path / "ocor.pb").stat().st_size > 0
