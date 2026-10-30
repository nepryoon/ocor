#!/usr/bin/env python3
"""Generate the OCOR implementation planning package without touching runtime code."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = ROOT / "docs/development_plan"
REPORT_DIR = ROOT / "reports/planning"
BASE_COMMIT = "67cda4b44a8d27b831eb461b1e28d71e1d3398ab"
INPUTS_TREE = "60a73de8e47b38e94aeb0e2b8dedc689fab6eb35"
RUN_ID = "OCOR-PLAN-20260901T195716Z"

MEMORY_KINDS = [
    "WORKING", "EPISODIC", "SEMANTIC", "PROCEDURAL", "PREFERENCE",
    "REFLECTION", "DISSENT", "TEAM_SHARED",
]
MEMORY_SCOPES = ["RUN", "TASK", "AGENT", "TEAM", "PROJECT", "DOMAIN", "FEDERATED"]
MEMORY_LIFECYCLE = [
    "admission", "immutable_versioning", "provenance", "marking_taint",
    "cross_run_persistence", "structured_retrieval", "full_text_retrieval",
    "vector_retrieval", "hybrid_retrieval", "embedding_versioning",
    "consolidation", "reflection", "dissent", "correction", "supersession",
    "revocation", "expiry", "retention", "forgetting", "legal_hold",
    "deletion_saga_tombstones", "restore_without_resurrection",
    "non_interference", "context_assembly_receipts", "promotion_via_C6_C3",
]

WORKSTREAMS = {
    "WS-00": "Delivery foundation",
    "WS-01": "Canonical contracts and shared kernel",
    "WS-02": "C1 Ontology Compiler and IR Pipeline",
    "WS-03": "C2 Ontology and Query Gateway",
    "WS-04": "C3 Versioned Asserted State",
    "WS-05": "C4 Projection Adapters",
    "WS-06": "C5 Event Backbone",
    "WS-07": "C6 Governed Action Engine",
    "WS-08": "C7 Causal Runtime",
    "WS-09": "C8 Governed Agent Kernel",
    "WS-10": "Full Governed Agent Memory",
    "WS-11": "Security and governance integration",
    "WS-12": "Deployment, operations and recovery",
    "WS-13": "Verification and evidence",
}

WORKSTREAM_REFERENCES = {
    "WS-00": ("IRB BR-003/NFR-074", "ADD v1.3 Part I §§6.3, 7", "LLD v1.1 §§5, 7"),
    "WS-01": ("IRB cross-cutting P0/PoC rows", "ADD v1.3 Part I §3.0", "LLD v1.1 §1"),
    "WS-02": ("IRB C1-allocated rows", "ADD v1.3 Part I §§3.1, 7", "LLD v1.1 §2.1"),
    "WS-03": ("IRB C2-allocated rows", "ADD v1.3 Part I §§3.3, 7", "LLD v1.1 §2.2"),
    "WS-04": ("IRB C3-allocated rows", "ADD v1.3 Part I §§2.3, 3.6", "LLD v1.1 §§1.5, 2.3"),
    "WS-05": ("IRB C4-allocated rows", "ADD v1.3 Part I §§2.2, 6.2", "LLD v1.1 §2.4"),
    "WS-06": ("IRB C5-allocated rows", "ADD v1.3 Part I §§3.8, 6.2", "LLD v1.1 §2.5"),
    "WS-07": ("IRB C6-allocated rows", "ADD v1.3 Part I §§4.1, 5.4–5.5", "LLD v1.1 §§2.6, 3, 4"),
    "WS-08": ("IRB C7-allocated rows", "ADD v1.3 Part I §4.2", "LLD v1.1 §2.7"),
    "WS-09": ("IRB C8-allocated rows", "ADD v1.3 Part I §4.3", "LLD v1.1 §2.8"),
    "WS-10": ("IRB FR-118/FR-119 and ELM-084 allocations", "ADD v1.3 Part II §§2.3–2.13", "LLD v1.1 §§2.8.1–2.8.8, 7.2"),
    "WS-11": ("IRB security/authority/marking rows", "ADD v1.3 Part I §5 and Part II §2.12", "LLD v1.1 §4"),
    "WS-12": ("IRB deployment/operations rows", "ADD v1.3 Part I §6 and Part II §2.13", "LLD v1.1 §5"),
    "WS-13": ("IRB acceptance/verification rows", "ADD v1.3 Part I §7 and Part II §3", "LLD v1.1 §7"),
}

GATES = {
    "G0": {
        "name": "Baseline and protection",
        "entry": "DEC-209 authority and clean origin/main are verified.",
        "exit": "Deterministic environment, branch protection contract, task ledger and baseline results exist.",
        "services": ["GitHub Actions"],
        "evidence": "reports/evidence/G0/MANIFEST.json",
        "rollback": "Revert planning/bootstrap commits; no data migration exists.",
        "failure": "Freeze implementation task dispatch and repair baseline reproducibility.",
        "authority": "Delivery Coordinator plus Configuration Manager",
        "prohibited": "No runtime-conformance, E1, PoC-GO or Production claim.",
    },
    "G1": {
        "name": "Shared delivery and contract foundation",
        "entry": "G0 is green and approved contracts are hash-pinned.",
        "exit": "Canonical types, GCS, leases, errors, evidence envelopes, generated-boundary rules and contract tests are green.",
        "services": ["local schema validators", "protoc"],
        "evidence": "reports/evidence/G1/MANIFEST.json",
        "rollback": "Revert contract implementation while retaining compatibility adapters and stored-version readers.",
        "failure": "Block component work; resolve contract drift through governed decision if semantics differ.",
        "authority": "Contract Authority and Integration Agent",
        "prohibited": "No backend selection or runtime verification from schema validation.",
    },
    "G2": {
        "name": "Risk retirement",
        "entry": "G1 contracts are fixed and disposable environments are available.",
        "exit": "All critical spikes have reproducible evidence and an explicit retain/harden/discard disposition.",
        "services": ["PostgreSQL", "TypeDB", "Jena", "Kafka/Strimzi", "OPA", "Keycloak", "SPIFFE/SPIRE", "OpenBao"],
        "evidence": "reports/evidence/G2/MANIFEST.json",
        "rollback": "Destroy disposable spike environments; retain only manifests and decision inputs.",
        "failure": "Create a blocking governance decision; do not silently substitute technology.",
        "authority": "Architecture Review Authority for architecture-affecting outcomes",
        "prohibited": "Spike success is not final implementation evidence or PoC conformance.",
    },
    "G3": {
        "name": "First governed vertical slice",
        "entry": "Relevant G2 risks are resolved and qualifying services are pinned.",
        "exit": "One synthetic thread traverses real C1-C8 boundaries with fail-closed controls and reproducible receipts.",
        "services": ["PostgreSQL", "TypeDB", "Jena", "Kafka", "OPA/Keycloak"],
        "evidence": "reports/evidence/G3/MANIFEST.json",
        "rollback": "Revert the slice release and restore the pre-slice schema snapshot.",
        "failure": "Return failing boundary to its owning workstream; no partial mission-thread claim.",
        "authority": "Integration Agent and Independent Conformance Reviewer",
        "prohibited": "No E1 or PoC-GO; a thin slice does not cover the 285-requirement universe.",
    },
    "G4": {
        "name": "Progressive C1-C8 expansion",
        "entry": "G3 thread is repeatable and compatibility boundaries are explicit.",
        "exit": "C1-C8 responsibilities, the 44-transition FSM and security/operations integrations meet task-level oracles.",
        "services": ["all selected PoC services"],
        "evidence": "reports/evidence/G4/MANIFEST.json",
        "rollback": "Rollback per component release and replay from the last compatible canonical checkpoint.",
        "failure": "Quarantine the component increment; keep prior compatible slice active.",
        "authority": "Delivery Coordinator after independent task review",
        "prohibited": "No global Verified state before qualifying campaigns.",
    },
    "G5": {
        "name": "Full Governed Agent Memory",
        "entry": "C3, C4, C6, C8 and security controls required by memory are green.",
        "exit": "All kinds, scopes and lifecycle semantics are implemented; preparatory tests are green.",
        "services": ["PostgreSQL", "object store", "full-text index", "vector index", "OPA/Keycloak"],
        "evidence": "reports/evidence/G5/MANIFEST.json",
        "rollback": "Disable new memory admissions, preserve immutable versions/tombstones and restore prior readers.",
        "failure": "Full-memory runtime remains NO-GO; no kind or scope may be deferred.",
        "authority": "Governed Memory Lead plus Security Reviewer",
        "prohibited": "No full-memory claim until FGM-01–FGM-20 qualify at G6.",
    },
    "G6": {
        "name": "Runtime conformance campaign",
        "entry": "G4 and G5 are green; environments and fixtures are content-addressed.",
        "exit": "BA-01–BA-08, FGM-01–FGM-20, 44 FSM transitions and mission thread all have qualifying non-skipped results.",
        "services": ["complete selected-component PoC stack"],
        "evidence": "reports/evidence/G6/MANIFEST.json",
        "rollback": "Invalidate the campaign manifest and preserve raw results for diagnosis.",
        "failure": "Any failed/unavailable mandatory case keeps PoC runtime NO-GO.",
        "authority": "Independent Conformance Reviewer",
        "prohibited": "No skipped/mock result counts as PASS; no Production readiness claim.",
    },
    "G7": {
        "name": "PoC-GO decision package",
        "entry": "G6 qualifying evidence is complete and traceable to all P0/PoC requirements.",
        "exit": "A governed decision package states results, limitations, residual risks and exact evidence scope.",
        "services": ["GitHub protected CI", "evidence archive"],
        "evidence": "reports/evidence/G7/MANIFEST.json",
        "rollback": "Withdraw the candidate decision package; do not rewrite evidence or decisions.",
        "failure": "Remain PoC NO-GO and issue scoped remediation tasks.",
        "authority": "Product Owner and Architecture Review Authority under recorded governance",
        "prohibited": "PoC-GO cannot imply Production readiness, E2, scale, HA or multi-region qualification.",
    },
}

GATE_TESTS = {
    "G0": ["immutable-path guard", "clean-environment reproducibility", "mandatory-red CI probe", "manifest self-test"],
    "G1": ["JSON Schema positive/negative branches", "OpenAPI 3.1 validation", "Proto3 compilation", "cross-language canonical-byte vectors", "generated SDK drift"],
    "G2": ["each spike's real-service positive, negative and fault oracle", "clean rerun reproducibility", "retain/harden/discard disposition validation"],
    "G3": ["real C1-C8 thin mission thread", "control-plane outage", "stale GCS/lease/decision", "correlation and evidence-chain checks"],
    "G4": ["component unit/property/contract tests", "real-service integration", "44-transition implementation equality", "fault and compatibility migration"],
    "G5": ["all kind/scope admission cases", "retrieval and non-interference", "lifecycle/deletion/restore", "context replay and C6/C3 promotion"],
    "G6": ["BA-01–BA-08", "FGM-01–FGM-20", "44 transition positive/negative/effect cases", "security faults", "full mission thread", "backup/restore/air-gap"],
    "G7": ["285-row evidence validation", "independent reproduction sample", "manifest and decision-package integrity"],
}

# id suffix, title, workstream, gate, dependencies, exclusive file ownership,
# observable positive oracle, observable negative oracle, duration days
TASK_SPECS = [
    (1, "Protect repository and establish immutable task ledger", "WS-00", "G0", [], ".github/CODEOWNERS", "Protected-path and task-ledger checks reject direct edits to inputs and approved baselines.", "A fixture modifying inputs/ exits non-zero before tests execute.", 2),
    (2, "Pin deterministic Python and service toolchains", "WS-00", "G0", [1], "ocor-runtime/devcontainer.json", "Two clean environments resolve identical lock and image digests.", "An unpinned dependency or mutable image tag fails the reproducibility check.", 3),
    (3, "Create layered CI and mandatory-gate topology", "WS-00", "G0", [1, 2], ".github/workflows/ocor-poc-ci.yml", "PR checks expose separate contract, unit, integration, backend, FGM and evidence statuses and mandatory red blocks integration.", "A deliberately failing mandatory test prevents integration and cannot be reported as skipped PASS.", 4),
    (4, "Create evidence manifest and requirement-result ledger", "WS-13", "G0", [1], "ocor-runtime/tools/evidence_manifest.py", "Manifest records commit, environment, command, inputs, raw hashes and result status for every case.", "Missing raw output, hash or command makes manifest validation fail.", 3),
    (5, "Establish static, secret, dependency and SBOM gates", "WS-00", "G0", [2], ".github/workflows/ocor-supply-chain.yml", "Pinned scanners emit SBOM and machine-readable findings with blocking severities.", "Seeded secret and disallowed license fixtures are rejected.", 3),
    (6, "Create reproducible local integration environment", "WS-12", "G0", [2], "deploy/local/compose.yaml", "One command starts version-pinned PoC dependencies and health probes identify each service digest.", "A missing, unhealthy or public-network-dependent service fails readiness.", 5),
    (7, "Implement canonical identifiers, bytes, digest and time kernel", "WS-01", "G1", [3, 4], "ocor-runtime/src/ocor_runtime/kernel/canonical.py", "RFC 8785 vectors, UTC boundaries, correlation and causation identifiers produce stable bytes and digests.", "Duplicate keys, non-I-JSON values, naive time and malformed IDs are rejected.", 4),
    (8, "Implement exact Governed Context Set", "WS-01", "G1", [7], "ocor-runtime/src/ocor_runtime/kernel/governed_context.py", "Closed 11-field GCS round-trips identically across JSON, OpenAPI and Proto boundaries.", "Missing, extra or stale context fields fail before persistence or dispatch.", 4),
    (9, "Implement leases, Authority, evidence, provenance and error taxonomy", "WS-01", "G1", [7, 8], "ocor-runtime/src/ocor_runtime/kernel/governance.py", "Authority, CapabilityLease, evidence/provenance and typed errors preserve scope, TTL, purpose and causal bindings.", "Expired, widened, unsigned or unbound authority fails closed with stable reason codes.", 5),
    (10, "Materialize contract-first SDK boundaries and drift checks", "WS-01", "G1", [8, 9], "ocor-runtime/tools/generate_contracts.py", "Pinned generators reproduce SDK hashes from approved OpenAPI, Proto3 and JSON Schemas.", "Generated drift, backend identifiers or open records fail CI.", 4),
    (11, "Define C1 source DSL and canonical IR ports", "WS-02", "G1", [7, 10], "ocor-runtime/src/ocor_runtime/c1/ports.py", "Parser/compiler ports expose exact typed inputs, immutable release outputs and deterministic errors.", "Unknown syntax, unresolved reference and non-deterministic generation are rejected.", 3),
    (12, "Define C2 named-query and consistency ports", "WS-03", "G1", [8, 10], "ocor-runtime/src/ocor_runtime/c2/ports.py", "Named-query ports bind identity, purpose, policy, commit requirement and watermarks.", "Arbitrary query text, missing purpose or silent consistency downgrade is rejected.", 3),
    (13, "Define C3 commit, revision, idempotency and outbox ports", "WS-04", "G1", [8, 9, 10], "ocor-runtime/src/ocor_runtime/c3/ports.py", "Commit receipts bind revision, state, idempotency, evidence, GCS and outbox event.", "A receipt missing any binding or reusing a key with different content is rejected.", 3),
    (14, "Define security-control ports and fail-closed policy contract", "WS-11", "G1", [5, 8, 9, 10], "ocor-runtime/src/ocor_runtime/security/ports.py", "Identity, policy, workload identity, secrets and stop epoch expose typed availability/failure semantics.", "Unavailable control plane cannot degrade to permit or anonymous identity.", 4),
    (15, "SPIKE C3 revision-state-idempotency-outbox atomicity", "WS-04", "G2", [13], "spikes/c3_atomicity/", "Crash-window matrix proves all-or-none durable visibility and identical retry receipts.", "Any partial state/outbox/idempotency visibility falsifies the hypothesis.", 4),
    (16, "SPIKE selected C3 backend behaviour", "WS-04", "G2", [6, 13, 15, 84], "spikes/c3_backend/", "Selected backend meets locking, isolation, failure and reconciliation oracles under real concurrency.", "Lost update, phantom receipt or unreconciled commit triggers governed backend decision.", 5),
    (17, "SPIKE TypeDB exact-at-commit semantics", "WS-05", "G2", [6, 12, 13, 84], "spikes/typedb_exact_commit/", "Queries at required commit return exact projection or PROJECTION_NOT_READY with observable watermark.", "Returning older facts as exact-at-commit falsifies the adapter approach.", 5),
    (18, "SPIKE Jena marking-safe projection", "WS-05", "G2", [6, 8, 14, 84], "spikes/jena_marking/", "RDF/JSON-LD/SHACL projection preserves marking joins and filters existence/count paths.", "Any unauthorized triple, count or error-shape leak fails the spike.", 5),
    (19, "SPIKE Kafka ordering replay and deduplication", "WS-06", "G2", [6, 10, 13], "spikes/kafka_delivery/", "Real Kafka preserves aggregate order, deterministic replay and dedup under broker/consumer faults.", "Out-of-order externally visible effect or unrecoverable poison event fails.", 5),
    (20, "SPIKE executable fidelity of 44 C6 transitions", "WS-07", "G2", [9, 13, 14], "spikes/c6_fsm_fidelity/", "A generated transition table matches all 44 LLD IDs, sources, guards, effects and destinations.", "Missing/extra transition or altered durable effect fails equality.", 5),
    (21, "SPIKE identity-policy latency and failure semantics", "WS-11", "G2", [6, 14, 84], "spikes/control_plane_latency/", "OPA/Keycloak/SPIFFE/OpenBao timeouts remain bounded and deny with correlated audit evidence.", "Timeout, stale policy or identity outage resulting in permit fails.", 4),
    (22, "SPIKE causal reproducibility", "WS-08", "G2", [7, 9, 13], "spikes/causal_reproducibility/", "Pinned model/data/intervention seeds reproduce sealed causal results and identify-or-abstain outcomes.", "Same inputs yielding an unexplained digest change fails.", 5),
    (23, "SPIKE vector-index partition isolation", "WS-10", "G2", [6, 8, 14], "spikes/vector_partition/", "Authorized partitions return stable ranked results without cross-scope candidates or metadata leakage.", "Injected foreign-scope vectors influence result, rank, count or timing envelope and fail.", 5),
    (24, "SPIKE cross-compartment non-interference", "WS-10", "G2", [18, 21, 23], "spikes/non_interference/", "Paired fixtures are observationally equivalent across content, existence, rank, count, cache and bounded timing.", "Any distinguishable unauthorized compartment signal fails.", 6),
    (25, "SPIKE distributed deletion saga", "WS-10", "G2", [16, 17, 18, 19, 23], "spikes/memory_deletion/", "Partial failures remain DELETION_INCOMPLETE until metadata, content, indexes, cache and replicas acknowledge tombstone.", "A success receipt while any searchable copy remains fails.", 6),
    (26, "SPIKE restore without resurrection", "WS-10", "G2", [25], "spikes/restore_no_resurrection/", "Restore reconciles tombstone journal before serving and deleted content never reappears.", "Any restored deleted item, embedding or cache entry fails and blocks restore.", 5),
    (27, "SPIKE deterministic context-assembly replay", "WS-10", "G2", [23, 24], "spikes/context_replay/", "Pinned item versions, redactions, ordering, truncation and representation reproduce receipt digest.", "Unrecorded retrieval/ranking/model input or digest divergence fails.", 5),
    (28, "Build retained C1 compiler slice", "WS-02", "G3", [11, 16], "ocor-runtime/src/ocor_runtime/c1/compiler.py", "A versioned DSL fixture compiles to immutable canonical IR and migration metadata with reproducible digest.", "Invalid semantics or incompatible release cannot publish an IR release.", 5),
    (29, "Build retained C3 canonical commit slice", "WS-04", "G3", [16], "ocor-runtime/src/ocor_runtime/c3/service.py", "Real C3 commits state, revision, evidence, idempotency and outbox atomically and recovers from crash fixtures.", "Injected boundary failures expose neither partial state nor success receipt.", 6),
    (30, "Build retained governed-action slice", "WS-07", "G3", [20, 21, 29], "ocor-runtime/src/ocor_runtime/c6/engine.py", "A risk-bearing action crosses Authority, Human Gate, Decision and EMISSION-FENCE before a simulated effect.", "Missing/stale approval, decision, lease, GCS or stop epoch prevents command creation.", 6),
    (31, "Integrate first real C1-C8 synthetic mission thread", "WS-13", "G3", [17, 18, 19, 22, 24, 27, 28, 29, 30], "ocor-runtime/tests/mission_thread/test_first_governed_slice.py", "A content-addressed fixture crosses real selected services and produces correlated canonical, projection, event, causal, agent and action receipts.", "Replacing a required service with a mock or dropping correlation/causation makes the test non-qualifying.", 7),
    (32, "Complete C1 parser type-checker and semantic validation", "WS-02", "G4", [28, 31], "ocor-runtime/src/ocor_runtime/c1/frontend.py", "Grammar, type and semantic negative corpora produce stable diagnostics; valid corpus compiles deterministically.", "Ambiguous, cyclic or invalid models cannot reach generation.", 7),
    (33, "Complete C1 releases semantic diff migration and generators", "WS-02", "G4", [32], "ocor-runtime/src/ocor_runtime/c1/releases.py", "Immutable releases, compatibility classification, migration plans and generated artifacts are content-addressed.", "Breaking change without governed migration is blocked.", 6),
    (34, "Implement C2 named-query gateway and identity resolution", "WS-03", "G4", [12, 17, 18, 31], "ocor-runtime/src/ocor_runtime/c2/gateway.py", "Only registered named queries execute after identity, purpose, marking and policy checks.", "Arbitrary query, ambiguous identity or missing purpose returns typed abstain/deny without data.", 7),
    (35, "Implement C2 policy-filtered planning consistency and watermarks", "WS-03", "G4", [34], "ocor-runtime/src/ocor_runtime/c2/planner.py", "Planner proves policy filters and returns required commit or PROJECTION_NOT_READY with watermarks.", "Silent stale fallback or backend query leakage is rejected.", 6),
    (36, "Complete C3 single-writer recovery and reconciliation", "WS-04", "G4", [29, 31], "ocor-runtime/src/ocor_runtime/c3/recovery.py", "Concurrent writers, lost ACK, corrupt outbox and restart fixtures converge without duplicate canonical effects.", "Non-authoritative write or unreconciled durable intent blocks service health.", 7),
    (37, "Implement C4 TypeDB projection adapter", "WS-05", "G4", [17, 29, 31], "ocor-runtime/src/ocor_runtime/c4/typedb_adapter.py", "Facts/relations and watermark commit atomically and exact-at-commit behavior matches the port.", "Stale projection cannot masquerade as exact.", 6),
    (38, "Implement C4 Jena RDF SHACL adapter", "WS-05", "G4", [18, 29, 31], "ocor-runtime/src/ocor_runtime/c4/jena_adapter.py", "RDF/JSON-LD output passes SHACL and marking non-interference fixtures.", "Unauthorized triples or lossy provenance block publication.", 6),
    (39, "Implement C4 rebuild and drift reconciliation", "WS-05", "G4", [37, 38], "ocor-runtime/src/ocor_runtime/c4/rebuild.py", "Projection rebuild from canonical log reproduces digest/watermark and drift is quarantined.", "Serving divergent projection after failed reconciliation is prohibited.", 5),
    (40, "Implement C5 canonical event backbone", "WS-06", "G4", [19, 29, 31], "ocor-runtime/src/ocor_runtime/c5/backbone.py", "Schema-bound events preserve partition order, correlation, causation, markings and idempotency on Kafka.", "Unknown schema, missing context or out-of-order aggregate effect goes to quarantine.", 7),
    (41, "Implement C5 registry replay backpressure DLQ and quarantine", "WS-06", "G4", [40], "ocor-runtime/src/ocor_runtime/c5/operations.py", "Replay and poison-event fixtures are bounded, observable and never bypass compatibility checks.", "DLQ replay with incompatible schema or lost marking is blocked.", 6),
    (42, "Implement exact approved 44-transition C6 FSM", "WS-07", "G4", [20, 30, 31], "ocor-runtime/src/ocor_runtime/c6/fsm.py", "Runtime table equals all 44 LLD transition tuples and persists each declared effect.", "Any missing, extra or wrong source/event/guard/effect/destination fails startup and CI.", 8),
    (43, "Implement Human Gate Decision Approval and dual control", "WS-07", "G4", [21, 30, 42], "ocor-runtime/src/ocor_runtime/c6/human_gate.py", "Quorum, SoD, signatures, scope and TTL are revalidated at resolution and dispatch.", "Same-human dual role is not counted twice; expired or scope-mismatched approval denies.", 6),
    (44, "Implement compensation reconciliation break-glass and emergency stop", "WS-07", "G4", [42, 43], "ocor-runtime/src/ocor_runtime/c6/safety.py", "Unknown outcomes, compensation, stop precedence and break-glass produce immutable evidence and fail-safe state.", "Stop race cannot emit after stop epoch; ambiguous non-idempotent effect cannot auto-retry.", 7),
    (45, "Implement C7 scenario and causal runtime", "WS-08", "G4", [22, 31, 40], "ocor-runtime/src/ocor_runtime/c7/runtime.py", "Branches cannot write main; interventions, counterfactuals, uncertainty and sensitivity produce sealed reproducible results.", "Unsupported identification returns abstain and no authoritative causal claim.", 8),
    (46, "Implement C8 AgentRun Task Assignment Commitment Handoff and Dissent", "WS-09", "G4", [9, 27, 31], "ocor-runtime/src/ocor_runtime/c8/orchestrator.py", "Agent/team state transitions preserve authority, commitments, handoffs and dissent as explicit records.", "Agent cannot self-grant capability, suppress dissent or mutate canonical state.", 8),
    (47, "Implement C8 tool boundary sandbox budgets and kill switch", "WS-09", "G4", [21, 44, 46], "ocor-runtime/src/ocor_runtime/c8/tool_runtime.py", "Every model/tool call is capability-, purpose-, marking-, budget- and stop-bound with receipts.", "Escape syntax, over-budget work or revoked capability produces no tool effect.", 6),
    (48, "Integrate OPA Keycloak SPIFFE OpenBao and mTLS", "WS-11", "G4", [14, 21, 31], "ocor-runtime/src/ocor_runtime/security/control_plane.py", "Real services enforce least privilege, workload identity, policy bundles, delegation and secret isolation.", "Control-plane outage or stale bundle fails closed and emits correlated diagnostics.", 8),
    (49, "Implement PoC deployment observability backup and safe degradation", "WS-12", "G4", [6, 31, 36, 39, 41, 44, 45, 47, 48], "deploy/helm/ocor-poc/", "Compose and Helm profiles expose health, metrics, logs, traces, backup/replay and bounded safe-degraded modes.", "Missing mandatory dependency, untested restore or public-network dependency blocks readiness.", 8),
    (50, "Implement GovernedMemoryItem admission and immutable versions", "WS-10", "G5", [9, 36, 46, 48], "ocor-runtime/src/ocor_runtime/memory/model.py", "All 8 kinds and 7 scopes validate with provenance, evidence, markings, taint and immutable version lineage.", "Missing metadata, invalid scope/kind or mutable overwrite is rejected before persistence.", 7),
    (51, "Implement memory metadata content and index stores", "WS-10", "G5", [23, 25, 50], "ocor-runtime/src/ocor_runtime/memory/stores.py", "Metadata, content, lexical and vector representations commit with versioned pointers and compartment partitions.", "Partial store visibility or unbound representation is non-queryable and reconciled.", 8),
    (52, "Implement structured full-text vector and hybrid retrieval", "WS-10", "G5", [24, 27, 51], "ocor-runtime/src/ocor_runtime/memory/retrieval.py", "Policy-first retrieval pins query, representation, ranking, filters and exact item versions.", "Unauthorized items cannot affect content, existence, rank, count, cache or explanation.", 8),
    (53, "Implement embedding lifecycle and deterministic rebuild", "WS-10", "G5", [23, 51], "ocor-runtime/src/ocor_runtime/memory/embeddings.py", "Parallel versioned representations rebuild deterministically without changing immutable memory items.", "Unpinned model/vector dimensions or mixed representation versions fail retrieval.", 6),
    (54, "Implement consolidation reflection dissent and correction", "WS-10", "G5", [50, 52], "ocor-runtime/src/ocor_runtime/memory/consolidation.py", "Derived memories cite immutable sources and preserve conflicts/dissent without silent majority merge.", "Correction cannot rewrite source, erase dissent or become authority.", 7),
    (55, "Implement retention expiry revocation forgetting and legal hold", "WS-10", "G5", [50, 51, 54], "ocor-runtime/src/ocor_runtime/memory/lifecycle.py", "Policy transitions deterministically exclude revoked/expired items while legal hold blocks deletion.", "Held content cannot be deleted; excluded items cannot influence results or caches.", 7),
    (56, "Implement deletion saga tombstones and restore reconciliation", "WS-10", "G5", [25, 26, 51, 55], "ocor-runtime/src/ocor_runtime/memory/deletion.py", "Deletion completes across stores/indexes/cache/replicas/backups and restore honors tombstones before serving.", "Any surviving or resurrected deleted representation keeps status incomplete and service fail-closed.", 8),
    (57, "Implement context assembly receipts and exact replay", "WS-10", "G5", [27, 52, 53, 54, 55], "ocor-runtime/src/ocor_runtime/memory/context.py", "Receipt binds selected versions, redactions, order, truncation, representations and final context digest.", "Unrecorded input or non-deterministic replay is rejected as evidence.", 7),
    (58, "Implement memory promotion through C6 and C3", "WS-10", "G5", [42, 43, 50, 54, 57], "ocor-runtime/src/ocor_runtime/memory/promotion.py", "Memory-derived proposal reaches canonical state only through C6 approval/decision and C3 commit receipt.", "Direct memory write, capability grant or policy mutation is impossible at the port and integration levels.", 6),
    (59, "Integrate memory operations quotas backup and non-interference monitoring", "WS-10", "G5", [49, 52, 56, 57, 58], "ocor-runtime/src/ocor_runtime/memory/operations.py", "Quota, retention pressure, backup and monitoring preserve holds, tombstones and bounded non-interference metrics.", "Pressure cannot evict legal hold or leak compartment cardinality.", 6),
    (60, "Execute qualifying BA-01 through BA-08 campaign", "WS-13", "G6", [33, 35, 36, 39, 41, 44, 45, 47, 48, 49], "ocor-runtime/tests/conformance/ba/", "Each BA case runs on its selected real component and emits an individual signed result and raw-log hash.", "Mock, skipped, unavailable or legacy RBA result cannot satisfy a BA identifier.", 8),
    (61, "Execute FGM-01 through FGM-10 campaign", "WS-13", "G6", [50, 51, 52, 53, 54, 55, 59], "ocor-runtime/tests/conformance/fgm/test_fgm_01_10.py", "FGM-01..10 each produce qualifying real-store results covering taxonomy, retrieval, embedding and correction.", "Any absent, skipped or cross-scope-leaking case keeps full-memory runtime NO-GO.", 7),
    (62, "Execute FGM-11 through FGM-20 campaign", "WS-13", "G6", [54, 55, 56, 57, 58, 59], "ocor-runtime/tests/conformance/fgm/test_fgm_11_20.py", "FGM-11..20 each prove hold, deletion, dissent, promotion, non-interference, stop, restore, quota and replay oracles.", "Any resurrection, direct promotion, leakage or non-reproducible receipt fails the campaign.", 8),
    (63, "Execute all 44 FSM transition and fault cases", "WS-13", "G6", [42, 43, 44, 48, 49], "ocor-runtime/tests/conformance/fsm/test_all_44.py", "Every approved transition executes positive, guard-negative and durable-effect checks with exact tuple equality.", "A test that merely counts IDs or omits negative guard/effect validation is non-qualifying.", 6),
    (64, "Execute security non-interference and fault-injection campaign", "WS-13", "G6", [24, 41, 44, 47, 48, 49, 59], "ocor-runtime/tests/conformance/security/", "Identity, policy, workload, secret, stop, marking and partition failures remain fail-closed on real services.", "Unavailable service reported as PASS or observable cross-compartment difference fails.", 8),
    (65, "Execute qualifying complete synthetic mission thread", "WS-13", "G6", [33, 35, 36, 39, 41, 44, 45, 47, 48, 59, 60, 61, 62, 63, 64], "ocor-runtime/tests/conformance/mission_thread/", "The full fixture traverses C1-C8 and memory with correlated, content-addressed evidence and no mocked required boundary.", "Broken trace, skipped backend, direct canonical write or ungoverned memory influence fails.", 9),
    (66, "Execute deployment backup restore replay and air-gap qualification", "WS-13", "G6", [49, 56, 59, 65], "ocor-runtime/tests/conformance/operations/", "Fresh offline install, backup, destructive restore drill and replay reproduce declared checkpoints without resurrection.", "Public network use, missing image digest or unreconciled restore blocks qualification.", 8),
    (67, "Close 285-requirement runtime traceability ledger", "WS-13", "G7", [60, 61, 62, 63, 64, 65, 66], "reports/evidence/G7/requirement_results.json", "Every approved requirement points to implementation commit and qualifying non-skipped test/evidence hashes.", "Unmapped, documentation-only, mock-only or unreproducible evidence leaves the requirement unverified.", 6),
    (68, "Perform independent adversarial conformance review", "WS-13", "G7", [67], "reports/evidence/G7/independent_review.md", "A reviewer independent of implementation paths reproduces manifests, samples negative cases and records all findings/dispositions.", "Self-authored summary without raw-evidence reproduction cannot close review.", 5),
    (69, "Assemble governed PoC-GO candidate decision package", "WS-13", "G7", [68], "reports/evidence/G7/poc_go_candidate/", "Package binds exact commit, environment, 285 results, BA/FGM/FSM/mission/recovery evidence, limitations and residual risks.", "Any mandatory red/unavailable result produces NO-GO and no approval record.", 4),
]

# WS-12 infrastructure-bootstrap-repair workstream (OCOR-DEV-0070..0084),
# adopted under DEC-211 to close the gap the four G2 backend spikes were
# blocked on (OCOR-DEV-0016/0017/0018/0021's WAITING_EXTERNAL_SERVICE state,
# superseded once these are accepted). These 15 tasks share one uniform
# template distinct from TASK_SPECS's -- see build_tasks()'s WS-12 branch --
# so they are kept in their own compact per-task tuple list of
# (number, title, deps, area) rather than forced into the nine-field
# TASK_SPECS shape.
WS12_TASK_SPECS = [
    (70, "Verify container runtime availability", [6], "infra/services.lock.json"),
    (71, "Restore frozen Python environment", [2], "infra/toolchain.lock.json"),
    (72, "Install required CLI and test tools", [70, 71], "scripts/bootstrap_development_environment.py"),
    (73, "Provision real TerminusDB", [72], "deploy/bootstrap/services/terminusdb/"),
    (74, "Provision real TypeDB", [72], "deploy/bootstrap/services/typedb/"),
    (75, "Provision real Apache Jena Fuseki", [72], "deploy/bootstrap/services/fuseki/"),
    (76, "Provision OPA and Keycloak", [72], "deploy/bootstrap/services/policy-identity/"),
    (77, "Provision SPIFFE SPIRE server and agent", [72], "deploy/bootstrap/services/spire/"),
    (78, "Provision OpenBao", [72], "deploy/bootstrap/services/openbao/"),
    (79, "Implement typed service health checks", [73, 74, 75, 76, 77, 78], "scripts/verify_external_services.py"),
    (80, "Implement deterministic service initialization", [79], "deploy/bootstrap/init/"),
    (81, "Load deterministic synthetic test fixtures", [80], "deploy/bootstrap/fixtures/"),
    (82, "Implement service reset and teardown", [80], "scripts/reset_test_environment.py"),
    (83, "Implement bounded fault injection", [79], "scripts/fault_inject_test_environment.py"),
    (84, "Capture reproducible environment evidence", [81, 82, 83], "scripts/capture_environment_evidence.py"),
]

SPIKE_DETAILS = {
    15: ("C3 can atomically bind state, revision, idempotency and outbox.", "Partial durable visibility", "retained contract harness", "PostgreSQL disposable", "5 crash windows + concurrent retry", "state/outbox/idempotency counts and receipt digests", "partial visibility or divergent retry", "retain atomic port; choose backend only after task 16", "32k–70k", "20–40 CPU-h"),
    16: ("The selected C3 backend meets approved isolation and recovery semantics.", "Wrong persistence choice", "harden if green", "real selected C3 backend", "concurrent writers, lost ACK, restart, reconciliation", "one commit and deterministic repair", "lost update or phantom success", "harden selection or raise blocking decision", "40k–90k", "30–70 service-h"),
    17: ("TypeDB can expose exact-at-commit or explicit not-ready.", "Silent projection downgrade", "harden adapter kernel", "real TypeDB", "lagged projection and requested commit", "exact result or PROJECTION_NOT_READY", "older facts labeled exact", "retain adapter or govern alternative", "40k–85k", "25–60 service-h"),
    18: ("Jena projection can preserve markings and non-interference.", "RDF leakage", "harden mapper", "real Jena", "paired compartment RDF/SHACL fixtures", "authorized graph only and equal unauthorized observations", "triple/count/error leak", "retain mapper or block Jena profile", "40k–85k", "25–60 service-h"),
    19: ("Kafka provides required order/replay/dedup with OCOR envelope.", "Duplicate or reordered effects", "harden harness and adapter", "Kafka/Strimzi", "broker restart, rebalance, poison event", "ordered idempotent delivery and bounded quarantine", "visible reorder or unbounded retry", "retain settings or govern topology change", "45k–95k", "35–90 service-h"),
    20: ("The LLD 44-transition table is executable without reinterpretation.", "FSM semantic drift", "retained generator/equality suite", "local + PostgreSQL", "all tuples, every guard and durable effect", "44 exact positive/negative cases", "missing/extra tuple or wrong effect", "implement exact table; conflict requires ARA decision", "45k–100k", "20–50 CPU-h"),
    21: ("Security controls fail closed within bounded latency.", "Permit on control outage", "harden client policies", "OPA/Keycloak/SPIFFE/OpenBao", "latency, timeout, rotation and stale bundle", "typed deny/unavailable with audit", "permit or unbounded hang", "retain timeouts or govern availability trade-off", "40k–90k", "35–80 service-h"),
    22: ("Causal results are reproducible when inputs and methods are pinned.", "Unverifiable causal claims", "retained reproducibility kernel", "local causal runner + object store", "seed/model/data/intervention variants", "same sealed digest or explained method-version change", "unexplained divergence", "retain method or abstain/govern replacement", "45k–100k", "20–80 CPU-h"),
    23: ("Vector partitions prevent cross-scope influence.", "Semantic retrieval leakage", "harden partition adapter", "real vector index", "paired authorized/foreign embeddings", "no foreign influence on content/rank/count/cache/timing band", "any measurable forbidden influence", "retain backend or raise selection blocker", "45k–100k", "30–90 service-h"),
    24: ("The full retrieval path is non-interfering across compartments.", "Cross-compartment disclosure", "retained security suite", "full retrieval stack", "paired worlds differing only in forbidden data", "observational equivalence within preregistered timing bound", "content/existence/rank/count/cache/timing distinction", "block G5 until design-compatible control exists", "55k–120k", "50–120 service-h"),
    25: ("Deletion can converge across all memory representations.", "Incomplete deletion reported complete", "retained saga skeleton", "metadata/content/index/cache/replica stack", "fault at each saga participant", "DELETION_INCOMPLETE then deterministic completion", "success with surviving copy", "harden saga or govern backend limitation", "55k–120k", "50–130 service-h"),
    26: ("Restore can reconcile tombstones before reads.", "Deleted memory resurrection", "retained restore gate", "backup plus complete memory stack", "backup-before-delete then restore", "deleted item absent from all read/influence paths", "any resurrection", "block restore and PoC campaign", "45k–100k", "40–100 service-h"),
    27: ("Context assembly can replay exact model input.", "Non-reproducible agent decisions", "retained receipt kernel", "retrieval stack", "ranking/redaction/truncation permutations", "exact item versions/order/digest replay", "unrecorded or divergent context", "retain pinned pipeline or prohibit evidence claim", "45k–100k", "25–70 service-h"),
}

STRATEGY_CRITERIA = [
    ("Compliance preservation", 10, 3, 4, 4, 5),
    ("Architectural regression probability", 9, 2, 4, 4, 5),
    ("Early risk retirement", 10, 2, 3, 5, 5),
    ("Autonomous executability", 7, 4, 4, 4, 5),
    ("Bounded agent context", 5, 3, 4, 5, 5),
    ("Dependency complexity", 5, 2, 4, 3, 4),
    ("Feedback speed", 8, 2, 3, 5, 5),
    ("Testability", 8, 3, 5, 4, 5),
    ("Rollback safety", 5, 3, 4, 5, 5),
    ("CI integration", 5, 3, 5, 4, 5),
    ("Token efficiency", 4, 3, 4, 5, 5),
    ("Compute cost", 3, 4, 3, 4, 4),
    ("Merge-conflict probability", 4, 2, 3, 4, 5),
    ("Time to first mission thread", 5, 1, 2, 5, 5),
    ("Time to PoC conformance", 6, 2, 3, 4, 5),
    ("Incremental evidence suitability", 4, 2, 4, 5, 5),
    ("Compatibility migration risk", 2, 2, 4, 4, 5),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


def classify(path: str) -> str:
    lower = path.lower()
    if path.endswith("AGENTS.md"):
        return "instruction"
    if path in {
        "reports/OCOR_IRB_ADD_LLD_Exhaustive_Alignment_Audit_v1.0.md",
        "reports/tests/irb_add_lld_audit_results.json",
    }:
        return "superseded"
    if "/governance_dossier/ara_" in lower or "decision_register_v1.3" in lower or "decision_traceability_index_v1.3" in lower:
        return "effective_governance"
    if path == "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md" or path == "docs/OCOR_LLD_v1.1.md" or "requirement_register_v1.1_approved" in lower or "requirement_traceability_index_v1.1_approved" in lower or "cap_elm_requirement_crosswalk_v1.1_approved" in lower or "/governance_dossier/contracts/" in lower:
        return "authoritative"
    if "candidate" in lower or "draft" in lower:
        return "candidate"
    if path.startswith("inputs/") or "v1.0" in lower or "v1.2_approved_baseline" in lower or "prior/" in lower or "histor" in lower:
        return "historical"
    if path.startswith("ocor-runtime/src/"):
        return "source"
    if "/tests/" in lower or lower.startswith("reports/tests/"):
        return "test" if lower.endswith(".py") else "generated"
    if "/schemas/" in lower or "/contracts/" in lower or lower.endswith((".proto", ".schema.json")):
        return "schema_or_contract"
    if path.startswith(".github/workflows/"):
        return "ci_cd"
    if path.startswith("deploy/") or "helm" in lower or "compose" in lower:
        return "infrastructure"
    if lower.endswith((".json", ".xml", ".log", ".txt")) or "sha256sums" in lower:
        return "generated"
    if path.startswith("reports/"):
        return "evidence"
    if path.startswith("prompts/"):
        return "instruction"
    if lower.endswith((".lock", ".toml")):
        return "third_party"
    if lower.endswith((".png", ".jpg", ".pdf", ".bin")):
        return "binary"
    return "operational"


def tracked_inventory() -> list[dict[str, Any]]:
    files = git("ls-tree", "-r", "--name-only", BASE_COMMIT).splitlines()
    result = []
    for rel in files:
        data = subprocess.run(
            ["git", "show", f"{BASE_COMMIT}:{rel}"], cwd=ROOT, check=True,
            capture_output=True,
        ).stdout
        result.append({
            "path": rel,
            "category": classify(rel),
            "bytes": len(data),
            "lines": data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0),
            "sha256": hashlib.sha256(data).hexdigest(),
            "provenance": f"git:{BASE_COMMIT}:{rel}",
            "inspection": "full text" if len(data) < 250_000 and b"\0" not in data else "metadata/hash/generator",
        })
    return result


def task_id(number: int) -> str:
    return f"OCOR-DEV-{number:04d}"


def topological(tasks: list[dict[str, Any]]) -> tuple[list[str], dict[str, int], list[str], int]:
    by_id = {t["id"]: t for t in tasks}
    indegree = {tid: 0 for tid in by_id}
    successors: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for dep in task["hard_dependencies"]:
            indegree[task["id"]] += 1
            successors[dep].append(task["id"])
    queue = deque(sorted(tid for tid, degree in indegree.items() if degree == 0))
    order: list[str] = []
    wave: dict[str, int] = {}
    distance: dict[str, int] = {}
    predecessor: dict[str, str | None] = {}
    while queue:
        current = queue.popleft()
        order.append(current)
        deps = by_id[current]["hard_dependencies"]
        wave[current] = 1 + max((wave[d] for d in deps), default=0)
        best = max(deps, key=lambda d: distance[d], default=None)
        distance[current] = by_id[current]["expected_duration_days"] + (distance[best] if best else 0)
        predecessor[current] = best
        for nxt in sorted(successors[current]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(tasks):
        raise RuntimeError("task graph contains a cycle")
    end = max(order, key=lambda tid: distance[tid])
    critical: list[str] = []
    while end:
        critical.append(end)
        end = predecessor[end]  # type: ignore[assignment]
    critical.reverse()
    return order, wave, critical, distance[critical[-1]]


def requirement_owner(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get(k, "")) for k in ("title", "normative_statement", "acceptance_criterion", "add_anchor", "lld_anchor")).lower()
    rules = [
        ("WS-10", ("memory", "memoria", "embedding", "forgetting", "dissent", "reflection", "tombstone", "legal hold")),
        ("WS-07", ("action", "human gate", "approval", "decision", "emission-fence", "compensation", "break-glass", "emergency stop")),
        ("WS-08", ("causal", "scenario", "counterfactual", "intervention", "uncertainty")),
        ("WS-09", ("agent", "assignment", "handoff", "commitment", "tool", "sandbox")),
        ("WS-06", ("event", "kafka", "replay", "backpressure", "dlq", "subscription")),
        ("WS-05", ("projection", "typedb", "jena", "rdf", "shacl", "watermark")),
        ("WS-04", ("canonical state", "single writer", "outbox", "idempot", "revision", "commit")),
        ("WS-03", ("query", "gateway", "identity", "identify", "ontology access")),
        ("WS-02", ("ontology", "compiler", "canonical ir", "dsl", "semantic diff", "schema")),
        ("WS-11", ("security", "authority", "marking", "privacy", "policy", "capability", "secret", "identity")),
        ("WS-12", ("deploy", "backup", "restore", "observability", "air-gap", "portability", "availability")),
        ("WS-13", ("evidence", "verification", "test", "acceptance", "audit")),
    ]
    for ws, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return ws
    return "WS-01"


def build_tasks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for number, title, ws, gate, deps, area, oracle, negative, days in TASK_SPECS:
        task_test_area = area if area.startswith("ocor-runtime/tests/") else f"ocor-runtime/tests/tasks/test_ocor_dev_{number:04d}.py"
        tokens = {
            "input_context": [12000 + days * 1800, 22000 + days * 3000],
            "implementation": [10000 + days * 2500, 24000 + days * 6000],
            "review_and_repair": [6000 + days * 1200, 16000 + days * 2800],
            "likely_retries": [1, 2 if gate not in {"G6", "G7"} else 3],
            "confidence_interval": "-25%/+60%; higher for real-service and fault-injection tasks",
        }
        task = {
            "id": task_id(number),
            "title": title,
            "workstream": ws,
            "delivery_gate": gate,
            "objective": oracle,
            "rationale": f"Closes an evidence-backed obligation in {WORKSTREAMS[ws]} without changing approved architecture.",
            "requirement_ids": ["BR-003"],
            "normative_references": list(WORKSTREAM_REFERENCES[ws]),
            "affected_components": [],
            "expected_file_areas": [area] if task_test_area == area else [area, task_test_area],
            "prohibited_file_areas": [
                "inputs/", "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md",
                "docs/OCOR_LLD_v1.1.md",
            ],
            "hard_dependencies": [task_id(d) for d in deps],
            "soft_dependencies": [],
            "parallel_group": f"{gate}-{ws}-{number:04d}",
            "integration_point": f"{gate} integration branch after evidence review",
            "preconditions": ["All hard dependencies are merged and green", f"Approved ADD/LLD hashes match {BASE_COMMIT}"],
            "bounded_agent_context_pack": [area, "docs/OCOR_LLD_v1.1.md", "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"],
            "assumptions": ["Candidate implementations require spike evidence before hardening", "Mocks may support unit tests but never qualifying runtime evidence"],
            "implementation_procedure": [
                "Verify context-manifest hashes and task dependencies.",
                "Add the smallest contract-compliant implementation behind an explicit port.",
                "Add positive, negative and fault tests before broad integration.",
                "Emit raw results and a content-addressed handoff; stop after two failed repair cycles.",
            ],
            "migration_and_compatibility_procedure": "Preserve existing public imports through versioned adapters; use expand-migrate-contract for persisted data and remove shims only after consumer inventory is empty.",
            "required_test_levels": ["unit", "contract", "negative", "integration", "fault-injection"],
            "validation_commands": [
                f"uv run pytest -q {task_test_area}",
                f"python scripts/validate_runtime_evidence.py --task {task_id(number)} --non-skipped --manifest reports/evidence/{gate}/MANIFEST.json",
            ],
            "acceptance_criteria": [oracle, f"Evidence manifest contains task_id={task_id(number)}, commit, command, environment and raw-output hashes."],
            "negative_acceptance_criteria": [negative, "A SKIPPED, UNAVAILABLE, mock-only or NOT_EXECUTED qualifying case is not accepted."],
            "evidence_outputs": [f"reports/evidence/{gate}/{task_id(number)}.json", f"reports/evidence/{gate}/{task_id(number)}.log"],
            "rollback_procedure": "Stop dispatch, revert the isolated task commit through a new revert commit, execute versioned down/forward recovery in a disposable environment, and revalidate the prior evidence manifest.",
            "security_considerations": "Fail closed on missing identity, Authority, purpose, marking, lease, policy, evidence or stop state; never log secrets or unauthorized content.",
            "observability_requirements": ["correlation_id and causation_id on every boundary", "stable error code and bounded metric cardinality", "trace plus audit receipt for durable effects"],
            "expected_duration_days": days,
            "ai_token_estimate": tokens,
            "compute_estimate": {"local": f"{max(2, days * 3)}–{days * 8} CPU-h", "external_services": "0–80 service-h depending on qualifying backend", "gpu": "0 by default; 2–20 GPU-h only for governed embedding/model fixtures"},
            "uncertainty": "MEDIUM" if gate in {"G0", "G1"} else "HIGH",
            "confidence": 0.75 if gate in {"G0", "G1"} else 0.58,
            "failure_and_escalation_conditions": ["Two materially different repairs fail", "Normative conflict is found", "Required real service or credential is unavailable", "A change would substitute approved architecture"],
            "definition_of_done": ["Named acceptance and negative criteria are observed", "Required validations exit zero with no mandatory skip", "Independent review accepts hashes and trace links", "Rollback drill or mechanically reviewed rollback is recorded"],
            "coverage": {"components": [], "fsm_transitions": [], "ba_campaigns": [], "fgm_campaigns": [], "memory_kinds": [], "memory_scopes": [], "memory_lifecycle": []},
        }
        tasks.append(task)

    for number, title, deps, area in WS12_TASK_SPECS:
        tasks.append({
            "id": task_id(number),
            "title": title,
            "workstream": "WS-12",
            "delivery_gate": "G2",
            "objective": f"{title} with pinned artifacts, deterministic checks and content-addressed evidence.",
            "rationale": "Repairs the governed infrastructure-bootstrap dependency gap without changing approved architecture.",
            "requirement_ids": ["BR-003"],
            "normative_references": list(WORKSTREAM_REFERENCES["WS-12"]),
            "affected_components": [],
            "expected_file_areas": [area, f"reports/evidence/G2/{task_id(number)}.json"],
            "prohibited_file_areas": [
                "inputs/", "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md",
                "docs/OCOR_LLD_v1.1.md",
            ],
            "hard_dependencies": [task_id(d) for d in deps],
            "soft_dependencies": [],
            "parallel_group": f"G2-WS-12-{number:04d}",
            "integration_point": "DEC-211 infrastructure bootstrap workstream",
            "preconditions": ["All hard dependencies are merged and green", f"Approved ADD/LLD hashes match {BASE_COMMIT}"],
            "bounded_agent_context_pack": ["infra/services.lock.json", "docs/development_methodology/OCOR_INFRASTRUCTURE_BOOTSTRAP_STRATEGY.md", area],
            "assumptions": ["Candidate implementations require spike evidence before hardening", "Mocks may support unit tests but never qualifying runtime evidence"],
            "implementation_procedure": [
                "Verify context-manifest hashes and task dependencies.",
                "Add the smallest contract-compliant implementation behind an explicit port.",
                "Add positive, negative and fault tests before broad integration.",
                "Emit raw results and a content-addressed handoff; stop after two failed repair cycles.",
            ],
            "migration_and_compatibility_procedure": "Preserve existing public imports through versioned adapters; use expand-migrate-contract for persisted data and remove shims only after consumer inventory is empty.",
            "required_test_levels": ["unit", "contract", "negative", "integration", "fault-injection"],
            "validation_commands": [
                "python3 scripts/verify_external_services.py --manifest-only",
                f"python3 scripts/validate_runtime_evidence.py --task {task_id(number)} --non-skipped --manifest reports/evidence/G2/MANIFEST.json",
            ],
            "acceptance_criteria": [
                f"{title} completes against the exact lock manifest without a skipped qualifying control.",
                f"Evidence manifest contains task_id={task_id(number)}, commit, commands, environment and raw-output hashes.",
            ],
            "negative_acceptance_criteria": ["A mutable, unhealthy, substituted or externally exposed service fails readiness.", "A SKIPPED, UNAVAILABLE, mock-only or NOT_EXECUTED qualifying case is not accepted."],
            "evidence_outputs": [f"reports/evidence/G2/{task_id(number)}.json", f"reports/evidence/G2/{task_id(number)}.log"],
            "rollback_procedure": "Stop dispatch, revert the isolated task commit through a new revert commit, execute versioned down/forward recovery in a disposable environment, and revalidate the prior evidence manifest.",
            "security_considerations": "Fail closed on missing identity, Authority, purpose, marking, lease, policy, evidence or stop state; never log secrets or unauthorized content.",
            "observability_requirements": ["correlation_id and causation_id on every boundary", "stable error code and bounded metric cardinality", "trace plus audit receipt for durable effects"],
            "expected_duration_days": 1,
            "ai_token_estimate": {
                "input_context": [21000, 37000],
                "implementation": [22500, 54000],
                "review_and_repair": [12000, 30000],
                "likely_retries": [1, 2],
                "confidence_interval": "-25%/+60%; higher for real-service and fault-injection tasks",
            },
            "compute_estimate": {"local": "15–40 CPU-h", "external_services": "0–80 service-h depending on qualifying backend", "gpu": "0 by default; 2–20 GPU-h only for governed embedding/model fixtures"},
            "uncertainty": "MEDIUM",
            "confidence": 0.75,
            "failure_and_escalation_conditions": ["Two materially different repairs fail", "Normative conflict is found", "Required real service or credential is unavailable", "A change would substitute approved architecture"],
            "definition_of_done": ["Named acceptance and negative criteria are observed", "Required validations exit zero with no mandatory skip", "Independent review accepts hashes and trace links", "Rollback drill or mechanically reviewed rollback is recorded"],
            "coverage": {"components": [], "fsm_transitions": [], "ba_campaigns": [], "fgm_campaigns": [], "memory_kinds": [], "memory_scopes": [], "memory_lifecycle": []},
        })

    by_num = {int(task["id"][-4:]): task for task in tasks}
    component_tasks = {1: 32, 2: 34, 3: 36, 4: 39, 5: 41, 6: 44, 7: 45, 8: 47}
    for component, number in component_tasks.items():
        by_num[number]["coverage"]["components"].append(f"C{component}")
        by_num[number]["affected_components"].append(f"C{component}")
    # Integration task covers boundary continuity, not a substitute for component tasks.
    by_num[31]["affected_components"] = [f"C{i}" for i in range(1, 9)]

    lld = (ROOT / "docs/OCOR_LLD_v1.1.md").read_text(encoding="utf-8")
    transition_ids = []
    for line in lld.splitlines():
        if line.startswith("| `ACT-T"):
            transition_ids.append(line.split("`")[1])
    by_num[42]["coverage"]["fsm_transitions"] = transition_ids
    by_num[63]["coverage"]["fsm_transitions"] = transition_ids
    by_num[60]["coverage"]["ba_campaigns"] = [f"BA-{i:02d}" for i in range(1, 9)]
    by_num[61]["coverage"]["fgm_campaigns"] = [f"FGM-{i:02d}" for i in range(1, 11)]
    by_num[62]["coverage"]["fgm_campaigns"] = [f"FGM-{i:02d}" for i in range(11, 21)]
    by_num[50]["coverage"]["memory_kinds"] = MEMORY_KINDS
    by_num[50]["coverage"]["memory_scopes"] = MEMORY_SCOPES
    lifecycle_task = {50: MEMORY_LIFECYCLE[:5], 52: MEMORY_LIFECYCLE[5:9], 53: MEMORY_LIFECYCLE[9:10], 54: MEMORY_LIFECYCLE[10:15], 55: MEMORY_LIFECYCLE[15:21], 56: MEMORY_LIFECYCLE[21:22], 57: MEMORY_LIFECYCLE[22:24], 58: MEMORY_LIFECYCLE[24:]}
    for number, items in lifecycle_task.items():
        by_num[number]["coverage"]["memory_lifecycle"] = items

    default_implementation_task = {
        "WS-00": 3, "WS-01": 9, "WS-02": 33, "WS-03": 35, "WS-04": 36,
        "WS-05": 39, "WS-06": 41, "WS-07": 44, "WS-08": 45, "WS-09": 47,
        "WS-10": 59, "WS-11": 48, "WS-12": 49, "WS-13": 67,
    }
    for row in rows:
        ws = requirement_owner(row)
        text = " ".join(str(row.get(k, "")) for k in ("title", "normative_statement", "acceptance_criterion", "add_anchor", "lld_anchor")).lower()
        number = default_implementation_task[ws]
        if ws == "WS-02":
            number = 33 if any(k in text for k in ("release", "migration", "semantic diff", "generator", "compatib")) else 32
        elif ws == "WS-03":
            number = 35 if any(k in text for k in ("consistency", "watermark", "planning", "stale")) else 34
        elif ws == "WS-05":
            number = 37 if "typedb" in text else 38 if any(k in text for k in ("jena", "rdf", "shacl")) else 39
        elif ws == "WS-06":
            number = 41 if any(k in text for k in ("replay", "backpressure", "dlq", "quarantine", "registry")) else 40
        elif ws == "WS-07":
            if any(k in text for k in ("compensation", "break-glass", "emergency stop", "unknown", "reconciliation")):
                number = 44
            elif any(k in text for k in ("human gate", "approval", "decision", "quorum", "dual control", "separation of duties")):
                number = 43
            else:
                number = 42
        elif ws == "WS-09":
            number = 47 if any(k in text for k in ("tool", "sandbox", "budget", "kill switch", "capability")) else 46
        elif ws == "WS-10":
            memory_rules = [
                (56, ("deletion", "tombstone", "resurrection", "restore")),
                (55, ("retention", "expiry", "revocation", "forgetting", "legal hold")),
                (57, ("context assembly", "context-assembly", "replay", "receipt")),
                (58, ("promotion", "canonical", "c6", "c3")),
                (54, ("consolidation", "reflection", "dissent", "correction", "supersession")),
                (53, ("embedding", "representation")),
                (52, ("retrieval", "full-text", "vector", "hybrid", "non-interference")),
                (51, ("store", "index", "persistence", "content")),
                (59, ("quota", "backup", "operations")),
            ]
            number = next((candidate for candidate, keywords in memory_rules if any(k in text for k in keywords)), 50)
        target = by_num[number]
        if row["requirement_id"] not in target["requirement_ids"]:
            target["requirement_ids"].append(row["requirement_id"])

    # FR-047 ("SDK e tool MCP generati") keyword-matches WS-09's "tool"
    # branch above -- landing on task 47, the C8 agent tool-invocation
    # sandbox -- purely because its own title contains the word "tool";
    # the real owner is task 10, which materializes the generated SDK/MCP
    # contracts FR-047 actually describes. Phase 2.4 corrected this in
    # OCOR_TRACEABILITY_PLAN.csv and the committed backlog; mirrored here so
    # a future regeneration reproduces the fix instead of reverting it.
    if "FR-047" in by_num[47]["requirement_ids"]:
        by_num[47]["requirement_ids"].remove("FR-047")
    if "FR-047" not in by_num[10]["requirement_ids"]:
        by_num[10]["requirement_ids"].append("FR-047")
    apply_normative_conformance_plan(by_num)

    _order, waves, _critical, _duration = topological(tasks)
    for task in tasks:
        task["parallel_wave"] = waves[task["id"]]
    return tasks


REGISTER_V11 = "ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md"
NORMATIVE_CONFORMANCE_REGISTER = "reports/development/NORMATIVE_CONFORMANCE_REGISTER.json"
SEALED_EVIDENCE_REGISTRY = "reports/traceability/OCOR_SEALED_EVIDENCE_REGISTRY.json"
G6_G7_PROPOSAL_TASKS = (60, 62, 63, 64, 65, 66, 67)
# NCR-PLAN-002 and NCR-PLAN-003 (NCP-U13): implementation allocation of the twelve
# requirements allocated to the ledger or the decision package and of the three
# misallocated ones. A planning allocation, not a claim that the task implements them.
IMPLEMENTATION_ALLOCATION = {
    "BR-001": 32, "BR-003": 31, "BR-018": 49, "FR-014": 4, "FR-017": 34, "FR-022": 32,
    "FR-029": 9, "FR-150": 34, "FR-161": 45, "NFR-011": 4, "NFR-014": 34, "NFR-021": 5,
    "FR-164": 33, "FR-045": 33, "NFR-088": 33,
}
MISALLOCATED = {"FR-164": 47, "FR-045": 45, "NFR-088": 45}
EVIDENCE_PACKAGE_UNION = (
    "baseline", "dataset_or_scenario", "evidence", "method", "metric", "owner", "raw_log",
    "release_digest", "requirement_id", "result", "scenario_or_dataset", "signature", "threshold",
)


def requirement_register() -> dict[str, dict[str, Any]]:
    """Requirement Register v1.1 rows parsed by header name (header = row before a separator)."""
    lines = (ROOT / REGISTER_V11).read_text(encoding="utf-8").splitlines()
    out: dict[str, dict[str, Any]] = {}
    header: list[str] | None = None
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            header = None
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index + 1 < len(lines) and re.fullmatch(r"\|[\s\-:|]+\|?", lines[index + 1].strip()):
            header = cells
            continue
        rid = cells[0].strip("`")
        if header is None or not re.fullmatch(r"(BR|FR|NFR)-[0-9]{3}", rid):
            continue
        row = dict(zip(header, cells))
        values = {key: next(v for k, v in row.items() if k.startswith(key)) for key in ("Priorit", "Criteri", "Metodo", "Release")}
        out[rid] = {"line": index + 1, "priority": values["Priorit"], "acceptance": values["Criteri"], "method": values["Metodo"], "release": values["Release"]}
    if len(out) != 285:
        raise ValueError(f"Requirement Register has {len(out)} requirements, expected 285")
    return out


def method_kind(method: str) -> str:
    """NCP-S08: inspection, demonstration, benchmark or audit is not proven by an automated test case."""
    lowered = method.lower()
    has_test = bool(re.search(r"test|replay|fault|injection", lowered))
    has_other = bool(re.search(r"ispezion|inspection|dimostraz|demonstrat|benchmark|audit|analisi|review|tabletop|drill|scan|game day", lowered))
    if has_test and has_other:
        return "MIXED"
    return "AUTOMATED_TEST" if has_test else "NON_TEST_METHOD"


def fgm_requirements(register: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """FGM cases the Register acceptance criteria of FR-118 and FR-119 assign (Register v1.1 :267-268)."""
    out: dict[str, list[str]] = {f"FGM-{n:02d}": [] for n in range(1, 21)}
    for rid in ("FR-118", "FR-119"):
        text = register[rid]["acceptance"].replace("`", "")
        named = set(re.findall(r"FGM-\d{2}", text))
        for first, last in re.findall(r"FGM-(\d{2})\s*(?:\.\.|–|-|to)\s*(?:FGM-)?(\d{2})", text):
            named.update(f"FGM-{n:02d}" for n in range(int(first), int(last) + 1))
        for fgm in sorted(named):
            out[fgm].append(rid)
    return out


def apply_normative_conformance_plan(by_num: dict[int, dict[str, Any]]) -> None:
    """NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 3, unit NCP-U13 (OCOR-DEV-REM-0046):
    criteria, requirements and per-requirement cases of OCOR-DEV-0060 and 0062-0067 from
    g6_g7_proposals of the approved plan, without the requirements whose Register release
    does not include the PoC; FR-118/FR-119 bound to OCOR-DEV-0061; implementation
    allocation of NCR-PLAN-002/003. Priority, release, method and criteria come from the
    Register v1.1 only, never from the normative matrix (NCR-GOVERNANCE-002)."""
    register = requirement_register()
    proposals = json.loads((ROOT / NORMATIVE_CONFORMANCE_REGISTER).read_text(encoding="utf-8"))["g6_g7_proposals"]["tasks"]

    def poc(rid: str) -> bool:
        # "Ogni release" (NFR-073, Register v1.1 :368) includes every release, the PoC among them
        return "PoC" in register[rid]["release"] or register[rid]["release"] == "Ogni release"

    for rid, number in IMPLEMENTATION_ALLOCATION.items():
        if rid not in by_num[number]["requirement_ids"]:
            by_num[number]["requirement_ids"].append(rid)
    for rid, number in MISALLOCATED.items():
        if rid in by_num[number]["requirement_ids"]:
            by_num[number]["requirement_ids"].remove(rid)

    def case(source: dict[str, Any]) -> dict[str, Any]:
        out = dict(source)
        if out["requirement_id"] in IMPLEMENTATION_ALLOCATION:
            out["implementation_task"] = task_id(IMPLEMENTATION_ALLOCATION[out["requirement_id"]])
        return out

    for number in G6_G7_PROPOSAL_TASKS:
        task, proposal = by_num[number], proposals[task_id(number)]
        kept = [rid for rid in proposal["proposed_requirement_ids"] if poc(rid)]
        split = proposal["method_split"]
        other = len([rid for rid in split["non_test_method"] if rid in kept])
        mixed = len([rid for rid in split["mixed_test_and_method"] if rid in kept])
        criteria = []
        for criterion in proposal["proposed_acceptance_criteria"]:
            criterion = re.sub(r"is not an automated test \(\d+ here\)", f"is not an automated test ({other} here)", criterion)
            criteria.append(re.sub(r"mixed method \(\d+ here\)", f"mixed method ({mixed} here)", criterion))
        if number == 67:
            criteria.append(
                "The ledger keeps one row for each of the 285 requirements; for a requirement whose Register release does not "
                "include the PoC the row declares «fuori dal profilo PoC», without qualifying evidence. Every case carries the "
                "evidence-package fields " + ", ".join(EVIDENCE_PACKAGE_UNION) + " (NFR-004, Register v1.1 :26; LLD v1.1 §7.3 :411). "
                f"The non-conforming sealed records listed in {SEALED_EVIDENCE_REGISTRY} are not evidence of any P0 requirement, "
                "and the OCOR-DEV-0061 evidence counts only after its supersession requalification (NORMATIVE-CONFORMANCE-PLAN point 3)."
            )
        task["requirement_ids"] = kept
        task["acceptance_criteria"] = criteria
        cases = {c["requirement_id"]: c for c in proposal["requirement_cases"]}
        for rid in kept:
            # FR-119 joins OCOR-DEV-0062 through its FGM cases (FGM-16, FGM-17) and has no plan row there
            cases.setdefault(rid, {
                "acceptance_criterion": {"path": REGISTER_V11, "lines": str(register[rid]["line"])},
                "expected_evidence": f"reports/evidence/G6/{rid}.json + raw-log hash",
                "method_kind": method_kind(register[rid]["method"]),
                "priority": register[rid]["priority"],
                "register_method": register[rid]["method"],
                "release": register[rid]["release"],
                "requirement_id": rid,
            })
        task["requirement_cases"] = [case(cases[rid]) for rid in kept]
        if "ba_cases" in proposal:
            task["ba_cases"] = [
                {**ba, "requirement_ids": [r for r in ba["requirement_ids"] if poc(r)],
                 "requirement_cases": [case(c) for c in ba["requirement_cases"] if poc(c["requirement_id"])]}
                for ba in proposal["ba_cases"]
            ]
        if "fgm_cases" in proposal:
            task["fgm_cases"] = [dict(c) for c in proposal["fgm_cases"]]

    fgm = fgm_requirements(register)
    lld = (ROOT / "docs/OCOR_LLD_v1.1.md").read_text(encoding="utf-8").splitlines()
    task = by_num[61]
    for rid in ("FR-118", "FR-119"):
        if rid not in task["requirement_ids"]:
            task["requirement_ids"].append(rid)
    task["fgm_cases"] = [
        {"fgm": f"FGM-{n:02d}", "norm_ref": {"path": "docs/OCOR_LLD_v1.1.md", "lines": str(381 + n)}, "requirement_ids": fgm[f"FGM-{n:02d}"]}
        for n in range(1, 11)
    ]
    for item in task["fgm_cases"]:
        if item["fgm"] not in lld[int(item["norm_ref"]["lines"]) - 1]:
            raise ValueError(f"LLD v1.1 FGM row not found for {item['fgm']}")
    named = {rid: ", ".join(c["fgm"] for c in task["fgm_cases"] if rid in c["requirement_ids"]) for rid in ("FR-118", "FR-119")}
    criterion = (
        f"FGM cases are bound to the requirements the Register v1.1 assigns them (:267-268): FR-118 to {named['FR-118']}, "
        f"FR-119 to {named['FR-119']}; the evidence of OCOR-DEV-0061 counts for OCOR-DEV-0067 only after its supersession "
        "requalification (NORMATIVE-CONFORMANCE-PLAN point 3)."
    )
    if criterion not in task["acceptance_criteria"]:
        task["acceptance_criteria"].append(criterion)


def strategy_decision() -> dict[str, Any]:
    names = ["A_COMPONENT_FIRST", "B_FOUNDATION_FIRST", "C_RISK_FIRST_VERTICAL", "D_EVIDENCE_DERIVED_HYBRID"]
    totals = {name: 0.0 for name in names}
    records = []
    for criterion, weight, *scores in STRATEGY_CRITERIA:
        item = {"criterion": criterion, "weight": weight, "scores": {}}
        for name, score in zip(names, scores):
            contribution = weight * score / 5
            totals[name] += contribution
            item["scores"][name] = {"score": score, "weighted": round(contribution, 2)}
        records.append(item)
    return {
        "scale": "1=poor/high risk, 3=adequate, 5=strong/low risk",
        "criteria": records,
        "totals_out_of_100": {k: round(v, 2) for k, v in totals.items()},
        "selected": "D_EVIDENCE_DERIVED_HYBRID",
        "rationale": "The repository already has a narrow reference slice but lacks approved component allocation, 12 FSM transitions, real backend breadth and all governed memory. A minimal contract foundation plus disposable risk spikes and early real vertical integration retires these risks before parallel expansion.",
        "sensitivity": "D remains first when any single criterion weight changes by ±20%; C becomes competitive only if contract/regression and real-backend evidence weights are jointly reduced, a disqualifying governance posture.",
        "disqualifiers": {
            "A_COMPONENT_FIRST": "Defers cross-component and memory integration too late.",
            "B_FOUNDATION_FIRST": "Risks overbuilding foundations before TypeDB/Jena/Kafka/memory assumptions are tested.",
            "C_RISK_FIRST_VERTICAL": "Without a bounded shared kernel it can duplicate contracts across slices.",
            "D_EVIDENCE_DERIVED_HYBRID": "Disqualified if spikes are treated as final evidence or foundation expands beyond G1 contracts.",
        },
    }


def build_trace(rows: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_ws = {}
    for task in tasks:
        for rid in task["requirement_ids"]:
            if rid.startswith(("BR-", "FR-", "NFR-")):
                by_ws[rid] = task
    baseline_status = {
        "WS-00": "PARTIALLY_IMPLEMENTED", "WS-01": "PARTIALLY_IMPLEMENTED",
        "WS-02": "PARTIALLY_IMPLEMENTED", "WS-03": "ABSENT",
        "WS-04": "PARTIALLY_IMPLEMENTED", "WS-05": "ABSENT", "WS-06": "ABSENT",
        "WS-07": "PARTIALLY_IMPLEMENTED", "WS-08": "ABSENT",
        "WS-09": "PARTIALLY_IMPLEMENTED", "WS-10": "ABSENT",
        "WS-11": "DOCUMENTATION_ONLY", "WS-12": "ABSENT",
        "WS-13": "PARTIALLY_IMPLEMENTED",
    }
    result = []
    for row in rows:
        rid = row["requirement_id"]
        task = by_ws[rid]
        ws = task["workstream"]
        if ws == "WS-10":
            verification = task_id(61 if int(rid.split("-")[1]) % 2 else 62)
            test = "FGM qualifying case plus requirement-specific negative fixture"
            backend = "real memory metadata/content/full-text/vector stack"
            gate = "G6"
        elif ws == "WS-07":
            verification, test, backend, gate = task_id(63), "44-FSM positive/negative/durable-effect case", "PostgreSQL + OPA/Keycloak + action adapter", "G6"
        elif ws == "WS-11":
            verification, test, backend, gate = task_id(64), "security and non-interference fault case", "OPA/Keycloak/SPIFFE/OpenBao", "G6"
        elif ws == "WS-12":
            verification, test, backend, gate = task_id(66), "deployment/recovery/air-gap qualification", "complete offline PoC stack", "G6"
        else:
            verification, test, backend, gate = task_id(65), "requirement-bound synthetic mission-thread case", "selected real C1-C8 service stack", "G6"
        result.append({
            "requirement_id": rid,
            "source": row["source_authority"],
            "owning_workstream": ws,
            "implementation_task": task["id"],
            "verification_task": verification,
            "qualifying_test": test,
            "required_backend": backend,
            "expected_evidence": f"reports/evidence/G6/{rid}.json + raw-log hash",
            "target_gate": gate,
            "current_baseline_status": baseline_status[ws],
        })
    return result


def make_inventory_md(inventory: list[dict[str, Any]]) -> str:
    counts = Counter(item["category"] for item in inventory)
    rows = "\n".join(f"| `{i['path']}` | {i['category']} | {i['bytes']} | `{i['sha256'][:12]}` | {i['inspection']} |" for i in inventory)
    return f"""# OCOR Repository Inventory

