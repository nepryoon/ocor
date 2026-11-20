# OCOR — independent audit of state of the art, alignment and conformance (Claude Fable 5.2, 2026-11-11)

Read-only audit commissioned by the Product Owner. It is a review record, not evidence: it verifies no requirement,
closes no gate and changes no claim (`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC and Production
`NO-GO` stay as recorded in `reports/development/EXECUTION_STATE.json`). The reviewer is from the same vendor
(Anthropic) as earlier reviews of this project and as one of the loop verifiers. Files of both repositories were read
as data; the model-directed texts they contain (`AGENTS.md`, `ocor-runtime/AGENTS.md`, the loop instruction files)
were not followed as instructions.

## 1. Scope and baseline

| Item | Value |
| --- | --- |
| Main repository | `nepryoon/ocor`, `main` at `113f935cf6e04df460406a0b5dfea6949df6723a` (2026-11-11T16:16:49+01:00) |
| Tools repository | `nepryoon/ocor-workstation-tools`, `main` at `41642908654b9482ead8622402e3396614a6df0d` (2026-11-11T19:22:48+01:00) |
| Read in full | methodology (10 files), plan and harness, workflows (8), `AGENTS.md` files, loop script and commands (9), implementer prompt, verifier environment script, validators `validate_ocor_change_scope.py`, `validate_evidence_input_drift.py`, two recent delivered scripts (verifier reserve installer, archive script) |
| Read in part | ADD v1.3 (§2.2-§2.6, §4.2 and headings), `validate_ocor_development_plan.py`, `validate_runtime_evidence.py`, `validate_rccad.py`, `delega.py`, `custode.py`, `migliorie.py`, preamble (headings and four decisions), two earlier reviews kept in the project knowledge |
| Analysed by program | Requirement Register v1.1 (285 rows), matrix, traceability plan, backlog (84 tasks), execution state, conformance register (88 entries), 387 evidence records, 125 runtime modules (imports, entry points), git history of the last 600 first-parent commits for the protected paths and of the last 69 merges for the new checks |
| Executed | `sha256sum -c inputs/normative/SHA256SUMS` (8/8), `validate_evidence_input_drift.py` (PASS, 75 tasks, 241 inputs), `validate_ocor_change_scope.py`, `validate_language_policy.py`, `validate_test_reverse_traceability.py` (PASS), `validate_runtime_evidence.py --requirement-evidence` for the 285 requirements |
| Run on this change set | pinned `ruff` 0.13.1 on the whole tree, `mypy --strict` on the validator, 16 unit tests, `validate_ocor_change_scope.py`, `validate_language_policy.py`, `validate_evidence_input_drift.py` (all PASS); `validate_ocor_development_plan.py` (FAIL as expected, see §8.1); the patched loop script end to end on a test bench with stub agents; the installer on a copy of the archived workstation files |

Limits. No runtime suite, service stack or campaign was run. LLD v1.1, the Decision Register, the tests (128 files)
and the runtime modules were not read line by line; code conformance was sampled, and the 88 entries of
`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json` were taken as registered data, not re-verified. The
installed copies on the workstation were not seen: the tools analysis is of the archive, whose manifest records the
fingerprints of the installed sources. `validate_rccad.py` reports one `AFF-008` finding on a shallow clone only
(ancestor check); it is not counted.

## 2. Verdict

| Question | Answer |
| --- | --- |
| State of the art | **Partially.** The architecture matches or exceeds the 2026 market on governed actions, abstention, provenance and governed memory; it trails on protocol currency (MCP 2026-07-28, A2A 1.0), on open semantic interchange, on measured memory quality and on a deployable product surface. |
| Documentary alignment | **About 80 % (estimate).** Register, matrix, traceability plan and backlog name the same 285 requirements; six of ten cross-document checks find drift, all of it in derived and operational documents (plan text, satellite state, runner configuration, register statuses, agent instruction files). |
| Code conformance | **About 65 % of the PoC profile (estimate with a margin of ten points, not evidence).** Basis: 76 of the 88 registered divergences belong to remediation units recorded as merged, 6 are open, 4 deferred, 2 refuted; this audit adds 3 unregistered code divergences (F-05, F-06, F-07), two of them on P0 PoC requirements. The repository's own rule returns no qualifying evidence record for any of the 285 requirements, consistent with the declared fence. |

## 3. State-of-the-art assessment

Facts are from the sources in §9; the last two columns are the reviewer's judgement.

| Gap | Evidence | Impact | Proposal | Needed for production-ready |
| --- | --- | --- | --- | --- |
| G-1 MCP profile predates the 2026-07-28 revision (stateless core, sessions removed, Tasks as extension, issuer check in authorisation) | S4, S5; ADD v1.3 §3.5 names no protocol revision | Tool contract and C8 leases must map to a per-request, stateless transport; long-running tools map to the Tasks extension | Pin the MCP revision in the tool contract profile and add a conformance case per changed rule | Necessary |
| G-2 No agent-to-agent interoperability: `FR-048` (A2A, Rust SDK) is deferred (ADD v1.3 :210, :3580) while A2A 1.0 is stable and widely backed | S6 | External agents cannot reach the Agent Kernel through a standard; internal coordination is unaffected | Keep deferred for the PoC; schedule an A2A boundary adapter behind C8 after the PoC decision | Optional (MVP) |
| G-3 No open semantic interchange target: OSI v0.1 (January 2026) standardises metrics, dimensions and relationships in YAML | S7 | The BI layer the Product Owner plans above OCOR cannot exchange definitions with warehouse and BI tools | Add an OSI export generator to C1 as a derived artefact | Optional (MVP, needed for the BI positioning) |
| G-4 W3C boundary fixed at RDF 1.1 while RDF 1.2 (triple terms) is a Candidate Recommendation and SHACL 1.2 is in draft | S8; ADD v1.3 :321, :357 | Provenance on statements needs reification at the boundary; no effect on the canonical model | Track; declare RDF 1.2 as a capability once Jena support and the Recommendation exist | Optional |
| G-5 Governed memory has no retrieval-quality gate; products compete on LongMemEval and LoCoMo with temporal knowledge graphs | S9; ADD v1.3 :3767, :3806 | Lifecycle and non-interference are specified, answer quality is not measured | Add a benchmark task with a preregistered threshold on a public memory benchmark, run on the real stores | Necessary (MVP) |
| G-6 Causal runtime: identification by backdoor only, counterfactual deferred (`ELM-070`), no structure discovery | `c7/adapters/dowhy_engine.py:3-8`; ADD v1.3 :3036; S10 | What-if on pinned models is sound; proposing new relations from data (the adaptive-ontology idea) has no governed path | Add discovery as hypothesis generation only: proposals enter as tainted `DecisionProposal`, never as model edits | Optional (differentiator) |
| G-7 Agent governance is not mapped to the OWASP Top 10 for Agentic Applications (ASI01-ASI10, least agency, kill switch) | S11 | The controls exist in the design (leases, kill switch, human gate); the mapping auditors now ask for does not | Add a mapping table and an agent and tool inventory to the decision package | Necessary (documentation) |
| G-8 Development supply chain: mutable action tags in required workflows; required checks defined by the change they gate | F-04, F-08; S12 | A change set can weaken its own checks | Base-anchored guard (this change set) and SHA pinning | Necessary |
| G-9 Product surface: Palantir ships Ontology MCP, scoped pro-code agents and branching for automations; Microsoft ships a shared ontology layer reachable over MCP | S1, S2, S3 | OCOR has contracts and a library, no served endpoint, CLI or UI (F-05, F-06) | Post-PoC programme (decision request `FABLE52-POST-POC-PROGRAMME`) | Necessary |

Differentiators that hold against these products: vendor-neutral and air-gapped stack, code-first Ontology-as-Code,
explicit structural causal models with typed abstention, governed memory with deletion and legal hold.

## 4. Findings

Severity: blocking, high, medium, low. Cause: document, code, process, tool. References are at the commits of §1;
tools references are relative to the tools repository. "Registered" means present in the conformance register or
in the execution state.

| ID | Severity | Cause | References | Description | Correction | Where |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 | High | Process | `scripts/validate_ocor_development_plan.py:274`, `:1776-1788`; 134 evidence records list this file as input | The allowed-path list is edited by the change set it authorises and lives in a sealed-evidence input, so each unit self-authorises its paths and forces three requalification records. Not registered. | Move the list to data bound to a decision identifier; check it from the base revision | DR `FABLE52-SCOPE-ALLOWLIST-DATA` |
| F-02 | High | Tool | `loop/ocor-loop2.sh:381-386` | A verdict file already present with the right head closes the request without any verifier run; nothing binds a verdict to a run of the loop. Not registered. | Verdict ledger written only by the loop | Installer |
| F-03 | High | Tool | `loop/ocor-loop2.sh:373-380`, `:421-423`; `loop/prepare_verifier_env.sh:20`; `loop/istruzioni/openhands_preamble.md:1778-1790` | The loop checks only that `request_id` and `head_sha` are non-empty; the pre-campaign gate is a text rule; a malformed identifier stops the whole loop (STOP 8). Not registered. | Mechanical pre-verification gate, bounded, never stopping the loop | Installer |
| F-04 | High | Code (CI) | `.github/workflows/ocor-rccad.yml:3-7`, `ocor-poc-ci.yml:3-7`; `.github/CODEOWNERS:1-3` | Every required check runs the workflow and validators of the pull request itself; code owners are one account and advisory. Not registered. | Guard on `pull_request_target` running the base revision of the validator | `.github/workflows/ocor-alignment-guard.yml` |
| F-05 | High | Code | `ocor-runtime/pyproject.toml:10-15`, `:18-27`; `c6/fsm.py:56`; `c2/transport.py:39-41` | `psycopg`, `temporalio`, `rdflib` are imported by the runtime and declared only as test extras; two modules read normative files by a path outside the package. Not registered. | Declare runtime dependencies; ship contract data inside the package | Check S07; DR `FABLE52-RUNTIME-PACKAGING-AND-CLI` |
| F-06 | High | Code | Register v1.1 :146 (`FR-050`), :409 (`FR-164`), both P0 PoC; `ocor-runtime/pyproject.toml` (no entry point) | No command-line tool exists for the OaC toolchain. `NCR-PLAN-003` registers only the task allocation. | New register entry and unit | DR `FABLE52-RUNTIME-PACKAGING-AND-CLI` |
| F-07 | Medium | Code | `ocor-runtime/src/ocor_runtime/security/control_plane.py:2054-2062` | Workload identity is fetched with `docker exec` on the SPIRE agent container. Not registered. | Workload API adapter behind the existing port | Same DR |
| F-08 | Medium | Code (CI) | `ocor-poc-ci.yml:22-26`; `ocor-supply-chain.yml:24,26,319`; `ocor-lld-add-alignment.yml:27,30,37`; `ocor-tooling-bootstrap.yml:28`; `ocor-auto-merge.yml:27`; policy `OCOR_EXTERNAL_DEPENDENCY_POLICY.md:3-5` | Nine action references by mutable tag (24 occurrences) and two floating runners, against the dependency policy. Not registered. | Pin; ratchet on new lines | Checks S05, D06; DR `FABLE52-ALIGNMENT-GUARD-ENFORCEMENT` |
| F-09 | Medium | Code | `ocor-runtime/pyproject.toml:2`, `:13-14`, `:19`, `:21`, `:23-24` | Seven floating constraints; the lock covers all but the build requirement. Not registered. | Exact pins | Check S06; same DR |
| F-10 | Medium | Process | 351 JSON records, for example `reports/assurance/OCOR-DEV-REM-0059-RCCAD/OCOR-DEV-REM-0059.json:1128` | Evidence cites check and comparison scripts kept under the loop home, outside the repository; a clean environment cannot rerun them. Not registered. | Version the tools; reject new citations | Check D04; DR `FABLE52-EVIDENCE-TOOLS-VERSIONING` |
| F-11 | Medium | Process | 741 files with an absolute home path, 7 with a personal e-mail address, for example `reports/planning/OCOR_PLAN_RUN_STATE.json:48` | Personal data in a public repository. Sealed records cannot change. Not registered. | Redact at the source from now on | Check D05; same DR |
| F-12 | Medium | Document | `docs/development_plan/OCOR_AI_FIRST_DEVELOPMENT_PLAN.md:42`, `:50`, `:61` | Plan states 69 tasks, 13 G2 tasks and 28 waves; the backlog has 84, 28 and 29. The text is hash-pinned and its generator is excluded as drifted (`pyproject.toml:14-21`). Not registered. | Regenerate through the generator | Check S01; DR `FABLE52-PLAN-STATE-DOC-REFRESH` |
| F-13 | Medium | Process | `reports/development/METHOD_COMPLIANCE.json:14`, `:25`; `INFRASTRUCTURE_STATE.json:26`; `TOOLING_STATE.json:13`; `docs/development_methodology/OCOR_MODEL_OPERATING_PROFILE.md:3-14` | Satellite state is weeks old: a deviation still open that the execution state records as resolved, 11 services against 14 in the lock, the fingerprint of a former host. Not registered. | Refresh or retire each file | Check S03; same DR |
| F-14 | Medium | Document | `docs/development_plan/OCOR_DELIVERY_RUNNER_CONFIG.json:11-19`; `reports/planning/OCOR_COMPENSATING_PROTECTION_MODE.md:5-7` | Runner declares 2 mandatory contexts and pending external control; the state records a ruleset with 13 required checks. Not registered. | Align configuration and note | Check S04; same DR |
| F-15 | Medium | Document | `AGENTS.md:3`, `:19`; `ocor-runtime/AGENTS.md:3-4`; `loop/istruzioni/prompt.md:17`; `loop/istruzioni/openhands_preamble.md:1-5` | Agent instruction files describe a review-only repository, an old goal and an old repository name, and are read at every iteration. Not registered. | Refresh under a decision | Same DR |
| F-16 | Medium | Tool | `MANIFEST.json:747` (preamble 391,738 bytes, 152 sections); `loop/ocor-loop2.sh:662`, `:669`; `openhands_preamble.md:145`, `:167` (same heading twice) | Every implementer iteration receives the whole decision history, closed units included. | Index plus archive of closed sections | DR `FABLE52-LOOP-INSTRUCTIONS-AND-ARCHIVE` |
| F-17 | Medium | Tool | `consegne/ocor-strumenti-repo-v2-20261111.sh:37-50`; `sorveglianza/custode.py:101`; `grok/hooks/ocor-segreti.json:1` | The archive omits the extension folders that automatic improvements may write and the hook program the Grok hook runs. | Extend the collector | Same DR |
| F-18 | Low | Tool | `loop/ocor-loop2.sh:4-6`, `:21` | Header describes a superseded agent order; `set -uo pipefail` without `-e` is deliberate in a long-running loop but differs from the workstation rule. | Note only | None |
| F-19 | Medium | Tool | `loop/ocor-loop2.sh:335-361`, `:353`; `sorveglianza/custode.py:35` | Implementer independence is rebuilt from a writable log; one line resets it. Same-user limit, stated by the custodian itself. | Ledger narrows it; residual risk | Installer (part) |
| F-20 | Low | Document | Register v1.1 `:122`, `:125-128`, `:144`, `:414`, `:415`, `:422`: nine rows whose priority is not a single level (for example `P0/P1`, `P2/Deferred`, `P1 MVP; P0 Production`); six table layouts (headers at `:14`, `:40`, `:110`, `:173`, `:290`, `:398`) | Tools must special-case priority and release. | Normative erratum with the matrix erratum | DR `FABLE52-PLAN-STATE-DOC-REFRESH` (question C) |
| F-21 | Medium | Document, code | `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json:6875` (`NCR-GOVERNANCE-002`, 115 matrix rows), `:5874` (`NCR-TESTS-001` to `005`), `:6133` (`NCR-LEGACY-001`); `ocor-runtime/src/ocor_runtime/__init__.py:3-16` | Registered: matrix erratum pending, test realignment in progress, legacy slice still the public interface. | Existing units | None |
| F-22 | High | Process | `docs/development_plan/OCOR_AI_FIRST_DEVELOPMENT_PLAN.md:57`; backlog gates G0-G7; `validate_runtime_evidence.py --requirement-evidence` (0 qualifying, 93 legacy-only, 192 unbound) | No governed plan exists beyond the PoC decision package, while the stated objective is production integration; the 2026-10-30 proposal of gates G8-G11 was not adopted. | Decide the post-PoC programme | DR `FABLE52-POST-POC-PROGRAMME` |
| F-23 | Low | Process | `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json:74` (first of 76 `entries[].status`), `:22579` (`progress.pending_sections`); `EXECUTION_STATE.json:11071` (`remediation_status`) | 76 entries are still `IN_REMEDIATION` while every one of their units is recorded as merged; closure of the register is pending. Partly registered. | Advance statuses at closure | Check S10 |

Requirements without a task: none (285 of 285 allocated). Tasks without a requirement: none. Code without a
requirement: the legacy slice (registered, `NCR-LEGACY-001`).

## 5. Structural prevention

| Countermeasure | Mechanical check | Where it runs | What it blocks |
| --- | --- | --- | --- |
| C-1 Base-anchored guard | `scripts/validate_alignment_invariants.py`, base revision, reading the head through git objects | `ocor-alignment-guard.yml` on `pull_request_target` | D01 change to `inputs/` or to an approved baseline file; D02 change of a fenced claim; D03 change or deletion of sealed evidence. Replayed on the last 69 merges of `main`: no blocking finding. |
| C-2 Ratchet on registered drift | Checks S01-S10 and D04-D07 against `reports/development/ALIGNMENT_BASELINE.json` (31 registered findings) | Same job; advisory until decided | New drift of the kinds F-05, F-08-F-14, F-23; turned blocking by decision |
| C-3 Pre-verification gate | Request form, head present and published, base ancestry, evidence paths at the head, `inputs/` untouched, then the validator of C-1 read from `origin/main` once it is there | Loop, before the verifier is chosen | A request the verifier could not receive is rejected and archived (today it stops the loop, STOP 8); other defects are rejected twice per task at most, then passed to the verifier with the report. Rules checked on the request records kept in the repository: 242 of 242 identifiers hold the head prefix, 27 of 27 bases are ancestors of their head, 64 of 64 evidence paths exist at their head |
| C-4 Verdict ledger | sha256 of each verdict appended by the loop after its own verifier run | Loop | Closing a request with a verdict the loop did not obtain: such a file is archived and the verification runs |

## 6. Proposed normative changes

Each is a decision request in `reports/development/decision_requests/`, with options, recommendation, cascade and
acceptance criteria; none is applied here. They take effect only when the loop registers them in the execution
state; the Product Owner can keep any of them with `python3 -I ~/ocor-sentinella/delega.py riserva <ID>`. The last
one names loop files, so the decision component leaves it to the Product Owner by its own rule.

| Decision request | Subject | Recommendation |
| --- | --- | --- |
| `FABLE52-SCOPE-ALLOWLIST-DATA` | Allowed-path list as data bound to decisions | Option 1 |
| `FABLE52-ALIGNMENT-GUARD-ENFORCEMENT` | Guard as required check; modes of the advisory checks | Option 1 |
| `FABLE52-RUNTIME-PACKAGING-AND-CLI` | Register entries and unit for F-05, F-06, F-07 | Option 1 |
| `FABLE52-EVIDENCE-TOOLS-VERSIONING` | Evidence tools in the repository; redaction | Option 1 |
| `FABLE52-PLAN-STATE-DOC-REFRESH` | Plan text, satellite state, agent instruction files, register priorities | A1, B1, C1 |
| `FABLE52-POST-POC-PROGRAMME` | Programme after the PoC decision, with the state-of-the-art items | Option 1 |
| `FABLE52-LOOP-INSTRUCTIONS-AND-ARCHIVE` | Preamble index, archive coverage | Option 1 |

## 7. Script map

Script: `ocor-fable52-riallineamento-20261111.sh` (`--check` by default, `--apply`). Every file below is embedded in
full with its expected sha256, except the manifest, which is changed by inserting one entry.

| Repository | Path | Action | Reason |
| --- | --- | --- | --- |
| Main, branch `governed/fable52-realignment-20261111` | `scripts/validate_alignment_invariants.py` | New | C-1, C-2: checks S01-S10 and D01-D07 |
| Main | `reports/tests/test_validate_alignment_invariants.py` | New | 16 unit tests of the validator |
| Main | `reports/development/ALIGNMENT_BASELINE.json` | New | 31 registered findings and the mode of each check |
| Main | `.github/workflows/ocor-alignment-guard.yml` | New | C-1: job on `pull_request_target`, base revision only |
| Main | `reports/review/OCOR_FABLE52_AUDIT_2026-11-11.md` | New | This report |
| Main | `reports/development/decision_requests/FABLE52-SCOPE-ALLOWLIST-DATA.md` | New | F-01 |
| Main | `reports/development/decision_requests/FABLE52-ALIGNMENT-GUARD-ENFORCEMENT.md` | New | F-04, F-08 to F-11, C-1, C-2 |
| Main | `reports/development/decision_requests/FABLE52-RUNTIME-PACKAGING-AND-CLI.md` | New | F-05, F-06, F-07 |
| Main | `reports/development/decision_requests/FABLE52-EVIDENCE-TOOLS-VERSIONING.md` | New | F-10, F-11 |
| Main | `reports/development/decision_requests/FABLE52-PLAN-STATE-DOC-REFRESH.md` | New | F-12 to F-15, F-20, F-23 |
| Main | `reports/development/decision_requests/FABLE52-POST-POC-PROGRAMME.md` | New | F-22, G-1 to G-9 |
| Main | `reports/development/decision_requests/FABLE52-LOOP-INSTRUCTIONS-AND-ARCHIVE.md` | New | F-16, F-17, F-19 |
| Tools, branch `fable52-20261111` | `consegne/ocor-install-fable52-controlli-20261111.sh` | New | C-3, C-4: installer for the workstation |
| Tools | `MANIFEST.json` | One entry inserted | Archive manifest entry for the installer |
| Workstation | `~/ocor-strumenti/consegne/ocor-install-fable52-controlli-20261111.sh` | Written, not run | The same installer, for the Product Owner to run with the loop stopped |

The installer, when the Product Owner runs it, changes `~/.ocor-codex/ocor-loop2.sh` (six exact substitutions,
fingerprint checked before and after), appends two sections to each of the three instruction files and creates
`~/.ocor-codex/verdicts.ledger`. It makes a backup, runs the three authorisation and integrity checks on copies and
then on the real files, and restores everything on any failure.

## 8. Residual risks and what the script does not do

1. The pull request cannot pass `tooling-policy` by itself: the twelve new paths are absent from the allowed-path
   list (`authorized planning-only diff` fails with exactly these paths), and adding them changes a sealed-evidence
   input. Adoption is a remediation unit of the loop, asked for by the section `FABLE52-REALIGNMENT (2026-11-11)`
   that the installer adds; `OCOR_FABLE52_SENZA_ADOZIONE=1` installs the gate without that section.
2. The guard runs only after it is on `main`, and GitHub disables `pull_request_target` by default on public
   repositories from 2 December 2026: an event policy and the ruleset entry are Product Owner actions.
3. Loop, verifiers and automatic improvements run as one user: ledger and gate raise the cost of an unintended
   shortcut, they are not a cryptographic boundary. The durable invariants are the ones checked from `main`. The
   ledger starts from the verdict files present at installation, which it takes as they are.
4. The script stops if `main` of either repository has moved, and the installer stops if the installed loop script
   is not the archived one. Both accept a named exception (`OCOR_FABLE52_MAIN_SHA`, `OCOR_FABLE52_TOOLS_SHA`,
   `OCOR_FABLE52_LOOP_SHA`): then the new files must still be absent and every substitution must still match once,
   but the baseline may show findings this audit did not see, as new advisory findings.
5. The gate rules were replayed on recorded requests, not on live ones. The gate rejects a request twice per task
   at most and the loop variable `OCOR_PREVERIFY=0` turns it off.
6. Not corrected, each with a decision request and acceptance criteria: plan text, satellite state, agent
   instruction files, action and dependency pins, packaging and command-line tool, evidence tools kept outside the
   repository, personal data in sealed records, size of the instruction files, archive coverage, the programme
   after the PoC. They are hash-pinned, normative, part of sealed inputs or loop instructions.
7. Not done: no merge, no write to `main`, `inputs/`, `EXECUTION_STATE.json` or sealed evidence; no change to the
   delegation, to the automatic improvements or to agent start options; no paid resource. The script does not run
   `validate_ocor_development_plan.py`, which rewrites tracked planning files.
8. Estimates in §2 rest on sampling (§1, Limits).

## 9. Sources

- S1 Palantir, announcements 2026-08 (object timeline): <https://www.palantir.com/docs/foundry/announcements/2026-08>
- S2 Palantir release notes, July 2026 (pro-code agents, branching in Automate): <https://releasebot.io/updates/palantir>
- S3 Microsoft Fabric IQ, general availability with the ontology item in preview: <https://letsdatascience.com/news/microsoft-expands-fabric-iq-as-a-context-layer-for-ai-agents-e9a90bd8>, <https://kanerika.com/blogs/fabric-ontology/>
- S4 MCP 2026-07-28 changelog: <https://modelcontextprotocol.io/specification/2026-07-28/changelog>
- S5 MCP 2026-07-28 release note: <https://blog.modelcontextprotocol.io/posts/2026-07-28/>
- S6 Linux Foundation, A2A at one year (9 April 2026): <https://linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year>
- S7 Open Semantic Interchange specification (27 January 2026): <https://www.snowflake.com/en/blog/open-semantic-interchanges-specs-finalized/>
- S8 W3C RDF 1.2 Concepts, Candidate Recommendation Snapshot (7 April 2026): <https://www.w3.org/TR/2026/CR-rdf12-concepts-20260407/>; SHACL 1.2 Rules draft: <https://www.w3.org/TR/2026/WD-shacl12-rules-20260508/>
- S9 Agent memory benchmarks: <https://mem0.ai/blog/ai-agent-memory-benchmark>, <https://vectorize.io/articles/mem0-vs-zep>
- S10 Causal discovery with language models, survey (IJCAI 2025): <https://www.ijcai.org/proceedings/2025/1186.pdf>
- S11 OWASP Top 10 for Agentic Applications 2026: <https://cycode.com/blog/owasp-top-10-agentic-applications/>
- S12 GitHub Actions hardening and `pull_request_target` changes: <https://socket.dev/glossary/github-actions-security>, <https://www.wiz.io/blog/github-actions-security-pwn-request-reckoning>
