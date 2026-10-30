# NORMATIVE-CONFORMANCE-PLAN

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Decision request prevista da `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)` punto 4.g e punto 5, con i contenuti aggiunti da `NORMATIVE-CONFORMANCE-PROGRAMME-SUPPLEMENT (2026-10-29)` punto 5. È riservata al PO: nessuna remediation di codice del programma e nessun task G6 parte prima della sua decisione.

## Fonte

- Registro `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json` su `main` al merge commit `4781e06de140f770ef0f61d9dab7a6c189cdf97b` (PR #423), sha256 `1b9b0885e19fdb139548a76c44782d8200e95f013c7ca280f245fc9799ac9590`. Record dell'unità `reports/assurance/OCOR-DEV-REM-0044-RCCAD/OCOR-DEV-REM-0044.json` (`SEALED`), sha256 `295696c43c13011904dc3d5ff69fc4058300d838a28f4a7c3179aeb2d4c23e73`.
- Unità del registro `OCOR-DEV-REM-0044`: verdetto `OCOR-DEV-REM-0044-f8270ae90ca9-0` `GO_FOR_EVIDENCE_SEAL` (Cursor CLI / grok-4.7-high / xAI), integrata con l'autorizzazione di `REM-0044-ITERATION-LIMIT (2026-10-30)`, opzione 1.
- Le righe e i dettagli completi di ogni voce, unità e proposta (ancore normative, `code_refs`, `test_refs`, prove riproducibili) sono nel registro; questo documento ne riporta i conteggi, il piano e le scelte richieste.
- Il registro non è evidenza: nessuna voce, risolta o no, rende `Verified` un requisito. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## 1. Conteggi del registro

83 voci: OPEN 73, DECISION_REQUIRED 8, REFUTED 2; gravità HIGH 59, MEDIUM 21, LOW 3. Copertura: elenco iniziale 59/59, elenco integrativo 11/11, osservazioni 6/6.

### Per componente e stato

| | OPEN | DECISION_REQUIRED | REFUTED | Totale |
|---|---|---|---|---|
| C1 | 9 | 1 | 0 | 10 |
| C2 | 10 | 1 | 1 | 12 |
| C3 | 5 | 2 | 0 | 7 |
| C4 | 3 | 0 | 0 | 3 |
| C5 | 3 | 0 | 0 | 3 |
| C6 | 14 | 0 | 0 | 14 |
| C7 | 4 | 2 | 1 | 7 |
| C8 | 6 | 1 | 0 | 7 |
| MEMORY | 5 | 0 | 0 | 5 |
| TESTS | 5 | 0 | 0 | 5 |
| LEGACY | 0 | 1 | 0 | 1 |
| PLAN | 6 | 0 | 0 | 6 |
| EVIDENCE | 2 | 0 | 0 | 2 |
| GOVERNANCE | 1 | 0 | 0 | 1 |
| **Totale** | 73 | 8 | 2 | 83 |

### Per componente e gravità

| | HIGH | MEDIUM | LOW | Totale |
|---|---|---|---|---|
| C1 | 7 | 3 | 0 | 10 |
| C2 | 11 | 0 | 1 | 12 |
| C3 | 3 | 4 | 0 | 7 |
| C4 | 1 | 2 | 0 | 3 |
| C5 | 3 | 0 | 0 | 3 |
| C6 | 11 | 3 | 0 | 14 |
| C7 | 5 | 2 | 0 | 7 |
| C8 | 7 | 0 | 0 | 7 |
| MEMORY | 3 | 2 | 0 | 5 |
| TESTS | 1 | 3 | 1 | 5 |
| LEGACY | 0 | 0 | 1 | 1 |
| PLAN | 5 | 1 | 0 | 6 |
| EVIDENCE | 2 | 0 | 0 | 2 |
| GOVERNANCE | 0 | 1 | 0 | 1 |
| **Totale** | 59 | 21 | 3 | 83 |

### Per gravità e stato

| | OPEN | DECISION_REQUIRED | REFUTED | Totale |
|---|---|---|---|---|
| HIGH | 56 | 3 | 0 | 59 |
| MEDIUM | 16 | 4 | 1 | 21 |
| LOW | 1 | 1 | 1 | 3 |
| **Totale** | 73 | 8 | 2 | 83 |

### Voci derivate dall'elenco integrativo (SUPPLEMENT punto 5)

| Ipotesi | Voce | Stato | Gravità | Unità | Nota |
|---|---|---|---|---|---|
| NCP-S01 | NCR-TESTS-001 | OPEN | HIGH | NCP-U12 |  |
| NCP-S02 | NCR-TESTS-002 | OPEN | MEDIUM | NCP-U12 |  |
| NCP-S03 | NCR-TESTS-003 | OPEN | MEDIUM | NCP-U12 |  |
| NCP-S04 | NCR-C3-006 | OPEN | MEDIUM | NCP-U04 | PostgreSQL part OPEN; TerminusDB part NCR-C3-007 DECISION_REQUIRED (SUPPLEMENT point 4) |
| NCP-S05 | NCR-PLAN-004 | OPEN | HIGH | NCP-U13 |  |
| NCP-S06 | NCR-EVIDENCE-001 | OPEN | HIGH | NCP-U13 |  |
| NCP-S07 | NCR-EVIDENCE-002 | OPEN | HIGH | NCP-U13 | overlaps OBS-TRACEABILITY |
| NCP-S08 | NCR-PLAN-005 | OPEN | HIGH | NCP-U13 |  |
| NCP-S09 | NCR-PLAN-006 | OPEN | MEDIUM | NCP-U13 | overlaps OBS-TRACEABILITY; joint entry |
| NCP-S10 | NCR-GOVERNANCE-001 | OPEN | MEDIUM | NCP-U13 |  |
| NCP-S11 | NCR-TESTS-004 | OPEN | LOW | NCP-U12 |  |
| NCP-S04 (parte TerminusDB) | NCR-C3-007 | DECISION_REQUIRED | MEDIUM | — | SUPPLEMENT punto 4 |

Conteggio per stato delle voci integrative: DECISION_REQUIRED 1, OPEN 11. Nessuna voce è stata riportata da `DECISION_REQUIRED` a `OPEN` dopo la registrazione: il registro non era ancora integrato, quindi le voci del punto 4 dell'aggiunta sono state classificate direttamente secondo la norma (SUPPLEMENT punto 3, primo caso).

## 2. Piano di remediation (punto 4.e)

13 unità `NCP-Uxx`, tutte `PROPOSED`; risolvono 73 voci `OPEN` su 73; stima complessiva 48 iterazioni (estimates are planning figures, not commitments; each unit follows the full remediation cycle of point 5). Ordine proposto, per dipendenze: NCP-U13 → NCP-U01 → NCP-U02 → NCP-U03 → NCP-U04 → NCP-U06 → NCP-U05 → NCP-U07 → NCP-U08 → NCP-U09 → NCP-U10 → NCP-U11 → NCP-U12.

| Ordine | Unità | Ambito | Voci risolte | Dipende da | RED | Test da riallineare/adattare | Stima | Task G6 sbloccati (ultima unità) |
|---|---|---|---|---|---|---|---|---|
| 1 | NCP-U13 | Plan, evidence and governance tooling (proposals under point 4.f until the PO decision): requirement-specific bindings and criteria for OCOR-DEV-0060..0067, implementation allocation of the twelve ledger-allocated and three misallocated requirements, FGM binding to FR-118/FR-119, verification method per the Register, reverse test traceability, evidence-package fields and their validator, AFF-009/AFF-010 strengthened | 9 | — | 9 | 0 | 3 | — |
| 2 | NCP-U01 | C1 OaC metamodel, Canonical IR structure, normalisation, signing and admission, artefact generation, semantic diff | 8 | — | 8 | REALIGN 1 | 4 | — |
| 3 | NCP-U02 | Function and Model Registry (ocor.registry.v1) | 1 | — | 1 | 0 | 3 | — |
| 4 | NCP-U03 | C2 Named Query Gateway: transport-bound principal and full policy context, six contract operations, closed request/served/Problem model, consistency ordering and bounded wait, contract-digest and release checks, denial audit | 10 | NCP-U01 | 10 | ADAPT_CONSTRUCTION 1, REALIGN 10 | 4 | — |
| 5 | NCP-U04 | C3 commit admission (Decision/Authority/GatePackage/Evidence/preconditions/invariants/stop and writer epoch), C6->C3 composition replacing the legacy store, outbox relay (SKIP LOCKED, DeliveryAttempt, event payload) and outbox->C5->C4 chain, canonical_source_binding | 5 | — | 5 | 0 | 4 | — |
| 6 | NCP-U06 | C5 backbone: canonical-ingestion-envelope:1.2 with payload second validation and producer signature, full failure taxonomy, authorised windowed replay, Subscribe surface with opaque cursor, priority-class backpressure with audit/security exemption, durable DLQ/quarantine | 3 | — | 3 | 0 | 3 | — |
| 7 | NCP-U05 | C4 projections: monotonic per-branch watermark with durable deduplication, real served release/staleness, durable drift quarantine enforced on the read path, rebuild from the canonical store with signed checkpoint, Jena watermark/SHACL/canonical marking, typed adapter errors | 3 | NCP-U03 | 3 | REALIGN 1 | 3 | — |
| 8 | NCP-U07 | C6 action path: composition root; G-CONTRACT with risk class from the signed ActionType; FSM with current state, guards and ACT-T23 precedence; signed, bound Approval/ApprovalSet/Decision with risk-derived quorum and expiry; normative CapabilityLease consumed at emission; EMISSION-FENCE (G-FRESHNESS and G-DISPATCH) before C3 commit and dispatch with DeliveryAttempt; the LLD v1.1 §2.6 records; evidence-based reconciliation without blind retry; memory promotion through the same path | 10 | NCP-U04 | 10 | ADAPT_CONSTRUCTION 2, ADAPT_PRECONDITION 2, REALIGN 1 | 6 | — |
| 9 | NCP-U08 | C6 safety and policy: authorised stop activation with signed stop epoch, reset with incident/recovery verification, signed break-glass delegation with typed reason; OPA effects with constraints, approval requirement and obligations; MARKING_UNRESOLVED instead of the legacy bottom default in current components; ADD v1.3 risk-class names and gates | 4 | NCP-U03, NCP-U07 | 4 | 0 | 3 | OCOR-DEV-0063 |
| 10 | NCP-U09 | C7 causal runtime: SCM with do(X) and identification (NOT_IDENTIFIED), intervention comparison, CausalRunOutcome ESTIMATED/ABSTAIN/REJECTED/FAILED with the ADD closed reason set and precedence (after the PO decision on NCR-C7-002), uncertainty and sensitivity on every estimate, immutable SimulationResult, CausalQuery from ScenarioRunSpec read through the overlay, L2 job lifecycle, declared tolerance and a digest independent of trace identifiers, ELM-070 per the PO decision on NCR-C7-006 | 4 | — | 4 | REALIGN 1 | 4 | OCOR-DEV-0060 |
| 11 | NCP-U10 | C8 Governed Agent Kernel: AgentRun/Task/Assignment/Commitment/Handoff/Dissent/DecisionProposal/ToolInvocation records in C8 state (not canonical aggregates), kernel-attested HandoffEnvelope with sender bound to the transport Principal, roles and task lifecycle with cycle/depth/timeout/termination, dissent severity and blocking, contract-bound tool registry (mcp-tool-contract:1.2) with schema, taint and egress checks and the contract error codes, live policy/autonomy-tier/instruction-eligibility/capability/delegation re-evaluation at every dispatch (with the OCOR-DEV-REM-0043 correction), multidimensional budget, a current kernel with no fail-open default | 6 | NCP-U04, NCP-U08 | 6 | ADAPT_CONSTRUCTION 1, REALIGN 4 | 5 | OCOR-DEV-0064 |
| 12 | NCP-U11 | Governed memory: retrieval whose work and errors are independent of policy-denied items (pre-query policy partition, FGM-16), quota at admitMemory and on consolidation, the four contract deletion scopes, a governed getMemoryItemVersion operation, rebuild of committed full-text and vector projections from metadata, content and the event journal | 5 | — | 5 | PO_CHOICE_REQUIRED 1, REALIGN 1 | 3 | OCOR-DEV-0061, OCOR-DEV-0062, OCOR-DEV-0066 |
| 13 | NCP-U12 | Tests: mission thread through the retained C1-C8 components (no legacy classes, no spike adapters or oracles); closed-record, exact-field-set and negative-corpus meta-tests for the OpenAPI, Proto and ADD-embedded schemas; schema integrity over the LLD v1.1 §0.2 contracts; reason-code assertions in negative tests; technique routing (property, stateful, metamorphic, golden, bounded model checking; a new test dependency needs a PO decision) | 5 | — | 5 | ADAPT_CONSTRUCTION 1 | 3 | OCOR-DEV-0065, OCOR-DEV-0067 |

### NCP-U13

- Voci risolte: NCR-PLAN-001, NCR-PLAN-002, NCR-PLAN-003, NCR-PLAN-004, NCR-PLAN-005, NCR-PLAN-006, NCR-EVIDENCE-001, NCR-EVIDENCE-002, NCR-GOVERNANCE-001.
- Codice: `docs/development_plan/OCOR_IMPLEMENTATION_BACKLOG.json`, `docs/development_plan/OCOR_TRACEABILITY_PLAN.csv`, `reports/evidence/G4/OCOR-DEV-0042.json`, `reports/evidence/G6/OCOR-DEV-0061.json`, `reports/traceability/OCOR_IRB_ADD_LLD_v1.1_Matrix.json`, `scripts/validate_rccad.py`, `scripts/validate_runtime_evidence.py`.
- Backend richiesto: none (plan, backlog, traceability and evidence tooling).
- Criteri di accettazione: 9, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U13.acceptance_criteria`). Test RED da scrivere sul codice attuale: 9.
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: nessuno (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 0 file di codice con i rispettivi test.
- Stima: 3 iterazioni. Governance first: the G6/G7 bindings, the allocation corrections and the evidence-package fields are needed by every later campaign and touch no runtime code. Changes to backlog and OCOR_TRACEABILITY_PLAN.csv are exactly the 4.f proposals approved by the PO; validate_runtime_evidence.py and the fitness functions are extended fail-closed, never relaxed.

### NCP-U01

- Voci risolte: NCR-C1-002, NCR-C1-003, NCR-C1-004, NCR-C1-005, NCR-C1-006, NCR-C1-008, NCR-C1-009, NCR-C1-010.
- Codice: `ocor-runtime/src/ocor_runtime/c1/compiler.py`, `ocor-runtime/src/ocor_runtime/c1/frontend.py`, `ocor-runtime/src/ocor_runtime/c1/ports.py`, `ocor-runtime/src/ocor_runtime/c1/releases.py`.
- Backend richiesto: none (pure C1 compiler; signing with a locally generated test key).
- Criteri di accettazione: 8, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U01.acceptance_criteria`). Test RED da scrivere sul codice attuale: 8.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/tasks/test_ocor_dev_0028.py:81` `test_valid_dsl_fixture_compiles_to_canonical_ir_with_migration_metadata` — REALIGN (RED richiesto); attuale: assert release.signature_envelope_ref == f"urn:ocor:unsigned:{canonical_digest(release.core)}"; prescritto: the reference resolves to a signed-canonical-ir:1.0 DSSE envelope over the release core digest that admission verifies (trust root, PAE, digest); the norm fixes the envelope, not a literal reference string (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:466-521`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:523`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0011, OCOR-DEV-0028, OCOR-DEV-0032, OCOR-DEV-0033 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 4 file di codice con i rispettivi test.
- Stima: 4 iterazioni. C1 before C2: release and contract-digest checks of the gateway (NCR-C2-004) need signed, verifiable releases.

### NCP-U02

- Voci risolte: NCR-C1-001.
- Codice: `ocor-runtime/src/ocor_runtime/memory/embeddings.py`.
- Backend richiesto: PostgreSQL (registry persistence) on the ocor-bootstrap stack.
- Criteri di accettazione: 1, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U02.acceptance_criteria`). Test RED da scrivere sul codice attuale: 1.
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0053, OCOR-DEV-0061 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 1 file di codice con i rispettivi test.
- Stima: 3 iterazioni. Registry after C1: Function and Model publication binds the release produced by NCP-U01.