## Scope and authority

Inventory of all {len(inventory)} files tracked at `{BASE_COMMIT}`. Planning outputs created after that immutable base are intentionally outside the base inventory and are hashed in `OCOR_PLAN_RUN_STATE.json`.

Commands: `git ls-tree -r --name-only {BASE_COMMIT}`, `git show {BASE_COMMIT}:<path>`, SHA-256 over exact Git bytes. Categories: {json.dumps(dict(sorted(counts.items())), ensure_ascii=False)}.

## Material conclusions

- Current authority is ADD v1.3 and LLD v1.1: `ocor-runtime/docs/governance_dossier/ARA_DECISION_RECORD_v1.3.md` §2–§5 at `{BASE_COMMIT}`.
- Runtime is a 0.1.0 Python reference slice: `ocor-runtime/pyproject.toml` `[project]`; executable modules are under `ocor-runtime/src/ocor_runtime/`.
- Top-level `ocor-runtime/src/c1_compiler.py` through `c8_agent.py` are compatibility exports, not independent subsystem implementations.
- Runtime FSM is `ocor-runtime/src/ocor_runtime/c5_actions.py::_SPECS` with 32 entries; approved FSM is `docs/OCOR_LLD_v1.1.md` §3.2 with 44 entries.
- Full Governed Agent Memory has no source/test symbols; `rg -i memory ...` found only Python `memoryview`, in-memory C3 text and documentation-independent noise.
- CI is concentrated in `.github/workflows/ocor-validation-closure.yml`; it does not yet express the G0–G7 planning gate topology.

