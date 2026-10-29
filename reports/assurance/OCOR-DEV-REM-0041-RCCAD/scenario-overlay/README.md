# OCOR-DEV-REM-0041-RCCAD, unità overlay — `ScenarioOverlayStore` di C7 su TerminusDB

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo di riparazione 1 (dopo il `NO_GO` `OCOR-DEV-REM-0041-e9aa8e1cc659-0`).
  Verifier scelto dal loop (fornitore né Anthropic né OpenAI né Google), processo e contesto separati. Implementatori:
  Claude Code (Anthropic, `claude-opus-5-5`, implementatore di riserva del loop) e Codex (OpenAI, contato dal loop per l'unità C3).
  Revisore preventivo: Antigravity CLI / `gemini-4-argon-high` (Google), escluso dalla verifica finale (`PRE-CAMPAIGN-REVIEW`, 2026-10-26).
- **Fonte**: decisione normativa del PO `OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26)`, change set d; disposition
  `REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28)`, punti 1, 3 e 9. L'unità C3 di REM-0041 è già integrata
  (`../OCOR-DEV-REM-0041.json`, PR #391).
- **Branch**: `governed/ocor-dev-rem-0041-scenario-overlay-store`; commit di codice `621c0a41ffe1c84fed4ff932c6ebbcbdfb39c9f7`.
- **Stato**: TerminusDB, SeaweedFS e l'overlay store restano `Candidate Implementation` fino alla qualifica di `OCOR-DEV-0060`.
  Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Modifica

| File | Modifica |
|---|---|
| `ocor-runtime/src/ocor_runtime/c7/scenario_overlay.py` | nuovo: `Protocol` vendor-neutral `ScenarioOverlayStore` (ADD v1.3 §4.2: `open_snapshot`, `fork_scenario`, `append_overlay`, `read_at`, `discard`) che estende senza modifiche `ScenarioOverlayStoreSealSubset` di REM-0040 |
| `ocor-runtime/src/ocor_runtime/c7/adapters/terminusdb_overlay.py` | nuovo: `TerminusDBScenarioOverlayStore`, unico modulo di C7 che parla con TerminusDB (sola libreria standard): snapshot solo di `main`; un branch di scenario per `(scenario_id, run_id, compartments)`; delta append-only concatenati per hash in transazioni WOQL condizionate; `read_at` verifica l'intera catena; `discard` cancella solo il branch di scenario; nessun percorso di scrittura verso `main`; risposte malformate rifiutate come `ScenarioOverlayError` (ciclo 0, P1; ciclo 1: VF-001, VF-002 e P1–P5 della revisione preventiva) |
| `ocor-runtime/tests/tasks/test_ocor_dev_rem_0041_overlay.py` | nuovo modulo del task, 37 casi su TerminusDB e SeaweedFS reali (più nove casi loopback per la sola gestione locale degli errori: due del ciclo 0, due per VF-001/VF-002, cinque per la revisione preventiva del ciclo 1) |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti e self-hash |

Invariati (hash verificati dal modulo del task): `c7/sealed_results.py`, `c7/adapters/seaweedfs.py`, `c7/runtime.py`,
`c3/adapters/terminusdb.py`, `c3/terminusdb_service.py`; inoltre `CausalOutcome`, contratti, schemi, reason code,
`deploy/`, lock, `uv.lock`, script di campagna, controllo dei residui delle corsie, workflow, limiti, timeout, soglie e gate.

## Casi qualificanti

| Caso | Requisito citato | Casi passati | Esito |
|---|---|---|---|
| `OCOR-DEV-REM-0041-OVERLAY-PORT-COMPOSITION-AND-CONFINEMENT` | NFR-064 | 12 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-FAIL-CLOSED-INPUTS-AND-TRANSPORT` | NFR-064 | 39 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-SNAPSHOT-AND-READ-ONLY-BASELINE` | NFR-015 | 12 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-APPEND-ONLY-ISOLATED-OVERLAYS` | NFR-058 | 15 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-TAMPER-EVIDENT-CHAIN` | NFR-058 | 24 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-FORK-WITHOUT-DELIVERY-AND-SEAL-COMPOSITION` | NFR-058 | 9 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-VALIDATION-CLOSURE-GUARDS-LOCAL` | NFR-073 | 428 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-STACK-LIFECYCLE` | NFR-073 | 9 | PASS |
| `OCOR-DEV-REM-0041-OVERLAY-FULL-SUITE` | NFR-073 | 3334 | PASS |

I requisiti sono citati soltanto per il comportamento dell'overlay store e per la procedura di qualifica: nessuna promozione.

## Misura del fork concorrente

3 prove da 6 creazioni concorrenti dello stesso branch su TerminusDB 12.0.7, fuori dalla
campagna: esattamente una risposta 200 per prova, i perdenti ricevono 500 (`api:InternalServerError`, non `api:BranchExistsError`);
l'adapter classifica rileggendo l'elenco dei branch (conteggi: 200: 3, 500: 15).

## Suite completa

- Modalità `TWO_LANE` (`scripts/run_local_lane_campaign.py --execute`, ammissione di memoria all'avvio).
- 3334/3334 PASS, zero skip, unione JUnit uguale alla raccolta
  (`aece5d924b34d44e…`).
- Durata complessiva 2438,106 s; margine dal tetto di 5400 s: 2961,894 s;
  margine dalla notifica di 3600 s: 1161,894 s.
  Soglia di decision request (5100 s) non raggiunta.
- Memoria: MemAvailable all'avvio 21899,2 MiB (soglia 14340,6 MiB), minimo 13043,1 MiB;
  guardia di 3000 MiB rispettata.
- Alimentazione: rete elettrica per tutta la campagna (una lettura al minuto).

| Corsia | Casi | Durata della corsia (s) | Tempo dall'avvio della campagna (s) | Esito |
|---|---|---|---|---|
| 1 | 1028 | 1720,305 | 1842,947 | PASS |
| 2 | 2306 | 2301,102 | 2426,779 | PASS |

## Riqualifiche

| Task | Record | Supersede | Tipo |
|---|---|---|---|
| `OCOR-DEV-0005` | `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0041-overlay.json` | `OCOR-DEV-0005-requalified-rem0040-f04375e27981` | sola regressione |
| `OCOR-DEV-0050` | `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0041-overlay.json` | `OCOR-DEV-0050-requalified-rem0040-f04375e27981` | sola regressione |
| `OCOR-DEV-0082` | `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0041-overlay.json` | `OCOR-DEV-0082-requalified-rem0040-f04375e27981` | sola regressione |

L'unico input sigillato cambiato è `scripts/validate_ocor_development_plan.py` (allowlist): riqualifiche di sola
regressione (punto 4 di `LOCAL-FULL-SUITE-CAP-90-AMENDMENT`); test invariati; record sigillati intatti; inserimenti
chirurgici nei `MANIFEST.json`.

## Ciclo di riparazione 1

- Verdetto `OCOR-DEV-REM-0041-e9aa8e1cc659-0`: `NO_GO` (Cursor CLI, contesto pulito, esecuzione non interattiva, grok-4.7-high, xAI), VF-001 alto e VF-002 medio, entrambi bloccanti.
- VF-001: fixed in 22642a0: a stored revision is accepted only as an exact integer (bool, float and string rejected, nothing truncated or converted), otherwise OVERLAY_TAMPERED; RED in 6798519.
- VF-002: fixed in 22642a0: a log of main whose head is not an object with a COMMIT_REF identifier is BACKEND_ERROR, never a raw KeyError or TypeError; RED in 6798519.
- RED di VF-001/VF-002 su `e9aa8e1`: fingerprint `99fcb0dad535`; RED dei finding preventivi su `22642a0`: 5/5 casi falliti, fingerprint `7f6df69783f9`.
- Sonde di mutazione: 20/20 a `22642a0`, 28/28 all'head di codice.
- Revisione preventiva `OCOR-DEV-REM-0041-22642a02169f-pre` (Antigravity CLI, gemini-4-argon-high, Google): `BLOCKING_FINDINGS`, tre bloccanti e due consultivi, tutti corretti con RED/GREEN:
  - P1: fixed in 097c3aa: the first delta must store exactly the empty link that append_overlay writes; omitted or falsy non-string links are OVERLAY_TAMPERED (RED 7f6df69783f9, GREEN).
  - P2: fixed in 097c3aa: every listing entry must be an object with a string path, otherwise BACKEND_ERROR; the canonical database is matched on the full organization/database path.
  - P3: fixed in 097c3aa: the commit of the TerminusDB-Data-Version header must match COMMIT_REF, otherwise BACKEND_ERROR before the run-record request.
  - P4: accepted and fixed in 097c3aa: every entry of a log page of main must carry a COMMIT_REF identifier, otherwise BACKEND_ERROR (aligned with current_canonical_commit).
  - P5: accepted and fixed in 097c3aa: http.client.HTTPException and UnicodeDecodeError on the answer or on an error body are BACKEND_ERROR; connection failures stay STORE_UNAVAILABLE.
- Tentativo non qualificante: 097c3aaf5bab, fase A (bootstrap), about 40 s in: stopped by the implementer to relabel the docstrings of the five new cases as repair cycle 1 (they had been written as cycle 2); stack torn down with reset_test_environment.py --execute (PASS, zero residue) and credentials archived; no result used.

## TDD, mutazioni, gate e revisione preventiva (ciclo 0)

- RED iniziale sulla base `f72ebd66e403`: fingerprint `323d3b563ca5`. RED finale sulla stessa
  base con il test dell'head di codice: 29/30 casi falliti per `ModuleNotFoundError`; passa solo la guardia
  degli hash dei moduli sigillati. Fingerprint `f341be0788fa`.
- RED di P1 su `da5e512`: 2/2 casi falliti (`JSONDecodeError` e `ValueError` grezzi), fingerprint `a8060d678d89`.
- Sonda di mutazione all'head di codice del ciclo 1: 28/28 mutanti uccisi, baseline M0 verde.
- `PRE-CAMPAIGN-GATE` sull'head di codice del ciclo 1: 42/42 PASS, `drift` 0.
- Revisione preventiva del ciclo 0 `OCOR-DEV-REM-0041-da5e512efde2-pre`: `NO_BLOCKING_FINDINGS`, tre finding consultivi. P1 accolto e corretto; P2 rinviato a `OCOR-DEV-0060` (livello di ammissione
  degli scenari di C7); P3 applicato allo script locale del gate.

## Rischi residui

- TerminusDB, SeaweedFS and the C7 overlay store remain Candidate Implementation until OCOR-DEV-0060 qualifies BA-01/BA-06 on the selected components; the store has no runtime consumer yet.
- Tail truncation of an overlay by a principal with write access to the scenario branch is not detectable from the delta chain alone (the TerminusDB commit log keeps it); every non-final removal, modification or reordering is rejected.
- The isolation key does not bind governed_context_digest (preventive review P2): the C7 admission layer of OCOR-DEV-0060 must bind or check it.
- Concurrent-fork classification relies on the measured 500 answer of terminusdb 12.0.7 to the losers; a server change requires re-measurement.
- Remediation evidence only; no runtime conformance, BA or FGM evidence.

## Rollback

Revert dei commit dell'unità overlay: spariscono port, adapter, modulo di test e voci dell'allowlist; i record di
riqualifica di REM-0040 tornano i più recenti. Nessun consumer, contratto, lock o migrazione coinvolti; i database di
prova usa e getta vengono cancellati allo smontaggio.
