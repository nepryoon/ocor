# OCOR — Independent Assessment of the Extension Proposal (Annex A)

Technical Report · 12 November 2026 · Claude Fable 5.2 · read-only engagement · British English

Evidence labels: `[Verified]` observed at the analysed commit with `file:line`; `[Verified — search]` an absence established by a stated search over a stated scope (no line can be cited for something that is not there); `[Inferred]` deduced, with the reason; `[Not determinable]`; `[External source]` with link (list in §1.3).

Path abbreviations (main repository): **ADD** = `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md`; **LLD** = `docs/OCOR_LLD_v1.1.md`; **REG** = `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md`; **XW** = `…/registers/OCOR_CAP_ELM_Requirement_Crosswalk_v1.1_APPROVED.md`; **PLAN** = `docs/development_plan/OCOR_AI_FIRST_DEVELOPMENT_PLAN.md`; **TRACE** = `docs/development_plan/OCOR_TRACEABILITY_PLAN.csv`; **STATE** = `reports/development/EXECUTION_STATE.json`; **NCR** = `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`; **LANG** = `docs/development_methodology/OCOR_LANGUAGE_POLICY.md`; **DEP** = `docs/development_methodology/OCOR_EXTERNAL_DEPENDENCY_POLICY.md`; **RCCAD** = `docs/development_methodology/OCOR_RCCAD_v1.0.md`; **SRC** = `ocor-runtime/src/ocor_runtime`. Tools repository: **LOOP** = `loop/ocor-loop2.sh`.

---

## 1. Scope and baseline

### 1.1 Commits analysed