## File inventory

| Path | Classification | Bytes | SHA-256 prefix | Inspection |
|---|---:|---:|---|---|
{rows}
"""


def baseline_data() -> dict[str, Any]:
    capabilities = [
        ("Canonical JSON/digest kernel", "ADD §3.0; LLD §1.1", "IMPLEMENTED_AND_VERIFIED", "ocor_runtime/canonical.py; EV-001..004 and BA-04", "Qualifying multi-language contract evidence", "Generated SDK parity", "MEDIUM"),
        ("C1 compiler/IR", "ADD §3.1; LLD §2.1", "PARTIALLY_IMPLEMENTED", "SemanticCompiler validates/canonicalizes one envelope", "DSL, type checking, releases, diff, migration, generation", "Architecture C1 exceeds current helper", "HIGH"),
        ("C2 query gateway", "ADD §3.3; LLD §2.2", "ABSENT", "Current c2_identity.py is identity registry only", "Named queries, purpose/policy planning, evidence, watermarks", "Current module label misallocates responsibility", "CRITICAL"),
        ("C3 asserted state", "ADD §§2.3/3.6; LLD §2.3", "PARTIALLY_IMPLEMENTED", "In-memory AtomicOutboxStore; PostgreSQL fallback and five live tests", "Approved full commit bindings, qualifying backend campaign", "Local live suite cannot collect without psycopg", "HIGH"),
        ("C4 projections", "ADD §2.2; LLD §2.4", "ABSENT", "Current c4_marking.py implements marking lattice only", "TypeDB/Jena adapters, watermarks, rebuild, drift", "No projection backend code", "CRITICAL"),
        ("C5 event backbone", "ADD §§2.2/3.8; LLD §2.5", "ABSENT", "Current c5_actions.py is an obsolete 32-transition action FSM", "Kafka/Strimzi, registry, replay, DLQ, quarantine", "Component naming conflicts with approved allocation", "CRITICAL"),
        ("C6 governed action engine", "ADD §4.1; LLD §§2.6/3", "PARTIALLY_IMPLEMENTED", "CapabilityAuthority plus action FSM/emission helpers in C5/C6/C7 labels", "Exact 44 transitions, Human Gate, Decision, EMISSION-FENCE, safety", "12 transitions absent and durable effects incomplete", "CRITICAL"),
        ("C7 causal runtime", "ADD §4.2; LLD §2.7", "ABSENT", "Current c7_emission.py is emission fence", "Scenario branches, interventions, counterfactuals, uncertainty, sealing", "No causal symbols/tests", "CRITICAL"),
        ("C8 governed agent kernel", "ADD §4.3; LLD §2.8", "PARTIALLY_IMPLEMENTED", "Sandbox, token budget, identify/abstain model wrapper", "AgentRun/Task/Assignment/Commitment/Handoff/Dissent and governed tools", "No durable multi-agent orchestration", "HIGH"),
        ("Full Governed Agent Memory", "DEC-208; ADD Part II; LLD §2.8.1–2.8.8", "ABSENT", "No runtime source, schema or test implementation", "All 8 kinds, 7 scopes, lifecycle, stores, retrieval, deletion, replay, promotion", "FGM-01–20 absent", "CRITICAL"),
        ("Security control plane", "ADD §5; LLD §4", "DOCUMENTATION_ONLY", "In-process marking and capability primitives", "OPA, Keycloak, SPIFFE/SPIRE, OpenBao, mTLS, dual control", "No real control-plane integration", "CRITICAL"),
        ("Deployment and recovery", "ADD §6; LLD §5", "ABSENT", "CI starts PostgreSQL service only", "Compose, Helm, observability, backup, restore, air-gap", "No deploy directory or runbooks", "HIGH"),
        ("BA-01–BA-08", "LLD §7.1", "COMPATIBILITY_ONLY", "Files named BA exercise mostly in-memory abstractions; one live PostgreSQL slice exists", "Real selected-component cases for all BA IDs", "Legacy names do not establish architectural BA evidence", "CRITICAL"),
        ("FGM-01–FGM-20", "LLD §7.2", "ABSENT", "Only documented future oracles", "Twenty qualifying real-backend cases", "Full-memory runtime remains NO-GO", "CRITICAL"),
        ("Synthetic mission thread", "LLD §7.3", "COMPATIBILITY_ONLY", "EV-035 is an in-process Python path using no C2 gateway/C4/C5/C7 causal/memory services", "Real selected-service C1-C8+memory thread", "Current test name cannot prove full architecture", "CRITICAL"),
        ("CI merge prevention", "Repository workflows", "UNKNOWN", "PR workflow exists and ran green on DEC-209; branch-protection API returned HTTP 403", "Explicit G0-G7 jobs, no mandatory skip, readable/enforced protection rules", "Current workflow mixes legacy runtime/document gates and enforcement cannot be proven", "HIGH"),
    ]
    return {
        "schema_version": "1.0",
        "base_commit": BASE_COMMIT,
        "authority": {"DEC-209": "effective", "IRB": "APPROVED_DESIGN", "ADD": "v1.3", "LLD": "v1.1", "runtime_conformance": "NOT_ESTABLISHED_NO_GO", "E1": 0, "E2": 0, "global_verified": 0},
        "environment": {
            "python_host": "3.14.4", "python_runtime_venv": "3.12.14", "pytest": "9.1.1",
            "jsonschema": "4.26.0", "openapi_spec_validator": "0.9.0", "grpcio_tools": "1.83.1",
            "docker": "29.7.2", "node": "20.20.2",
            "unavailable": ["psycopg in local runtime venv", "markdownlint", "mmdc", "mypy", "bandit", "trivy", "syft", "grype"],
        },
        "executions": [
            {"command": "sha256sum -c inputs/normative/SHA256SUMS", "exit_code": 0, "pass": 8, "fail": 0, "skipped": 0, "not_executed": 0, "duration_seconds": "<1", "reproducible": True},
            {"command": "./.venv/bin/python3 scripts/verify.py --json", "exit_code": 0, "pass": 14, "fail": 0, "skipped": 0, "not_executed": 0, "duration_seconds": "<1", "reproducible": True},
            {"command": "ocor-runtime/.venv/bin/python -m pytest -q -rA", "exit_code": 2, "pass": 0, "fail": 1, "skipped": 0, "not_executed": 5, "duration_seconds": 0, "reproducible": True, "detail": "collection error: ModuleNotFoundError psycopg; five live PostgreSQL tests not collected"},
            {"command": "ocor-runtime/.venv/bin/python -m pytest -q -rA --ignore=tests/integration/test_postgres_outbox_live.py", "exit_code": 0, "pass": 104, "fail": 0, "skipped": 0, "not_executed": 5, "duration_seconds": 0.35, "reproducible": True},
        ],
        "runtime_fsm": {"implemented_transition_count": 32, "approved_transition_count": 44, "status": "PARTIALLY_IMPLEMENTED", "evidence": "ocor-runtime/src/ocor_runtime/c5_actions.py::_SPECS vs docs/OCOR_LLD_v1.1.md §3.2"},
        "capabilities": [
            {
                "capability": item[0],
                "required_by": item[1],
                "status": item[2],
                "current_implementation": item[3],
                "current_evidence": item[4],
                "missing_evidence": item[5],
                "gap": item[5],
                "risk": item[6],
            }
            for item in capabilities
        ],
    }


def baseline_md(data: dict[str, Any]) -> str:
    table = "\n".join(
        f"| {c['capability']} | {c['required_by']} | `{c['status']}` | {c['current_implementation']} | {c['current_evidence']} | {c['missing_evidence']} | {c['gap']} | {c['risk']} |"
        for c in data["capabilities"]
    )
    return f"""# OCOR Current State Baseline

