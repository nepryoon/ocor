#!/usr/bin/env python3
"""Validate the post-PoC plan without touching the approved plan.

The builder is pure: ``build_documents`` reads the Register, the traceability
plan and the approved workstream catalogue, and returns the four plan
documents. ``--write`` is the only path that creates files. Nothing here
starts a task, edits ``inputs/`` or promotes a claim.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

PLAN_ID = "OCOR-POST-POC-PLAN-20261112"
BASELINE_COMMIT = "2278be4180de5d91d1fec9d7608027b0f287b545"
SCHEMA_VERSION = "1.0"
POST_POC = Path("docs/development_plan/post_poc")
REGISTER_REL = (
    "ocor-runtime/docs/governance_dossier/registers/"
    "OCOR_Requirement_Register_v1.1_APPROVED.md"
)
TRACE_REL = "docs/development_plan/OCOR_TRACEABILITY_PLAN.csv"
APPROVED_BACKLOG_REL = "docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json"
STATE_REL = "reports/development/EXECUTION_STATE.json"
CONFORMANCE_REL = "reports/development/NORMATIVE_CONFORMANCE_REGISTER.json"
README_REL = POST_POC / "README.md"
DECISION_REL = Path(
    "reports/development/decision_requests/POST-POC-BACKLOG-ACTIVATION.md"
)
DOCUMENT_FILES = {
    "allocation": POST_POC / "OCOR_POST_POC_REQUIREMENT_ALLOCATION.json",
    "backlog": POST_POC / "OCOR_POST_POC_BACKLOG.json",
    "external": POST_POC / "OCOR_POST_POC_EXTERNAL_DECISIONS.json",
    "graph": POST_POC / "OCOR_POST_POC_DEPENDENCY_GRAPH.json",
}

ID_HEADERS = {"id", "id temporaneo", "temp id"}
REQUIREMENT_ID = re.compile(r"^(BR|FR|NFR|IRB)-(\d+)$")
PREFIX_ORDER = {"BR": 0, "FR": 1, "NFR": 2, "IRB": 3}
WAVE = {
    "G8": {"REALISE": 1, "VERIFY": 2},
    "G9": {"REALISE": 3, "VERIFY": 4},
    "G10": {"REALISE": 5, "VERIFY": 6},
    "G11": {"REALISE": 7, "VERIFY": 8},
}
PREVIOUS_GATE = {"G9": "G8", "G10": "G9", "G11": "G10"}
EMPTY_ADOPTED = {
    "G-1",
    "G-3",
    "G-5",
    "G-6",
    "G-9-FUNCTIONAL",
    "G-9-OPERATIONAL",
}
PROHIBITED_CLAIMS = (
    "Production readiness: GO",
    "PoC-GO",
    "Verified=1",
    "E1=1",
    "E2=1",
    "runtime conformance is established",
)
G6_POSITIVE = "Causal discovery emits only tainted DecisionProposal hypotheses."
G6_NEGATIVE = (
    "A proposed relation is written into a registered causal model "
    "or into canonical state without the governed path."
)
G2_POSITIVE = (
    "The A2A contracts of FR-048 are realised only as a boundary adapter "
    "behind C8, after the Product Owner decision on G7, and stay optional."
)
G2_NEGATIVE = (
    "An external agent reaches the Agent Kernel without the C8 boundary, "
    "or A2A is enabled before the Product Owner decision on G7."
)
FR048_SDK_POSITIVE = (
    "Additional SDKs of FR-048, including Rust, keep a capability contract "
    "and a conformance profile for each language and protocol before "
    "implementation."
)
FR048_A2A_ONLY_RESTRICTION = "FR-048 is realised only as an A2A"
# Blobs of BASELINE_COMMIT, from `git show BASELINE_COMMIT:<path> | sha256sum`.
# Regeneration does not read these files. A later state sync must not turn
# this validator red. The Register, the traceability plan and the approved
# backlog stay live inputs.
BASELINE_SOURCE_SHA256 = {
    CONFORMANCE_REL: (
        "c06247d39f7cdeb7068ff08bee694e0f7878a84776fa123866d767b6558a2dae"
    ),
    STATE_REL: (
        "3ad7d014785323c61930f518339630dc46494cae4bd17a2f24735df0b82e4256"
    ),
}
REQUIRED_DECISIONS = (
    "G5-BENCHMARK-PREREGISTRATION",
    "G7-PO-DECISION",
    "POST-POC-BACKLOG-ACTIVATION",
)
REQUIRED_TASK_FIELDS = (
    "acceptance_criteria",
    "adopted_item",
    "affected_components",
    "ai_token_estimate",
    "assumptions",
    "bounded_agent_context_pack",
    "compute_estimate",
    "confidence",
    "coverage",
    "definition_of_done",
    "delivery_gate",
    "evidence_outputs",
    "expected_duration_days",
    "expected_file_areas",
    "failure_and_escalation_conditions",
    "hard_dependencies",
    "id",
    "implementation_procedure",
    "integration_point",
    "migration_and_compatibility_procedure",
    "negative_acceptance_criteria",
    "normative_references",
    "objective",
    "observability_requirements",
    "parallel_group",
    "parallel_wave",
    "preconditions",
    "prohibited_file_areas",
    "rationale",
    "required_test_levels",
    "requirement_ids",
    "rollback_procedure",
    "security_considerations",
    "soft_dependencies",
    "status",
    "title",
    "uncertainty",
    "validation_commands",
    "workstream",
)
TOKEN_ESTIMATE = {
    "confidence_interval": (
        "-25%/+60%; higher for real-service and fault-injection tasks"
    ),
    "implementation": [15000, 36000],
    "input_context": [15600, 28000],
    "likely_retries": [1, 2],
    "review_and_repair": [8400, 21600],
}
DEFINITION_OF_DONE = [
    "Named acceptance and negative criteria are observed",
    "Required validations exit zero with no mandatory skip",
    "Independent review accepts hashes and trace links",
    "Rollback drill or mechanically reviewed rollback is recorded",
]
COVERAGE: dict[str, list[str]] = {
    "ba_campaigns": [],
    "components": [],
    "fgm_campaigns": [],
    "fsm_transitions": [],
    "memory_kinds": [],
    "memory_lifecycle": [],
    "memory_scopes": [],
}


def is_beyond_poc(release: str) -> bool:
    """Return whether a Register release is outside the PoC profile."""
    return release.strip() != "PoC"


def assign_gate(release: str, type_cell: str) -> str:
    """Assign the single owning gate. The latest stage wins."""
    kind = type_cell.strip().lower()
    if (
        "Production" in release
        or "Future" in release
        or release.strip() == "Ogni release"
    ):
        return "G11"
    if kind == "br":
        return "G8"
    if kind in {"fr", "funzionale"}:
        return "G9"
    if kind == "nfr" or "non funz" in kind:
        return "G10"
    raise ValueError(f"unclassified requirement {type_cell!r} / {release!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"{path} is not a JSON object")
    return cast(dict[str, Any], raw)


def _split_row(line: str) -> list[str]:
    text = line.strip()
    if not text.startswith("|"):
        return []
    return [cell.strip() for cell in text.strip("|").split("|")]


def _separator(cells: Sequence[str]) -> bool:
    return bool(cells) and all(set(cell) <= set("-: ") and cell for cell in cells)


def _column(headers: Sequence[str], predicate: Any) -> int:
    for index, name in enumerate(headers):
        if predicate(name):
            return index
    raise ValueError(f"missing column in {headers}")


def _cell(cells: Sequence[str], index: int) -> str:
    if index >= len(cells):
        return ""
    return cells[index].strip().strip("`").strip()


def load_register(root: Path) -> list[dict[str, Any]]:
    """Parse every requirement row of Register v1.1."""
    columns: dict[str, int] | None = None
    found: dict[str, dict[str, Any]] = {}
    text = (root / REGISTER_REL).read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), start=1):
        cells = _split_row(line)
        if not cells:
            columns = None
            continue
        if _separator(cells):
            continue
        folded = [cell.lower() for cell in cells]
        if any(name in ID_HEADERS for name in folded):
            columns = {
                "id": _column(folded, lambda name: name in ID_HEADERS),
                "title": _column(folded, lambda name: name.startswith("titolo")),
                "type": _column(folded, lambda name: name == "tipo"),
                "priority": _column(
                    folded, lambda name: name.startswith("priorit")
                ),
                "acceptance": _column(
                    folded, lambda name: "accettazione" in name
                ),
                "method": _column(folded, lambda name: name.startswith("metodo")),
                "release": _column(folded, lambda name: "release" in name),
            }
            continue
        if columns is None:
            continue
        identifier = _cell(cells, columns["id"])
        if REQUIREMENT_ID.fullmatch(identifier) is None:
            continue
        if identifier in found:
            raise ValueError(f"duplicate requirement {identifier}")
        found[identifier] = {
            "acceptance": _cell(cells, columns["acceptance"]),
            "id": identifier,
            "line": line_number,
            "method": _cell(cells, columns["method"]),
            "priority": _cell(cells, columns["priority"]),
            "release": _cell(cells, columns["release"]),
            "title": _cell(cells, columns["title"]),
            "type": _cell(cells, columns["type"]),
        }
    return sorted(found.values(), key=lambda item: _requirement_key(item["id"]))


def load_traceability(root: Path) -> dict[str, dict[str, str]]:
    """Index the traceability plan by requirement identifier."""
    traced: dict[str, dict[str, str]] = {}
    with (root / TRACE_REL).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            identifier = row.get("requirement_id") or ""
            if not identifier:
                continue
            traced[identifier] = {
                "register_method": row.get("register_method") or "",
                "register_release": row.get("register_release") or "",
                "workstream": row.get("owning_workstream") or "",
            }
    return traced


def load_workstreams(root: Path) -> dict[str, str]:
    """Return the approved workstream catalogue. The file is not rewritten."""
    raw = _load_json(root / APPROVED_BACKLOG_REL).get("workstreams")
    if not isinstance(raw, dict):
        raise ValueError("approved backlog has no workstreams")
    catalogue: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("workstream catalogue is not a string map")
        catalogue[key] = value
    return catalogue


def _requirement_key(identifier: str) -> tuple[int, int, str]:
    prefix, number = identifier.split("-", 1)
    return (PREFIX_ORDER.get(prefix, 9), int(number), identifier)


def _source_hashes(root: Path) -> dict[str, str]:
    """Hash live normative inputs and pin state files to the baseline commit."""
    hashes = {
        relative: _sha256(root / relative)
        for relative in (
            APPROVED_BACKLOG_REL,
            REGISTER_REL,
            TRACE_REL,
        )
    }
    hashes.update(BASELINE_SOURCE_SHA256)
    return hashes


def _common_task(
    *,
    task_id: str,
    title: str,
    gate: str,
    workstream: str,
    role: str,
    objective: str,
    rationale: str,
    requirement_ids: list[str],
    adopted_item: str | None,
    acceptance: list[str],
    negative: list[str],
) -> dict[str, Any]:
    duration = 3 if adopted_item and adopted_item != "G-2" else max(
        2, len(requirement_ids)
    )
    return {
        "acceptance_criteria": acceptance,
        "adopted_item": adopted_item,
        "affected_components": [],
        "ai_token_estimate": {
            key: list(value) if isinstance(value, list) else value
            for key, value in TOKEN_ESTIMATE.items()
        },
        "assumptions": [
            "The task is not executable while its status is PLANNED_NOT_ACTIVE.",
            "Mocks may support unit tests but never qualifying runtime evidence.",
            (
                "expected_file_areas, affected_components and coverage are "
                "placeholders fixed when POST-POC-BACKLOG-ACTIVATION admits "
                "the task. They do not authorise a file area."
            ),
        ],
        "bounded_agent_context_pack": [
            "docs/development_plan/post_poc/OCOR_POST_POC_BACKLOG.json",
            REGISTER_REL,
            TRACE_REL,
        ],
        "compute_estimate": {
            "external_services": "0-80 service-h depending on qualifying backend",
            "gpu": "0 by default; only a governed benchmark fixture may add GPU",
            "local": "6-16 CPU-h",
        },
        "confidence": 0.5,
        "coverage": {key: [] for key in COVERAGE},
        "definition_of_done": list(DEFINITION_OF_DONE),
        "delivery_gate": gate,
        "evidence_outputs": [
            f"reports/evidence/{gate}/{task_id}.json",
            f"reports/evidence/{gate}/{task_id}.log",
        ],
        "expected_duration_days": duration,
        "expected_file_areas": ["docs/development_plan/post_poc/"],
        "failure_and_escalation_conditions": [
            "Two materially different repairs fail",
            "A normative conflict is found",
            "A required real service is unavailable",
            "The change would edit the approved plan or promote a claim",
        ],
        "hard_dependencies": [],
        "id": task_id,
        "implementation_procedure": [
            "Confirm the Product Owner decision on G7.",
            "Confirm POST-POC-BACKLOG-ACTIVATION before any edit outside this plan.",
            "Implement only this task's requirement identifiers and adopted item.",
            "Stop when a change would edit the approved plan or promote a claim.",
        ],
        "integration_point": (
            f"{gate} integration branch after evidence review. Not active."
        ),
        "migration_and_compatibility_procedure": (
            "Preserve approved public contracts through versioned adapters. "
            "This planned task does not migrate persisted data."
        ),
        "negative_acceptance_criteria": negative,
        "normative_references": [
            "ADD v1.3",
            "FABLE52-POST-POC-PROGRAMME (2026-11-11)",
            "Requirement Register v1.1",
        ],
        "objective": objective,
        "observability_requirements": [
            "correlation_id and causation_id on every boundary",
            "stable error code and bounded metric cardinality",
            "trace plus audit receipt for durable effects",
        ],
        "parallel_group": f"{gate}-{workstream}-{role}",
        "parallel_wave": WAVE[gate][role],
        "preconditions": [
            "The Product Owner decision on G7 is recorded.",
            "POST-POC-BACKLOG-ACTIVATION is decided.",
            "All hard dependencies are merged and green.",
        ],
        "prohibited_file_areas": [
            "docs/development_plan/OCOR_DEPENDENCY_DAG.mmd",
            APPROVED_BACKLOG_REL,
            TRACE_REL,
            "inputs/",
        ],
        "rationale": rationale,
        "required_test_levels": [
            "contract",
            "fault-injection",
            "integration",
            "negative",
            "unit",
        ],
        "requirement_ids": requirement_ids,
        "rollback_procedure": (
            "Stop dispatch, revert the isolated task commit through a new "
            "revert commit, and revalidate the previous evidence manifest. "
            "Do not rewrite sealed records."
        ),
        "security_considerations": (
            "Fail closed on missing identity, authority, purpose, marking, "
            "lease, policy, evidence or stop state. Never log secrets."
        ),
        "soft_dependencies": [],
        "status": "PLANNED_NOT_ACTIVE",
        "title": title,
        "uncertainty": "HIGH",
        "validation_commands": [
            "python3 scripts/validate_post_poc_plan.py",
        ],
        "workstream": workstream,
    }


def _adopted_specs() -> list[dict[str, str]]:
    return [
        {
            "adopted_item": "G-1",
            "gate": "G9",
            "negative": (
                "A session handshake is required before a tool call, or the "
                "Tasks extension is treated as part of the core session."
            ),
            "objective": (
                "Follow up G-1 after the separate PoC MCP profile unit. "
                "Disposition: DEFERRED_POST_POC. Use a stateless MCP "
                "transport, map long-running tools to the Tasks extension, "
                "and check the issuer during authorisation."
            ),
            "positive": (
                "Tool calls are stateless, long-running tools use the Tasks "
                "extension, and authorisation checks the issuer."
            ),
            "stem": "OCOR-POST-G9-G1",
            "title": "Stateless MCP transport, Tasks extension and authorisation",
            "workstream": "WS-09",
        },
        {
            "adopted_item": "G-3",
            "gate": "G9",
            "negative": (
                "The OSI export is required for the functional MVP, or it "
                "writes the canonical ontology."
            ),
            "objective": (
                "Optional. C1 emits an OSI export as a derived artefact and "
                "does not make that export part of the canonical ontology."
            ),
            "positive": (
                "C1 emits an optional OSI export as a derived artefact."
            ),
            "stem": "OCOR-POST-G9-G3",
            "title": "Optional OSI export generated by C1",
            "workstream": "WS-02",
        },
        {
            "adopted_item": "G-9-FUNCTIONAL",
            "gate": "G9",
            "negative": (
                "The product surface writes canonical state or an ontology "
                "artefact without the governed path."
            ),
            "objective": (
                "Provide the functional product surface for the governed "
                "contracts of C1-C8. The surface adds no write path around "
                "those contracts."
            ),
            "positive": (
                "The functional product surface exposes the C1-C8 contracts "
                "without a new write path around them."
            ),
            "stem": "OCOR-POST-G9-SURFACE",
            "title": "Functional product surface",
            "workstream": "WS-03",
        },
        {
            "adopted_item": "G-5",
            "gate": "G10",
            "negative": (
                "This task selects the numeric threshold or the benchmark "
                "identity, or a mock store supplies the qualifying run."
            ),
            "objective": (
                "Run a preregistered public memory benchmark on the real "
                "stores. The threshold and the benchmark identity stay an "
                "external decision recorded before execution."
            ),
            "positive": (
                "The benchmark runs on the real stores only after "
                "G5-BENCHMARK-PREREGISTRATION names the threshold and the "
                "benchmark."
            ),
            "stem": "OCOR-POST-G10-G5",
            "title": "Preregistered public memory benchmark on real stores",
            "workstream": "WS-10",
        },
        {
            "adopted_item": "G-9-OPERATIONAL",
            "gate": "G10",
            "negative": (
                "Operations depend on a vendor console or on a network path "
                "forbidden by the air-gap profile."
            ),
            "objective": (
                "Operate the product surface: install, recover and observe it. "
                "This task depends on the functional surface through the G9 "
                "verify wave."
            ),
            "positive": (
                "The product surface can be installed, recovered and observed "
                "on the operational MVP profile."
            ),
            "stem": "OCOR-POST-G10-SURFACE",
            "title": "Operational product surface",
            "workstream": "WS-12",
        },
        {
            "adopted_item": "G-6",
            "gate": "G11",
            "negative": G6_NEGATIVE,
            "objective": (
                "Optional. Causal discovery emits only tainted "
                "DecisionProposal hypotheses and never edits a registered "
                "causal model."
            ),
            "positive": G6_POSITIVE,
            "stem": "OCOR-POST-G11-G6",
            "title": "Optional causal discovery as tainted hypotheses",
            "workstream": "WS-08",
        },
    ]


def _requirement_tasks(
    clusters: Mapping[tuple[str, str], list[dict[str, Any]]],
    workstreams: Mapping[str, str],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for gate, workstream in sorted(clusters):
        rows = clusters[(gate, workstream)]
        identifiers = [str(row["id"]) for row in rows]
        listed = ", ".join(identifiers)
        name = workstreams.get(workstream, workstream)
        stem = f"OCOR-POST-{gate}-{workstream.replace('-', '')}"
        adopted = "G-2" if "FR-048" in identifiers else None
        realise_acceptance = [
            f"{identifier} keeps the Register acceptance criterion at its line."
            for identifier in identifiers
        ]
        verify_acceptance = [
            (
                f"Verify {identifier} by the Register method: "
                f"{row['method']}."
            )
            for identifier, row in zip(identifiers, rows, strict=True)
        ]
        negative = [
            "A skipped, mock-only or NOT_EXECUTED result closes a requirement.",
            "This task edits inputs/ or the approved backlog.",
        ]
        if adopted == "G-2":
            realise_acceptance.append(G2_POSITIVE)
            realise_acceptance.append(FR048_SDK_POSITIVE)
            verify_acceptance.append(G2_POSITIVE)
            verify_acceptance.append(FR048_SDK_POSITIVE)
            negative.append(G2_NEGATIVE)
            negative.append(
                "Additional SDKs of FR-048, including Rust, are implemented "
                "before a capability contract and a conformance profile exist "
                "for that language and protocol."
            )
        tasks.append(
            _common_task(
                task_id=f"{stem}-REALISE",
                title=f"Realise {gate} {workstream} beyond-PoC requirements",
                gate=gate,
                workstream=workstream,
                role="REALISE",
                objective=(
                    f"Realise {listed} for {gate} on {workstream} ({name}). "
                    "Claims stay E1=0, E2=0, Verified=0, runtime "
                    "NOT_ESTABLISHED, PoC NO-GO and Production NO-GO."
                ),
                rationale=(
                    f"Latest-stage allocation of {workstream} to {gate}. "
                    "This file is not the approved plan."
                ),
                requirement_ids=identifiers,
                adopted_item=adopted,
                acceptance=realise_acceptance,
                negative=list(negative),
            )
        )
        tasks.append(
            _common_task(
                task_id=f"{stem}-VERIFY",
                title=f"Verify {gate} {workstream} beyond-PoC requirements",
                gate=gate,
                workstream=workstream,
                role="VERIFY",
                objective=(
                    f"Verify {listed} for {gate} on {workstream} ({name}) "
                    "with the Register method of each requirement."
                ),
                rationale=(
                    "Verification uses the Register method and does not "
                    "move the approved traceability plan."
                ),
                requirement_ids=identifiers,
                adopted_item=adopted,
                acceptance=verify_acceptance,
                negative=list(negative),
            )
        )
    return tasks


def _bind_dependencies(tasks: list[dict[str, Any]]) -> None:
    by_gate_role: dict[tuple[str, str], list[str]] = {}
    for task in tasks:
        role = "VERIFY" if str(task["id"]).endswith("-VERIFY") else "REALISE"
        by_gate_role.setdefault((str(task["delivery_gate"]), role), []).append(
            str(task["id"])
        )
    for identifiers in by_gate_role.values():
        identifiers.sort()
    for task in tasks:
        role = "VERIFY" if str(task["id"]).endswith("-VERIFY") else "REALISE"
        gate = str(task["delivery_gate"])
        if role == "VERIFY":
            task["hard_dependencies"] = [str(task["id"]).replace("-VERIFY", "-REALISE")]
            continue
        previous = PREVIOUS_GATE.get(gate)
        task["hard_dependencies"] = (
            [] if previous is None else list(by_gate_role[(previous, "VERIFY")])
        )


def _edges(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for task in tasks:
        dependent = str(task["id"])
        dependencies = task.get("hard_dependencies")
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            edges.append({"from": str(dependency), "to": dependent})
    edges.sort(key=lambda edge: (edge["from"], edge["to"]))
    return edges


def _topological_order(
    task_ids: Sequence[str], edges: Sequence[Mapping[str, str]]
) -> list[str] | None:
    dependents: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    indegree = {task_id: 0 for task_id in task_ids}
    for edge in edges:
        source = str(edge["from"])
        target = str(edge["to"])
        if source not in dependents or target not in indegree:
            return None
        dependents[source].append(target)
        indegree[target] += 1
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for nxt in sorted(dependents[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort()
    if len(order) != len(task_ids):
        return None
    return order


def _external_documents() -> dict[str, Any]:
    return {
        "decisions": [
            {
                "blocks": "Execution of OCOR-POST-G10-G5-REALISE.",
                "id": "G5-BENCHMARK-PREREGISTRATION",
                "recommendation_on_timing": "NONE",
                "status": "OPEN_EXTERNAL_DECISION",
                "subject": (
                    "The numeric threshold and the public memory benchmark "
                    "identity are preregistered before execution. This plan "
                    "does not choose either."
                ),
            },
            {
                "blocks": "Execution of every G8-G11 task.",
                "id": "G7-PO-DECISION",
                "recommendation_on_timing": "NONE",
                "status": "OPEN_PO_DECISION_REQUIRED",
                "subject": (
                    "Product Owner decision on G7 before any post-PoC task runs."
                ),
            },
            {
                "blocks": "Admission of every G8-G11 task into the executable backlog.",
                "id": "POST-POC-BACKLOG-ACTIVATION",
                "recommendation_on_timing": "NONE",
                "status": "OPEN_PO_NORMATIVE_DECISION_REQUIRED",
                "subject": (
                    "When, if ever, post-PoC tasks enter the executable backlog."
                ),
            },
        ],
        "observations": [
            {
                "disposition": "NOT_GATE_G8",
                "id": "AUDIT-G-8",
                "reason": (
                    "Supply-chain pins belong to the alignment requests. "
                    "They are not gate G8."
                ),
                "task_id": None,
            },
            {
                "disposition": "OBSERVE_ONLY",
                "id": "G-4",
                "reason": (
                    "RDF 1.2 and SHACL 1.2 stay outside the W3C boundary, "
                    "which remains RDF 1.1. No task is planned."
                ),
                "task_id": None,
            },
            {
                "disposition": "SEPARATE_UNIT_BEFORE_OCOR_DEV_0062",
                "id": "G-7",
                "reason": (
                    "The OWASP agentic map is a separate unit before "
                    "OCOR-DEV-0062. It is not a G8-G11 task."
                ),
                "task_id": None,
            },
            {
                "disposition": "NOT_REGISTER_ROWS",
                "entry_ids": [
                    "NCR-C1-007",
                    "NCR-C3-005",
                    "NCR-C8-006",
                    "NCR-GOVERNANCE-002",
                    "NCR-LEGACY-001",
                    "NCR-TESTS-002",
                    "NCR-TESTS-003",
                    "NCR-TESTS-004",
                    "NCR-TESTS-005",
                ],
                "id": "NCR-OPEN-DEFERRED",
                "reason": (
                    "At the baseline these conformance entries are OPEN or "
                    "DEFERRED_BY_PO. They are not Requirement Register rows, "
                    "so this plan does not allocate them to G8. Gate G8 stays "
                    "the Register rows whose release is beyond the PoC and "
                    "whose type is BR. Their disposition stays in the "
                    "conformance register."
                ),
                "task_id": None,
            },
        ],
        "plan_id": PLAN_ID,
        "schema_version": SCHEMA_VERSION,
    }


def _gate_catalogue(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    meanings = {
        "G8": "MVP entry: hygiene, productisation and profile registers.",
        "G9": "Functional MVP: completion of C1-C8.",
        "G10": "Operational MVP: portability, security, recovery, load and tools.",
        "G11": "Production.",
    }
    catalogue: dict[str, Any] = {}
    for gate, meaning in meanings.items():
        identifiers = sorted(
            str(task["id"])
            for task in tasks
            if task.get("delivery_gate") == gate
        )
        catalogue[gate] = {
            "entry": (
                "The Product Owner decision on G7 is recorded and "
                "POST-POC-BACKLOG-ACTIVATION has been decided."
            ),
            "exit": meaning,
            "meaning": meaning,
            "name": meaning.split(":", 1)[0],
            "required_tasks": identifiers,
        }
    return catalogue


def build_documents(
    root: Path,
    requirements: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Mapping[str, str]],
    workstreams: Mapping[str, str],
) -> dict[str, Any]:
    """Return the four plan documents. This function does not write."""
    clusters: dict[tuple[str, str], list[dict[str, Any]]] = {}
    allocation_rows: list[dict[str, Any]] = []
    for item in requirements:
        if not is_beyond_poc(str(item["release"])):
            continue
        identifier = str(item["id"])
        traced = trace[identifier]
        gate = assign_gate(str(item["release"]), str(item["type"]))
        workstream = traced["workstream"]
        clusters.setdefault((gate, workstream), []).append(dict(item))
    for rows in clusters.values():
        rows.sort(key=lambda row: _requirement_key(str(row["id"])))
    tasks = _requirement_tasks(clusters, workstreams)
    for spec in _adopted_specs():
        for role, verb in (("REALISE", "Realise"), ("VERIFY", "Verify")):
            tasks.append(
                _common_task(
                    task_id=f"{spec['stem']}-{role}",
                    title=f"{verb} {spec['title']}",
                    gate=spec["gate"],
                    workstream=spec["workstream"],
                    role=role,
                    objective=spec["objective"],
                    rationale=(
                        f"Adopted item {spec['adopted_item']} stays a planned "
                        "task with positive and negative criteria. It is not "
                        "active."
                    ),
                    requirement_ids=[],
                    adopted_item=spec["adopted_item"],
                    acceptance=[spec["positive"]],
                    negative=[spec["negative"]],
                )
            )
    tasks.sort(key=lambda task: (int(task["parallel_wave"]), str(task["id"])))
    _bind_dependencies(tasks)
    for (gate, workstream), rows in sorted(clusters.items()):
        stem = f"OCOR-POST-{gate}-{workstream.replace('-', '')}"
        for row in rows:
            allocation_rows.append(
                {
                    "gate": gate,
                    "method": row["method"],
                    "priority": row["priority"],
                    "realise_task": f"{stem}-REALISE",
                    "register_line": row["line"],
                    "release": row["release"],
                    "requirement_id": row["id"],
                    "title": row["title"],
                    "type": row["type"],
                    "verify_task": f"{stem}-VERIFY",
                    "workstream": workstream,
                }
            )
    allocation_rows.sort(key=lambda row: _requirement_key(str(row["requirement_id"])))
    edges = _edges(tasks)
    order = _topological_order([str(task["id"]) for task in tasks], edges)
    if order is None:
        raise RuntimeError("generated post-PoC graph has a cycle")
    return {
        "allocation": {
            "baseline_commit": BASELINE_COMMIT,
            "classification_rule": (
                "The latest stage owns the single realise and verify pair. "
                "Production, Future or Ogni release selects G11. Otherwise "
                "BR selects G8, FR or Funzionale selects G9, and NFR or "
                "Non funzionale selects G10. A release of exactly PoC is "
                "out of this plan."
            ),
            "plan_id": PLAN_ID,
            "requirements": allocation_rows,
            "schema_version": SCHEMA_VERSION,
        },
        "backlog": {
            "baseline_commit": BASELINE_COMMIT,
            "claims_fence": (
                "E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, "
                "PoC NO-GO, Production NO-GO."
            ),
            "gates": _gate_catalogue(tasks),
            "plan_id": PLAN_ID,
            "requirement_count": len(allocation_rows),
            "schema_version": SCHEMA_VERSION,
            "source_hash_policy": (
                "Hashes of reports/development/EXECUTION_STATE.json and "
                "reports/development/NORMATIVE_CONFORMANCE_REGISTER.json are "
                "the blobs of the baseline commit. The Requirement Register, "
                "the traceability plan and the approved backlog are read from "
                "the working tree, and a change there fails this check."
            ),
            "source_hashes": _source_hashes(root),
            "task_count": len(tasks),
            "tasks": tasks,
        },
        "external": _external_documents(),
        "graph": {
            "acyclic": True,
            "edges": edges,
            "plan_id": PLAN_ID,
            "schema_version": SCHEMA_VERSION,
            "topological_order": order,
        },
    }


def load_documents(root: Path) -> dict[str, Any]:
    """Load the four plan documents from disk."""
    return {
        key: _load_json(root / relative)
        for key, relative in DOCUMENT_FILES.items()
    }


def write_documents(root: Path, documents: Mapping[str, Any]) -> None:
    """Write the four plan documents in canonical JSON."""
    for key, relative in DOCUMENT_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_canonical(documents[key]), encoding="utf-8")


def _walk_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _tasks_of(documents: Mapping[str, Any]) -> list[dict[str, Any]]:
    backlog = documents.get("backlog")
    if not isinstance(backlog, dict):
        return []
    raw = backlog.get("tasks")
    if not isinstance(raw, list):
        return []
    return [task for task in raw if isinstance(task, dict)]


def _allocation_rows(documents: Mapping[str, Any]) -> list[dict[str, Any]]:
    allocation = documents.get("allocation")
    if not isinstance(allocation, dict):
        return []
    raw = allocation.get("requirements")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _joined(task: Mapping[str, Any], field: str) -> str:
    raw = task.get(field)
    if not isinstance(raw, list):
        return ""
    return "\n".join(str(item) for item in raw)


def validate_documents(
    documents: Mapping[str, Any],
    requirements: Sequence[Mapping[str, Any]],
    trace: Mapping[str, Mapping[str, str]],
    workstreams: Mapping[str, str],
) -> list[str]:
    """Return ``CODE: message`` findings. An empty list is acceptance."""
    findings: list[str] = []
    saw_claim = False
    saw_path = False
    for text in _walk_strings(documents):
        if not saw_claim and any(phrase in text for phrase in PROHIBITED_CLAIMS):
            findings.append("PROHIBITED_CLAIM: fenced claim text")
            saw_claim = True
        if not saw_path and "/home/" in text:
            findings.append("LOCAL_PATH: personal absolute path")
            saw_path = True
    tasks = _tasks_of(documents)
    rows = _allocation_rows(documents)
    by_id = {str(task.get("id")): task for task in tasks}
    if len(by_id) != len(tasks):
        findings.append("FIELD: duplicate task id")
    for task in tasks:
        task_id = str(task.get("id", ""))
        missing = [field for field in REQUIRED_TASK_FIELDS if field not in task]
        if missing:
            findings.append(f"FIELD: {task_id} missing {', '.join(missing)}")
        if task.get("status") != "PLANNED_NOT_ACTIVE":
            findings.append(f"STATUS: {task_id}")
        requirement_ids = task.get("requirement_ids")
        adopted = task.get("adopted_item")
        if isinstance(requirement_ids, list) and not requirement_ids:
            if adopted not in EMPTY_ADOPTED:
                findings.append(f"FIELD: {task_id} empty requirement_ids")
        if adopted == "G-2" and (
            not isinstance(requirement_ids, list) or "FR-048" not in requirement_ids
        ):
            findings.append(f"FIELD: {task_id} G-2 binding")
        if "FR-048" in (requirement_ids or []):
            if adopted != "G-2":
                findings.append(f"FIELD: {task_id} FR-048 binding")
            acceptance = _joined(task, "acceptance_criteria")
            if G2_POSITIVE not in acceptance:
                findings.append(f"FIELD: {task_id} G-2 positive criterion")
            if FR048_SDK_POSITIVE not in acceptance:
                findings.append(f"FR048_SCOPE: {task_id} sdk criterion")
            if FR048_A2A_ONLY_RESTRICTION in acceptance:
                findings.append(f"FR048_SCOPE: {task_id} a2a-only restriction")
            if G2_NEGATIVE not in _joined(task, "negative_acceptance_criteria"):
                findings.append(f"FIELD: {task_id} G-2 negative criterion")
        if adopted == "G-6":
            if G6_POSITIVE not in _joined(task, "acceptance_criteria"):
                findings.append(f"G6_CRITERIA: {task_id}")
            elif G6_NEGATIVE not in _joined(task, "negative_acceptance_criteria"):
                findings.append(f"G6_CRITERIA: {task_id}")
        workstream = task.get("workstream")
        if isinstance(workstream, str) and workstream not in workstreams:
            findings.append(f"FIELD: unknown workstream {workstream}")
    edges = _edges(tasks)
    order = _topological_order(list(by_id), edges)
    if order is None:
        findings.append("CYCLE: hard_dependencies")
    else:
        graph = documents.get("graph")
        graph_edges = graph.get("edges") if isinstance(graph, dict) else None
        graph_order = (
            graph.get("topological_order") if isinstance(graph, dict) else None
        )
        if graph_edges != edges or graph_order != order:
            findings.append("GRAPH_MISMATCH: dependency graph")
    known_requirements = {str(item["id"]): item for item in requirements}
    allocated: list[str] = []
    for row in rows:
        identifier = str(row.get("requirement_id", ""))
        release = str(row.get("release", ""))
        allocated.append(identifier)
        if not is_beyond_poc(release):
            findings.append(f"POC_REQUIREMENT: {identifier}")
            continue
        item = known_requirements.get(identifier)
        if item is not None and "type" in row:
            expected = assign_gate(str(item["release"]), str(item["type"]))
            if row.get("gate") != expected or row.get("release") != item["release"]:
                findings.append(f"FIELD: allocation {identifier}")
            traced = trace.get(identifier)
            if traced is None or traced.get("workstream") != row.get("workstream"):
                findings.append(f"UNTRACED: {identifier}")
            realise = by_id.get(str(row.get("realise_task")))
            verify = by_id.get(str(row.get("verify_task")))
            bindings = ((realise, "realise"), (verify, "verify"))
            for bound, label in bindings:
                identifiers = bound.get("requirement_ids") if bound else None
                if bound is None or identifier not in (identifiers or []):
                    findings.append(f"MISSING_REQUIREMENT: {identifier} {label}")
            if verify is not None:
                method = str(item["method"])
                if method not in _joined(verify, "acceptance_criteria"):
                    findings.append(f"FIELD: method {identifier}")
    for item in requirements:
        if not is_beyond_poc(str(item["release"])):
            continue
        identifier = str(item["id"])
        if identifier not in allocated:
            findings.append(f"MISSING_REQUIREMENT: {identifier}")
        traced = trace.get(identifier)
        if traced is None:
            findings.append(f"UNTRACED: {identifier}")
        elif traced.get("register_release") != item["release"]:
            findings.append(f"FIELD: release drift {identifier}")
    external = documents.get("external")
    decisions = external.get("decisions") if isinstance(external, dict) else None
    decision_rows = decisions if isinstance(decisions, list) else []
    found_ids = {
        str(item.get("id"))
        for item in decision_rows
        if isinstance(item, dict)
    }
    for identifier in REQUIRED_DECISIONS:
        if identifier not in found_ids:
            findings.append(f"EXTERNAL: {identifier}")
    if isinstance(decisions, list):
        for item in decisions:
            if not isinstance(item, dict):
                continue
            if item.get("id") in REQUIRED_DECISIONS and (
                item.get("recommendation_on_timing") != "NONE"
            ):
                findings.append(f"EXTERNAL: {item.get('id')} timing")
    observations = (
        external.get("observations") if isinstance(external, dict) else None
    )
    expected_observations = {
        "AUDIT-G-8": "NOT_GATE_G8",
        "G-4": "OBSERVE_ONLY",
        "G-7": "SEPARATE_UNIT_BEFORE_OCOR_DEV_0062",
        "NCR-OPEN-DEFERRED": "NOT_REGISTER_ROWS",
    }
    seen_observations: dict[str, list[dict[str, Any]]] = {}
    if isinstance(observations, list):
        for item in observations:
            if isinstance(item, dict):
                seen_observations.setdefault(str(item.get("id")), []).append(item)
    for identifier, disposition in expected_observations.items():
        matches = seen_observations.get(identifier, [])
        if not any(item.get("disposition") == disposition for item in matches):
            findings.append(f"FIELD: observation {identifier}")
        if identifier == "G-4" and any(item.get("task_id") is not None for item in matches):
            findings.append("G4_TASK: G-4 has a task identifier")
    return findings


def validate_repository(root: Path) -> list[str]:
    """Check the README and the decision request that travel with the plan."""
    findings: list[str] = []
    readme_path = root / README_REL
    try:
        readme = readme_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"README: {exc}"]
    for phrase in (
        "not the approved plan",
        "PLANNED_NOT_ACTIVE",
        "ADD v1.3",
        "E1=0",
        "POST-POC-BACKLOG-ACTIVATION",
        "Product Owner decision on G7",
        "2026-11-12",
    ):
        if phrase not in readme:
            findings.append(f"README: missing {phrase}")
    if "/home/" in readme or any(phrase in readme for phrase in PROHIBITED_CLAIMS):
        findings.append("README: prohibited text")
    try:
        decision = (root / DECISION_REL).read_text(encoding="utf-8")
    except OSError as exc:
        return [*findings, f"DR: {exc}"]
    if "OPEN_PO_NORMATIVE_DECISION_REQUIRED" not in decision:
        findings.append("DR: status")
    if "Nessuna raccomandazione sul momento" not in decision:
        findings.append("DR: timing sentence")
    options = [
        line
        for line in decision.splitlines()
        if re.match(r"^[A-Z]?[0-9]{1,2}\. \*\*", line)
    ]
    if len(options) != 3:
        findings.append(f"DR: option count {len(options)}")
    if "## Raccomandazione" not in decision:
        findings.append("DR: recommendation heading")
    else:
        recommendation = decision.split("## Raccomandazione", 1)[1].lower()
        if "opzione 1" in recommendation or "si raccomanda" in recommendation:
            findings.append("DR: timing recommendation")
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the four plan documents",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    requirements = load_register(root)
    trace = load_traceability(root)
    workstreams = load_workstreams(root)
    generated = build_documents(root, requirements, trace, workstreams)
    findings: list[str] = []
    if args.write:
        write_documents(root, generated)
    else:
        try:
            on_disk = load_documents(root)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            findings.append(f"DISK_MISMATCH: {exc}")
        else:
            if on_disk != generated:
                findings.append("DISK_MISMATCH: generated plan differs from disk")
    findings.extend(
        validate_documents(generated, requirements, trace, workstreams)
    )
    findings.extend(validate_repository(root))
    if findings:
        for item in findings:
            print(item)
        return 1
    beyond = sum(1 for item in requirements if is_beyond_poc(str(item["release"])))
    print(f"PASS: {beyond} beyond-PoC requirements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
