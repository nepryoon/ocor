"""C1 -- Canonical IR: the conforming OaC compiler and the IR Protobuf encoding.

Realises ADD v1.3 §3.1.1 normalisation (:433-440) and §3.1.2 CanonicalIRCore
(:441-464) of OCOR_ADD_v1.3_APPROVED_BASELINE.md, and the deterministic pipeline of
LLD v1.1 §2.1 (docs/OCOR_LLD_v1.1.md :107) up to the RFC 8785 digest:

1. imports resolved through the lock ``(resource_id, version, sha256)``; the lock
   enters ``release.lock_digest`` and so ``ir_digest`` (FR-041);
2. Unicode NFC, RFC 3339 UTC timestamps and canonical decimals (``oac``);
3. non-semantic collections ordered by ``(kind, stable_resource_id, version)`` and
   set-like arrays sorted and duplicate-free (LLD v1.1 :39);
4. type checking, constraint analysis and a single ``execution_owner``;
5. capability classification for every (capability, adapter role) pair;
6. fail-closed rejection of cycles, unresolved references, multiple owners and
   unapproved ``unsupported`` dispositions.

The IR Protobuf serialisation is a ``google.protobuf.Struct`` with the fields
``ir_digest`` and ``core``; it is semantically equivalent to the IR JSON and carries
the same ``ir_digest`` (ADD v1.3 :464). The wire encoding is written here with the
standard library, so the runtime gains no dependency.
"""

from __future__ import annotations

import re
import struct
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

import jsonschema

from ..kernel.canonical import canonical_bytes, canonical_digest
from .oac import (
    ARTIFACT_TARGETS,
    URN,
    YamlOacParser,
    meta_schema_diagnostics,
    normalise_default,
    parse_value_type,
)
from .ports import (
    SEMVER,
    C1Diagnostic,
    C1Error,
    CanonicalIrRelease,
    CompilerRequest,
    DiagnosticCode,
    OacParser,
)

IR_FORMAT = "ocor.cir/1.0"
CORE_KEYS = (
    "format", "release", "namespaces", "modules", "symbol_table", "types", "links", "constraints",
    "temporal_semantics", "derived_definitions", "named_contracts", "causal_manifests", "security_profiles",
    "capability_matrix", "artifact_plan",
)
RELEASE_KEYS = ("package_id", "semantic_version", "source_commit", "compiler_version", "lock_digest",
                "mapping_version")
ARTIFACT_MEDIA_TYPES: Mapping[str, str] = {
    "asyncapi": "application/vnd.aai.asyncapi+json;version=3.0.0",
    "json-schema": "application/schema+json",
    "mcp-descriptor": "application/vnd.ocor.mcp-descriptor+json",
    "openapi": "application/vnd.oai.openapi+json;version=3.1",
    "protobuf": "text/x-protobuf",
    "sdk-python": "text/x-python",
    "sdk-typescript": "application/typescript",
}
# Every member of an approved_exceptions pair is (semantic_capability_id, adapter_role).
CapabilityPair = tuple[str, str]
_DEFINITION_ID = {
    "TypeDefinition": "type_id",
    "LinkDefinition": "link_id",
    "ConstraintDefinition": "constraint_id",
    "DerivedDefinition": "derived_id",
    "ContractDefinition": "contract_id",
    "MarkingSchemeDefinition": "scheme_id",
    "SecurityProfileDefinition": "security_profile_id",
}
_REFERENCE_FAMILIES = {"structured": "type_ref", "enum": "type_ref", "object_reference": "type_ref",
                       "sensitive_reference": "security_profile_ref"}


def _diag(code: DiagnosticCode, path: str, message: str) -> C1Diagnostic:
    return C1Diagnostic(code, path, message[:500])


def _body(definition: Mapping[str, Any]) -> dict[str, Any]:
    """A definition without its ``construct`` discriminator (the IR collection names it)."""
    return {key: value for key, value in definition.items() if key != "construct"}


def _set(values: Iterable[str], path: str, diagnostics: list[C1Diagnostic]) -> list[str]:
    """Set-like array: sorted lexicographically and duplicate-free (LLD v1.1 :39)."""
    items = list(values)
    if len(items) != len(set(items)):
        diagnostics.append(_diag(DiagnosticCode.DUPLICATE_RESOURCE, path, "set-like array contains duplicates"))
    return sorted(set(items))