## Verdict

The documentation chain is approved at design level, but runtime conformance is `NOT_ESTABLISHED / NO-GO`. The current code is a small Python reference/compatibility slice, not the approved C1–C8 PoC topology.

At `{BASE_COMMIT}`, immutable-input checks are 8 PASS and the document harness is 14 PASS. The complete local pytest command has 1 collection FAIL (`psycopg` missing), which prevents 5 live PostgreSQL tests from executing. The materially different non-live command has 104 PASS, 0 FAIL, 0 SKIPPED; the 5 live cases remain `NOT_EXECUTED`, never PASS.

## Capability baseline

| Capability | Required by | Status | Current implementation | Current evidence | Missing evidence | Gap | Risk |
|---|---|---|---|---|---|---|---|
{table}

## Evidence interpretation

- `ocor-runtime/tests/acceptance_ev/test_ev_029_035_fence_agent_e2e.py::test_ev_035...` is in-process and does not traverse approved real C2, C4, C5, C7 or memory services; it is `COMPATIBILITY_ONLY` for the final mission thread.
- `ocor-runtime/tests/backend_assumptions/` names BA cases, but most use `AtomicOutboxStore` or fakes. They are preparatory tests, not qualifying BA-01–BA-08 selected-component evidence.
- `.github/workflows/ocor-validation-closure.yml` previously ran a live PostgreSQL job, but DEC-209 explicitly excludes legacy runtime/BA/EV steps from its evidence scope.
- No `FGM-*` runtime test files or memory implementation modules exist. Therefore Full Governed Agent Memory remains `NO-GO`.
- `gh api repos/nepryoon/ocor-detailed-design/branches/main/protection` returned HTTP 403; merge-blocking protection is `UNKNOWN`, not inferred from prior green runs.
"""


def plan_md(backlog: dict[str, Any], tasks: list[dict[str, Any]]) -> str:
    strategy = backlog["strategy_decision"]
    strategy_rows = "\n".join(
        f"| {c['criterion']} | {c['weight']} | {c['scores']['A_COMPONENT_FIRST']['score']} | {c['scores']['B_FOUNDATION_FIRST']['score']} | {c['scores']['C_RISK_FIRST_VERTICAL']['score']} | {c['scores']['D_EVIDENCE_DERIVED_HYBRID']['score']} |"
        for c in strategy["criteria"]
    )
    gate_rows = "\n".join(
        f"| {gid} | {', '.join(g['required_tasks'])} | {g['entry']} | {g['exit']} | {', '.join(g['required_tests'])} | {', '.join(g['services'])} | `{g['evidence']}` | {g['rollback']} | {g['failure']} | {g['authority']} | {g['prohibited']} |"
        for gid, g in backlog["gates"].items()
    )
    wave_counts = Counter(t["parallel_wave"] for t in tasks)
    wave_rows = "\n".join(f"| {wave} | {count} | {min(count, 6 if wave > 2 else 3)} |" for wave, count in sorted(wave_counts.items()))
    cp = backlog["graph_analysis"]["critical_path"]
    return f"""# OCOR AI-First Development Plan