| Repository | Branch | Commit | Commit time |
|---|---|---|---|
| `nepryoon/ocor` | `main` | `1be8dd6ad73c1af94cb6726c70b8243ec8498ad3` (merge of PR #605) | 2026-11-12 11:00:04 +01:00 |
| `nepryoon/ocor-workstation-tools` | `main` | `38124102cbb9e1e9f98fc3a8aa5d535825cdd8bc` | 2026-11-12 03:43:04 +01:00 |

Both repositories were readable. Both clones are shallow (depth 1) and were left unmodified. The loop was running; everything below refers to these two commits only.

### 1.2 Material read

| Area | Files in area | How it was read |
|---|---:|---|
| Approved norm (ADD v1.3, LLD v1.1, Requirement Register v1.1, CAP/ELM Crosswalk v1.1) | 4 | ADD §§1.1–1.5, 2.2–2.5, 3.2 (prose, enumerations, runtime rules), 3.6, 3.8, 3.9 read; LLD §§0–2, 5, 7 read; Register searched by pattern across all 285 rows, about 45 rows read in full; all 26 CAP rows and selected ELM rows read |
| Methodology and policies | 9 | RCCAD, language policy, external dependency policy, Definition of Done, test strategy, fitness functions, tooling policy read in full |
| Plan and backlog | 5 | Development plan read in full; backlog JSON (84 tasks) and traceability plan (285 rows) parsed programmatically |
| Versioned state | 3 | `EXECUTION_STATE.json` parsed (top-level structure, claims, ready set, roles, escalation); conformance register parsed (88 entries); one decision request read in part |
| Runtime code | 125 | Inventory of all modules; 14 modules read in part (C1 code generation, C2 transport, C3 admission and ports, C4 SHACL, seven C5 modules, C8 orchestrator, memory embeddings); symbol searches over the whole tree |
| Tests | 128 + 107 | Inventory; three task tests read in part; requirement-identifier search over all test files |
| CI and deployment | 8 + 42 | Job structure of the eight workflows; Helm chart (3 files) |
| `README.md`, `AGENTS.md` | 2 | Read in full |
| Tools: loop | 11 | `ocor-loop2.sh` header, configuration, pre-verify gate and rotation logic read (about 45 % of 996 lines); remainder by targeted search |
| Tools: surveillance, commands, hooks | 13 | Header documentation of the six surveillance programs; hook file shape only |
| Tools: delivered scripts | 104 | Names of the latest 20; one section of `consegne/ocor-fable52-riallineamento-20261111.sh` |
| Tools: agent instructions | 4 | Sizes and section counts; `prompt.md` by search. Not read in full |

### 1.3 External sources consulted

- **E1** Docling technical paper — <https://arxiv.org/html/2501.17887v1>
- **E2** Docling project listing (licence, governance, latest release) — <https://www.opentechhub.io/docling/>
- **E3** vLLM structured outputs documentation — <https://docs.vllm.ai/en/v0.9.1/features/structured_outputs.html>, <https://docs.vllm.ai/en/v0.8.5/features/structured_outputs.html>
- **E4** vLLM v0.16.0 release notes — <https://newreleases.io/project/pypi/vllm/release/0.16.0>; licence and hosting (secondary source) — <https://aiwiki.ai/wiki/vllm/raw>
- **E5** Splink — <https://pypi.org/project/splink>, <https://pypi.org/project/splink/3.4.2>, <https://awesome.ecosyste.ms/projects/github.com%2Fmoj-analytical-services%2Fsplink>
- **E6** JSONSchemaBench — <https://arxiv.org/abs/2501.10868>
- **E7** Ilves, Barbu, Übi, schema-constrained evaluation of LLM knowledge-graph extraction (KG-LLM @ LREC 2026) — <https://aclanthology.org/2026.kallm-1.21/>
- **E8** Text2KGBench-LettrIA and OSKGC (ISWC 2025 workshops) — <https://ceur-ws.org/Vol-4041/paper3.pdf>, <https://ceur-ws.org/Vol-4041/paper1.pdf>
- **E9** Wikontic — <https://arxiv.org/pdf/2512.00590v2>
- **E10** Wang et al., "Match, Compare, or Select?" (COLING 2025) — <https://arxiv.org/html/2405.16884v1>
- **E11** Moslemi et al., heterogeneity in entity matching (survey) — <https://arxiv.org/html/2508.08076v2>
- **E12** Palantir Object Monitors and Automate — <https://palantir.com/docs/foundry/object-monitors>, <https://www.palantir.com/docs/foundry/automate>, <https://palantir.com/docs/foundry/object-monitors/evaluation/>
- **E13** Palantir AIP Document Intelligence — <https://www.palantir.com/docs/foundry/document-intelligence/overview/>; marketplace listing "AIP for Entity Resolution" — <https://platform.softwareone.com/product/aip-for-entity-resolution/PCP-7699-1762>
- **E14** Microsoft Fabric IQ overview — <https://learn.microsoft.com/fabric/iq/overview>
- **E15** Kafka Connect error handling (KIP-298) — <https://cwiki.apache.org/confluence/spaces/KAFKA/pages/80453065/KIP-298+Error+Handling+in+Connect>
- **E16** RDF 1.2 TriG Working Draft and RDF 1.2 status talk — <https://www.w3.org/TR/2026/WD-rdf12-trig-20260915/>, <https://watch.knowledgegraph.tech/videos/rdf-1-2-status-report>

### 1.4 Limits

1. Static analysis only: no test, campaign or CI run was executed, and no GitHub API was queried.
2. Absence findings rest on searches; a behaviour could exist under names the searches did not cover. Each search is stated.
3. Shallow clones: no history was examined.
4. The instruction files of the loop (589,984 bytes in four files) were not read in full.
5. `inputs/` was consulted only by search: the approved dossier supersedes it for obligations (`README.md:126-127`).
6. External sources are abstracts, documentation pages and vendor self-descriptions; vendor pages are not independent evidence of quality.
7. Effort is stated qualitatively; no numeric estimate is offered where the repository gives no basis.

### 1.5 Instructions addressed to models found in the material (not followed)

- `AGENTS.md` (main repository) instructs models, among other things, to write reports in Italian and to write under `reports/` (`AGENTS.md:17-18`, `:124-126`). The commission prevails; nothing was written to either repository.
- `prompts/*.md` (main repository) and `loop/istruzioni/*.md` (tools repository) are prompts for agents. Treated as data.
- No instruction hidden in data files was observed in the material read.

---

## 2. Decision summary

**Overall verdict on Annex A: partial value. Adopt a narrowed subset with changes; defer the rest; reject one element as redundant.** The proposal is internally coherent, but three of its five elements largely restate obligations that OCOR's approved design already contains. Its one genuinely new capability (document extraction) lies outside the current perimeter and belongs after the G7 decision, outside the core.

Main conclusions:

1. **H-0 is right on one point and wrong on another.** OCOR defines no path from unstructured documents to Claims. It does, however, already require identity resolution as a P0 PoC capability with a complete governance model (candidate match, adjudicated merge and split, reversibility). What is missing is the low-level specification and the runtime: only SHACL shapes and role output names exist in code, and the conformance register carries no entry for it. This exposure exists before G7 and independently of the proposal.
2. **H-1 holds on the ingress side only.** The ingestion contract accepts `CLAIM` envelopes and forbids adapters from writing state, so an upstream producer can attach without contract changes. The receiving half (the C3 `AdmitClaim` port and a claim lifecycle) has no implementation, so today such claims would be journalled and never admitted.
3. **P-02 and P-03 add a matcher technique and a no-match rule, not a model; P-05 is already normative and implemented in C5; P-04 is an MVP application feature over the existing subscription contract; P-01 is new.**
4. **The distance to "ready for production integration" is dominated by items the proposal does not touch:** no deployable service surface for the runtime, G6 and G7 open, no post-PoC plan in the repository (the backlog schema admits only `G0`–`G7`), and a mission-thread test that still runs legacy and spike components.
5. **Parallel product: "Yes, worth building" — one product, started after the G7 decision, not before.**

Decisions requested from the Product Owner (drafts in §10):

1. Specify identity resolution and claim admission at LLD level and schedule a remediation unit before `OCOR-DEV-0065` (or choose one of the two stated alternatives).
2. Define the semantics of a no-match decision.
3. Fix the boundary, language and dependency treatment of an upstream acquisition component, to take effect after G7.
4. Reconcile the stated objective with the release rules by defining an "integration-ready" release profile and a post-PoC plan.

---

## 3. Original intent and coherence criteria

Purpose, as approved: a sovereign, proprietary, vendor-neutral semantic-operational core; in the PoC a thin vertical slice over a wholly synthetic crisis scenario with simulated sources and targets `[Verified] ADD:104`. In scope for the PoC: the eight subsystems, policy and authority, Human Gate, audit, local PKI, contract-faithful simulators; deferred: `FR-048`, extended hardening of `CAP-024` and eight `ELM` items; out of perimeter: `CAP-026`, full Foundry/AIP/Apollo replication, real data and systems, physical effects, accreditation, Production HA and national scale `[Verified] ADD:209-212`.

State as recorded in the repository: claims `E1=0`, `E2=0`, `PoC_GO=NO-GO`, `Production_readiness=NO-GO`, `runtime_conformance=NOT_ESTABLISHED` `[Verified] STATE:8994-9000`; `current_gate=G6_IN_PROGRESS` `[Verified] STATE:9134`; status `REM_0061_CYCLE3_AWAITING_REASSIGNED_VERIFICATION` `[Verified] STATE:41543`. Backlog tasks recorded as completed-with-evidence: all of G0–G5 and one of seven in G6; six G6 tasks and three G7 tasks open `[Verified]` by parsing the backlog against `completed_evidence_tasks` (`STATE:9001` onwards). Code: 125 source files under `ocor-runtime/src`, about 58,900 lines of Python; 5,826 tests reported by the latest four-lane campaign note `[Verified] STATE:28`. These are records of the governed process, restated here without endorsement.

| ID | Criterion | Source | Nature |
|---|---|---|---|
| C-01 | Ontology-as-Code is the only authoritative definition source; every contract and artefact derives from one Canonical IR; drift blocks the release | ADD:146; LLD:107 | Absolute |
| C-02 | Epistemic separation: Observation/Claim ≠ Canonical State ≠ Projection ≠ Prediction ≠ Intervention ≠ Action ≠ Outcome; no implicit promotion | ADD:158-163; ADD:2048; REG:175 (`FR-053`) | Absolute |
| C-03 | One governed mutation path: only C6 → C3 changes canonical state; adapters and C5 deliver non-canonical input only | ADD:342; REG:200 (`FR-070`) | Absolute |
| C-04 | Closed, typed contracts; no backend dialect or identifier in public contracts; no arbitrary queries or predicates | ADD:270; ADD:2575; LLD:28 | Absolute |
| C-05 | Identity resolution is adjudicated, bitemporal and reversible; no canonical membership from a non-adjudicated candidate match | ADD:2051; ADD:2059; REG:120, 335, 336 | Absolute |
| C-06 | Marking and compartment isolation with conservative propagation; non-interference includes existence, rank, count and timing | ADD:201; LLD:214 | Absolute |
| C-07 | Fail-closed defaults; no silent fallback and no technology substitution | `OCOR_ARCHITECTURE_FITNESS_FUNCTIONS.md:20`; `OCOR_AUTONOMOUS_TOOLING_POLICY.md:31` | Absolute |
| C-08 | PoC boundary: synthetic, unclassified data; no real systems; no SaaS required at runtime | ADD:104; REG:307 (`NFR-046`); REG:349 (`NFR-059`) | Absolute for the PoC |
| C-09 | Claims change only through governed gates; PoC, MVP and Production have distinct exit criteria and none promotes another | RCCAD:40-42; REG:69 (`BR-012`); REG:436 (`BR-018`) | Absolute |
| C-10 | Sovereignty: on-premises and air-gap capable, including model serving; egress denied by default | REG:350 (`NFR-060`); REG:370 (`NFR-074`); LLD:332 | Absolute for MVP and Production |
| C-11 | Every dependency declares exact version, source, licence and cryptographic identity; licence and capability gate; paid or proprietary terms are escalated | DEP:3-5; DEP:15-16; REG:368 (`NFR-073`) | Absolute |
| C-12 | Implementation language fixed by policy (Python 3.12.11 for C1–C8 and adapters); migration only through thresholds fixed before measurement and a new decision | LANG:43; LANG:94-106 | Absolute |
| C-13 | Normative precedence and change control; a semantic change needs a governed decision; `inputs/` is immutable | RCCAD:11-14; `AGENTS.md:11` | Absolute |
| C-14 | Domain-neutral core: the vertical is removable without changing metamodel, IR or core contracts | REG:16 (`BR-001`) | Absolute |
| C-15 | Delivery discipline: one coherent task per iteration, independent verification, real-backend qualification; mocks never prove conformance | RCCAD:20; RCCAD:26-27; `OCOR_TEST_STRATEGY.md:23` | Absolute (process) |
| C-16 | Product Owner objective: prefer the production-destined solution, introduce no surrogate to be replaced later, do not preclude MVP or Production requirements | `reports/development/decision_requests/NORMATIVE-CONFORMANCE-PLAN.md:428` | Preference (operative PO disposition) |

**Tension to flag (C-16 against C-08 and C-09).** The approved plan ends with a PoC decision package and states that the Production campaign is deliberately absent from implementation tasks `[Verified] PLAN:57`; the backlog schema admits only gates `G0`–`G7` `[Verified] docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.schema.json:97-99`; 68 of 285 requirements are outside the PoC profile and are carried as ledger rows `[Verified]` by parsing TRACE (`campaign_profile`). Under `BR-012`, `BR-018` and `NFR-050` (REG:318) a PoC result cannot be presented as production readiness. The objective "ready for production integration at the end of development" is therefore not reachable at G7 by construction; it needs a defined post-PoC profile (§10, fourth draft). The objective is coherent with the norm as a design preference; it is not coherent as an end-state of the current plan.

---

## 4. Production-readiness gaps

Assessed from repository evidence only, without using Annex A as a source or as a checklist.

| # | Gap | Severity | Evidence | Already planned? |
|---|---|---|---|---|
| G-01 | Runtime conformance is not established; six G6 campaigns and the three G7 tasks are open; G6 campaigns are suspended behind the conformance programme | Blocking | `[Verified] STATE:8994-9000`, `STATE:9134`, `STATE:11151` | Yes — G6, G7 |
| G-02 | The runtime has no deployable service surface. No network listener exists under `ocor-runtime/src`; C2 has a wire-form transport adapter without a server; the Helm chart deploys only an operations agent (health, metrics, backup) | Blocking | `[Verified — search]` no match for `fastapi|uvicorn|grpc.server|aiohttp|flask|starlette|asgi|wsgi|http.server|serve_forever|add_secure_port` in `ocor-runtime/src`; `[Verified] SRC/c2/transport.py:1-9`; `deploy/helm/ocor-poc/templates/deployment.yaml:26-29`; LLD:338 expects a namespace and service account per subsystem | No — in no plan at this commit |
| G-03 | No post-PoC plan exists in the repository; the 68 non-PoC requirements have no implementation or qualification task | Blocking for the PO objective | `[Verified] PLAN:57`; schema `:97-99`; a programme proposal exists only inside a delivered script of the tools repository (`consegne/ocor-fable52-riallineamento-20261111.sh:1803-1833`), not in `reports/development/decision_requests/` of `main` `[Verified — search]` | No |
| G-04 | Entity identity resolution has no runtime. Code contains only SHACL shapes and the names of the Fusion/Identity role outputs; nothing produces candidate matches, executes merge or split, maintains bitemporal membership or retracts derivations. The LLD does not specify it. `FR-012`, `FR-030`, `FR-150`, `NFR-055` are cited in no source or test file. The task named "gateway and identity resolution" delivered principal identity | High (blocking for the G6 mission thread) | `[Verified] SRC/c4/shacl.py:81-110`; `SRC/c8/orchestrator.py:195`; `ocor-runtime/tests/tasks/test_ocor_dev_0034.py:1`, `:126-128`; TRACE:31, 49, 169, 248; ADD:2745 ("Identity reversibile … NOT RUN"); `[Verified — search]` no identity `merge`/`split`/`candidate match` behaviour in `SRC`; in the LLD no occurrence of `AdmitClaim`, candidate match or identity merge/split (the only "merge" is the memory-consolidation oracle at LLD:394) | Partly — allocated to `OCOR-DEV-0034`/`0065`; no entry in NCR for these identifiers |
| G-05 | Claim admission is not implemented: the C3 port `AdmitClaim` named by the ADD has no counterpart in code, and no claim lifecycle store exists (claims appear only as `claim_ref` bindings of a commit) | High | `[Verified] ADD:284`, `ADD:342`; `SRC/c3/ports.py:71`; `[Verified — search]` no `admit_claim`/`AdmitClaim` in `SRC` | No explicit task |
| G-06 | The qualified mission-thread test runs legacy and spike components instead of the retained C2, C4, C5, C7, C8 packages | High | `[Verified] NCR:5874` (`NCR-TESTS-001`, status `OPEN`) | Yes — `NCP-U12` (`STATE:11120`) |
| G-07 | The mission-thread view required at P0 for the PoC (`FR-166`) has no implementation symbol; it is allocated to the C6 FSM task | Medium–High | `[Verified] REG:411`; TRACE:185; LLD:246; `[Verified — search]` no `MissionThreadView` in `SRC`. `[Inferred]` misallocation: the allocated task concerns the action FSM | Allocated (`0043`/`0063`), probably not delivered by them |
| G-08 | No connector to a real source and no adapter to a real target: by design the PoC uses simulators | High for production; none for the PoC | `[Verified] ADD:104`; REG:435 (`BR-017`, connectors are MVP scope) | Requirement exists (MVP); no task |
| G-09 | No path from unstructured sources to Claims | Medium (High if the first pilot is document-centred) | `[Verified — search]` no match for `unstructured|non strutturat|OCR|PDF|information extraction|named entity` in ADD, LLD, REG; only a typed media reference exists (XW:61, `ELM-012`) | No — absent from every plan |
| G-10 | HA, scale, multi-region, SLO ratification and E2 evidence are outside the PoC | High for production | `[Verified] PLAN:55`, `PLAN:57`; LLD:421 | No plan |
| G-11 | Numeric acceptance thresholds are not frozen (`OI-008`) | Medium | `[Verified] LANG:60-69` | Open item |
| G-12 | The legacy slice coexists with the normative components; a legacy agent kernel built without a capability authority skips authorisation instead of failing closed | Medium (security-relevant) | `[Verified] NCR:5293` (`NCR-C8-006`, `DEFERRED_BY_PO`); `NCR:6133` (`NCR-LEGACY-001`) | Deferred by PO |
| G-13 | No operator or user surface (adjudication queue, quarantine console, role-oriented tools) | Medium | `[Verified] LLD:246-248`; TRACE:186 (`FR-167`, MVP) | Requirement exists (MVP); no task |
| G-14 | Integrity of the development tooling: the verdict ledger and the implementer set are files writable by the same OS user; a verifier-assignment error consumed a verification cycle on `REM-0061` | Medium (process) | `[Verified]` tools `LOOP:116-119`, `LOOP:382`; `STATE:10552` | Limit declared in the tools; no countermeasure planned |

Heuristic, to be read with caution: 121 of the 217 PoC-profile requirement identifiers appear in no file under `ocor-runtime/src`, `ocor-runtime/tests` or `reports/tests` `[Verified]` by identifier search. `[Inferred]` this is not proof of absence (code can implement without citing), but for G-04 it coincides with the absence of any implementing symbol.

---

## 5. SOTA context

| Theme | State of the art in 2026 | Source | Position of OCOR |
|---|---|---|---|
| Ontology- or schema-guided extraction | Extraction against an explicit ontology with schema-injected prompts and structured generation is the mainstream approach. Benchmarks moved to ontology conformance and hallucination metrics; manual review shows automatic triple-F1 understates quality because gold annotations are incomplete. Pipelines add ontology-aware refinement and entity normalisation after extraction | `[External source]` E7, E8, E9 | No extraction. The precondition exists: a typed IR and JSON Schema generation per type |
| Schema-constrained generation | Constrained decoding against JSON Schema is the dominant technique. Frameworks differ widely in which schema features they support (the best handled about twice as many real schemas as the worst). It guarantees form, not truth. vLLM serves JSON-schema-constrained output with `xgrammar` or `guidance` back ends | `[External source]` E6, E3 | Closed JSON Schema 2020-12 records throughout (LANG:52). A generated extraction schema would have to stay inside the subset the chosen decoder supports |
| Document understanding | Docling: MIT-licensed code, hosted by LF AI & Data, runs fully locally (suitable for air-gapped use), unified document model with page-level provenance; frequent releases | `[External source]` E1, E2 | None. The `Evidence` class (digest, acquisition, chain of custody) would hold documents (ADD:2006) |
| Entity resolution | Blocking followed by matching remains the standard pipeline. Fellegi–Sunter tooling (Splink: MIT, DuckDB or Spark back ends, unsupervised parameter estimation, explanatory charts) is mature. LLM matching is strong zero-shot but independent pairwise decisions ignore global consistency. Heterogeneous data breaks benchmark-level results; human-in-the-loop is listed as an open direction | `[External source]` E5, E10, E11 | The normative model is stricter than common tooling (adjudicated, bitemporal, reversible). The implementation is absent (G-04) |
| Knowledge graph provenance | PROV-O remains the reference vocabulary; RDF 1.2 adds triple terms for statements about statements and is in late Working Draft | `[External source]` E16 | PROV-O-based metamodel at claim level (ADD:1998-2018); the declared boundary is RDF 1.1 (LANG:55) |
| Human-in-the-loop on model output | Commercial platforms pair extraction with evaluation of extraction strategies and with entity-resolution suggestion workflows; research surveys treat human review as unresolved at scale | `[External source]` E13, E11 | Human Gate and steward/adjudicator roles are normative (REG:335). No review surface (G-13) |
| Subscriptions and alerting on ontology objects | Palantir Object Monitors are in sunset in favour of Automate: conditions on object data, notification effects, evaluation per subscriber so that permissions are respected | `[External source]` E12 | Event Subscription Contract with policy re-evaluated per delivery, marking propagation and declared redaction (ADD:2575, ADD:2728); triggers and automation are MVP scope (REG:217). No notification layer |
| Error handling in ingestion | Kafka Connect baseline: tolerance setting, dead-letter topic, error context headers, error metrics | `[External source]` E15 | Four failure classes including a non-disclosing policy quarantine and an operator gate (LLD:156-165); implemented in C5 with durable dead letters and quarantine (`SRC/c5/adapters/postgres.py:44-62`) — stricter than the baseline |
| Operational ontology platforms | Microsoft Fabric IQ ships an ontology item (preview) with entity types, relationships, rules and agent grounding; Palantir remains the reference | `[External source]` E14, E12 | Differentiators in the design: epistemic separation, causal runtime with abstention, governed agent kernel, sovereignty. Behind on connectors, user surfaces and deployability (G-02, G-08, G-13) |

---

## 6. Proposal assessment

### 6.1 Hypotheses

**H-0 — partly true.**

- *"Input is assumed structured and schema-conformant"* — **true.** The envelope is a closed schema; the payload undergoes a second mandatory validation against a content-addressed schema; ingest modes are `BATCH`, `STREAM`, `CDC` `[Verified] ADD:529`, `ADD:593`; REG:199 (`FR-069`).
- *"No definition of how unstructured sources become admissible claims"* — **true** `[Verified — search]` (see G-09).
- *"No definition of how to establish that two records describe the same object"* — **false at normative level, true for algorithm and implementation.** The norm requires candidate identities, reversible merge and split and fail-safe blocking of action (REG:65 `FR-012`; REG:120 `FR-030`; REG:335 `FR-150`; REG:336 `NFR-055`; XW:34 `CAP-016`); the ADD defines `CandidateMatch` (matcher or model pin, score, score semantics), `MatchEvidence`, `MergeDecision`, `SplitDecision`, `ClusterMembershipAssertion` (ADD:2010-2015), routes admission, merge and split through the same FSM, guards and Human Gate (ADD:2789), and assigns candidate generation to a Fusion/Identity agent role with no autonomous adjudication (ADD:3059). What is undefined is the matching method and any LLD-level specification; what is missing is the runtime (G-04).

Elements that lose foundation: the data-model and governance content of **P-02** (it restates ADD §3.6 and §4.1) and the recording half of **P-03** (it restates `FR-054`, REG:176). Their residual content is the matcher technique and the no-match rule.

**H-1 — true, with two caveats.** The separation and the governed admission are normative and partly implemented: source systems are authoritative only for the Observation or Claim they emit (ADD:140); a payload may create `Observation`, `Claim`, `ObservedEvent` or `CDCChange` and never canonical state (ADD:849); C5 delivers to C3 only non-canonical input, inadmissible without the governed path (ADD:342); the C3 commit admission checks GatePackage, Decision, Authority and Evidence `[Verified] SRC/c3/admission.py:1-13`. Caveats: (1) the receiving half is not implemented (G-05), so "without modifying the core" is true of the contract and false of the code needed to make such claims useful; (2) each new claim payload needs an event type and a payload schema generated by C1 and registered, that is an OaC change and a release — in design, but not "no change".

### 6.2 Summary

| Element | Verdict | Confidence | Placement | Timing |
|---|---|---|---|---|
| P-01 Ontology-guided extraction | `DEFER` | High on timing; medium on eventual value | Separate product, plus one derived artefact in C1 | After the G7 decision |
| P-02 Identity resolution as claims | `ADOPT WITH CHANGES` | High on the core gap; medium on the matcher choice | Core for decision records and merge/split path (already normative); periphery for the matcher | Core part before `OCOR-DEV-0065`; probabilistic matcher after G7 |
| P-03 Human decisions as evidence | `ADOPT WITH CHANGES` | Medium–high | Core semantics (identity decision model) | Recording with the P-02 core part; suppression rule after G7 |
| P-04 Subscriptions and convergence alerts | `DEFER` | Medium–high | Peripheral component over the existing `Subscribe` port | After G7 (MVP scope) |
| P-05 Explicit processing lifecycle | `REJECT` as a core extension (already covered); narrow residual deferred | High | None for the core; design rule for any upstream component | Residual after G7 |

### 6.3 P-01 — Ontology-guided extraction

1. **Problem.** Real, and outside the current perimeter: no document path exists (G-09) and the PoC forbids real data (REG:307).
2. **Existing coverage.** Enablers only. C1 already renders JSON Schema for every IR type from the one IR and checks drift `[Verified] SRC/c1/codegen.py:118`, `:159`, `:441`; the envelope accepts `semantic_class=CLAIM` (ADD:594-596); `Evidence`, `Source` and `TransformationActivity` carry digest, acquisition and model or prompt pin (ADD:2006, 2008, 2017). No component, task or deferred capability covers extraction.
3. **Coherence.** Respects C-01, C-02, C-03 if its only output is ingestion envelopes. Tensions: C-08 (cannot run on real documents inside the PoC), C-10 (local serving required), C-11 (model-weight licences are separate from code licences), C-12 (a new component has no row in the language table), C-15 (single-lane loop with G6 pending). No violation if kept out of the core and after G7.
4. **Value.** Makes document-heavy pilots possible. Beneficiaries: integrators and analysts. Measures: precision and recall of admitted claims on an adjudicated sample; share of claims whose cited span is found verbatim in the source; adjudication minutes per admitted claim. Contribution to the PO objective: indirect; it is not on the path to an integration-ready core.
5. **SOTA.** Architecture aligned (E7, E8). As written it is below current practice on three points: no grounding check of the cited passage, no abstention or uncertainty output, no evaluation protocol. Decoder coverage of JSON Schema features varies (E6), so "the ontology changes and the extractor follows with no manual step" holds only if generated schemas stay within a tested subset.
6. **Cost and risk.** Heavy dependency chain (document models, GPU serving); prompt injection through documents (content must stay tainted); marking of extracted claims must inherit the document marking by conservative join (C-06); adjudication capacity becomes the bottleneck; Model Registry pins for every model and prompt (REG:184). No effect on open gates if deferred; high scope-drift risk if started earlier.
7. **Strongest counter-argument.** Without documents OCOR can be piloted only where clean structured feeds exist, which is rare in the reference vertical; deferring postpones the first realistic data flow, and the admission path will be designed without ever being loaded by noisy, low-reliability input. *Assessment:* this argues for designing admission with such input in mind now (§10, first draft), not for building extraction now.
8. **Alternatives.** (a) Nothing: integrators supply typed claims. (b) Structured connectors first (`BR-017`), which yield more per unit of effort. (c) Human-entered claims through a workbench. (d) Only the C1 artefact, leaving extraction to third parties.
9. **Placement.** Separate product; one derived artefact ("extraction profile") in C1.
10. **Timing.** After the G7 decision.
11. **Verdict.** `DEFER`. On activation, required changes: the generator lives in C1 and its output carries `irDigest` and is drift-checked; provenance is an `Evidence` record for the document plus a `TransformationActivity` with model and prompt pins, not a bare passage reference; a deterministic check that each cited span occurs in the source; an explicit abstain outcome; a pre-registered evaluation set and threshold; output only as `CLAIM` envelopes. The verdict would change to `ADOPT WITH CHANGES` if the PO re-baselines the first pilot as document-centred and accepts the delay to G7.

### 6.4 P-02 — Identity resolution as claims

1. **Problem.** Real and current, but not the one stated: the model exists, the runtime and the LLD specification do not (G-04). OCOR must show merge followed by split reconstructing prior states in the mission thread (REG:120; ADD:2745).
2. **Existing coverage.** The proposal's output ("identity claim with score, per-property contribution and provenance; not a fusion; merge and split governed, approved, reversible, traced") is ADD §3.6 and §4.1 almost item for item (ADD:2010-2015, 2051, 2789). Code: validation shapes only (`SRC/c4/shacl.py:81-110`). Synthetic data must include identity ground truth (REG:66, `FR-013`).
3. **Coherence.** Respects C-02, C-03, C-05. Tensions: C-06 — candidate generation across compartments is an existence channel, and shared approximate-nearest-neighbour structures across compartments are forbidden without a non-interference proof (LLD:220); C-11 and C-07 — DuckDB would be a new engine and must sit behind an adapter (fitness rule `AFF-006`, `OCOR_ARCHITECTURE_FITNESS_FUNCTIONS.md:17`); the vector profile of the ontology state is deferred (ADD:326), so vector blocking must stay a private index of the matcher.
4. **Value.** For the core part: removes a P0 exposure before the mission-thread campaign. For the matcher: explainable scores that adjudicators can act on. Measures: pairwise precision and recall against the fixture ground truth; share of merges reversed; adjudication time per candidate.
5. **SOTA.** Blocking plus Fellegi–Sunter is aligned with established practice and explainable (E5, E10). Limits: the model needs several weakly correlated attributes and is not designed for a single free-text column such as a bare organisation name (E5); pairwise scoring ignores cluster-level consistency (E10). The OCOR model is ahead of typical tools on reversibility and adjudication.
6. **Cost and risk.** Core part: one remediation unit touching C3, C6 action types, C8 role outputs, tests and the LLD; it sits on the path to `OCOR-DEV-0065`. Matcher: new dependencies, parameter governance per entity type, risk of threshold tuning on the test data (forbidden in spirit by LANG:86-92 for benchmarks).
7. **Strongest counter-argument.** The PoC needs only a deterministic matcher over synthetic fixtures; introducing a probabilistic engine now adds dependencies and tuning with no acceptance criterion that requires it. *Assessment:* correct — hence the split in timing.
8. **Alternatives.** (a) Deterministic rule matcher pinned by version for the PoC, probabilistic matcher later behind the same record shape. (b) Reclassify the identity requirements to MVP by a register decision, as the crosswalk records for `FR-095` (XW:37; ADD:211); this would also touch `BR-015`, which names identity resolution in the mission thread (REG:426). (c) Nothing: let `OCOR-DEV-0065` implement "the smallest contract-compliant implementation" without an LLD anchor.
9. **Placement.** Core: decision records, admission, merge and split through C6 → C3. Periphery: the matcher, as the realisation of the Fusion/Identity role or inside the upstream product.
10. **Timing.** Core part before `OCOR-DEV-0065`. Probabilistic matcher after G7.
11. **Verdict.** `ADOPT WITH CHANGES`. Changes: introduce no new model — emit `CandidateMatch` and `MatchEvidence` exactly as in ADD §3.6 with `scoreSemantics=probability` and one `MatchEvidence` per comparison carrying its weight; weights and thresholds versioned in OaC and pinned as a model in the registry; blocking index partitioned by the full isolation tuple (ADD:201); merges only as C6 decisions with `effect_class=CANONICAL_COMMIT`. The verdict becomes `DEFER` for the whole element if the PO chooses alternative (b).

### 6.5 P-03 — Human decisions as evidence

1. **Problem.** Partly real. Recording acceptance and rejection is already required (REG:176, `FR-054`). Not specified anywhere: that a later run must respect a rejection and not re-propose the same pair without new evidence.
2. **Existing coverage.** `IdentityResolutionDecision` has an outcome, adjudicator, rationale and evidence set (ADD:2012); non-adjudicated candidates remain representable (ADD:2053). The shape in code targets only merge and split decisions (`SRC/c4/shacl.py:87-88`); the outcome values are not enumerated in the ADD `[Verified — search]`.
3. **Coherence.** Respects C-02 and C-05 and strengthens the conservation of dissent. Tension with C-13: an outcome enumeration and a matcher obligation are normative refinements.
4. **Value.** Removes repeated adjudication of the same pair; preserves negative knowledge as evidence. Measure: re-proposal rate of pairs already rejected (target zero while the evidence set is unchanged).
5. **SOTA.** Aligned: cannot-link constraints and reviewer labels feeding later runs are standard; human review is still an open problem at scale (E11).
6. **Cost and risk.** Small once the decision record exists. Risks: stale rejections after the world changes; "new explicit evidence" must be mechanical, or it becomes discretionary.
7. **Strongest counter-argument.** Suppression hides true matches that become evident later and creates a silent bias toward past human error. *Assessment:* addressed by tying suppression to the evidence-set digest and by making suppressed candidates queryable.
8. **Alternatives.** Record only (the current requirement); or matcher-side configuration without normative semantics, at the price of divergent matchers.
9. **Placement.** Core semantics.
10. **Timing.** Outcome enumeration and record with the P-02 core part; suppression rule after G7 (no PoC criterion requires it).
11. **Verdict.** `ADOPT WITH CHANGES`: define the outcome set and the re-opening rule (§10, second draft). It becomes `DEFER` if the first draft in §10 is not adopted.

### 6.6 P-04 — Subscriptions and convergence alerts

1. **Problem.** A real user need; not a defect of the core.
2. **Existing coverage.** Substantial for the mechanism: Event Subscription Contract (ADD:2575), policy and authority re-evaluated on every delivery with propagated marking and declared redaction (ADD:2728), `Subscribe` implemented in C5 (`SRC/c5/subscription.py:1-10`; `SRC/c5/backbone.py:405`); derived subscription contracts and triggers with auditable automation runs are MVP requirements (REG:79 `FR-016`; REG:217 `FR-084`). Missing: a watchlist as a named filter over an entity set, and delivery of notifications to people.
3. **Coherence.** Respects C-04 only if the watchlist is a filter contract generated by C1 (the contract forbids arbitrary predicates). Tensions: C-06 — an alert reveals that information exists; C-02 — alerting on *proposed* information invites action on unadmitted claims unless the epistemic status is carried and shown.
4. **Value.** Analyst productivity in case work. Measure: time from admission of a relevant claim to analyst awareness; share of alerts acted upon.
5. **SOTA.** Comparable platforms offer object-condition monitors with per-subscriber evaluation (E12). The OCOR contract already encodes the per-delivery policy check, which is the hard part.
6. **Cost and risk.** Notification channels are new egress paths (C-10); alert fatigue; timing channels across compartments.
7. **Strongest counter-argument.** Without alerting a pilot user must poll, and an operational ontology that cannot notify is not operational. *Assessment:* fair for MVP; no PoC criterion depends on it.
8. **Alternatives.** Deliver through `FR-084` triggers plus the existing `Subscribe` port; in the PoC, expose nothing.
9. **Placement.** Peripheral component and client surface.
10. **Timing.** After G7.
11. **Verdict.** `DEFER`. Becomes `ADOPT WITH CHANGES` in the post-PoC plan with these changes: watchlists as OaC filter contracts; alerts carry epistemic status and marking; unadmitted claims alert only principals holding an adjudication role.

### 6.7 P-05 — Explicit processing lifecycle

1. **Problem.** Not present in the core: the lifecycle is already normative and implemented for ingestion.
2. **Existing coverage.** Requirement (REG:205, `FR-074`); design with four classes, bounded retry, immutable dead letters, non-disclosing quarantine, operator gate, declared replay (LLD:156-165); code: failure classes (`SRC/c5/retry.py:24-28`), durable dead-letter, quarantine and checkpoint tables (`SRC/c5/adapters/postgres.py:44-62`), authorised reprocessing and replay (`SRC/c5/backbone.py:577`, `:618`). The conformance register recorded the earlier gaps (NCR:2654, NCR:2731) and the state file records the corresponding unit as merged (`STATE:11132`).
3. **Coherence.** The element as written creates one tension: "observable state for every phase" conflicts with the non-disclosing quarantine of policy-denied events (LLD:162) if the observer is the producer.
4. **Value.** For the core, none beyond what exists. Residual: an authorised read surface for the fate of one item (the publish receipt returns only the event identifier and a duplicate flag, `SRC/c5/backbone.py:95-97`).
5. **SOTA.** OCOR is at or above the common baseline (E15).
6. **Cost and risk.** A second lifecycle vocabulary beside the C5 one would be a regression.
7. **Strongest counter-argument.** Integrators need to know what happened to what they sent; operator-only visibility is not enough for production support. *Assessment:* valid for the residual surface, with policy filtering.
8. **Alternatives.** Nothing for the core; require any upstream component to reuse the four C5 classes verbatim.
9. **Placement.** None for the core; design rule for upstream stages.
10. **Timing.** Residual after G7.
11. **Verdict.** `REJECT` as a core extension, because it is redundant. Residual (authorised item-status surface; reuse of the C5 taxonomy upstream) deferred with P-01. The verdict would change only if evidence showed the C5 implementation failing its G6 campaign (`BA-07`).

### 6.8 Excluded elements (A.3)

| Exclusion | Assessment |
|---|---|
| Generic untyped interchange format | Correct and already imposed by OCOR: closed records with `additionalProperties: false` (ADD:537), C-04 |
| Single entry point dispatching heterogeneous actions by parameter | Correct and already imposed: typed ports per subsystem (ADD:282-289), six named queries (LLD:28) |
| One signing secret shared by all components | Correct and already imposed: workload identity, mTLS, producer-signed envelopes (LLD:332; LLD:154) |
| One model call per text fragment and entity type | Reasonable as a cost rule, not an absolute: a single call needs a union schema, and decoder support for complex schemas varies (E6); batching by groups of types may be necessary |

The first three exclusions add nothing to OCOR; they would matter only for a product built outside its contracts.

### 6.9 Technology hypotheses (A.4)

| Hypothesis | Licence and maintenance | Fit with OCOR policies |
|---|---|---|
| Docling for parsing and OCR | Code MIT; hosted by LF AI & Data; local execution; active releases through 2026 `[External source]` E1, E2 | Admissible subject to DEP: exact pin, checksum, and a separate licence record for each model it downloads (the project states model licences are those of the original packages, E2). Large transitive dependency set |
| vLLM with JSON-Schema-constrained decoding | Apache-2.0 per a secondary source (E4); structured outputs with `xgrammar`/`guidance` (E3); fast release cadence (E4); `[Inferred]` from E3: the documented request parameters differ between the versions consulted, so client code must be pinned with the server | Meets C-10 as a local service. To be run as a digest-pinned image, not imported into the runtime process. Model weights need their own licence gate; terms requiring acceptance are escalated (DEP:15-16). Generated schemas must be tested against the pinned decoder |
| Splink on DuckDB, vector preselection | Splink MIT; DuckDB back end; Fellegi–Sunter (E5) | Admissible in a peripheral component behind an adapter (`AFF-006`). Qdrant is already a client authorised by the language policy (LANG:49) and should be preferred to a new vector store. Weak on single free-text attributes (E5) |
| Language: per repository policy; another language for the resolver only above the policy's migration thresholds | — | Consistent in principle with LANG §3. Two gaps: the language table enumerates existing areas and has no row for a new component (LANG:40-56); migration thresholds exist only for four named components (LANG:94-99), so none applies to a resolver. The policy's own rule requires thresholds to be fixed before any measurement (LANG:91-92) |

### 6.10 The proposal as a whole

- **Internal coherence:** good; the five elements form a consistent upstream pipeline.
- **Undeclared assumptions:** that OCOR lacks an identity and lifecycle model; that markings of extracted and matched data are unproblematic; that adjudication capacity scales with extraction volume; that Italian and multilingual documents behave like benchmark English; that a legal basis and retention rules for real documents exist (the register lists them as open before real data, REG:381, REG:384).
- **Missing elements:** source reliability assessment (ADD:2009); deduplication of the same claim from many documents and handling of contradiction as dissent; propagation of deletion to claims and embeddings; an evaluation harness; back-pressure between extraction rate and adjudication capacity; treatment of documents as untrusted, tainted input.

---

## 7. Improvements to existing and planned tools

Origin: **A** = derived from Annex A; **E** = emerged from the analysis.

| # | Origin | Object | Improvement | Evidence | Mechanical control | Priority | Output form |
|---|---|---|---|---|---|---|---|
| I-01 | E | Conformance register (implemented) | Record the divergences for identity resolution, claim admission and the mission-thread view | G-04, G-05, G-07 | Register entries present; `OCOR-DEV-0065` lists them as blocking | High | Backlog BI-01 |
| I-02 | E | LLD (normative) | Specify `AdmitClaim` and identity decisions | G-04, G-05 | — | High | Decision request (§10.1) |
| I-03 | A (P-03) | Identity decision model (normative) | Outcome enumeration and no-match rule | §6.5 | — | Medium | Decision request (§10.2) |
| I-04 | E | CI of the main repository | Report-only check that each PoC requirement has an implementation or test reference, with an explicit allow-list | 121 of 217 identifiers uncited (§4) | Validator exit code; fixture tests | Medium | Backlog BI-02 |
| I-05 | E | Loop, before verifier dispatch | Preflight of vendor independence from three sources (implementer files, loop log, commit trailers of the unit branch) | `STATE:10552`; `LOOP:382`, `LOOP:458-465` | PASS/FAIL preflight with self-test | High | Backlog BI-03 |
| I-06 | E | Loop, pre-verify gate | Make a non-executed invariant check visible. Check `G15` is skipped silently while `scripts/validate_alignment_invariants.py` is absent from `origin/main` | `LOOP:286`, `LOOP:296`; `[Verified — search]` file absent from `scripts/` at the analysed commit | Gate report carries `G15: NOT_EXECUTED` | Medium | Backlog BI-04 |
| I-07 | E | Tools archive | Conformance with the shell-header rule: ten archived shell scripts lack `set -euo pipefail`, including the loop (`set -uo pipefail`) | `LOOP:23`; `[Verified]` count by search over the tools repository | Archive-time lint with allow-list and reason | Low–Medium | Backlog BI-05 |
| I-08 | E | Agent instructions | Size budget: decisions file 398,949 bytes in 155 sections, verifier prompt 130,455 bytes in 100 sections. An index-and-archive request is already drafted (`consegne/ocor-fable52-riallineamento-20261111.sh`, section `FABLE52-LOOP-INSTRUCTIONS-AND-ARCHIVE`) and is not applied at this commit | `[Verified]` file sizes and `^## ` counts | Size threshold in the archive job | Medium | Existing request reserved to the PO; no new item |
| I-09 | E | Runtime packaging | Pin the six floating specifiers of `ocor-runtime/pyproject.toml` to the versions resolved in `uv.lock` (policy rejects floating Python constraints) | `ocor-runtime/pyproject.toml:13-14`, `:19`, `:21`, `:23-24`; DEP:3-5. `[Not determinable]` whether an existing decision accepts the lock file as the authority | Search for range operators returns none | Low | Backlog BI-06 |
| I-10 | A (P-01) | C1 (planned, post-G7) | Derived "extraction profile" artefact | §6.3 | Drift check | Low now | Within decision request §10.3 |
| I-11 | A (P-05) | C5 (planned, post-G7) | Authorised item-status read surface | §6.7 | Negative test: producer cannot read policy-denied status | Low | Within decision request §10.3 |
| I-12 | E | Plan (planned) | Post-PoC profile and plan | G-03 | Plan validator on extended schema | High | Decision request (§10.4) |

Rules observed for tool items: changes to loop scripts are applied only with the loop stopped or at the end of an iteration; installers run a read-only `--check` first, are idempotent and keep backups; no text added to instruction files names the delegation or uses revocation or suspension wording (the delegation treats any such section as a revocation, tools `sorveglianza/delega.py:18-21`).

---

## 8. Product completeness features

**Necessary for production**

| Feature | User problem | Coherence | Placement | Depends on | What it costs |
|---|---|---|---|---|---|
| Service packaging and network surface for gateway, ingress and action submission (images, listeners, workload identity) | Nothing can integrate with a library | C-04, C-07, C-10 | Core | G7 decision | Operational complexity; a second qualification surface |
| Claim admission and adjudication runtime | Ingested claims can never become state | C-02, C-03 | Core | §10.1 | Load on Human Gate |
| Identity resolution runtime with merge, split and derivation retraction | Duplicates and false attribution | C-05 | Core (matcher pluggable) | §10.1 | Truth-maintenance cost |
| Connector contract kit for structured sources (batch, stream, CDC) with a conformance suite | Each integration is bespoke | C-04, `BR-017` | Periphery | Service surface | Maintenance of a public kit |
| Action adapter contract kit with reconciliation | No real effect can be commanded safely | C-03 | Periphery | Service surface | Liability for external effects |
| Post-PoC qualification (recovery, scale, security, SLO) | No basis for a production decision | C-09 | Process | §10.4 | Time; real infrastructure |
| Operator surfaces: adjudication queue, quarantine and dead-letter console, mission-thread view | Governance cannot be exercised by people | LLD:246-248 | Client | Admission runtime | A UI stack to maintain |
| Upgrade, migration and rollback path with a compatibility matrix | Releases cannot be changed safely | LLD:417 | Core | Service surface | Compatibility burden |

**Useful**

| Feature | Note |
|---|---|
| Document-to-claim extraction (P-01) | Separate product |
| Probabilistic matcher and no-match constraints (P-02, P-03) | Matcher in the periphery; semantics in the core |
| Watchlists and alerts (P-04) | Periphery over `Subscribe` and automation triggers |
| Authorised item-status surface (P-05 residual) | Core operations port |
| Visual authoring of the ontology producing OaC | Separate client; every change as a signed change proposal (LLD:246) |
| Semantic-layer export for analytics tools | Derived C1 artefact |

**To avoid — useful in appearance, but they would denature the project**

| Feature | Why |
|---|---|
| Automatic merge above a confidence threshold | Removes adjudication; violates C-05 (REG:335) |
| Extraction or matching writing directly to state or projections | Violates C-03 (REG:200) |
| A generic untyped ingest or a free-form query endpoint "for convenience" | Violates C-04 |
| A vertical application inside the core | Violates C-14 |
| Hosted external model endpoints as a runtime requirement | Violates C-10 and `NFR-059` |
| Alerts presenting unadmitted claims as facts, or revealing cross-compartment existence | Violates C-02 and C-06 |
| Relations or schema induced from data and applied automatically | Every definition change must pass a change proposal (REG:325, `FR-144`); acceptable only as proposals marked as hypotheses |

---

## 9. Parallel products

**Answer: "Yes, worth building."** One product has clear merit; a second is worth building because the core needs it anyway. Timing differs from the question's premise in one respect: neither should start before the G7 decision, and the first also needs the admission and identity runtime of §10.1.

### 9.1 Product 1 — Upstream acquisition and resolution service (Alt-1, amended)

- **Problem and users.** Turning documents and heterogeneous records into governed Claims and candidate matches; integrators and data stewards.
- **Value proposition; difference from using OCOR directly.** OCOR accepts only typed, signed envelopes; this service produces them from material OCOR cannot read, with span-level provenance and explainable match scores.
- **Relationship with OCOR.** Consumes: the C1 release (extraction profile, payload schemas, event types), the Model Registry for pins. Produces: Canonical Ingestion Envelopes with `semantic_class=CLAIM`, `CandidateMatch` and `MatchEvidence` records, resolution proposals. Stays in OCOR: admission, adjudication, merge and split, canonical state, policy. Stays in the product: parsing, extraction, blocking, scoring, its own processing lifecycle using the four C5 failure classes.
- **Boundaries.** It never writes state or projections, never merges, never lowers a marking, holds no datastore credentials of OCOR, and calls no external model endpoint by default.
- **MVP.** One document family (text PDF), three to five entity types of one ontology release, constrained extraction on a local model, span verification, Fellegi–Sunter matcher for one entity type, envelopes delivered to a test OCOR. Later: OCR and tables, more types, multilingual evaluation, no-match constraints, cluster-level consistency checks, review integration.
- **Logical architecture.** Document intake and evidence store → parser → schema-constrained extractor (model server) → span verifier and normaliser → claim emitter (envelope signer) → blocking index → matcher → candidate emitter; a stage ledger records the state of each item.
- **Prerequisites in OCOR.** G7 decision taken; §10.1 implemented; service surface for ingress (G-02); C1 extraction profile (§10.3).
- **Market and SOTA.** Commercial platforms offer document extraction with strategy evaluation and entity-resolution suggestion tooling inside their own ontology stack (E13); open components exist for each stage (E1, E3, E5); research pipelines combine ontology-aware refinement with normalisation (E9). Differentiation is governance: claims that are never facts until adjudicated, reversible identity, sovereignty. `[Inferred]` differentiation on extraction or matching quality alone is unlikely.
- **Risks and abandonment criteria.** Technical: extraction quality on real, non-English documents; GPU cost. Product: becoming a generic "document to graph" tool with no OCOR advantage. Governance: contract drift from OCOR. Abandon if, on a pre-registered sample, verified-span precision of extracted claims stays below the threshold fixed beforehand after two iterations, or if adjudication effort per admitted claim exceeds manual entry.
- **Relative effort.** Large — `[Inferred]` comparable to one G4 component workstream plus an evaluation harness.
- **Success indicators.** Share of emitted claims admitted after adjudication; verified-span rate; match precision and recall on labelled pairs; zero envelopes rejected for contract violations; zero findings of direct writes.

### 9.2 Product 2 — Adjudication and operations workbench

- **Problem and users.** Stewards, adjudicators and operators have no surface to review claims and candidate matches, approve merges, or work the quarantine and dead-letter queues.
- **Value; difference from OCOR.** OCOR exposes contracts; this is the human side of the Human Gate.
- **Relationship.** Consumes the named-query gateway, action submission and approval ports, and the C5 operations surface. Produces only proposals and approvals. A non-authoritative client, as the LLD requires (LLD:246).
- **Boundaries.** No direct backend access; it does not construct the effective principal; every modification is a signed proposal.
- **MVP.** Adjudication queue for candidate matches with evidence and score contributions; merge, split and no-match decisions; quarantine and dead-letter console; mission-thread view (`FR-166`). Later: watchlists and alerts (P-04), role-oriented tools (`FR-167`).
- **Architecture.** Web client → backend-for-frontend holding no authority → OCOR ports.
- **Prerequisites.** Service surface (G-02); §10.1; for alerts, the post-PoC plan.
- **Alternatives.** Generic annotation tools cover labelling but not governed decisions with authority and audit. `[Inferred]` no off-the-shelf tool speaks OCOR's contracts.
- **Risks and abandonment.** UI scope creep; accessibility obligations (REG:415). Abandon the standalone product, keeping a minimal console, if no pilot user is secured by the MVP gate.
- **Effort.** Medium to large.
- **Indicators.** Median adjudication time; share of decisions with a complete evidence set; zero authorisation bypass findings.

### 9.3 Alternatives assessed and not recommended

| Alternative | Answer | Reason |
|---|---|---|
| Alt-2 — autonomous vertical application "document → graph → case" | **Not now** | Requires Products 1 and 2 and an MVP-grade core; before that it disperses effort, as its own stated risk says. Reconsider after the Product 1 MVP with a named pilot user |
| Alt-3 — autonomous identity-resolution service | **No, not worth building** as a product | Mature open tooling already exists (E5) and platforms bundle it (E13); the differentiating part (governed, reversible decisions) lives in OCOR, not in the matcher. Keep it as a module of Product 1 |
| Governed multi-vendor delivery harness (the workstation tools as a product) | **Not determinable**; not recommended now | The tooling exists, but its integrity rests on same-user file permissions by its own statement (tools `LOOP:116-119`; `sorveglianza/custode.py:33-35`); productising would require a redesign |

---

## 10. Proposed normative changes (drafts; no identifier assigned; nothing here is approved)

### 10.1 Draft — `IDENTITY-RESOLUTION-AND-CLAIM-ADMISSION-SPEC` (working title)

**Context.** Four P0 PoC requirements (`FR-012` REG:65, `FR-030` REG:120, `FR-150` REG:335, `NFR-055` REG:336) and the ADD (ADD:284, 342, 2010-2015, 2051, 2745, 2789, 3059) require claim admission and reversible identity resolution. The LLD contains no specification of either, the code contains validation shapes only, the allocated implementation task delivered principal identity, and the conformance register has no entry (G-04, G-05). `OCOR-DEV-0065` must qualify these requirements with one case each.

**Options.**

1. **LLD-level specification and a remediation unit before `OCOR-DEV-0065` (recommended).** An LLD addendum, once decided by the PO through the governed process, defines: the C3 `AdmitClaim` handler and its command record; closed records for `CandidateMatch`, `MatchEvidence`, `IdentityResolutionDecision` (merge, split) and `ClusterMembershipAssertion`; the C6 action types that carry admission, merge and split as `CANONICAL_COMMIT` decisions; the Fusion/Identity role outputs; the retraction of dependent derivations after a split; a deterministic, version-pinned matcher for the synthetic fixtures. One remediation unit implements it with the full cycle.
2. **Status quo.** `OCOR-DEV-0065` adds "the smallest contract-compliant implementation". Risk: a P0 capability implemented inside a campaign task with no normative anchor for the verifier.
3. **Reclassification.** Move the four requirements out of the PoC by a register decision. Requires amending `BR-015` (REG:426), which names identity resolution in the PoC mission thread, and weakens the PoC's value claim.

**Recommendation.** Option 1.

**Cascade impact (option 1).** LLD: new subsections under §2.3 and §2.8 and an addition to §7.3; version and approval manifest. Decision register and traceability index: one entry. TRACE: rows 31, 49, 169, 248 re-allocated to the new unit. NCR: entries per BI-01, closed by the unit. Backlog: one remediation unit before `OCOR-DEV-0065`; `0065` waits for it. Code: C3 (handler, commit shape), C6 (action types), C8 (role outputs), C4 shapes unchanged. Contracts: the six named queries are unchanged if candidates are returned through existing result fields (`FR-007`, REG:58, requires candidates not to be flattened) — to be confirmed in the addendum. Claims: unchanged.

**Verifiable acceptance.** (a) The addendum names every record with a closed field set. (b) A fixture with homonyms keeps candidates separate until adjudication; a merge followed by a split restores both bitemporal views and retracts every derivation that depended on the merge. (c) A candidate match without an accepted decision produces no membership (negative test). (d) Admission of a claim without Decision and Authority is refused with the normative reason code. (e) All on real backends, zero skips.

### 10.2 Draft — `IDENTITY-NO-MATCH-DECISION-SEMANTICS` (working title)

**Context.** Rejections must be recorded (REG:176), but the decision outcome is not enumerated (ADD:2012), the shape in code covers merge and split only (`SRC/c4/shacl.py:87-88`), and nothing obliges a matcher to respect a past rejection.

**Options.**

1. **Normative no-match decision with a re-opening rule (recommended).** Outcomes `MERGE`, `SPLIT`, `NO_MATCH`, `DEFERRED`. A `NO_MATCH` decision binds the set of Source Identities and the digest of the evidence set considered. While it is in force, a candidate over the same set with the same evidence-set digest is not re-opened; it remains queryable as suppressed, with a reference to the decision. A different evidence-set digest re-opens it. Reversal is a new decision. The record is bitemporal.
2. **Record only.** No obligation on later runs.
3. **Matcher configuration only.** No normative semantics.

**Recommendation.** Option 1, as an LLD refinement (the ADD leaves the outcome open, so no ADD change is required `[Inferred]`). If §10.1 is adopted, include the outcome set and the record there and implement the suppression rule after G7.

**Cascade impact.** LLD identity subsection; C4 shape extended to the base decision class; matcher contract of the Fusion/Identity role; TRACE rows for `FR-054`, `FR-150`, `NFR-055`; tests. No public contract change. Claims: unchanged.

**Verifiable acceptance.** Re-running the matcher on unchanged evidence yields zero re-opened pairs covered by a `NO_MATCH`; adding one evidence item re-opens exactly the affected pairs; a suppressed candidate is returned by the provenance query with its decision reference.

### 10.3 Draft — `UPSTREAM-ACQUISITION-COMPONENT-BOUNDARY` (working title; to be decided after the G7 decision)

**Context.** No document path exists (G-09); the PoC forbids real data (C-08); the language table and the migration thresholds do not cover a new component (LANG:40-56, 94-99); dependencies need the gate of DEP and `NFR-073`.

**Options.**

1. **Separate product in its own repository (recommended).** OCOR gains only (a) a derived C1 artefact, the extraction profile, generated from the IR and drift-checked, and (b) an authorised item-status read surface in C5. The product emits `CLAIM` envelopes and candidate matches and follows OCOR's dependency policy; local model serving only.
2. **Peripheral component inside the OCOR repository.** Same CI; needs a new language-policy row and thresholds fixed before measurement.
3. **A ninth core subsystem.** Rejected in this draft: it changes the approved decomposition and violates C-14 in spirit.
4. **Nothing.** Integrators supply typed claims.

**Recommendation.** Option 1; no work starts before the G7 decision.

**Cascade impact.** Option 1: C1 code generation (one target, manifest media type, drift check); OaC event types for claim payloads; one C5 port addition (normative: the ADD lists C5 ports at ADD:286); Model Registry pins. No change to the 285 requirements; if the PO wants extraction inside the product baseline, new requirements enter through IRB change control. Option 2 adds: language-policy row, thresholds, CI jobs, dependency records for each library and model weight.

**Verifiable acceptance.** The extraction profile is byte-identical across two isolated builds and carries the IR digest; a producer cannot read the status of a policy-denied item (negative test); an envelope from the product passes C5 admission unchanged; no symbol of the product is imported by `ocor-runtime`.

### 10.4 Draft — `INTEGRATION-READY-RELEASE-PROFILE` (working title)

**Context.** The PO objective (C-16) cannot be met at G7 under the release rules (C-09); the plan omits Production (PLAN:57); the backlog schema stops at `G7`; 68 requirements lie outside the PoC profile. A related request (`FABLE52-POST-POC-PROGRAMME`) exists only in a delivered script of the tools repository.

**Options.**

1. **Define the profile and plan it now, execute after the G7 decision (recommended).** "Integration-ready" becomes a named release profile equal to the MVP entry and scope rules (`BR-016`, `BR-017`) plus an explicit list: service surface (G-02), admission and identity runtime, connector and action adapter kits, operator surfaces, a stated subset of recovery, security and SLO evidence. The backlog schema is extended to post-PoC gates. A planning-only unit builds the extended backlog in read-only mode. This draft and the existing programme request are merged into one request.
2. **Decide after G7.** Risk: G6 units fix choices that must be redone.
3. **Declare the objective met at PoC-GO.** Rejected in this draft: contrary to `BR-012` and `NFR-050`.

**Recommendation.** Option 1.

**Cascade impact.** Backlog schema (gate and identifier patterns); backlog; dependency graph; TRACE (a release profile for the 68 rows); the plan validator. No requirement text changes. Claims: unchanged.

**Verifiable acceptance.** The extended backlog passes the plan validator; every requirement whose release is not PoC has a verification task in a post-PoC gate and none in G6; no post-PoC task is marked ready before the G7 decision is recorded.

---

## 11. Proposed backlog items (non-normative)

**BI-01 — Register the identity, admission and view divergences.** Executor: the loop, as a register-maintenance unit under the conformance programme (implementer and independent verifier as usual).
Work: add entries to NCR for (1) identity resolution runtime (`FR-012`, `FR-030`, `FR-150`, `NFR-055`), (2) claim admission (`AdmitClaim`), (3) mission-thread view (`FR-166`), each with the first free identifier of its component series verified read-only at execution time, `norm_refs` to the lines cited in G-04, G-05, G-07, `code_refs` to `SRC/c4/shacl.py` and `SRC/c8/orchestrator.py`, status `OPEN`; add the three identifiers to `g6_g7_proposals.tasks["OCOR-DEV-0065"].blocking_register_entries` of the same register (`[Verified] NCR:14146-14151`).
PASS when: the file parses as JSON; each new entry has exactly the twenty keys of existing entries; `git diff` shows no change to any `claims` object; the three identifiers appear in the blocking list of `OCOR-DEV-0065`; `scripts/validate_ocor_development_plan.py` exits 0. FAIL otherwise.

**BI-02 — Requirement reference check (report mode).** Executor: the loop; runs in the `rccad-methodology` job.
Work: a Python 3.12.11 validator under `scripts/` that, for each TRACE row with `campaign_profile=PoC`, reports whether the requirement identifier occurs under `ocor-runtime/src`, `ocor-runtime/tests` or `reports/tests`, with an allow-list file giving a reason per exempted identifier; non-mutating; JSON output; `--strict` returns 1 when an identifier is neither referenced nor allow-listed.
PASS when: on the analysed tree the report lists `FR-012`, `FR-030`, `FR-150`, `NFR-055` as unreferenced; default mode exits 0; `--strict` exits 1; unit tests cover one positive and one negative fixture; no existing required check changes result.

**BI-03 — Verifier-assignment preflight.** Executor: PO workstation installer, applied with the loop stopped or at the end of an iteration.
Work: before a verifier is launched, compute the set of implementer vendors since the last GO as the union of `.impl_vendors`, `.impl_actual`, the implementer lines of `loop.log`, and the agent trailers of the commits on the unit branch; exclude candidates of those vendors; record the computed set in the verdict ledger line.
PASS when: (a) with a fixture where `loop.log` names an implementer missing from `.impl_actual`, the preflight excludes that vendor and selects the next candidate; (b) with all candidates excluded and no fallback configured, no verifier process starts and the log states the reason; (c) the installer's `--check` reports no change on a second run; (d) a backup of the previous script exists; (e) the archived script's sha256 equals the manifest entry after the next archive run.

**BI-04 — Visible non-execution of the invariant check.** Executor: PO workstation installer, same conditions.
Work: when the validator is absent from `origin/main`, write an entry with identifier `G15` and status `NOT_EXECUTED` in `pre_verify_gate.json` and in the loop log line of that gate run.
PASS when: with the validator absent the gate report contains that entry and the verification still proceeds; with the validator present the report is unchanged from today's behaviour.

**BI-05 — Shell-header lint in the archive job.** Executor: workstation archive script.
Work: list every archived shell script whose first `set` line is not `set -euo pipefail`; exit non-zero unless each is in an allow-list with a one-line reason.
PASS when: on the analysed archive the list is exactly the ten scripts found (`comandi/notify-send`, `comandi/ocor-stato`, `consegne/ocor-controllo-grok-20261110.sh`, `consegne/ocor-revisione-host-20261026.sh`, `consegne/ocor-stop-a-fine-iterazione.sh`, `loop/avvia-loop.sh`, `loop/ferma.sh`, `loop/guardia.sh`, `loop/ocor-loop2.sh`, `loop/riprendi.sh`); the job fails with an empty allow-list and passes once each has a reason.

**BI-06 — Exact pins in the runtime project file.** Executor: the loop; checked by the `supply-chain` job.
Work: replace the six range specifiers in `ocor-runtime/pyproject.toml` (lines 13, 14, 19, 21, 23, 24) with the exact versions recorded in `uv.lock`.
PASS when: no dependency array entry contains `>=`, `~=` or `^`; every resolved version in `uv.lock` is unchanged (only the recorded specifiers may differ); the unit and contract jobs keep their results.

**BI-07 — Identity and admission runtime (conditional on §10.1, option 1).** Executor: the loop, as a remediation unit before `OCOR-DEV-0065`.
PASS when the five acceptance points of §10.1 hold on real backends with zero skips and the BI-01 entries are closed by the governed process.

**BI-08 — C1 extraction profile (conditional on §10.3 and on the G7 decision).** Executor: the loop.
PASS when the first and third acceptance points of §10.3 hold.

---

## 12. Conditional roadmap

| Step | Content | Depends on | PO decision point |
|---|---|---|---|
| 1 (now, no interference with the loop's unit) | BI-01; decisions on §10.1 and §10.4 | — | **D1:** option for §10.1. **D2:** option for §10.4 |
| 2 (next loop stop) | BI-03, BI-04, BI-05 | Loop stopped or end of iteration | — |
| 3 (before `OCOR-DEV-0065`) | BI-07 if D1 = option 1; `NCP-U12`; BI-02 in report mode | D1; merge of `REM-0061` | — |
| 4 (G6) | Campaigns in the order recorded in the plan and state | Step 3 | — |
| 5 (G7) | Decision package | G6 | **D3:** PoC decision |
| 6 (after D3) | Planning-only unit for the post-PoC profile; decisions on §10.2 and §10.3 | D2, D3 | **D4:** boundary of the upstream component |
| 7 | Service surface → admission and identity hardening → connector and adapter kits | Step 6 | — |
| 8 | Product 1 MVP; Product 2 MVP | Step 7; BI-08 | **D5:** go or stop per abandonment criteria |
| 9 | Reconsider the vertical application (Alt-2) | A named pilot user | **D6** |

Nothing in steps 6–9 should start before D3. Step 3 is the only item this report places on the critical path to G7.

---

## 13. Adversarial review, residual risks and omissions

**Objections to this report's own conclusions.**

1. *G-04 rests on absence.* The mission-thread campaign may be intended to implement identity resolution itself. Counter-evidence: the LLD does not specify it and the register is silent, so a verifier would have no normative anchor. If the PO prefers that path, §10.1 option 2 states it and its risk.
2. *G-02 may be by design.* In-process qualification against real backends is legitimate for the PoC. It is classified here as a production gap, not as a PoC defect.
3. *The reference-count heuristic is weak.* It is used only as corroboration.
4. *The proposal is judged against the norm, not against running behaviour.* Where the norm exists and the code does not (P-02), the verdict says so; no element is credited to OCOR on the strength of design text alone.
5. *SOTA evidence is partly from abstracts and vendor pages.* No claim of superiority or parity is made on that basis.

**Residual risks.**

- Adding step 3 delays G7; the alternative (reclassification) weakens the PoC.
- Product 1 can pull effort toward a vertical; its abandonment criteria must be fixed before it starts.
- The tool items touch loop scripts; a faulty installer can stop the loop. They must follow the stop-or-end-of-iteration rule and the custodian's backup and restore path.
- The automatic improvement route may change loop scripts and instructions at a high rate (tools `sorveglianza/migliorie.py:15-19`); mechanical checks added by BI-03 and BI-04 need to be among the files whose self-tests the custodian runs, or they can be undone silently.

**Omissions, and why.**

- Full reading of the loop instruction files, of `inputs/`, of the decision registers and of 100 of the 104 delivered scripts: volume; searches were used instead.
- No execution of tests, campaigns or CI: read-only engagement on a running loop.
- No reassessment of MCP, A2A, memory benchmarks or causal discovery: outside the themes of steps 3 and 5.
- No numeric effort or cost estimate: the repository offers no calibrated basis for the proposed items.
- Detailed design of the two products beyond component level: premature before D3.

**Final checks performed.** After drafting, 155 `file:line` references were re-read programmatically against the two commits, each with an expected text fragment; one line range was wrong and was corrected, the other 154 matched. Verdicts of `ADOPT WITH CHANGES` (P-02, P-03) rest on REG, ADD and code evidence, not on Annex A. Sections 3 and 4 were derived from repository sources alone; Annex A is part of the commission and had been read, so their independence is one of method (no criterion or gap cites it), not of ignorance. No sentence of this report declares a requirement verified, a gate closed, a decision approved or a claim changed; where state is quoted, it is the repository's own record.