def _semver_key(version: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(version)
    if match is None:
        raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "semantic_version", "not a SemVer version"),))
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _walk_value_types(value_type: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield value_type
    for key in ("element", "value"):
        child = value_type.get(key)
        if isinstance(child, Mapping):
            yield from _walk_value_types(child)


def core_references(core: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every (path, symbol) reference of a CanonicalIRCore that must resolve in its symbol table."""
    refs: list[tuple[str, str]] = []

    def properties(owner: str, items: Sequence[Mapping[str, Any]]) -> None:
        for prop in items:
            base = f"{owner}/{prop['property_id']}"
            for value_type in _walk_value_types(prop["value_type"]):
                field = _REFERENCE_FAMILIES.get(str(value_type.get("family")))
                if field is not None:
                    refs.append((f"{base}/value_type", str(value_type[field])))
            refs.extend((f"{base}/constraint_refs", ref) for ref in prop.get("constraint_refs", ()))

    for module in core.get("modules", ()):
        refs.append((f"modules/{module['module_id']}/namespace_ref", module["namespace_ref"]))
        refs.extend((f"modules/{module['module_id']}/exports", ref) for ref in module.get("exports", ()))
    for type_ir in core.get("types", ()):
        base = f"types/{type_ir['type_id']}"
        refs.extend((f"{base}/interfaces", ref) for ref in type_ir.get("interfaces", ()))
        refs.extend((f"{base}/keys", ref) for ref in type_ir.get("keys", ()))
        refs.append((f"{base}/security_profile_ref", type_ir["security_profile_ref"]))
        properties(base, type_ir.get("properties", ()))
    for link in core.get("links", ()):
        base = f"links/{link['link_id']}"
        refs.extend((f"{base}/roles/{role['role']}", role["role_player_type_ref"]) for role in link["roles"])
        refs.append((f"{base}/security_profile_ref", link["security_profile_ref"]))
        properties(base, link.get("properties", ()))
    for constraint in core.get("constraints", ()):
        refs.append((f"constraints/{constraint['constraint_id']}/scope_ref", constraint["scope_ref"]))
    for derived in core.get("derived_definitions", ()):
        base = f"derived_definitions/{derived['derived_id']}"
        refs.append((f"{base}/result_type_ref", derived["result_type_ref"]))
        refs.extend((f"{base}/dependency_refs", ref) for ref in derived.get("dependency_refs", ()))
    for contract in core.get("named_contracts", ()):
        base = f"named_contracts/{contract['contract_id']}"
        for field in ("input_schema", "output_schema"):
            refs.extend((f"{base}/{field}", ref) for ref in schema_type_refs(contract[field]))
    for profile in core.get("security_profiles", ()):
        refs.append((f"security_profiles/{profile['security_profile_id']}/marking_scheme_ref",
                     profile["marking_scheme_ref"]))
    return refs


def schema_type_refs(schema: Any) -> list[str]:
    """``$ref`` values of an embedded contract schema (they name IR types)."""
    found: list[str] = []
    if isinstance(schema, Mapping):
        for key, value in schema.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(schema_type_refs(value))
    elif isinstance(schema, (list, tuple)):
        for value in schema:
            found.extend(schema_type_refs(value))
    return found


def used_capabilities(core: Mapping[str, Any]) -> set[str]:
    """The semantic capabilities the IR uses; each needs a disposition per adapter role."""
    used: set[str] = set()

    def from_properties(items: Sequence[Mapping[str, Any]]) -> None:
        for prop in items:
            for value_type in _walk_value_types(prop["value_type"]):
                used.add(f"value-family:{value_type['family']}")

    for type_ir in core.get("types", ()):
        from_properties(type_ir.get("properties", ()))
    for link in core.get("links", ()):
        from_properties(link.get("properties", ()))
        used.add("construct:link:n-ary" if len(link["roles"]) > 2 else "construct:link:binary")
    if core.get("constraints"):
        used.add("construct:constraint")
    if core.get("derived_definitions"):
        used.add("construct:derived")
    for temporal in core.get("temporal_semantics", ()):
        if temporal["mode"] != "ATEMPORAL":
            used.add("construct:temporal:" + temporal["mode"].lower().replace("_", "-"))
    return used


def _check_marking_scheme(scheme: Mapping[str, Any], path: str, diagnostics: list[C1Diagnostic]) -> None:
    """ADD v1.3 :429: a partial order with unique join and meet; five dual families."""
    levels = list(scheme["levels"])
    pairs = {(str(a), str(b)) for a, b in scheme["dominance_relation"]}
    problems: list[str] = []
    if len(levels) != len(set(levels)):
        problems.append("levels are duplicated")
    if any(a not in levels or b not in levels for a, b in pairs):
        problems.append("dominance_relation names an undeclared level")
    if scheme["top"] not in levels or scheme["bottom"] not in levels:
        problems.append("top and bottom must be declared levels")
    if any((level, level) not in pairs for level in levels):
        problems.append("dominance_relation is not reflexive")
    if any(a != b and (b, a) in pairs for a, b in pairs):
        problems.append("dominance_relation is not antisymmetric")
    if any((a, c) not in pairs for a, b in pairs for b2, c in pairs if b == b2):
        problems.append("dominance_relation is not transitive")
    if not problems:
        # (a, b) in pairs means a <= b (b dominates a).
        for a in levels:
            for b in levels:
                uppers = [u for u in levels if (a, u) in pairs and (b, u) in pairs]
                lowers = [w for w in levels if (w, a) in pairs and (w, b) in pairs]
                joins = [u for u in uppers if all((u, other) in pairs for other in uppers)]
                meets = [w for w in lowers if all((other, w) in pairs for other in lowers)]
                if len(joins) != 1 or len(meets) != 1:
                    problems.append(f"levels {a!r} and {b!r} have no unique join and meet")
    families = [family["family"] for family in scheme["family_definitions"]]
    if sorted(families) != sorted(set(families)) or len(set(families)) != 5:
        problems.append("the five mandatory marking families must each be declared once")
    for family in scheme["family_definitions"]:
        if family["join_operator"] == family["meet_operator"]:
            problems.append(f"family {family['family']!r}: meet_operator must be the dual of join_operator")
        if len(set(family["vocabulary"])) != len(family["vocabulary"]):
            problems.append(f"family {family['family']!r}: vocabulary contains duplicates")
        if not set(family["neutral_element"]) <= set(family["vocabulary"]):
            problems.append(f"family {family['family']!r}: neutral element is outside the vocabulary")
    diagnostics.extend(_diag(DiagnosticCode.CONSTRAINT_ERROR, path, problem) for problem in problems)


class OacCompiler:
    """CanonicalIrBuilder for the ADD v1.3 §3.1.1 OaC metamodel.

    ``approved_exceptions`` lists the (semantic_capability_id, adapter_role) pairs for
    which an ``unsupported`` disposition has an approved exception (ADD v1.3 :431).
    """

    def __init__(self, *, parser: OacParser | None = None,
                 approved_exceptions: Sequence[CapabilityPair] = ()) -> None:
        self._parser = parser or YamlOacParser()
        self._exceptions = frozenset((str(cap), str(role)) for cap, role in approved_exceptions)

    # -- ValidatePackage ---------------------------------------------------------------
    def validate(self, request: CompilerRequest) -> tuple[C1Diagnostic, ...]:
        """Every diagnostic of the request; empty when the package compiles."""
        try:
            self.build(request)
        except C1Error as error:
            return error.diagnostics
        return ()

    # -- Compile -------------------------------------------------------------------------
    def build(self, request: CompilerRequest) -> CanonicalIrRelease:
        core = self.compile_core(request)
        digest = canonical_digest(core)
        return CanonicalIrRelease.create(core=core, artifacts=(), signature_envelope_ref=f"urn:ocor:unsigned:{digest}")

    def compile_core(self, request: CompilerRequest) -> dict[str, Any]:
        documents = self._parse(request)
        package, namespaces, modules = self._documents(request, documents)
        lock = self._lock(request, package)
        diagnostics: list[C1Diagnostic] = []
        self._module_graph(modules, lock, diagnostics)
        definitions = [(path, index, definition)
                       for path, module in modules
                       for index, definition in enumerate(module["definitions"])]
        core = self._core(request, package, namespaces, modules, lock, definitions, diagnostics)
        if diagnostics:
            raise C1Error(tuple(sorted(set(diagnostics))))
        self._resolve(core)
        self._classify(core, package, definitions)
        return core

    # -- stages ---------------------------------------------------------------------------
    def _parse(self, request: CompilerRequest) -> list[tuple[str, Mapping[str, Any]]]:
        parsed: list[tuple[str, Mapping[str, Any]]] = []
        diagnostics: list[C1Diagnostic] = []
        for source in request.sources:
            try:
                document = self._parser.parse(source)
            except C1Error as error:
                diagnostics.extend(error.diagnostics)
                continue
            found = meta_schema_diagnostics(source.source_path, document)
            if found:
                diagnostics.extend(found)
                continue
            construct = document["construct"]
            identifier = document.get({"OntologyPackage": "package_id", "Namespace": "namespace_id",
                                       "Module": "module_id"}[construct])
            if identifier != source.resource_id:
                diagnostics.append(_diag(DiagnosticCode.SOURCE_INVALID, source.source_path,
                                         f"document id {identifier!r} differs from resource_id"))
            if construct in {"OntologyPackage", "Module"} and document["version"] != source.version:
                diagnostics.append(_diag(DiagnosticCode.SOURCE_INVALID, f"{source.source_path}/version",
                                         "document version differs from the source version"))
            parsed.append((source.source_path, document))
        if diagnostics:
            raise C1Error(tuple(sorted(set(diagnostics))))
        return parsed

    def _documents(
        self, request: CompilerRequest, documents: Sequence[tuple[str, Mapping[str, Any]]]
    ) -> tuple[Mapping[str, Any], list[tuple[str, Mapping[str, Any]]], list[tuple[str, Mapping[str, Any]]]]:
        packages = [doc for _, doc in documents if doc["construct"] == "OntologyPackage"]
        namespaces = [(path, doc) for path, doc in documents if doc["construct"] == "Namespace"]
        modules = [(path, doc) for path, doc in documents if doc["construct"] == "Module"]
        if len(packages) != 1:
            raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "sources",
                                 "exactly one OntologyPackage document is required"),))
        package = packages[0]
        problems: list[C1Diagnostic] = []
        if package["package_id"] != request.package_id:
            problems.append(_diag(DiagnosticCode.SOURCE_INVALID, "package_id", "package_id differs from the request"))
        if package["version"] != request.semantic_version:
            problems.append(_diag(DiagnosticCode.SOURCE_INVALID, "semantic_version",
                                  "package version differs from the request semantic_version"))
        if package["release_profile"] != request.release_profile:
            problems.append(_diag(DiagnosticCode.SOURCE_INVALID, "release_profile",
                                  "package release_profile differs from the request"))
        for field, docs, key in (("namespace_refs", namespaces, "namespace_id"), ("module_refs", modules, "module_id")):
            declared = list(package[field])
            present = [doc[key] for _, doc in docs]
            if len(present) != len(set(present)):
                problems.append(_diag(DiagnosticCode.DUPLICATE_RESOURCE, field, f"{key} is duplicated"))
            if sorted(set(declared)) != sorted(set(present)) or len(declared) != len(set(declared)):
                problems.append(_diag(DiagnosticCode.UNRESOLVED_REFERENCE, field,
                                      f"{field} must name exactly the {key} documents of the package"))
        if problems:
            raise C1Error(tuple(problems))
        return package, namespaces, modules

    def _lock(self, request: CompilerRequest, package: Mapping[str, Any]) -> list[dict[str, str]]:
        declared = sorted(({"resource_id": e["resource_id"], "sha256": e["sha256"], "version": e["version"]}
                           for e in package["dependency_lock"]), key=lambda e: (e["resource_id"], e["version"]))
        requested = sorted(({"resource_id": e.resource_id, "sha256": e.digest, "version": e.version}
                            for e in request.dependency_lock), key=lambda e: (e["resource_id"], e["version"]))
        if declared != requested:
            raise C1Error((_diag(DiagnosticCode.LOCK_INVALID, "dependency_lock",
                                 "package dependency_lock differs from the resolved lock"),))
        keys = [(e["resource_id"], e["version"]) for e in declared]
        if len(keys) != len(set(keys)) or len({e["resource_id"] for e in declared}) != len(declared):
            raise C1Error((_diag(DiagnosticCode.LOCK_INVALID, "dependency_lock",
                                 "each locked resource has exactly one version"),))
        return declared

    def _module_graph(self, modules: Sequence[tuple[str, Mapping[str, Any]]], lock: Sequence[Mapping[str, str]],
                      diagnostics: list[C1Diagnostic]) -> None:
        locked = {entry["resource_id"] for entry in lock}
        local = {doc["module_id"]: doc for _, doc in modules}
        for path, module in modules:
            for ref in module["imports"]:
                if ref not in locked and ref not in local:
                    diagnostics.append(_diag(DiagnosticCode.UNRESOLVED_REFERENCE, f"{path}/imports",
                                             f"import {ref!r} is neither locked nor a package module"))
        state: dict[str, int] = {}

        def visit(module_id: str, trail: tuple[str, ...]) -> None:
            if state.get(module_id) == 2:
                return
            if state.get(module_id) == 1:
                diagnostics.append(_diag(DiagnosticCode.CONSTRAINT_ERROR, "module_refs",
                                         "cyclic module import: " + " -> ".join((*trail, module_id))))
                return
            state[module_id] = 1
            for ref in sorted(local[module_id]["imports"]):
                if ref in local:
                    visit(ref, (*trail, module_id))
            state[module_id] = 2

        for module_id in sorted(local):
            visit(module_id, ())

    def _property(self, prop: Mapping[str, Any], path: str, diagnostics: list[C1Diagnostic]) -> dict[str, Any]:
        try:
            value_type = parse_value_type(prop["value_type_ref"], f"{path}/value_type_ref")
        except C1Error as error:
            diagnostics.extend(error.diagnostics)
            value_type = {"family": "primitive", "primitive": "string"}
        out: dict[str, Any] = {
            "property_id": prop["property_id"],
            "value_type": value_type,
            "cardinality": prop["cardinality"],
            "nullable": prop["nullable"],
            "constraint_refs": _set(prop["constraint_refs"], f"{path}/constraint_refs", diagnostics),
        }
        if value_type["family"] == "quantity" and "unit_ref" not in prop:
            diagnostics.append(_diag(DiagnosticCode.TYPE_ERROR, f"{path}/unit_ref", "a quantity requires unit_ref"))
        if "unit_ref" in prop and value_type["family"] != "quantity":
            diagnostics.append(_diag(DiagnosticCode.TYPE_ERROR, f"{path}/unit_ref", "unit_ref needs a quantity type"))
        for key in ("unit_ref", "marking_rule_ref", "temporal_annotation"):
            if key in prop:
                out[key] = prop[key]
        if "default" in prop:
            try:
                out["default"] = normalise_default(value_type, prop["default"], f"{path}/default")
            except C1Error as error:
                diagnostics.extend(error.diagnostics)
        return out

    def _properties(self, items: Sequence[Mapping[str, Any]], path: str,
                    diagnostics: list[C1Diagnostic]) -> list[dict[str, Any]]:
        built = [self._property(prop, f"{path}/properties/{index}", diagnostics) for index, prop in enumerate(items)]
        ids = [prop["property_id"] for prop in built]
        if len(ids) != len(set(ids)):
            diagnostics.append(_diag(DiagnosticCode.DUPLICATE_RESOURCE, f"{path}/properties", "property_id duplicated"))
        return sorted(built, key=lambda prop: str(prop["property_id"]))

    def _core(  # noqa: C901 - one linear pass over the construct table
        self,
        request: CompilerRequest,
        package: Mapping[str, Any],
        namespaces: Sequence[tuple[str, Mapping[str, Any]]],
        modules: Sequence[tuple[str, Mapping[str, Any]]],
        lock: Sequence[Mapping[str, str]],
        definitions: Sequence[tuple[str, int, Mapping[str, Any]]],
        diagnostics: list[C1Diagnostic],
    ) -> dict[str, Any]:
        locked = {entry["resource_id"]: entry for entry in lock}
        types: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        constraints: list[dict[str, Any]] = []
        derived: list[dict[str, Any]] = []
        contracts: list[dict[str, Any]] = []
        schemes: dict[str, dict[str, Any]] = {}
        profiles: list[dict[str, Any]] = []
        temporal: list[dict[str, Any]] = []
        symbols: list[dict[str, str]] = []
        owner_module: dict[str, str] = {}
        for path, index, definition in definitions:
            where = f"{path}/definitions/{index}"
            construct = definition["construct"]
            if construct == "CapabilityDisposition":
                continue
            identifier = definition[_DEFINITION_ID[construct]]
            module_id = next(doc["module_id"] for p, doc in modules if p == path)
            if identifier in owner_module:
                diagnostics.append(_diag(DiagnosticCode.DUPLICATE_RESOURCE, where, f"{identifier!r} is defined twice"))
                continue
            owner_module[identifier] = module_id
            symbols.append({"symbol_id": identifier, "kind": construct, "module_ref": module_id,
                            "version": str(definition.get("version", ""))})
            if construct == "TypeDefinition":
                item: dict[str, Any] = {
                    "type_id": identifier,
                    "kind": definition["kind"],
                    "version": definition["version"],
                    "properties": self._properties(definition["properties"], where, diagnostics),
                    "keys": _set(definition["keys"], f"{where}/keys", diagnostics),
                    "interfaces": _set(definition["interfaces"], f"{where}/interfaces", diagnostics),
                    "security_profile_ref": definition["security_profile_ref"],
                }
                for key in ("label", "lifecycle_ref"):
                    if key in definition:
                        item[key] = definition[key]
                if definition["kind"] == "ENUM":
                    if not definition.get("values"):
                        diagnostics.append(_diag(DiagnosticCode.TYPE_ERROR, f"{where}/values", "an ENUM needs values"))
                    item["values"] = _set(definition.get("values", ()), f"{where}/values", diagnostics)
                elif "values" in definition:
                    diagnostics.append(_diag(DiagnosticCode.TYPE_ERROR, f"{where}/values", "values only on an ENUM"))
                for key in item["keys"]:
                    if key not in {prop["property_id"] for prop in item["properties"]}:
                        diagnostics.append(_diag(DiagnosticCode.UNRESOLVED_REFERENCE, f"{where}/keys",
                                                 f"key {key!r} is not a property of the type"))
                for prop in item["properties"]:
                    symbols.append({"symbol_id": prop["property_id"], "kind": "PropertyDefinition",
                                    "module_ref": module_id, "version": definition["version"]})
                types.append(item)
                if "temporal_annotation" in definition:
                    temporal.append({"owner_ref": identifier, **definition["temporal_annotation"]})
            elif construct == "LinkDefinition":
                roles = [dict(role) for role in definition["roles"]]
                if len({role["role"] for role in roles}) != len(roles):
                    diagnostics.append(_diag(DiagnosticCode.DUPLICATE_RESOURCE, f"{where}/roles", "role names repeat"))
                link = {"link_id": identifier, "roles": roles,
                        "properties": self._properties(definition["properties"], where, diagnostics),
                        "security_profile_ref": definition["security_profile_ref"]}
                links.append(link)
                for prop in link["properties"]:
                    symbols.append({"symbol_id": prop["property_id"], "kind": "PropertyDefinition",
                                    "module_ref": module_id, "version": ""})
                if "temporal_annotation" in definition:
                    temporal.append({"owner_ref": identifier, **definition["temporal_annotation"]})
            elif construct == "ConstraintDefinition":
                constraints.append(_body(definition))
            elif construct == "DerivedDefinition":
                derived.append(_body(definition) | {"dependency_refs": _set(
                    definition["dependency_refs"], f"{where}/dependency_refs", diagnostics)})
            elif construct == "ContractDefinition":
                for field in ("input_schema", "output_schema"):
                    try:
                        jsonschema.Draft202012Validator.check_schema(definition[field])
                    except jsonschema.SchemaError as exc:
                        diagnostics.append(_diag(DiagnosticCode.SOURCE_INVALID, f"{where}/{field}", exc.message))
                contracts.append(_body(definition) | {"error_model": _set(
                    definition["error_model"], f"{where}/error_model", diagnostics),
                    "policy_refs": _set(definition["policy_refs"], f"{where}/policy_refs", diagnostics),
                    "approval_refs": _set(definition["approval_refs"], f"{where}/approval_refs", diagnostics)})
            elif construct == "MarkingSchemeDefinition":
                _check_marking_scheme(definition, where, diagnostics)
                scheme = _body(definition)
                scheme["family_definitions"] = sorted(definition["family_definitions"], key=lambda f: str(f["family"]))
                scheme["dominance_relation"] = sorted([list(pair) for pair in definition["dominance_relation"]])
                schemes[identifier] = scheme
            elif construct == "SecurityProfileDefinition":
                profiles.append(_body(definition))
        for profile in profiles:
            scheme_ir = schemes.get(profile["marking_scheme_ref"])
            if scheme_ir is not None:
                profile["marking_scheme"] = scheme_ir
                if profile["default_marking"] not in scheme_ir["levels"]:
                    diagnostics.append(_diag(DiagnosticCode.CONSTRAINT_ERROR,
                                             f"security_profiles/{profile['security_profile_id']}/default_marking",
                                             "default_marking is not a level of the marking scheme"))
        namespace_ir = sorted(({key: doc[key] for key in ("namespace_id", "uri", "prefix", "ownership_boundary",
                                                          "default_marking")} for _, doc in namespaces),
                              key=lambda ns: str(ns["namespace_id"]))
        module_ir = []
        for path, doc in modules:
            module_ir.append({
                "module_id": doc["module_id"], "version": doc["version"], "namespace_ref": doc["namespace_ref"],
                "imports": [{"resource_id": ref, "version": locked[ref]["version"], "sha256": locked[ref]["sha256"]}
                            if ref in locked else {"resource_id": ref}
                            for ref in _set(doc["imports"], f"{path}/imports", diagnostics)],
                "exports": _set(doc["exports"], f"{path}/exports", diagnostics),
                "definition_refs": sorted(i for i, m in owner_module.items() if m == doc["module_id"]),
                "owner": doc["owner"], "steward": doc["steward"], "reviewer": doc["reviewer"],
                "status": doc["status"], "review_date": doc["review_date"],
            })
            symbols.append({"symbol_id": doc["module_id"], "kind": "Module", "module_ref": doc["module_id"],
                            "version": doc["version"]})
        for ns in namespace_ir:
            symbols.append({"symbol_id": ns["namespace_id"], "kind": "Namespace", "module_ref": "", "version": ""})
        if not profiles:
            diagnostics.append(_diag(DiagnosticCode.SOURCE_INVALID, "security_profiles",
                                     "at least one SecurityProfileDefinition is required"))
        causal = [{"type_id": t["type_id"], "version": t["version"], "mechanism_digest": canonical_digest(t)}
                  for t in types if t["kind"] == "CAUSAL"]
        targets = _set(package["artifact_targets"], "package.artifact_targets", diagnostics)
        plan = [{"artifact_kind": target, "artifact_id": f"{request.package_id}:{target}",
                 "media_type": ARTIFACT_MEDIA_TYPES[target]} for target in targets if target in ARTIFACT_TARGETS]

        def by(key: str) -> Any:
            return lambda entry: (str(entry[key]), str(entry.get("version", "")))

        return {
            "format": IR_FORMAT,
            "release": {
                "package_id": request.package_id,
                "semantic_version": request.semantic_version,
                "source_commit": request.source_commit,
                "compiler_version": request.compiler_version,
                "lock_digest": canonical_digest(list(lock)),
                "mapping_version": request.mapping_version,
            },
            "namespaces": namespace_ir,
            "modules": sorted(module_ir, key=by("module_id")),
            "symbol_table": sorted(symbols, key=lambda s: (s["kind"], s["symbol_id"], s["version"])),
            "types": sorted(types, key=by("type_id")),
            "links": sorted(links, key=by("link_id")),
            "constraints": sorted(constraints, key=by("constraint_id")),
            "temporal_semantics": sorted(temporal, key=by("owner_ref")),
            "derived_definitions": sorted(derived, key=by("derived_id")),
            "named_contracts": sorted(contracts, key=by("contract_id")),
            "causal_manifests": sorted(causal, key=by("type_id")),
            "security_profiles": sorted(profiles, key=by("security_profile_id")),
            "capability_matrix": [],
            "artifact_plan": sorted(plan, key=by("artifact_kind")),
        }

    def _resolve(self, core: dict[str, Any]) -> None:
        symbols = {entry["symbol_id"] for entry in core["symbol_table"]}
        unresolved = sorted({(path, ref) for path, ref in core_references(core) if ref not in symbols})
        if unresolved:
            raise C1Error(tuple(_diag(DiagnosticCode.UNRESOLVED_REFERENCE, path,
                                      f"{ref!r} does not resolve in the symbol table") for path, ref in unresolved))
        derived_owners = [(d["derived_id"], d["execution_owner"]) for d in core["derived_definitions"]]
        constraint_owners = [(c["constraint_id"], c["execution_owner"]) for c in core["constraints"]]
        for identifier, owner in (*derived_owners, *constraint_owners):
            if not isinstance(owner, str) or re.fullmatch(URN, owner) is None:
                raise C1Error((_diag(DiagnosticCode.MULTIPLE_EXECUTION_OWNERS, identifier,
                                     "exactly one execution_owner is required"),))

    def _classify(self, core: dict[str, Any], package: Mapping[str, Any],
                  definitions: Sequence[tuple[str, int, Mapping[str, Any]]]) -> None:
        roles = sorted(set(package["adapter_roles"]))
        matrix: dict[CapabilityPair, dict[str, Any]] = {}
        diagnostics: list[C1Diagnostic] = []
        for path, index, definition in definitions:
            if definition["construct"] != "CapabilityDisposition":
                continue
            pair = (definition["semantic_capability_id"], definition["adapter_role"])
            where = f"{path}/definitions/{index}"
            if pair in matrix:
                diagnostics.append(_diag(DiagnosticCode.DUPLICATE_RESOURCE, where, f"disposition {pair} repeats"))
                continue
            if pair[1] not in roles:
                diagnostics.append(_diag(DiagnosticCode.SOURCE_INVALID, where,
                                         f"adapter role {pair[1]!r} is not declared by the package"))
                continue
            entry = {key: definition[key] for key in ("semantic_capability_id", "adapter_role", "disposition",
                                                      "limitation", "evidence_ref")}
            entry["approved_exception"] = definition["disposition"] == "unsupported" and pair in self._exceptions
            matrix[pair] = entry
        for capability in sorted(used_capabilities(core)):
            for role in roles:
                declared = matrix.get((capability, role))
                if declared is None:
                    diagnostics.append(_diag(DiagnosticCode.UNSUPPORTED_CAPABILITY, f"capability_matrix/{capability}",
                                             f"no disposition for adapter role {role!r}: unsupported"))
                elif declared["disposition"] == "unsupported" and not declared["approved_exception"]:
                    diagnostics.append(_diag(DiagnosticCode.UNSUPPORTED_CAPABILITY, f"capability_matrix/{capability}",
                                             f"unsupported on {role!r} without an approved exception"))
        if not matrix:
            diagnostics.append(_diag(DiagnosticCode.SOURCE_INVALID, "capability_matrix",
                                     "at least one CapabilityDisposition is required"))
        if diagnostics:
            raise C1Error(tuple(sorted(set(diagnostics))))
        core["capability_matrix"] = [matrix[pair] for pair in sorted(matrix)]


def is_nfc(value: Any) -> bool:
    """True when every string (keys included) of a JSON value is in Unicode NFC."""
    if isinstance(value, str):
        return unicodedata.is_normalized("NFC", value)
    if isinstance(value, Mapping):
        return all(is_nfc(key) and is_nfc(child) for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return all(is_nfc(child) for child in value)
    return True


# --------------------------------------------------------------------------------------
# google.protobuf.Struct wire encoding (struct.proto: Struct{map<string,Value> fields=1};
# Value{null_value=1, number_value=2, string_value=3, bool_value=4, struct_value=5,
# list_value=6}; ListValue{repeated Value values=1}). Map entries are written sorted by
# key, so the encoding of a release is deterministic.
# --------------------------------------------------------------------------------------


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(number: int, wire: int, payload: bytes) -> bytes:
    key = _varint((number << 3) | wire)
    if wire == 2:
        return key + _varint(len(payload)) + payload
    return key + payload


def _encode_value(value: Any) -> bytes:
    if value is None:
        return _field(1, 0, _varint(0))
    if isinstance(value, bool):
        return _field(4, 0, _varint(int(value)))
    if isinstance(value, int):
        if abs(value) > 2**53:
            raise C1Error((_diag(DiagnosticCode.TYPE_ERROR, "$", "integer exceeds the exact double range"),))
        return _field(2, 1, struct.pack("<d", float(value)))
    if isinstance(value, float):
        return _field(2, 1, struct.pack("<d", value))
    if isinstance(value, str):
        return _field(3, 2, value.encode("utf-8"))
    if isinstance(value, Mapping):
        return _field(5, 2, _encode_struct(value))
    if isinstance(value, (list, tuple)):
        return _field(6, 2, b"".join(_field(1, 2, _encode_value(item)) for item in value))
    raise C1Error((_diag(DiagnosticCode.TYPE_ERROR, "$", f"value {type(value).__name__} has no Struct form"),))


def _encode_struct(mapping: Mapping[str, Any]) -> bytes:
    out = bytearray()
    for key in sorted(mapping):
        entry = _field(1, 2, str(key).encode("utf-8")) + _field(2, 2, _encode_value(mapping[key]))
        out += _field(1, 2, entry)
    return bytes(out)


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if offset >= len(data) or shift > 63:
            raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", "truncated varint"),))
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7


def _fields(data: bytes) -> Iterator[tuple[int, int, Any]]:
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, offset = _read_varint(data, offset)
            yield number, wire, value
        elif wire == 1:
            if offset + 8 > len(data):
                raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", "truncated fixed64"),))
            yield number, wire, data[offset : offset + 8]
            offset += 8
        elif wire == 2:
            length, offset = _read_varint(data, offset)
            if offset + length > len(data):
                raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", "truncated length-delimited"),))
            yield number, wire, data[offset : offset + length]
            offset += length
        else:
            raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", f"unsupported wire type {wire}"),))


def _decode_value(data: bytes) -> Any:
    result: Any = None
    for number, wire, payload in _fields(data):
        if number == 1 and wire == 0:
            result = None
        elif number == 2 and wire == 1:
            number_value = struct.unpack("<d", payload)[0]
            result = int(number_value) if float(number_value).is_integer() else number_value
        elif number == 3 and wire == 2:
            result = payload.decode("utf-8")
        elif number == 4 and wire == 0:
            result = bool(payload)
        elif number == 5 and wire == 2:
            result = _decode_struct(payload)
        elif number == 6 and wire == 2:
            result = [_decode_value(item) for n, w, item in _fields(payload) if n == 1 and w == 2]
        else:
            raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", f"unexpected Value field {number}"),))
    return result


def _decode_struct(data: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for number, wire, entry in _fields(data):
        if number != 1 or wire != 2:
            raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", "unexpected Struct field"),))
        key: str | None = None
        value: Any = None
        for n, w, payload in _fields(entry):
            if n == 1 and w == 2:
                key = payload.decode("utf-8")
            elif n == 2 and w == 2:
                value = _decode_value(payload)
        if key is None or key in out:
            raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", "missing or duplicate Struct key"),))
        out[key] = value
    return out


def encode_protobuf(release: CanonicalIrRelease) -> bytes:
    """IR Protobuf form: Struct{ir_digest, core}; same ir_digest as the IR JSON (ADD v1.3 :464)."""
    core = parse_core(release.canonical_bytes)
    return _encode_struct({"core": core, "ir_digest": release.ir_digest})


def decode_protobuf(data: bytes) -> tuple[str, dict[str, Any]]:
    """Decode the IR Protobuf form; fail closed when the carried digest does not bind the core."""
    envelope = _decode_struct(bytes(data))
    digest, core = envelope.get("ir_digest"), envelope.get("core")
    if set(envelope) != {"core", "ir_digest"} or not isinstance(digest, str) or not isinstance(core, dict):
        raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "protobuf", "not an IR Protobuf envelope"),))
    if canonical_digest(core) != digest:
        raise C1Error((_diag(DiagnosticCode.SIGNATURE_INVALID, "protobuf", "ir_digest does not bind the core"),))
    return digest, core


def parse_core(data: bytes) -> dict[str, Any]:
    from ..kernel.canonical import parse_i_json

    try:
        core = parse_i_json(data)
    except ValueError as exc:
        raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "core", "IR bytes are not I-JSON"),)) from exc
    if not isinstance(core, dict) or canonical_bytes(core) != bytes(data):
        raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "core", "IR bytes are not RFC 8785 canonical"),))
    return core


def semver_major(version: str) -> int:
    return _semver_key(version)[0]


def semver_precedence(version: str) -> tuple[Any, ...]:
    """SemVer 2.0.0 precedence key (build metadata ignored, pre-release below release)."""
    match = SEMVER.fullmatch(version)
    if match is None:
        raise C1Error((_diag(DiagnosticCode.SOURCE_INVALID, "semantic_version", "not a SemVer version"),))
    pre = match.group(4)
    pre_key: tuple[Any, ...] = (1,) if pre is None else (0, *(
        (0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre.split(".")))
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), pre_key)