## Control and outcome

Base: `{BASE_COMMIT}` (`origin/main`, expected=actual). Authority: DEC-209, ADD v1.3 and LLD v1.1. This is an implementation plan only: runtime conformance, PoC-GO, E1/E2 and Production readiness remain unchanged and `NO-GO` where applicable.

## Factual baseline

The repository contains 247 base files, a Python 0.1.0 reference slice and 104 locally executable non-live tests. The current component labels are historical compatibility surfaces: C2 is identity-only, C4 is marking-only, C5 hosts a 32-transition action FSM, C6 is leases, C7 is emission fencing and C8 is a sandbox/model wrapper. Approved C2/C4/C5/C7 duties, 12 of 44 C6 transitions, real-service breadth and all Full Governed Agent Memory are absent. See `reports/planning/OCOR_CURRENT_STATE_BASELINE.md`.

## Strategy decision

Scores use 1 (poor/high risk) to 5 (strong/low risk); weights total 100.

| Criterion | Weight | A component-first | B foundation-first | C risk-first vertical | D evidence-derived hybrid |
|---|---:|---:|---:|---:|---:|
{strategy_rows}
| **Weighted total** | **100** | **{strategy['totals_out_of_100']['A_COMPONENT_FIRST']}** | **{strategy['totals_out_of_100']['B_FOUNDATION_FIRST']}** | **{strategy['totals_out_of_100']['C_RISK_FIRST_VERTICAL']}** | **{strategy['totals_out_of_100']['D_EVIDENCE_DERIVED_HYBRID']}** |

