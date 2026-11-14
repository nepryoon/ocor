#!/usr/bin/env python3
"""Generate the agentic risk inventory from repository registers and contracts.

The map is a derived reading. It is not evidence and it is not a conformance
claim. Category names are the labels named by the Product Owner; their
descriptions are not copied.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import TypedDict

SCAN_ROOTS = (
    "ocor-runtime/docs/governance_dossier/contracts",
    "ocor-runtime/schemas",
    "reports/contracts",
)
REGISTER = (
    "ocor-runtime/docs/governance_dossier/registers/"
    "OCOR_Requirement_Register_v1.1_APPROVED.md"
)
ADD = "ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md"
LLD = "docs/OCOR_LLD_v1.1.md"
ORCHESTRATOR = "ocor-runtime/src/ocor_runtime/c8/orchestrator.py"
STATE = "reports/development/EXECUTION_STATE.json"
MAP_PATH = "docs/security/OCOR_AGENTIC_RISK_MAP.md"
INVENTORY_PATH = "docs/security/agentic_risk_inventory.json"
REQUEST_PATH = "reports/development/decision_requests/AGENTIC-RISK-MAP-PARTIAL-GAPS.md"
REQUIREMENTS = ("NFR-038", "NFR-048", "NFR-050")
ABSENT = "ABSENT_NO_ROLE_CAPABILITY_REGISTER"
DECLARED = "DECLARED"


class Reference(TypedDict):
    anchor: str
    line: int
    path: str


class Control(TypedDict):
    anchor: str
    control_id: str
    path: str
    summary: str


class Row(TypedDict):
    id: str
    name: str
    outcome: str
    reason: str
    references: list[Reference]
    requirements: list[str]
    summaries: list[str]


class RoleRecord(TypedDict):
    admitted_capabilities: list[str]
    capability_binding: str
    enum_name: str
    label: str
    outputs: list[str]


class ToolRecord(TypedDict):
    approval: dict[str, object]
    effect_class: str
    risk_class: str
    source: str
    tool_name: str


class Inventory(TypedDict):
    agent_roles: list[RoleRecord]
    completed_evidence_tasks: list[str]
    orchestrator_sha256: str
    register_lines: dict[str, int]
    review_sealed: bool
    rows: list[Row]
    tool_instance_register: str
    tools: list[ToolRecord]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_of(text: str, anchor: str) -> int:
    for index, line in enumerate(text.splitlines(), start=1):
        if anchor in line:
            return index
    raise SystemExit(f"anchor not found: {anchor}")


def _cite(root: Path, path: str, anchor: str) -> Reference:
    return {
        "anchor": anchor,
        "line": _line_of(_text(root / path), anchor),
        "path": path,
    }


def _string_tuple(node: ast.AST) -> list[str] | None:
    if not isinstance(node, ast.Tuple):
        return None
    values: list[str] = []
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            values.append(element.value)
        else:
            return None
    return values


def _role_key(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "AgentRole"
    ):
        return node.attr
    return None


def _role_map(node: ast.AST) -> dict[str, list[str]] | None:
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "MappingProxyType"
            and len(node.args) == 1
        ):
            return _role_map(node.args[0])
        return None
    if not isinstance(node, ast.Dict):
        return None
    found: dict[str, list[str]] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None or value is None:
            return None
        role = _role_key(key)
        strings = _string_tuple(value)
        if role is None or strings is None:
            return None
        found[role] = strings
    return found


def _assignment_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Assign):
        return node.value
    if isinstance(node, ast.AnnAssign):
        return node.value
    return None


def parse_agent_roles(source: str) -> list[RoleRecord]:
    """Read agent roles, outputs and any declared capability allow-list."""

    tree = ast.parse(source)
    labels: list[tuple[str, str]] = []
    outputs: dict[str, list[str]] = {}
    capabilities: dict[str, list[str]] | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AgentRole":
            for item in node.body:
                if not isinstance(item, ast.Assign) or len(item.targets) != 1:
                    continue
                target = item.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                if isinstance(item.value, ast.Constant) and isinstance(
                    item.value.value, str
                ):
                    labels.append((target.id, item.value.value))
            continue
        name = _assignment_name(node)
        value = _assignment_value(node)
        if name is None or value is None:
            continue
        mapping = _role_map(value)
        if mapping is None:
            continue
        if "CAPABIL" in name:
            capabilities = mapping
        elif "OUTPUT" in name:
            outputs = mapping
    binding = DECLARED if capabilities is not None else ABSENT
    allowed = capabilities or {}
    return [
        {
            "admitted_capabilities": list(allowed.get(enum_name, [])),
            "capability_binding": binding if enum_name in allowed else ABSENT,
            "enum_name": enum_name,
            "label": label,
            "outputs": list(outputs.get(enum_name, [])),
        }
        for enum_name, label in labels
    ]


def tool_record(value: object) -> dict[str, object] | None:
    """Return a tool instance, or None when the object is a schema fragment."""

    if not isinstance(value, dict):
        return None
    name = value.get("tool_name")
    effect = value.get("effect_class")
    risk = value.get("risk_class")
    approval = value.get("approval")
    if not isinstance(name, str) or not isinstance(effect, str):
        return None
    if not isinstance(risk, str) or not isinstance(approval, dict):
        return None
    if (
        not name
        or name != name.strip()
        or any(character.isupper() for character in name)
    ):
        return None
    cleaned: dict[str, object] = {}
    for key, item in approval.items():
        if not isinstance(key, str):
            return None
        cleaned[key] = item
    return {
        "approval": cleaned,
        "effect_class": effect,
        "risk_class": risk,
        "tool_name": name,
    }


def _walk_tools(node: object, found: list[dict[str, object]]) -> None:
    record = tool_record(node)
    if record is not None:
        found.append(record)
    if isinstance(node, dict):
        for child in node.values():
            _walk_tools(child, found)
    elif isinstance(node, list):
        for child in node:
            _walk_tools(child, found)


def scan_tools(root: Path) -> list[ToolRecord]:
    found: list[ToolRecord] = []
    for prefix in SCAN_ROOTS:
        base = root / prefix
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.json")):
            if path.name.endswith(".schema.json"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            matches: list[dict[str, object]] = []
            _walk_tools(payload, matches)
            relative = path.relative_to(root).as_posix()
            for match in matches:
                approval = match["approval"]
                effect = match["effect_class"]
                risk = match["risk_class"]
                name = match["tool_name"]
                if (
                    not isinstance(approval, dict)
                    or not isinstance(effect, str)
                    or not isinstance(risk, str)
                    or not isinstance(name, str)
                ):
                    continue
                found.append(
                    {
                        "approval": approval,
                        "effect_class": effect,
                        "risk_class": risk,
                        "source": relative,
                        "tool_name": name,
                    }
                )
    found.sort(key=lambda item: (item["source"], item["tool_name"]))
    return found


def _completed(root: Path) -> list[str]:
    payload = json.loads(_text(root / STATE))
    if not isinstance(payload, dict):
        raise SystemExit("execution state is not an object")
    tasks = payload.get("completed_evidence_tasks")
    if not isinstance(tasks, list) or not all(isinstance(item, str) for item in tasks):
        raise SystemExit("completed_evidence_tasks is not a list of strings")
    return sorted(tasks)


def _register_lines(root: Path) -> dict[str, int]:
    text = _text(root / REGISTER)
    lines: dict[str, int] = {}
    for requirement_id in REQUIREMENTS:
        needle = f"| `{requirement_id}` |"
        found = [
            index
            for index, line in enumerate(text.splitlines(), start=1)
            if needle in line
        ]
        if len(found) != 1:
            raise SystemExit(f"{requirement_id} not found once in the register")
        lines[requirement_id] = found[0]
    return lines


def _controls() -> dict[str, tuple[Control, ...]]:
    return {
        "ASI01": (
            {
                "anchor": "instruction_pin: str",
                "control_id": "C8-INSTRUCTION-PIN",
                "path": "ocor-runtime/src/ocor_runtime/c8/tool_runtime.py",
                "summary": "Each agent run carries a model pin and an instruction pin.",
            },
        ),
        "ASI02": (
            {
                "anchor": 'TOOL_CONTRACT_SCHEMA_ID = "urn:ocor:schema:mcp-tool-contract:1.2"',
                "control_id": "C8-TOOL-CONTRACT",
                "path": "ocor-runtime/src/ocor_runtime/c8/tool_contract.py",
                "summary": "Admitted tools use the closed mcp-tool-contract schema.",
            },
            {
                "anchor": (
                    "The risk class of an action is the risk class of its "
                    "signed ActionType"
                ),
                "control_id": "C6-SIGNED-RISK",
                "path": "ocor-runtime/src/ocor_runtime/c6/contract.py",
                "summary": "Risk and effect come from the signed ActionType.",
            },
        ),
        "ASI03": (
            {
                "anchor": "class IdentityRegistry:",
                "control_id": "C2-IDENTITY-REGISTRY",
                "path": "ocor-runtime/src/ocor_runtime/c2_identity.py",
                "summary": "Principals are read from the identity registry.",
            },
            {
                "anchor": "def verify_signed_delegation(",
                "control_id": "SIGNED-DELEGATION",
                "path": "ocor-runtime/src/ocor_runtime/security/control_plane.py",
                "summary": "A delegation is accepted only when its signature verifies.",
            },
            {
                "anchor": "workload_identity must be a SPIFFE ID",
                "control_id": "C8-SPIFFE-BINDING",
                "path": "ocor-runtime/src/ocor_runtime/c8/tool_runtime.py",
                "summary": "Workload identity on a tool call is a SPIFFE ID.",
            },
        ),
        "ASI04": (
            {
                "anchor": '"acquired_at": "2026-10-01T16:38:05Z"',
                "control_id": "TOOLCHAIN-LOCK",
                "path": "infra/toolchain.lock.json",
                "summary": "Host tools are digest-pinned in the toolchain lock.",
            },
            {
                "anchor": "name: OCOR supply-chain gates",
                "control_id": "CI-SUPPLY-CHAIN",
                "path": ".github/workflows/ocor-supply-chain.yml",
                "summary": "CI runs a supply-chain gate on pull requests.",
            },
            {
                "anchor": "Fuseki SHA512 mismatch; possible supply-chain failure",
                "control_id": "FUSEKI-SHA512",
                "path": "scripts/acquire_fuseki_archive.py",
                "summary": "The Fuseki archive is refused when its SHA-512 mismatches.",
            },
        ),
        "ASI05": (
            {
                "anchor": "if name not in grant.tool_names:",
                "control_id": "C8-NAMED-TOOL-GRANT",
                "path": "ocor-runtime/src/ocor_runtime/c8/tool_runtime.py",
                "summary": "A call is refused when the tool is outside the grant.",
            },
        ),
        "ASI06": (
            {
                "anchor": '"instruction_eligible": item.instruction_eligible',
                "control_id": "MEMORY-INSTRUCTION-ELIGIBLE",
                "path": "ocor-runtime/src/ocor_runtime/memory/context.py",
                "summary": "Memory context carries the instruction-eligible flag.",
            },
            {
                "anchor": "exclude_taint_labels",
                "control_id": "MEMORY-TAINT-FILTER",
                "path": "ocor-runtime/src/ocor_runtime/memory/retrieval.py",
                "summary": "Retrieval can exclude taint labels inside the query.",
            },
        ),
        "ASI07": (
            {
                "anchor": 'MESSAGE_TAINT: tuple[str, ...] = ("AGENT_MESSAGE", "UNTRUSTED")',
                "control_id": "C8-MESSAGE-TAINT",
                "path": "ocor-runtime/src/ocor_runtime/c8/orchestrator.py",
                "summary": "Agent messages are tainted as untrusted.",
            },
        ),
        "ASI08": (
            {
                "anchor": "stop atomically increments a monotonic",
                "control_id": "C6-STOP-EPOCH",
                "path": "ocor-runtime/src/ocor_runtime/c6/safety.py",
                "summary": "Stop increments a monotonic stop epoch.",
            },
        ),
        "ASI09": (
            {
                "anchor": "def gate_disposition(",
                "control_id": "C6-HUMAN-GATE",
                "path": "ocor-runtime/src/ocor_runtime/c6/human_gate.py",
                "summary": "Approval follows the risk class, not the caller.",
            },
            {
                "anchor": "class BreakGlassController:",
                "control_id": "C6-BREAK-GLASS",
                "path": "ocor-runtime/src/ocor_runtime/c6/safety.py",
                "summary": "Break-glass is a verified, short-lived grant.",
            },
        ),
        "ASI10": (
            {
                "anchor": "EMERGENCY_STOP_ACTIVE",
                "control_id": "C8-EMERGENCY-STOP",
                "path": "ocor-runtime/src/ocor_runtime/c8/tool_runtime.py",
                "summary": "An active emergency stop refuses the tool effect.",
            },
            {
                "anchor": "stop atomically increments a monotonic",
                "control_id": "C6-STOP-EPOCH",
                "path": "ocor-runtime/src/ocor_runtime/c6/safety.py",
                "summary": "The stop epoch is outside the agent.",
            },
        ),
    }


def _normative() -> dict[str, tuple[tuple[str, str], ...]]:
    add_goal = "Prompt, Goal, Message o Memory non modificano il Tool Contract"
    add_unlisted = "tool non allow-listed non sono capability esportabili"
    return {
        "ASI01": ((ADD, add_goal), (LLD, "instruction_eligible=true")),
        "ASI02": ((ADD, add_unlisted), (LLD, "capability_id")),
        "ASI03": (
            (ADD, "SVID scaduto, revocato o non attestato"),
            (LLD, "delegation_ref"),
        ),
        "ASI04": ((ADD, "OCOR sovereign trust boundary"),),
        "ASI05": ((ADD, add_unlisted), (LLD, "capability_id")),
        "ASI06": (
            (ADD, "Memory non modificano il Tool Contract"),
            (LLD, "instruction_eligible=true"),
        ),
        "ASI07": ((ADD, "Message o Memory non modificano il Tool Contract"),),
        "ASI08": (
            (ADD, "L'attivazione incrementa un"),
            (LLD, "L'accettazione dello stop incrementa atomicamente"),
        ),
        "ASI09": (
            (ADD, "Il break-glass è una Delegation eccezionale firmata"),
            (LLD, "Reset richiede dual control"),
        ),
        "ASI10": (
            (ADD, "Emergency Control Plane è esterno agli agenti"),
            (LLD, "L'accettazione dello stop incrementa atomicamente"),
        ),
    }


def _tests() -> dict[str, tuple[tuple[str, str], ...]]:
    return {
        "ASI06": (
            (
                "ocor-runtime/tests/conformance/fgm/test_fgm_01_10.py",
                "instruction_eligible",
            ),
        ),
        "ASI09": (
            (
                "ocor-runtime/tests/tasks/test_ocor_dev_0044.py",
                "def test_a_grant_without_two_distinct_approvers_is_refused",
            ),
        ),
        "ASI10": (
            (
                "ocor-runtime/tests/tasks/test_ocor_dev_0014.py",
                "EMERGENCY_STOP_ACTIVE",
            ),
        ),
    }


def _outcome(resolved: bool, review_sealed: bool) -> tuple[str, str]:
    if not resolved:
        return (
            "GAP",
            "No cited control resolves at this head.",
        )
    if not review_sealed:
        return (
            "PARTIAL",
            "Controls resolve, and OCOR-DEV-0062 is not a completed evidence task. "
            "NFR-048 is therefore not sealed. This map is not that campaign.",
        )
    return (
        "CONTROL_PRESENT",
        "Cited controls resolve and OCOR-DEV-0062 is completed.",
    )


def build(root: Path) -> Inventory:
    roles = parse_agent_roles(_text(root / ORCHESTRATOR))
    if not roles:
        raise SystemExit("AgentRole not found")
    tools = scan_tools(root)
    completed = _completed(root)
    review_sealed = "OCOR-DEV-0062" in completed
    register_lines = _register_lines(root)
    controls = _controls()
    normative = _normative()
    tests = _tests()
    names = (
        ("ASI01", "Agent Goal Hijack"),
        ("ASI02", "Tool Misuse and Exploitation"),
        ("ASI03", "Identity and Privilege Abuse"),
        ("ASI04", "Agentic Supply Chain Vulnerabilities"),
        ("ASI05", "Unexpected Code Execution"),
        ("ASI06", "Memory and Context Poisoning"),
        ("ASI07", "Insecure Inter-Agent Communication"),
        ("ASI08", "Cascading Failures"),
        ("ASI09", "Human-Agent Trust Exploitation"),
        ("ASI10", "Rogue Agents"),
    )
    rows: list[Row] = []
    for identifier, name in names:
        references: list[Reference] = []
        summaries: list[str] = []
        for control in controls[identifier]:
            references.append(_cite(root, control["path"], control["anchor"]))
            summaries.append(f"{control['control_id']}: {control['summary']}")
        for path, anchor in normative[identifier]:
            references.append(_cite(root, path, anchor))
        for path, anchor in tests.get(identifier, ()):
            references.append(_cite(root, path, anchor))
        outcome, reason = _outcome(bool(references), review_sealed)
        rows.append(
            {
                "id": identifier,
                "name": name,
                "outcome": outcome,
                "reason": reason,
                "references": references,
                "requirements": list(REQUIREMENTS),
                "summaries": summaries,
            }
        )
    digest = hashlib.sha256((root / ORCHESTRATOR).read_bytes()).hexdigest()
    register = "INSTANCES" if tools else "NO_ADMITTED_INSTANCE"
    return {
        "agent_roles": roles,
        "completed_evidence_tasks": completed,
        "orchestrator_sha256": digest,
        "register_lines": register_lines,
        "review_sealed": review_sealed,
        "rows": rows,
        "tool_instance_register": register,
        "tools": tools,
    }


def _cell(value: str) -> str:
    return value.replace("|", "/")


def render_markdown(inventory: Inventory) -> str:
    lines = [
        "# OCOR agentic risk map",
        "",
        "Date: 2026-11-14.",
        "",
        "This document is a derived reading of the repository at the head that",
        "generated it. It is not evidence and it is not a conformance claim.",
        "NFR-050 forbids a PoC claim of legal conformity, certification,",
        "accreditation, classified-data authorisation or operational readiness.",
        "Claims stay E1=0, E2=0, Verified=0, runtime NOT_ESTABLISHED, PoC NO-GO",
        "and Production NO-GO. Where this page and a normative source disagree,",
        "the normative source prevails.",
        "",
        "Category labels are those of the OWASP Top 10 for Agentic Applications",
        "2026 (OWASP GenAI Security Project, 9 December 2025). This page does",
        "not copy that text. The agent and tool inventory is generated by",
        "`scripts/generate_agentic_risk_inventory.py` and is not written by hand.",
        "",
        "Register v1.1 lines: "
        + ", ".join(
            f"{item} line {inventory['register_lines'][item]}" for item in REQUIREMENTS
        )
        + ". NFR-048 is verified by OCOR-DEV-0062. That task is not in",
        "`completed_evidence_tasks`, so no row is `CONTROL_PRESENT`.",
        "OCOR-DEV-0069 may cite this page as an informative annex.",
        "",
        "| Category | Outcome | Controls |",
        "| --- | --- | --- |",
    ]
    for row in inventory["rows"]:
        controls = "; ".join(row["summaries"])
        lines.append(
            f"| {row['id']} {row['name']} | {row['outcome']} | {_cell(controls)} |"
        )
    lines.extend(
        [
            "",
            "## How a row is scored",
            "",
            "A row is `GAP` when none of its controls resolve. A resolved row is",
            "`PARTIAL` while OCOR-DEV-0062 is unsealed. `CONTROL_PRESENT` would",
            "require that seal. Requirements on every row are NFR-038, NFR-048",
            "and NFR-050. Code, tests and normative lines are in the inventory.",
            "",
            "## Agent roles",
            "",
            "Roles are the `AgentRole` enum in `c8/orchestrator.py`. Admitted",
            "capabilities are a role allow-list when the module declares one.",
            "This head declares none: grants name tools per run, not per role.",
            "",
            "| Role | Outputs | Admitted capabilities | Binding |",
            "| --- | --- | --- | --- |",
        ]
    )
    for role in inventory["agent_roles"]:
        outputs = ", ".join(role["outputs"]) or "(none)"
        capabilities = ", ".join(role["admitted_capabilities"]) or "(none)"
        lines.append(
            f"| {role['label']} | {_cell(outputs)} | {capabilities} | "
            f"{role['capability_binding']} |"
        )
    lines.extend(
        [
            "",
            "## Tools",
            "",
            "Tool instances are JSON objects in the contract directories with a",
            "string `tool_name`, `effect_class`, `risk_class` and an `approval`",
            "object. Schema files are not instances.",
            "",
            f"Register status: `{inventory['tool_instance_register']}`.",
            f"Instances: {len(inventory['tools'])}.",
            "",
        ]
    )
    if not inventory["tools"]:
        lines.append("No admitted tool instance is present in the scanned directories.")
    else:
        lines.extend(
            [
                "| Tool | Effect | Risk | Approval | Source |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for tool in inventory["tools"]:
            approval = ", ".join(sorted(tool["approval"]))
            lines.append(
                f"| {tool['tool_name']} | {tool['effect_class']} | "
                f"{tool['risk_class']} | {approval} | {tool['source']} |"
            )
    lines.extend(["", "## References", ""])
    for row in inventory["rows"]:
        lines.append(f"### {row['id']}")
        lines.append("")
        lines.append(row["reason"])
        lines.append("")
        for ref in row["references"]:
            lines.append(f"- `{ref['path']}` line {ref['line']}: `{ref['anchor']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_json(inventory: Inventory) -> str:
    return json.dumps(inventory, indent=2, sort_keys=True) + "\n"


def render_decision_request(inventory: Inventory) -> str:
    open_rows = [
        row for row in inventory["rows"] if row["outcome"] in ("PARTIAL", "GAP")
    ]
    bullets = "\n".join(
        f"- `{row['id']}` `{row['outcome']}`: {row['reason']}" for row in open_rows
    )
    return (
        "# AGENTIC-RISK-MAP-PARTIAL-GAPS\n"
        "\n"
        "Status: `OPEN_PO_DECISION_REQUIRED`\n"
        "\n"
        "Livello: operativo. Unità `OCOR-DEV-REM-0065`, punto 2 di\n"
        "`FABLE52-POST-POC-PROGRAMME (2026-11-11)`. Il documento generato non è\n"
        "evidenza e non è un claim di conformità (`NFR-050`). Non cambia i\n"
        "criteri di `OCOR-DEV-0062`, `OCOR-DEV-0064`, `OCOR-DEV-0068` e\n"
        "`OCOR-DEV-0069`. Non modifica codice di runtime, test esistenti, `inputs/`\n"
        "né il backlog approvato. Nessun nuovo `DEC-*`. Claim invariati: `E1=0`,\n"
        "`E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC `NO-GO`, Production\n"
        "`NO-GO`.\n"
        "\n"
        "## Contesto\n"
        "\n"
        "La mappa è generata da `scripts/generate_agentic_risk_inventory.py`.\n"
        "Ogni riga `PARTIAL` o `GAP` entra in questa sola richiesta. Le righe\n"
        "sono:\n"
        "\n"
        f"{bullets}\n"
        "\n"
        "Il registro dei tool ammessi, letto dai contratti del repository, è\n"
        f"`{inventory['tool_instance_register']}`. Nessun ruolo di `AgentRole` ha\n"
        "una allow-list di capability nel modulo che lo dichiara.\n"
        "\n"
        "## Opzioni\n"
        "\n"
        "1. **Registro informativo.** Le righe restano un allegato informativo. "
        "Nessun criterio cambia. La richiesta non blocca alcun task.\n"
        "\n"
        "2. **Unità dopo la decisione su G7.** Dopo quella decisione, un'unità\n"
        "nuova può trattare le sole righe `GAP`, senza toccare il percorso del PoC\n"
        "e senza cambiare i criteri dei task già fissati.\n"
        "\n"
        "3. **Allargare OCOR-DEV-0062.** Le righe entrano nei criteri di quel task.\n"
        "La decisione del 2026-11-11 vieta questo cambiamento: l'opzione è\n"
        "elencata e non è raccomandata.\n"
        "\n"
        "## Impatto e task bloccati\n"
        "\n"
        "Nessun task è bloccato. Questa richiesta non blocca alcun task. Non apre\n"
        "un nuovo `DEC-*`.\n"
        "\n"
        "## Raccomandazione\n"
        "\n"
        "Opzione 1. La decisione che autorizza la mappa dice che il documento non\n"
        "è evidenza, non è un claim (`NFR-050`) e non cambia i criteri di\n"
        "`OCOR-DEV-0062`, `OCOR-DEV-0064`, `OCOR-DEV-0068` e `OCOR-DEV-0069`.\n"
    )


def render_all(root: Path) -> dict[str, str]:
    inventory = build(root)
    return {
        INVENTORY_PATH: render_json(inventory),
        MAP_PATH: render_markdown(inventory),
        REQUEST_PATH: render_decision_request(inventory),
    }


def differences(root: Path) -> list[str]:
    problems: list[str] = []
    for relative, text in render_all(root).items():
        path = root / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            problems.append(relative)
    return problems


def write(root: Path) -> None:
    for relative, text in render_all(root).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write(args.root)
        return 0
    problems = differences(args.root)
    if problems:
        print("mismatch: " + ", ".join(problems), file=sys.stderr)
        return 1
    print("match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