### NCP-U03

- Voci risolte: NCR-C2-001, NCR-C2-002, NCR-C2-003, NCR-C2-004, NCR-C2-005, NCR-C2-006, NCR-C2-007, NCR-C2-009, NCR-C2-011, NCR-C2-012.
- Codice: `ocor-runtime/src/ocor_runtime/c2/gateway.py`, `ocor-runtime/src/ocor_runtime/c2/planner.py`, `ocor-runtime/src/ocor_runtime/c2/ports.py`, `ocor-runtime/src/ocor_runtime/c4/rebuild.py`, `ocor-runtime/src/ocor_runtime/c4/typedb_adapter.py`.
- Backend richiesto: TypeDB, Jena, Keycloak/SPIFFE (transport principal), PostgreSQL audit.
- Criteri di accettazione: 10, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U03.acceptance_criteria`). Test RED da scrivere sul codice attuale: 10.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/tasks/test_ocor_dev_0034.py:110-140` `make_request (helper used by the module's tests)` — ADAPT_CONSTRUCTION; attuale: governed_context.effective_principal_id and actor_chain are placed in the request body; prescritto: no Principal in the Query body: the principal is bound by the verified transport (TRANSPORT binding); assertions unchanged (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:380`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0034.py:335` `test_a_registered_query_without_a_resource_parameter_skips_the_marking_join` — REALIGN (RED richiesto); attuale: assert response.served.canonical_commit == "commit-1" (with marking_ref_to_clearance_level={}, i.e. an unresolvable marking reference); prescritto: DENY: Problem with reason_code POLICY_DENIED and no response, because the classification_marking_ref does not resolve (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:401`, `ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:452-466`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0034.py:221` `test_an_unregistered_contract_id_is_denied_without_any_response` — REALIGN (RED richiesto); attuale: assert error.reason_code == "ARBITRARY_QUERY_FORBIDDEN"; prescritto: a reason code of the closed Problem enum; proposed CONTRACT_NOT_FOUND (`ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:452-466`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:380`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0034.py:261` `test_an_ambiguous_unregistered_identity_is_denied_without_any_response` — REALIGN (RED richiesto); attuale: assert error.reason_code == "IDENTITY_AMBIGUOUS"; prescritto: the same code as for an unregistered contract (DENY before any identity lookup) (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:380`, `ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:452-466`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0034.py:418` `test_a_real_marking_backend_failure_propagates_and_never_defaults_to_permit` — REALIGN (RED richiesto); attuale: with pytest.raises(OSError): gateway.execute(request); prescritto: typed fail-closed Problem (application/problem+json) instead of a raw OSError (`ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:486-491`, `docs/OCOR_LLD_v1.1.md:346`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0037.py:107-117` `test_exact_at_commit_never_masquerades_a_stale_projection_as_exact` — REALIGN (RED richiesto); attuale: reason_code CONSISTENCY_DOWNGRADE for a not-yet-landed exact commit; prescritto: PROJECTION_NOT_READY with served (`docs/OCOR_LLD_v1.1.md:369`, `ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:472-479`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0012.py:134-138` `test_exact_consistency_cannot_silently_downgrade` — REALIGN (RED richiesto); attuale: assert exc_info.value.reason_code == "CONSISTENCY_DOWNGRADE"; prescritto: PROJECTION_NOT_READY (`docs/OCOR_LLD_v1.1.md:369`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0017.py:108` `test_exact_at_commit_fails_closed_when_the_fact_is_ingested_ahead_of_the_watermark` — REALIGN (RED richiesto); attuale: assert excinfo.value.reason_code == "CONSISTENCY_DOWNGRADE"; prescritto: PROJECTION_NOT_READY (`docs/OCOR_LLD_v1.1.md:369`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0017.py:126` `test_exact_at_commit_fails_closed_when_the_row_has_moved_ahead_of_the_watermark` — REALIGN (RED richiesto); attuale: assert excinfo.value.reason_code == "CONSISTENCY_DOWNGRADE"; prescritto: PROJECTION_NOT_READY (`docs/OCOR_LLD_v1.1.md:369`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0017.py:165, 178` `test_stale_reads_are_never_served_as_exact_across_a_real_commit_progression` — REALIGN (RED richiesto); attuale: two pytest.raises(C2Error, match="CONSISTENCY_DOWNGRADE"); prescritto: pytest.raises(C2Error, match="PROJECTION_NOT_READY") (both) (`docs/OCOR_LLD_v1.1.md:369`).
  - `ocor-runtime/tests/mission_thread/test_first_governed_slice.py:553` `test_typedb_projection_read_enforces_exact_at_commit_consistency_with_the_real_canonical_commit` — REALIGN (RED richiesto); attuale: assert excinfo.value.reason_code in {"PROJECTION_NOT_READY", "CONSISTENCY_DOWNGRADE"}; prescritto: assert excinfo.value.reason_code == "PROJECTION_NOT_READY" (the accepted set narrows) (`docs/OCOR_LLD_v1.1.md:369`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0012, OCOR-DEV-0017, OCOR-DEV-0031, OCOR-DEV-0034, OCOR-DEV-0035, OCOR-DEV-0037, OCOR-DEV-0039 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 5 file di codice con i rispettivi test.
- Scelte del PO legate all'unità: (1) NCR-C2-008 (DECISION_REQUIRED, digest format conflict) gates NCR-C2-007 and NCR-C2-011: the closed request schema and the six operations are implemented with the digest format the PO selects
- Stima: 4 iterazioni. C2 before C4: the C4 watermark and typed-error entries depend on the gateway release check and Problem model.

### NCP-U04

- Voci risolte: NCR-C3-001, NCR-C3-002, NCR-C3-003, NCR-C3-004, NCR-C3-006.
- Codice: `ocor-runtime/src/ocor_runtime/c3/adapters/postgres.py`, `ocor-runtime/src/ocor_runtime/c3/adapters/terminusdb.py`, `ocor-runtime/src/ocor_runtime/c3/ports.py`, `ocor-runtime/src/ocor_runtime/c3/recovery.py`, `ocor-runtime/src/ocor_runtime/c3/service.py`, `ocor-runtime/src/ocor_runtime/c3/terminusdb_service.py`, `ocor-runtime/src/ocor_runtime/c6/engine.py`, `ocor-runtime/src/ocor_runtime/c8/orchestrator.py`.
- Backend richiesto: PostgreSQL and TerminusDB (C3 adapters), Kafka for the relay.
- Criteri di accettazione: 5, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U04.acceptance_criteria`). Test RED da scrivere sul codice attuale: 5.
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0013, OCOR-DEV-0029, OCOR-DEV-0030, OCOR-DEV-0036, OCOR-DEV-0046 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 8 file di codice con i rispettivi test.
- Scelte del PO legate all'unità: (1) NCR-C3-005 and NCR-C3-007 (DECISION_REQUIRED) stay outside the unit
- Stima: 4 iterazioni. C3 first in the composition chain C3 -> C5 -> C4 required before the C6 action path.

### NCP-U06

- Voci risolte: NCR-C5-001, NCR-C5-002, NCR-C5-003.
- Codice: `ocor-runtime/src/ocor_runtime/c5/backbone.py`, `ocor-runtime/src/ocor_runtime/c5/operations.py`.
- Backend richiesto: Kafka/Strimzi, PostgreSQL (durable DLQ/quarantine).
- Criteri di accettazione: 3, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U06.acceptance_criteria`). Test RED da scrivere sul codice attuale: 3.
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0040, OCOR-DEV-0041, OCOR-DEV-REM-0018, OCOR-DEV-REM-0022 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 2 file di codice con i rispettivi test.
- Stima: 3 iterazioni. C5 second in the chain C3 -> C5 -> C4.

### NCP-U05

- Voci risolte: NCR-C4-001, NCR-C4-002, NCR-C4-003.
- Codice: `ocor-runtime/src/ocor_runtime/c4/jena_adapter.py`, `ocor-runtime/src/ocor_runtime/c4/rebuild.py`, `ocor-runtime/src/ocor_runtime/c4/typedb_adapter.py`.
- Backend richiesto: TypeDB, Jena, TerminusDB (rebuild source).
- Criteri di accettazione: 3, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U05.acceptance_criteria`). Test RED da scrivere sul codice attuale: 3.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/tasks/test_ocor_dev_0037.py:158-165` `test_a_real_typedb_unreachability_fails_closed_never_serving_a_fabricated_response` — REALIGN (RED richiesto); attuale: with pytest.raises(urllib.error.URLError): adapter.current_watermark(); prescritto: a typed fail-closed error of the contract with a reason code (`ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:486-491`, `docs/OCOR_LLD_v1.1.md:346`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0037, OCOR-DEV-0038, OCOR-DEV-0039 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 3 file di codice con i rispettivi test.
- Stima: 3 iterazioni. C4 third in the chain C3 -> C5 -> C4; needs NCP-U03 (release check, Problem model).

### NCP-U07

- Voci risolte: NCR-C6-001, NCR-C6-002, NCR-C6-003, NCR-C6-004, NCR-C6-005, NCR-C6-006, NCR-C6-007, NCR-C6-008, NCR-C6-009, NCR-C6-014.
- Codice: `ocor-runtime/src/ocor_runtime/c6/engine.py`, `ocor-runtime/src/ocor_runtime/c6/fsm.py`, `ocor-runtime/src/ocor_runtime/c6/human_gate.py`, `ocor-runtime/src/ocor_runtime/c6/safety.py`, `ocor-runtime/src/ocor_runtime/c6/temporal_workflows.py`, `ocor-runtime/src/ocor_runtime/c6_capabilities.py`, `ocor-runtime/src/ocor_runtime/c7_emission.py`, `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py`, `ocor-runtime/src/ocor_runtime/kernel/governance.py`, `ocor-runtime/src/ocor_runtime/memory/promotion.py`.
- Backend richiesto: PostgreSQL, Temporal, OPA, Keycloak/SPIFFE, OpenBao (signing).
- Criteri di accettazione: 10, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U07.acceptance_criteria`). Test RED da scrivere sul codice attuale: 10.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/tasks/test_ocor_dev_0030.py:92-93` `make_approval (helper)` — ADAPT_CONSTRUCTION; attuale: Approval(action_id, approver, approved, approved_at): an unsigned free value; prescritto: a signed Approval bound to proposal digest, revision, release and validity window, built by the test signer; assertions unchanged (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:2849-2850`, `docs/OCOR_LLD_v1.1.md:254`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0030.py:82-89` `grant_lease (helper)` — ADAPT_CONSTRUCTION; attuale: legacy CapabilityAuthority.issue(..., ttl=timedelta(hours=1)); prescritto: the normative CapabilityLease of kernel/governance.py, expires_at <= PT5S, bound to the action instance and emission attempt (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3194-3212`, `docs/OCOR_LLD_v1.1.md:69-81`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0030.py:216-217` `test_non_risk_bearing_action_does_not_require_a_human_gate_approval` — REALIGN (RED richiesto); attuale: assert outcome.simulated_effect is not None; assert len(sink.calls) == 1 (approval=None, canonical target); prescritto: the request is denied without execution: no simulated effect and no sink call, because the risk class comes from the signed ActionType and a canonical target never takes NOT_REQUIRED (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:2847`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3298`, `docs/OCOR_LLD_v1.1.md:268`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0042.py:128-141` `test_applying_every_one_of_the_44_transitions_persists_exactly_one_effect_each` — ADAPT_PRECONDITION; attuale: every transition applied on its own to a fresh GovernedActionFSM, without its source state; prescritto: each transition applied to an action already in its source state, with its event and guard satisfied; the three assertions (44 effects, the same 44 ids, all durable) are unchanged (`docs/OCOR_LLD_v1.1.md:260-305`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_rem_0039.py:473-482` `test_live_cancellation_after_dispatch_is_never_presumed` — ADAPT_PRECONDITION; attuale: fsm.apply("ACT-T14", ...) on a fresh action; prescritto: the action is first driven to the ACT-T14 source state; the assertions are unchanged (`docs/OCOR_LLD_v1.1.md:260-305`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0009, OCOR-DEV-0030, OCOR-DEV-0042, OCOR-DEV-0043, OCOR-DEV-0044, OCOR-DEV-0047, OCOR-DEV-0058, OCOR-DEV-REM-0028 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 10 file di codice con i rispettivi test.
- Stima: 6 iterazioni. C6 action path after the C3 composition (NCR-C6-014 and NCR-C6-005 depend on NCR-C3-002). Largest unit: may be split by the PO into composition/contract/FSM and lease/fence/records sub-units without changing the resolved entries.

### NCP-U08

- Voci risolte: NCR-C6-010, NCR-C6-011, NCR-C6-012, NCR-C6-013.
- Codice: `ocor-runtime/src/ocor_runtime/c2/gateway.py`, `ocor-runtime/src/ocor_runtime/c4_marking.py`, `ocor-runtime/src/ocor_runtime/c6/safety.py`, `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py`, `ocor-runtime/src/ocor_runtime/kernel/governance.py`, `ocor-runtime/src/ocor_runtime/security/control_plane.py`, `ocor-runtime/src/ocor_runtime/security/ports.py`.
- Backend richiesto: OPA, Keycloak, OpenBao.
- Criteri di accettazione: 4, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U08.acceptance_criteria`). Test RED da scrivere sul codice attuale: 4.
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0009, OCOR-DEV-0014, OCOR-DEV-0034, OCOR-DEV-0044, OCOR-DEV-0047, OCOR-DEV-0048, OCOR-DEV-REM-0028 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 7 file di codice con i rispettivi test.
- Stima: 3 iterazioni. C6 safety and policy after NCP-U07 (NCR-C6-013 depends on NCR-C6-002) and NCP-U03 (NCR-C6-012 depends on NCR-C2-003).

### NCP-U09

- Voci risolte: NCR-C7-001, NCR-C7-003, NCR-C7-004, NCR-C7-005.
- Codice: `ocor-runtime/src/ocor_runtime/c7/runtime.py`.
- Backend richiesto: PostgreSQL/S3 (sealed result, overlay store).
- Criteri di accettazione: 4, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U09.acceptance_criteria`). Test RED da scrivere sul codice attuale: 4.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/tasks/test_ocor_dev_0045.py:143-146` `test_pin_mismatch_fails_loudly` — REALIGN (RED richiesto); attuale: with pytest.raises(CausalRuntimeError, match="PIN_MISMATCH") (three parametrised pins); prescritto: outcome REJECTED for each pin mismatch (replacement of a pytest.raises with the prescribed outcome, point 7) (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3024`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:2979-3005`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0045 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 1 file di codice con i rispettivi test.
- Voci `DECISION_REQUIRED` fuori ambito: NCR-C7-002, NCR-C7-006.
- Scelte del PO legate all'unità: (1) NCR-C7-001: an executable SCM may need a new causal dependency; the dependency is a PO option (SUPPLEMENT point 4, C7-1), the entry stays OPEN (2) NCR-C7-002 (DECISION_REQUIRED): the reason-code mapping must be decided before the outcome precedence is implemented
- Stima: 4 iterazioni. C7 independent of the action path; placed after it because NCP-U12 needs both. NCR-C7-001 may need a new causal dependency: option in the decision request (SUPPLEMENT point 4, C7-1), the entry stays OPEN.

### NCP-U10

- Voci risolte: NCR-C8-001, NCR-C8-002, NCR-C8-003, NCR-C8-004, NCR-C8-005, NCR-C8-007.
- Codice: `ocor-runtime/src/ocor_runtime/c6_capabilities.py`, `ocor-runtime/src/ocor_runtime/c8/orchestrator.py`, `ocor-runtime/src/ocor_runtime/c8/tool_runtime.py`, `ocor-runtime/src/ocor_runtime/c8_agent.py`.
- Backend richiesto: OPA, Keycloak/SPIFFE, PostgreSQL.
- Criteri di accettazione: 6, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U10.acceptance_criteria`). Test RED da scrivere sul codice attuale: 6.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/tasks/test_ocor_dev_0046.py:58, 63, 69` `test_the_full_assign_commit_dissent_lifecycle_writes_real_canonical_state` — REALIGN (RED richiesto); attuale: assert store.get("urn:ocor:agentrun:...") is not None (assignment, commitment, dissent); prescritto: the records live in the C8 AgentRun state and no canonical aggregate urn:ocor:agentrun:* is written (store.get(...) is None) (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:342`, `docs/OCOR_LLD_v1.1.md:183`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0046.py:78` `test_handoff_transfers_the_commitment_to_a_new_agent` — REALIGN (RED richiesto); attuale: handoff_lease = grant(authority, subject="agent-2", capability="agent:handoff", resource="agent-2"); prescritto: the handoff is authorised for the sender holding the commitment (agent-1), compared with the transport Principal; the assertions are unchanged (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:388`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3042`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0047.py:286` `test_insufficient_clearance_produces_no_tool_effect` — REALIGN (RED richiesto); attuale: assert excinfo.value.reason_code == "MARKING_DENIED"; prescritto: a code of the Tool Contract error_codes enum; proposed POLICY_DENIED (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:1759-1778`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_rem_0027.py:410` `test_a_slow_tool_without_any_stop_is_bounded_by_the_call_deadline` — REALIGN (RED richiesto); attuale: assert refused.value.reason_code == "TOOL_DEADLINE_EXCEEDED"; prescritto: a code of the Tool Contract error_codes enum; proposed BUDGET_EXCEEDED (wall-time budget) (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:1759-1778`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3119`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0047.py:107-119` `test_a_fully_bound_call_produces_a_receipt_and_a_real_tool_effect` — ADAPT_CONSTRUCTION; attuale: runtime.invoke(...) without agent principal, agent_run_id, delegation or autonomy tier; prescritto: the invoke call passes the bindings the corrected runtime requires; the six assertions are unchanged (the new receipt fields are asserted by a new RED test) (`ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3140`, `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:47`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0046, OCOR-DEV-0047 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 4 file di codice con i rispettivi test.
- Voci `DECISION_REQUIRED` fuori ambito: NCR-C8-006.
- Scelte del PO legate all'unità: (1) NCR-C8-006 (DECISION_REQUIRED, legacy AgentKernel default) stays outside the unit (2) resuming the OCOR-DEV-REM-0043 branch requires the plan decision to name it (REM-0043-NCP-SUSPENSION point 2)
- Stima: 5 iterazioni. C8 after NCP-U04 (NCR-C8-001 depends on NCR-C3-002) and NCP-U08 (NCR-C8-005 depends on NCR-C6-011). May resume the test and correction of the OCOR-DEV-REM-0043 branch (RED 81a8b76) only if the PO decision on the plan names it.

### NCP-U11

- Voci risolte: NCR-MEMORY-001, NCR-MEMORY-002, NCR-MEMORY-003, NCR-MEMORY-004, NCR-MEMORY-005.
- Codice: `ocor-runtime/src/ocor_runtime/memory/consolidation.py`, `ocor-runtime/src/ocor_runtime/memory/embeddings.py`, `ocor-runtime/src/ocor_runtime/memory/lifecycle.py`, `ocor-runtime/src/ocor_runtime/memory/model.py`, `ocor-runtime/src/ocor_runtime/memory/operations.py`, `ocor-runtime/src/ocor_runtime/memory/retrieval.py`, `ocor-runtime/src/ocor_runtime/memory/stores.py`.
- Backend richiesto: real memory stack: PostgreSQL metadata, content store, full-text and vector indexes.
- Criteri di accettazione: 5, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U11.acceptance_criteria`). Test RED da scrivere sul codice attuale: 5.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/tasks/test_ocor_dev_rem_0020.py:560, 568-569` `test_f2_policy_denied_items_cost_no_more_index_work_than_before` — REALIGN (RED richiesto); attuale: baseline = {0: 1, 40: 6, 130: 15}[denied]; assert outcome == (["RETRIEVAL_BACKPRESSURE"] if denied == 130 else [allowed]); prescritto: work and error independent of policy-denied items: index lookups equal to the zero-denied case (1) and the allowed item returned for 0, 40 and 130 denied items (the bound tightens, the parametrisation is unchanged) (`ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:268`, `docs/OCOR_LLD_v1.1.md:214`, `docs/OCOR_LLD_v1.1.md:397`).
  - `ocor-runtime/tests/tasks/test_ocor_dev_0055.py:481-483` `test_invalid_deletion_requests_change_nothing_and_are_audited (INVALID_DELETIONS)` — PO_CHOICE_REQUIRED; attuale: three parametrised cases (LATEST_VERSION, PROJECT_SCOPE, PRINCIPAL_SCOPE) expect UNSUPPORTED_CAPABILITY/DELETION_SCOPE_UNSUPPORTED; prescritto: the three scopes are executed (contract enum, LLD :421): as cases of an 'invalid request' test they lose their meaning (`ocor-runtime/docs/governance_dossier/contracts/ocor-governed-memory.openapi.yaml:273`, `docs/OCOR_LLD_v1.1.md:421`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0050, OCOR-DEV-0051, OCOR-DEV-0052, OCOR-DEV-0053, OCOR-DEV-0054, OCOR-DEV-0055, OCOR-DEV-0059, OCOR-DEV-0061, OCOR-DEV-REM-0023, OCOR-DEV-REM-0036 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 7 file di codice con i rispettivi test.
- Stima: 3 iterazioni. Governed memory: independent of the action path except promotion (NCR-C6-009, NCP-U07); placed before NCP-U12.

### NCP-U12

- Voci risolte: NCR-TESTS-001, NCR-TESTS-002, NCR-TESTS-003, NCR-TESTS-004, NCR-TESTS-005.
- Codice: —.
- Backend richiesto: selected real C1-C8 service stack (as OCOR-DEV-0065).
- Criteri di accettazione: 5, uno per voce, ciascuno con le ancore normative di file e riga (`plan_units.NCP-U12.acceptance_criteria`). Test RED da scrivere sul codice attuale: 5.
- Test esistenti da riallineare o adattare (punto 7):
  - `ocor-runtime/tests/mission_thread/test_first_governed_slice.py:37-75, 130-131, 212, 295-304` `module imports and run_mission_thread / resolve_operator_identity` — ADAPT_CONSTRUCTION; attuale: legacy c2_identity, c3_store, c4_marking, c6_capabilities, c7_emission, c8_agent and spikes.* adapters and oracles; prescritto: the retained C1-C8 components and real adapters; syntax-tree comparison (same functions, assertions, raises, parametrisations) (`ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:427`, `docs/OCOR_LLD_v1.1.md:409`).
- Riqualifiche: di sola regressione OCOR-DEV-0005, OCOR-DEV-0050, OCOR-DEV-0082; con supersession, candidati: OCOR-DEV-0031 (limite superiore, fissato di nuovo all'head RED).
- Consumer da inventariare: 0 file di codice con i rispettivi test.
- Scelte del PO legate all'unità: (1) NCR-TESTS-005: Hypothesis (or another property-testing library) is a new test dependency and a uv.lock change: PO decision (point 6 stop rule)
- Stima: 3 iterazioni. Last: the mission thread through the retained components needs every component unit; the schema meta-tests can start earlier and are kept here only to keep one closed scope.

### Sblocco dei task G6 e G7

| Task | Unità necessarie | Voci `DECISION_REQUIRED` | Altre decisioni del PO |
|---|---|---|---|
| OCOR-DEV-0060 | NCP-U13, NCP-U03, NCP-U05, NCP-U07, NCP-U08, NCP-U09 | NCR-C7-002, NCR-LEGACY-001 | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5); OCOR-DEV-0060-BA-RUNTIME-GAPS |
| OCOR-DEV-0061 | NCP-U13, NCP-U11 | — | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5) |
| OCOR-DEV-0062 | NCP-U13, NCP-U07, NCP-U10, NCP-U11 | — | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5) |
| OCOR-DEV-0063 | NCP-U13, NCP-U01, NCP-U02, NCP-U04, NCP-U07, NCP-U08 | NCR-LEGACY-001 | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5) |
| OCOR-DEV-0064 | NCP-U13, NCP-U03, NCP-U04, NCP-U06, NCP-U05, NCP-U07, NCP-U08, NCP-U10 | — | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5) |
| OCOR-DEV-0065 | NCP-U13, NCP-U01, NCP-U02, NCP-U03, NCP-U04, NCP-U06, NCP-U05, NCP-U07, NCP-U09, NCP-U10, NCP-U11, NCP-U12 | NCR-C2-008, NCR-C7-002, NCR-C8-006 | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5); OCOR-DEV-0060-BA-RUNTIME-GAPS |
| OCOR-DEV-0066 | NCP-U13, NCP-U04, NCP-U06, NCP-U05, NCP-U09, NCP-U11 | — | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5); OCOR-DEV-0060-BA-RUNTIME-GAPS |
| OCOR-DEV-0067 | NCP-U13 | NCR-C2-008, NCR-C7-002, NCR-C8-006, NCR-LEGACY-001 | NORMATIVE-CONFORMANCE-PLAN (PO decision on this plan, point 5); OCOR-DEV-0060-BA-RUNTIME-GAPS |

Regola del punto 5: un task G6 parte solo dopo una decisione del PO su questa decision request che lo sblocca per nome, con ogni voce che lo indica in `blocks` risolta oppure `DEFERRED_BY_PO`; `OCOR-DEV-0067` solo con ogni voce `HIGH` risolta, `REFUTED` o `DEFERRED_BY_PO`.

## 3. Proposte per G6 e G7 (punto 4.f)

proposals only (point 4.f): no backlog or traceability-plan change before the PO decision. Le proposte complete per task sono in `g6_g7_proposals.tasks`.

| Task | Requisiti proposti | Metodo: test automatico / misto / altro metodo | Voci bloccanti | Criteri proposti |
|---|---|---|---|---|
| OCOR-DEV-0060 | 61 | 38 / 18 / 5 | 17 | 3 |
| OCOR-DEV-0062 | 10 | 5 / 3 / 1 | 11 | 3 |
| OCOR-DEV-0063 | 78 | 41 / 26 / 11 | 19 | 3 |
| OCOR-DEV-0064 | 27 | 12 / 5 / 10 | 24 | 3 |
| OCOR-DEV-0065 | 154 | 84 / 41 / 29 | 47 | 3 |
| OCOR-DEV-0066 | 8 | 2 / 3 / 3 | 11 | 3 |
| OCOR-DEV-0067 | 12 | 0 / 0 / 0 | 9 | 4 |

- **OCOR-DEV-0060**: Each BA-01..BA-08 case runs on its selected real component against the oracle of LLD v1.1 §7.1 (:367-374) and is bound to the requirements listed in ba_cases (never BR-003), with its own result, raw-log hash and the LLD v1.1 §7.3 fields. Each case realises the Register acceptance criterion at the cited line, with the Register method; requirements whose method is not an automated test (0 here) get the evidence of their method, not a test case, and those with a mixed method (0 here) get both (NCR-PLAN-005). Every register entry in blocking_register_entries is resolved or DEFERRED_BY_PO before the task starts (point 5).
- **OCOR-DEV-0062**: Every requirement in proposed_requirement_ids has its own case bound to that requirement (never BR-003), its own result, raw-log hash and the evidence-package fields of LLD v1.1 §7.3 (:411); a failed P0 makes the gate NO-GO. Each case realises the Register acceptance criterion at the cited line, with the Register method; requirements whose method is not an automated test (1 here) get the evidence of their method, not a test case, and those with a mixed method (3 here) get both (NCR-PLAN-005). Every register entry in blocking_register_entries is resolved or DEFERRED_BY_PO before the task starts (point 5).
- **OCOR-DEV-0063**: Every requirement in proposed_requirement_ids has its own case bound to that requirement (never BR-003), its own result, raw-log hash and the evidence-package fields of LLD v1.1 §7.3 (:411); a failed P0 makes the gate NO-GO. Each case realises the Register acceptance criterion at the cited line, with the Register method; requirements whose method is not an automated test (11 here) get the evidence of their method, not a test case, and those with a mixed method (26 here) get both (NCR-PLAN-005). Every register entry in blocking_register_entries is resolved or DEFERRED_BY_PO before the task starts (point 5).
- **OCOR-DEV-0064**: Every requirement in proposed_requirement_ids has its own case bound to that requirement (never BR-003), its own result, raw-log hash and the evidence-package fields of LLD v1.1 §7.3 (:411); a failed P0 makes the gate NO-GO. Each case realises the Register acceptance criterion at the cited line, with the Register method; requirements whose method is not an automated test (10 here) get the evidence of their method, not a test case, and those with a mixed method (5 here) get both (NCR-PLAN-005). Every register entry in blocking_register_entries is resolved or DEFERRED_BY_PO before the task starts (point 5).
- **OCOR-DEV-0065**: Every requirement in proposed_requirement_ids has its own case bound to that requirement (never BR-003), its own result, raw-log hash and the evidence-package fields of LLD v1.1 §7.3 (:411); a failed P0 makes the gate NO-GO. Each case realises the Register acceptance criterion at the cited line, with the Register method; requirements whose method is not an automated test (29 here) get the evidence of their method, not a test case, and those with a mixed method (41 here) get both (NCR-PLAN-005). Every register entry in blocking_register_entries is resolved or DEFERRED_BY_PO before the task starts (point 5).
- **OCOR-DEV-0066**: Every requirement in proposed_requirement_ids has its own case bound to that requirement (never BR-003), its own result, raw-log hash and the evidence-package fields of LLD v1.1 §7.3 (:411); a failed P0 makes the gate NO-GO. Each case realises the Register acceptance criterion at the cited line, with the Register method; requirements whose method is not an automated test (3 here) get the evidence of their method, not a test case, and those with a mixed method (3 here) get both (NCR-PLAN-005). Every register entry in blocking_register_entries is resolved or DEFERRED_BY_PO before the task starts (point 5).
- **OCOR-DEV-0067**: Every requirement in proposed_requirement_ids has its own case bound to that requirement (never BR-003), its own result, raw-log hash and the evidence-package fields of LLD v1.1 §7.3 (:411); a failed P0 makes the gate NO-GO. Each case realises the Register acceptance criterion at the cited line, with the Register method; requirements whose method is not an automated test (0 here) get the evidence of their method, not a test case, and those with a mixed method (0 here) get both (NCR-PLAN-005). Every register entry in blocking_register_entries is resolved or DEFERRED_BY_PO before the task starts (point 5). The ledger has one row per approved requirement (285) with implementation commit, qualifying non-skipped test or method evidence and hashes, and every field of evidence_package_fields.union; it starts only when every HIGH entry is resolved, REFUTED or DEFERRED_BY_PO (plan units NCP-U13, NCP-U01, NCP-U02, NCP-U03, NCP-U04, NCP-U06, NCP-U05, NCP-U07, NCP-U08, NCP-U09, NCP-U10, NCP-U11, NCP-U12).

Allocazioni incoerenti segnalate in `docs/development_plan/OCOR_TRACEABILITY_PLAN.csv`: 63 righe (`g6_g7_proposals.incoherent_allocations`, con requisito, riga e motivo). Backlog e piano di tracciabilità non cambiano senza la decisione del punto 5.

## 4. Voci `DECISION_REQUIRED`

### NCR-C1-007 (C1, MEDIUM; blocca: nessun task)

The legacy artefact ocor-runtime/schemas/ocor.openapi.yaml (version 1.2.0) describes itself as the 'Normative C1-C8 contract' although it is not among the contracts materialised by LLD v1.1 §0.2, and its /compile and /identities:resolve operations declare no security requirement; the legacy SemanticCompiler validates nothing when no schema is configured. Remediation would change the legacy slice (ocor-runtime/schemas/, c1_compiler.py).

Ancore: `docs/OCOR_LLD_v1.1.md:20-31`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:371`. Motivo: programme decision point 4.d: any item that would require changing the legacy slice.

- 1. Keep the legacy artefact unchanged and record it as non-normative in the register only (no runtime change).
- 2. Authorise a change of the legacy slice that marks the artefact non-normative and secures or removes the two operations, with requalification of the legacy tests.
- 3. Retire the legacy slice surface under a dedicated PO decision.

### NCR-C2-008 (C2, HIGH; blocca: OCOR-DEV-0065)

Digest format conflict between normative sources: the Named Query Gateway contract requires '^sha256:<hex>' for policy_bundle_digest, governed_context_digest, ontology_release_digest, contract_digest and SchemaPin.digest, while LLD v1.1 §1.1 and the GovernedContext schema prescribe 'urn:sha256:<hex>' (and the same gateway contract uses urn:sha256 for classification_marking_ref and provenance_ref). The code follows urn:sha256 and rejects every contract-form digest. Both sources are contracts of LLD v1.1 §0.2 / LLD text; the precedence of LLD v1.1 §0.1 does not settle a conflict inside the materialised contract set.

Ancore: `ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:170-192`, `ocor-runtime/docs/governance_dossier/contracts/ocor-named-query-gateway.openapi.yaml:118`, `ocor-runtime/docs/governance_dossier/contracts/governed-context.schema.json:43-48`, `docs/OCOR_LLD_v1.1.md:37`, `docs/OCOR_LLD_v1.1.md:16-18`. Motivo: programme decision point 4.d: a divergence between normative sources that the precedence of LLD v1.1 §0.1 does not resolve (the decision names this example).

- 1. The LLD v1.1 §1.1 form urn:sha256 prevails: the gateway contract patterns are corrected by a governed contract change (new decision), the code stays.
- 2. The gateway contract form sha256: prevails on the query wire: C2 maps between wire form and the internal urn:sha256 form at the transport boundary; the GovernedContext schema stays.
- 3. Accept both forms on the gateway wire and canonicalise to urn:sha256 before digest comparison (requires a contract clarification).

### NCR-C3-005 (C3, MEDIUM; blocca: nessun task)

fallback.postgres_outbox.select_atomic_backend selects the PostgreSQL transactional outbox implicitly from a capability attribute (supports_atomic_multi_document_writes), against 'no implicit fallback'; it is not wired to any operational path and raises non-normative errors (ConcurrencyConflict, ValueError, RuntimeError). Changing it changes the outcome of the legacy-slice test test_ba01_atomic_outbox.py.

Ancore: `ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Register_v1.3_APPROVED.md:244`, `docs/OCOR_LLD_v1.1.md:18`. Motivo: programme decision points 4.d and 6: a change that alters the outcome of a legacy-slice test, including through fallback/.

- 1. Leave fallback/ unchanged and record it as legacy-only, not wired (no runtime change).
- 2. Authorise removing the implicit selection (explicit configuration only) with requalification of the legacy test test_ba01_atomic_outbox.py.
- 3. Retire fallback/ with the legacy slice under a dedicated PO decision.

### NCR-C3-007 (C3, MEDIUM; blocca: nessun task)

From supplement NCP-S04, TerminusDB part: the TerminusDB claim_outbox_batch computes pending entries from a read snapshot without writing any claim, so concurrent relays read the same entries. The norm prescribes SKIP LOCKED for PostgreSQL rows and does not specify the TerminusDB equivalent.

Ancore: `docs/OCOR_LLD_v1.1.md:132`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:271`. Motivo: SUPPLEMENT point 4 (NCP-S04): the TerminusDB equivalent is DECISION_REQUIRED when the norm does not specify it.

- 1. Writer-epoch fencing suffices: only the fenced writer relays, so no per-entry claim is required (record as conforming).
- 2. Require a conditional claim document per entry (WOQL conditional insert) as the TerminusDB equivalent of SKIP LOCKED.
- 3. Require relays to run only through a single serialised coordinator and document it as the equivalent.

### NCR-C7-002 (C7, HIGH; blocca: OCOR-DEV-0060, OCOR-DEV-0065)

The six abstention codes produced (MAIN_CONTAMINATED, RELEASE_MISMATCH, MISSING_FACTUAL_SET, UNRESOLVED_CONFOUNDING, OUT_OF_DOMAIN, POSITIVITY_FAILURE) are outside the closed ABSTAIN set of ADD v1.3 §4.2 and no precedence is applied. LLD v1.1 §2.7 names exactly these six conditions as disjoint reason codes, ADD v1.3 §4.2 prescribes eight different codes with a precedence and sends signature, schema, policy and version-pin errors to REJECTED. ADD prevails (LLD v1.1 §0.1), and some mappings are univocal (RELEASE_MISMATCH -> REJECTED; an explicit valid_envelope violation -> OUTSIDE_VALIDITY_ENVELOPE), but the mapping of MAIN_CONTAMINATED, MISSING_FACTUAL_SET, UNRESOLVED_CONFOUNDING and POSITIVITY_FAILURE is not fixed by either text.

Ancore: `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3007-3022`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3024`, `docs/OCOR_LLD_v1.1.md:177`, `docs/OCOR_LLD_v1.1.md:16-18`, `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:60`, `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:239`. Motivo: programme decision point 4.d (sources not resolved by LLD v1.1 §0.1 precedence, or legacy slice).

- A (recommended): ADD v1.3 closed set with the univocal mappings (RELEASE_MISMATCH -> REJECTED, OUT_OF_DOMAIN on an explicit envelope -> OUTSIDE_VALIDITY_ENVELOPE) and a PO-fixed mapping MAIN_CONTAMINATED -> REJECTED (policy), MISSING_FACTUAL_SET -> REJECTED (contract; cf. FR-095 acceptance), UNRESOLVED_CONFOUNDING -> NOT_IDENTIFIED, POSITIVITY_FAILURE -> ASSUMPTION_VIOLATION, with the ADD precedence
- B: ADD v1.3 closed set with POSITIVITY_FAILURE -> INSUFFICIENT_EVIDENCE and MISSING_FACTUAL_SET -> INSUFFICIENT_EVIDENCE
- C: keep the LLD v1.1 §2.7 codes; requires a normative change (new DEC), outside this programme

### NCR-C7-006 (C7, MEDIUM; blocca: nessun task)

estimate_counterfactual returns IDENTIFIED with a unit-level counterfactual outcome (STRATIFIED_BACKDOOR_COUNTERFACTUAL: observed outcome plus the within-stratum arm difference). In the PoC profile the Counterfactual Query (ELM-070) is deferred and full abduction-action-prediction execution returns REJECTED{CAPABILITY_DEFERRED, ELM-070}; the operation is not AAP (no abduction of U), but it answers a unit-level counterfactual query, and the norm does not say whether such a non-AAP imputation is inside the deferred capability.

Ancore: `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3036`, `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:236`. Motivo: programme decision point 4.d (sources not resolved by LLD v1.1 §0.1 precedence, or legacy slice).

- A (recommended, fail-closed): treat every unit-level counterfactual query as ELM-070 and return REJECTED{CAPABILITY_DEFERRED, ELM-070} in the PoC profile
- B: keep the operation as a non-AAP interventional by-product, renamed and documented so that it makes no counterfactual claim (no IDENTIFIED counterfactual outcome)

### NCR-C8-006 (C8, HIGH; blocca: OCOR-DEV-0065)

The legacy AgentKernel built without capability_authority (its default) runs invoke and execute_sandboxed with no capability at all: authorisation is skipped instead of failing closed. No current component under ocor-runtime/src constructs AgentKernel; legacy-slice tests (acceptance_ev) and the mission-thread test construct it without an authority, so making it fail closed changes the legacy slice and the outcome of its tests.

Ancore: `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:47`, `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md:279`, `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md:3121`. Motivo: remediation in place would change the legacy slice (c8_agent.py) and the outcome of legacy-slice tests.

- A (recommended): leave the legacy AgentKernel unchanged and give the current C8 kernel (NCP-U10) a mandatory authority with no fail-open default; the mission thread (OCOR-DEV-0065) uses the current kernel
- B: make capability_authority mandatory in the legacy AgentKernel; changes the legacy slice and the outcome of acceptance_ev tests, needs a PO decision

### NCR-LEGACY-001 (LEGACY, LOW; blocca: OCOR-DEV-0060, OCOR-DEV-0063, OCOR-DEV-0067)

The legacy slice uses identifiers that collide with normative ones. (a) c5_actions.py implements ACT-T01..ACT-T31b with different semantics (legacy ACT-T21 is RUNNING -> SUCCEEDED on SUCCEED; LLD v1.1 ACT-T21 is EXECUTION_FAILED -> COMPENSATING) and ocor_runtime/__init__.py re-exports it. (b) tests/acceptance_ev uses EV-0xx identifiers that collide with the EV identifiers of the Decision Register (EV-020 is bit-for-bit replay, DEC-102). (c) tests/backend_assumptions/test_ba01..test_ba08 use the BA numbering with meanings different from LLD v1.1 §7.1 (for example test_ba05_temporal_guards against BA-05, Temporal/PostgreSQL running the 44 transitions); they were created as BA01-BA08 (commit ddfa97d), not renamed from RBA-*. Current components that depend on legacy classes are recorded per component (NCR-C3-002, NCR-C6-004, NCR-C6-005, NCR-C6-012, NCR-C8-004, NCR-C8-006). Renaming changes the legacy slice: DECISION_REQUIRED by point 4.d.

Ancore: `docs/OCOR_LLD_v1.1.md:288`, `docs/OCOR_LLD_v1.1.md:363-374`, `docs/OCOR_LLD_v1.1.md:405`, `ocor-runtime/docs/governance_dossier/registers/OCOR_Decision_Register_v1.1_APPROVED.md:123`. Motivo: programme decision point 4.d (sources not resolved by LLD v1.1 §0.1 precedence, or legacy slice).

- A (recommended): leave the legacy slice unchanged; the register, the G6 evidence and the ledger of OCOR-DEV-0067 cite LLD identifiers only, and every citation of a legacy test is qualified as legacy (for example 'legacy test_ba05', never 'BA-05'); a validator check rejects a G6 case that binds a legacy acceptance_ev or backend_assumptions test to an LLD ACT-T, BA or Decision Register EV identifier
- B: authorise a change of the legacy slice that renames the colliding identifiers (for example LEGACY-ACT-*, LEGACY-EV-*, LEGACY-BA-*) and drops the re-export from __init__.py, with requalification of the sealed records that include those tests
- C: retire the legacy slice under a dedicated PO decision, after the current components no longer depend on it (NCP-U04, NCP-U07, NCP-U08, NCP-U10)

## Opzioni per il PO

1. **Approvare il piano come proposto (raccomandata).** Le 13 unità entrano come unità di remediation del programma nell'ordine indicato, ciascuna con il proprio `OCOR-DEV-REM-*` assegnato all'avvio e il ciclo completo del punto 5; i test elencati per ciascuna unità sono riallineabili alle condizioni del punto 7; le proposte del punto 4.f entrano nel backlog e nel piano di tracciabilità con l'unità `NCP-U13`, la prima. Il PO decide inoltre ciascuna voce `DECISION_REQUIRED` (sezione 4) e le scelte legate alle unità (nuove dipendenze per `NCP-U09` e `NCP-U12`, ripresa del branch di `OCOR-DEV-REM-0043` in `NCP-U10`). Il punto 7 copre i riallineamenti con RED (`REALIGN`) e gli adattamenti di sola costruzione (`ADAPT_CONSTRUCTION`); i casi `ADAPT_PRECONDITION` (`NCP-U07`: `test_ocor_dev_0042.py`, `test_ocor_dev_rem_0039.py`) e `PO_CHOICE_REQUIRED` (`NCP-U11`: `test_ocor_dev_0055.py`) sono ammessi solo se il PO li autorizza per nome con questa decisione.
2. **Approvazione parziale.** Il PO approva soltanto un sottoinsieme di unità (per esempio `NCP-U13` e la catena C3 → C5 → C4 → C6 che sblocca `OCOR-DEV-0063`/`0064`) e rinvia le altre; le voci delle unità non approvate restano `OPEN` o diventano `DEFERRED_BY_PO` per `id`.
3. **Revisione del piano.** Il PO chiede una revisione del piano o delle proposte prima di approvare: nessuna remediation di codice parte e le campagne G6 restano sospese.

**Raccomandazione.** Opzione 1. Il piano segue le dipendenze dichiarate dalla norma (composizione C3 → C5 → C4 prima del percorso dell'azione di C6), mette per prima la correzione di piano ed evidenza (`NCP-U13`), da cui dipendono i criteri dei task G6, e lascia fuori ambito ogni modifica della slice legacy. Senza le decisioni sulle voci `DECISION_REQUIRED` restano bloccati `OCOR-DEV-0060`, `0063`, `0065` e `0067` anche dopo le unità.

## Impatto e task bloccati

- Bloccati fino alla decisione: `OCOR-DEV-0060`, `0062`–`0069` (blocker `NORMATIVE-CONFORMANCE-PROGRAMME`), `OCOR-DEV-REM-0043` (sospesa, `REM-0043-NCP-SUSPENSION`). `OCOR-DEV-0060`, `0065`–`0069` dipendono anche da `OCOR-DEV-0060-BA-RUNTIME-GAPS` (PR #408).
- Nessun lavoro ammesso resta eseguibile prima della decisione: il loop chiude con `TERMINAL_BLOCKED` (punto 5).
- Nessun nuovo `DEC-*`; ADD v1.3, LLD v1.1, contratti, schemi, registri normativi e profilo degli SDK generati invariati; `inputs/` intatto.