Selected: **D — evidence-derived hybrid**. It constrains shared foundation to canonical contracts and evidence mechanics, executes 13 real-service/fidelity spikes before irreversible choices, establishes an early real C1–C8 thread, then expands in bounded vertical increments. Sensitivity: {strategy['sensitivity']}

Disqualifiers: A defers integration; B overbuilds before backend proof; C risks duplicated contracts; D is invalid if spike results are promoted as final evidence.

## Workstreams

All WS-00–WS-13 are represented in the {len(tasks)}-task backlog. WS-00 protects deterministic delivery; WS-01 fixes cross-cutting contracts; WS-02..WS-09 implement C1..C8; WS-10 implements all governed memory; WS-11 integrates security; WS-12 owns deployment/recovery; WS-13 owns independent verification and evidence.

## Gates

| Gate | Required tasks | Entry | Exit | Required tests | Real services | Evidence | Rollback | Failure path | Promotion authority | Prohibited claims |
|---|---|---|---|---|---|---|---|---|---|---|
{gate_rows}

The separate Production campaign is deliberately absent from implementation tasks: production scale, HA, multi-region, Production SLO and E2 remain out of PoC conformance.

## Dependency and parallelisation model

The machine DAG has {backlog['graph_analysis']['parallel_waves']} waves. Critical path ({backlog['graph_analysis']['critical_path_duration_days']} nominal agent-days): `{' → '.join(cp)}`. Near-critical paths run through TypeDB/Jena/Kafka and the memory deletion/restore chain; they converge at `OCOR-DEV-0065` and must not be delayed behind component-local polish.

| Wave | Ready tasks | Maximum safe concurrency |
|---:|---:|---:|
{wave_rows}

Shared-file collision zones are canonical contracts, evidence manifests, C3 migrations, C6 FSM tables and deployment charts. They have one owner per wave; other tasks consume versioned interfaces. Isolated worktrees are recommended for every dependency-ready task except integration barriers 0031, 0049, 0065 and 0067–0069.

Conditional governance decisions are mandatory after any G2 failure that would change PostgreSQL/C3, TypeDB, Jena, Kafka, security-control or vector-index semantics; after any mismatch between the LLD 44-transition table and executable interpretation; and before any replacement of a Candidate Implementation. The decision input is the failed spike manifest, not an agent preference.

## AI-first execution and cost model

Use task-specific context manifests and source hashes; read normative excerpts plus owned ports/tests, not the whole repository. Run narrow tests before service suites; stop after two materially different repairs and escalate normative conflicts.

- Optimistic: 1.6–2.2M model tokens, 250–400 CPU-h, 180–300 real-service hours.
- Expected: 2.8–4.2M tokens, 400–750 CPU-h, 300–650 service hours, 10–40 optional GPU-h for embedding fixtures.
- Conservative: 5.5–8.0M tokens, 800–1,400 CPU-h, 700–1,400 service hours, 20–80 GPU-h.

Assumptions: frontier coding model for contracts, C3/C6, causal, security and memory lifecycle; smaller coding model for isolated adapters, fixtures, manifests and documentation. Main cost drivers are retries across real services, non-interference timing, deletion/restore fault matrices and integration failures. Recommended concurrency is 3 agents before G3, 4–6 in G4, 3 in G5 and 2 plus an independent reviewer in G6/G7.

## Governance and rollback

No task may edit `inputs/`, ADD v1.3 or LLD v1.1. Technology-changing spike outcomes require a governed decision. Every merge uses a task branch, structured handoff, independent review, integration branch and mandatory CI. Evidence generation records commit/environment/command/inputs/hashes; the generating code path is never the sole independent verifier. Rollback uses revert commits and forward-compatible migrations—never history rewrite or force-push.
"""


def harness_md() -> str:
    roles = {
        "Delivery Coordinator": "Select dependency-ready tasks, own task ledger and integration barriers; cannot waive red gates.",
        "Contract and Shared-Kernel Agent": "Own WS-01 and generated boundaries; cannot select backend semantics.",
        "Component Implementation Agent": "Own one C1-C8 task/file area; cannot edit other components or approved design.",
        "Governed Memory Agent": "Own WS-10; cannot defer any kind/scope/lifecycle or bypass C6/C3.",
        "Security and Policy Agent": "Own WS-11 and cross-compartment review; cannot add permit-on-failure paths.",
        "Infrastructure and Operations Agent": "Own WS-12 and disposable services; cannot promote environment availability as conformance.",
        "Verification and Evidence Agent": "Own qualifying fixtures/manifests; cannot accept mocks/skips as final evidence.",
        "Integration Agent": "Own integration branches and collision zones; cannot bypass branch protection.",
        "Independent Conformance Reviewer": "Reproduce G6/G7 evidence without using implementation summaries as sole evidence; cannot author implementation under review.",
    }
    role_rows = "\n".join(f"| {r} | {scope} | Hash-bound handoff, commands, results, risks, rollback | Missing authority, normative conflict, two failed repairs, mandatory service unavailable |" for r, scope in roles.items())
    return f"""# OCOR Autonomous Execution Harness

## Dispatch loop

1. Verify `origin/main`, approved artifact hashes, clean task worktree and current `OCOR_PLAN_RUN_STATE.json`.
2. Validate the backlog; select only tasks whose hard dependencies have accepted evidence.
3. Materialize the task context pack from `OCOR_AGENT_CONTEXT_MANIFEST.json`; reject hash drift.
4. Create `task/<ID>-<slug>` from the current integration branch; never reuse a dirty worktree.
5. Implement only `expected_file_areas`; a pre-commit guard rejects `prohibited_file_areas`.
6. Run named narrow positive/negative/fault checks, then integration checks. Record nonzero exits and at most two materially different repairs.
7. Emit `reports/evidence/<gate>/<ID>.json`, raw logs and a structured handoff with commit, commands, environment, hashes, limitations and rollback.
8. Independent review checks requirement, contract, negative-test, real-backend and evidence coverage.
9. Integration Agent incorporates through the gate integration branch and runs mandatory CI. Red, skipped-mandatory or unavailable results return to repair.
10. Promote only when the gate authority accepts the exact green commit; never infer E1, PoC-GO or Production readiness.

## Logical roles

| Role | Allowed/prohibited scope | Output contract and validation | Escalation |
|---|---|---|---|
{role_rows}

## Handoff schema

Each handoff contains `task_id`, `base_sha`, `head_sha`, `context_manifest_sha256`, changed paths, requirement IDs, test commands with exit/pass/fail/skip/not-executed counts, raw evidence hashes, migration/rollback result, security/observability notes, assumptions and unresolved blockers. A field omission is a failed handoff.

## Git and repair protocol

Use isolated worktrees and non-force task branches. Do not stash or discard user changes. Rebase only before review; after evidence sealing, merge without rewriting the task commit. Concurrent agents may not own the same exact file area in one wave. Two failed repair cycles, a normative conflict, a real-service blocker or an architecture substitution ends local retry and creates an escalation record. Rollback is a new revert commit plus explicit data forward/down procedure.

## Completion rule

G7 can prepare a PoC-GO candidate only after all 285 mappings, 44 transitions, BA-01–08, FGM-01–20, memory taxonomy/scopes/lifecycle, mission thread and recovery tests are qualifying and reproducible. A candidate is not approval. Production remains a separate campaign.
"""


def risk_md(tasks: list[dict[str, Any]]) -> str:
    sections = ["# OCOR Risk and Spike Register", "", "Spikes retire assumptions; they never constitute final implementation or PoC evidence. Time/token/compute figures are planning ranges.", ""]
    for number, details in SPIKE_DETAILS.items():
        hypothesis, risk, classification, environment, fixtures, success, failure, decision, tokens, compute = details
        task = next(t for t in tasks if t["id"] == task_id(number))
        sections.extend([
            f"## SPIKE-{number - 14:02d} — {task['title'].removeprefix('SPIKE ')}",
            "",
            f"- Task: `{task['id']}`; hypothesis: {hypothesis}",
            f"- Evidence/risk: baseline at `{BASE_COMMIT}` shows the corresponding approved responsibility absent or compatibility-only; retires **{risk}**.",
            f"- Minimum implementation/classification: only the adapter and fault harness needed for the oracle; **{classification}**.",
            f"- Environment/fixtures: {environment}; {fixtures}.",
            "- Test procedure: run the task validation commands against pinned real services, inject each named fault, hash raw logs and rerun from a clean state.",
            f"- Success oracle: {success}. Failure oracle: {failure}.",
            f"- Result decision: {decision}. Failure consequence: block dependent task and create an ARA decision item if architecture would change.",
            f"- Dependencies: {', '.join(task['hard_dependencies'])}; time budget {task['expected_duration_days']} agent-days; token budget {tokens}; compute {compute}.",
            f"- Stop condition: first conclusive success/failure after at most two repair variants. Required evidence: `{task['evidence_outputs'][0]}` plus raw log hash.",
            "",
        ])
    return "\n".join(sections)


def context_manifest(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    roles = ["Delivery Coordinator", "Contract and Shared-Kernel Agent", "Component Implementation Agent", "Governed Memory Agent", "Security and Policy Agent", "Infrastructure and Operations Agent", "Verification and Evidence Agent", "Integration Agent", "Independent Conformance Reviewer"]
    return {
        "schema_version": "1.0", "base_commit": BASE_COMMIT,
        "normative_core": [
            {"path": "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md", "sha256": sha256(ROOT / "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md")},
            {"path": "docs/OCOR_LLD_v1.1.md", "sha256": sha256(ROOT / "docs/OCOR_LLD_v1.1.md")},
            {"path": "reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json", "sha256": sha256(ROOT / "reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json")},
        ],
        "roles": [{"role": role, "required_context": ["AGENTS.md", "task record", "normative anchors", "owned source/tests", "dependency handoffs"], "output_contract": "structured handoff plus evidence manifest", "max_context_tokens": 60000 if role in {"Delivery Coordinator", "Independent Conformance Reviewer"} else 40000} for role in roles],
        "tasks": [_task_context_entry(t) for t in tasks],
    }


def _task_context_entry(t: dict[str, Any]) -> dict[str, Any]:
    # WS-12 ("Deployment, operations and recovery") also covers two ordinary
    # TASK_SPECS tasks (6, 49) that use the generic formula below -- only
    # the WS12_TASK_SPECS-generated infrastructure-bootstrap-repair tasks
    # (OCOR-DEV-0070..0084) were adopted with a concrete "Infrastructure and
    # Operations Agent" role, a smaller fixed token budget, and a
    # services-lock/area/strategy-doc path order distinct from
    # bounded_agent_context_pack's own storage order -- reproduced exactly
    # rather than folded into the generic formula.
    if 70 <= int(t["id"][-4:]) <= 84:
        services_lock, strategy_doc, area = t["bounded_agent_context_pack"]
        return {
            "task_id": t["id"],
            "role": "Infrastructure and Operations Agent",
            "paths": ["AGENTS.md", services_lock, area, strategy_doc],
            "max_input_tokens": 30000,
            "source_hash_policy": "resolve at dispatch; reject drift from integration HEAD",
            "exclusions": t["prohibited_file_areas"],
        }
    role = "Governed Memory Agent" if t["workstream"] == "WS-10" else "Verification and Evidence Agent" if t["workstream"] == "WS-13" else "Component Implementation Agent"
    return {
        "task_id": t["id"],
        "role": role,
        "paths": sorted({"AGENTS.md", *t["bounded_agent_context_pack"]}),
        "max_input_tokens": t["ai_token_estimate"]["input_context"][1],
        "source_hash_policy": "resolve at dispatch; reject drift from integration HEAD",
        "exclusions": t["prohibited_file_areas"],
    }


def backlog_schema() -> dict[str, Any]:
    required = ["id", "title", "workstream", "delivery_gate", "objective", "rationale", "requirement_ids", "normative_references", "affected_components", "expected_file_areas", "prohibited_file_areas", "hard_dependencies", "soft_dependencies", "parallel_group", "integration_point", "preconditions", "bounded_agent_context_pack", "assumptions", "implementation_procedure", "migration_and_compatibility_procedure", "required_test_levels", "validation_commands", "acceptance_criteria", "negative_acceptance_criteria", "evidence_outputs", "rollback_procedure", "security_considerations", "observability_requirements", "expected_duration_days", "ai_token_estimate", "compute_estimate", "uncertainty", "confidence", "failure_and_escalation_conditions", "definition_of_done", "coverage", "parallel_wave"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:ocor:development-backlog:1.0", "type": "object", "additionalProperties": False,
        "required": ["schema_version", "plan_id", "base_commit", "selected_strategy", "strategy_decision", "workstreams", "gates", "tasks", "graph_analysis"],
        "properties": {
            "schema_version": {"const": "1.0"}, "plan_id": {"type": "string"}, "base_commit": {"pattern": "^[0-9a-f]{40}$"}, "selected_strategy": {"const": "D_EVIDENCE_DERIVED_HYBRID"},
            "strategy_decision": {"type": "object"}, "workstreams": {"type": "object"}, "gates": {"type": "object"}, "graph_analysis": {"type": "object"},
            "tasks": {"type": "array", "minItems": 1, "items": {"type": "object", "required": required, "properties": {"id": {"pattern": "^OCOR-DEV-[0-9]{4}$"}, "title": {"type": "string", "minLength": 5}, "workstream": {"pattern": "^WS-(0[0-9]|1[0-3])$"}, "delivery_gate": {"pattern": "^G[0-7]$"}, "expected_duration_days": {"type": "integer", "minimum": 1}, "confidence": {"type": "number", "minimum": 0, "maximum": 1}}, "additionalProperties": True}},
        },
    }


def dag_text(tasks: list[dict[str, Any]], critical: list[str]) -> str:
    lines = ["flowchart LR"]
    for task in tasks:
        label = task["title"].replace('"', "'")
        lines.append(f'  {task["id"].replace("-", "_")}["{task["id"]}<br/>{label}"]')
    for task in tasks:
        for dep in task["hard_dependencies"]:
            lines.append(f'  {dep.replace("-", "_")} --> {task["id"].replace("-", "_")}')
    lines.append("  classDef critical fill:#ffdddd,stroke:#b00020,stroke-width:2px")
    lines.append("  class " + ",".join(item.replace("-", "_") for item in critical) + " critical")
    return "\n".join(lines)


def main() -> None:
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    matrix = json.loads((ROOT / "reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json").read_text(encoding="utf-8"))
    rows = matrix["rows"]
    inventory = tracked_inventory()
    tasks = build_tasks(rows)
    order, waves, critical, duration = topological(tasks)
    gates = {
        gid: {
            **gate,
            "required_tasks": [task["id"] for task in tasks if task["delivery_gate"] == gid],
            "required_tests": GATE_TESTS[gid],
        }
        for gid, gate in GATES.items()
    }
    backlog = {
        "schema_version": "1.0", "plan_id": RUN_ID, "base_commit": BASE_COMMIT,
        "selected_strategy": "D_EVIDENCE_DERIVED_HYBRID", "strategy_decision": strategy_decision(),
        "workstreams": WORKSTREAMS, "gates": gates, "tasks": tasks,
        "graph_analysis": {"topological_order": order, "parallel_waves": max(waves.values()), "critical_path": critical, "critical_path_duration_days": duration, "near_critical_paths": ["OCOR-DEV-0017/0018 → 0034/0037/0038 → 0039 → 0065", "OCOR-DEV-0019 → 0040 → 0041 → 0065", "OCOR-DEV-0025 → 0026 → 0056 → 0062 → 0065"]},
    }
    trace = build_trace(rows, tasks)
    base = baseline_data()
    write_json(REPORT_DIR / "OCOR_REPOSITORY_INVENTORY.json", {"schema_version": "1.0", "base_commit": BASE_COMMIT, "tracked_file_count": len(inventory), "classification_counts": dict(Counter(i["category"] for i in inventory)), "files": inventory})
    write_text(REPORT_DIR / "OCOR_REPOSITORY_INVENTORY.md", make_inventory_md(inventory))
    write_json(REPORT_DIR / "OCOR_CURRENT_STATE_BASELINE.json", base)
    write_text(REPORT_DIR / "OCOR_CURRENT_STATE_BASELINE.md", baseline_md(base))
    write_json(PLAN_DIR / "OCOR_IMPLEMENTATION_BACKLOG.json", backlog)
    write_json(PLAN_DIR / "OCOR_IMPLEMENTATION_BACKLOG.schema.json", backlog_schema())
    write_text(PLAN_DIR / "OCOR_DEPENDENCY_DAG.mmd", dag_text(tasks, critical))
    write_text(PLAN_DIR / "OCOR_AI_FIRST_DEVELOPMENT_PLAN.md", plan_md(backlog, tasks))
    write_text(PLAN_DIR / "OCOR_AUTONOMOUS_EXECUTION_HARNESS.md", harness_md())
    write_text(PLAN_DIR / "OCOR_RISK_AND_SPIKE_REGISTER.md", risk_md(tasks))
    write_json(PLAN_DIR / "OCOR_AGENT_CONTEXT_MANIFEST.json", context_manifest(tasks))
    trace_path = PLAN_DIR / "OCOR_TRACEABILITY_PLAN.csv"
    with trace_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trace[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(trace)

    state_path = REPORT_DIR / "OCOR_PLAN_RUN_STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update({"updated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "completed_phase": "DECOMPOSE", "validation_status": "PENDING_VALIDATION"})
    artifacts = [
        PLAN_DIR / "OCOR_AI_FIRST_DEVELOPMENT_PLAN.md", PLAN_DIR / "OCOR_AUTONOMOUS_EXECUTION_HARNESS.md",
        PLAN_DIR / "OCOR_IMPLEMENTATION_BACKLOG.json", PLAN_DIR / "OCOR_IMPLEMENTATION_BACKLOG.schema.json",
        PLAN_DIR / "OCOR_DEPENDENCY_DAG.mmd", PLAN_DIR / "OCOR_RISK_AND_SPIKE_REGISTER.md",
        PLAN_DIR / "OCOR_TRACEABILITY_PLAN.csv", PLAN_DIR / "OCOR_AGENT_CONTEXT_MANIFEST.json",
        REPORT_DIR / "OCOR_REPOSITORY_INVENTORY.md", REPORT_DIR / "OCOR_REPOSITORY_INVENTORY.json",
        REPORT_DIR / "OCOR_CURRENT_STATE_BASELINE.md", REPORT_DIR / "OCOR_CURRENT_STATE_BASELINE.json",
        ROOT / "scripts/build_ocor_development_plan.py",
    ]
    state["artifact_hashes"] = {str(path.relative_to(ROOT)): sha256(path) for path in artifacts}
    write_json(state_path, state)


if __name__ == "__main__":
    main()
