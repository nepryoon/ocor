# OCOR-DEV-REM-0040-RCCAD — sottoinsieme `sealResult` di C7 e adapter SeaweedFS

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier scelto dal loop (fornitore né Anthropic né OpenAI né Google), processo e contesto separati. Implementatori del task:
  Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal loop). Revisore preventivo:
  Antigravity CLI / `gemini-4-argon-high` (Google), escluso dalla verifica finale
  (`LOOP-IMPLEMENTER-ORDER-AUTH-FALLBACK`, `PRE-CAMPAIGN-REVIEW`, 2026-10-26).
- **Fonte**: decisione normativa del PO `OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26)`, change set c; disposition
  `REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28)`, opzione 1 con le condizioni dei punti 3-6.
- **Branch**: `governed/ocor-dev-rem-0040-seaweedfs-c7-adapter`; commit di codice `f04375e279814c9649e58bbf7a39285e8f843ca1`.
- **Stato**: SeaweedFS e l'adapter restano `Candidate Implementation` fino alla qualifica di `OCOR-DEV-0060`.
  Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Modifica

| File | Modifica |
|---|---|
| `ocor-runtime/src/ocor_runtime/c7/sealed_results.py` | nuovo: `Protocol` vendor-neutral `ScenarioOverlayStoreSealSubset` (`seal_result`, `read_sealed_result`), dichiarato nel nome e nella docstring sottoinsieme di `ScenarioOverlayStore` (ADD v1.3 §4.2) |
| `ocor-runtime/src/ocor_runtime/c7/adapters/seaweedfs.py` | nuovo: `SeaweedFSSealedResultStore`, unico modulo di C7 che parla con SeaweedFS (SigV4 con la sola libreria standard, solo `GET` e `PUT`); chiave dal `reproducibility_digest`; Object Lock e versioning verificati all'avvio; retention `COMPLIANCE`; scrittura condizionata `If-None-Match: *`; digest verificato a ogni lettura |
| `ocor-runtime/src/ocor_runtime/c7/adapters/__init__.py` | nuovo: package degli adapter di C7 |
| `ocor-runtime/tests/tasks/test_ocor_dev_rem_0040.py` | nuovo modulo del task, 21 casi su SeaweedFS reale |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti e self-hash |

Invariati: `c7/runtime.py` (hash verificato dal test), `CausalOutcome`, `c7_emission.EventSink`,
`memory.stores.MemoryContentStore`; contratti, schemi, reason code; `deploy/`, lock, `uv.lock`; script di campagna,
controllo dei residui delle corsie, workflow, limiti, timeout, soglie e gate.

## Casi qualificanti

| Caso | Requisito citato | Casi passati | Esito |
|---|---|---|---|
| `OCOR-DEV-REM-0040-PORT-CONFINEMENT-AND-CONFIGURATION` | NFR-064 | 18 | PASS |
| `OCOR-DEV-REM-0040-CANONICAL-SERIALIZATION` | NFR-015 | 9 | PASS |
| `OCOR-DEV-REM-0040-WORM-IMMUTABILITY` | NFR-030 | 18 | PASS |
| `OCOR-DEV-REM-0040-DIGEST-VERIFIED-ON-READ` | NFR-030 | 6 | PASS |
| `OCOR-DEV-REM-0040-FAIL-CLOSED-STARTUP-AND-ACCESS` | NFR-064 | 12 | PASS |
| `OCOR-DEV-REM-0040-VALIDATION-CLOSURE-GUARDS-LOCAL` | NFR-073 | 428 | PASS |
| `OCOR-DEV-REM-0040-STACK-LIFECYCLE` | NFR-073 | 9 | PASS |
| `OCOR-DEV-REM-0040-FULL-SUITE` | NFR-073 | 3297 | PASS |

I requisiti sono citati soltanto per il comportamento dell'adapter e per la procedura di qualifica: nessuna promozione.

## Misura della concorrenza

30 corse da 12 chiamanti sullo stesso risultato, su SeaweedFS pinned, fuori dalla campagna:
con `If-None-Match: *` una sola versione in 30/30 corse;
senza la condizione nessuna corsa con una sola versione (da 9 a 12 versioni).

## Suite completa

- Modalità `TWO_LANE` (`scripts/run_local_lane_campaign.py --execute`, ammissione di memoria all'avvio).
- 3297/3297 PASS, zero skip, unione JUnit uguale alla raccolta
  (`2dd2a6a9d434b427…`).
- Durata complessiva 2385,341 s; margine dal tetto di 5400 s: 3014,659 s;
  margine dalla notifica di 3600 s: 1214,659 s.
  Soglia di decision request (5100 s) non raggiunta.
- Memoria: MemAvailable all'avvio 24242,5 MiB (soglia 14340,6 MiB), minimo 16656,0 MiB;
  guardia di 3000 MiB rispettata.
- Alimentazione: rete elettrica per tutta la campagna (una lettura al minuto).

| Corsia | Casi | Durata della corsia (s) | Tempo dall'avvio della campagna (s) | Esito |
|---|---|---|---|---|
| 1 | 1024 | 1791,720 | 1911,879 | PASS |
| 2 | 2273 | 2255,477 | 2374,534 | PASS |

## Riqualifiche

| Task | Record | Supersede | Tipo |
|---|---|---|---|
| `OCOR-DEV-0005` | `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0040.json` | `OCOR-DEV-0005-requalified-rem0041-6a2dba8655d5` | sola regressione |
| `OCOR-DEV-0050` | `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0040.json` | `OCOR-DEV-0050-requalified-rem0041-6a2dba8655d5` | sola regressione |
| `OCOR-DEV-0082` | `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0040.json` | `OCOR-DEV-0082-requalified-rem0041-6a2dba8655d5` | sola regressione |

L'unico input sigillato cambiato è `scripts/validate_ocor_development_plan.py` (allowlist): riqualifiche di sola
regressione (punto 7 della disposition, punto 4 di `LOCAL-FULL-SUITE-CAP-90-AMENDMENT`); test invariati; record
sigillati intatti; inserimenti chirurgici nei `MANIFEST.json`.

## TDD, mutazioni, gate e revisione preventiva

- RED sulla base `13946dcf735a` con il test finale: 20/21 casi falliti per `ModuleNotFoundError`;
  passa solo il controllo dell'hash di `c7/runtime.py`. Fingerprint `56105d60ff0b`.
- Sonda di mutazione a `503cfc45637d` (sorgente dell'adapter identico all'head di codice): 11/12
  mutanti uccisi; M1 equivalente (i controlli successivi di `_decode` rifiutano gli stessi input).
- `PRE-CAMPAIGN-GATE` sull'head di codice: 41/42 PASS; `drift` atteso
  (0005, 0050, 0082) prima delle riqualifiche, 0 all'head dell'evidenza.
- Revisione preventiva `OCOR-DEV-REM-0040-b9eda5fe1204-pre` (Antigravity CLI, gemini-4-argon-high, Google):
  `NO_BLOCKING_FINDINGS`, un finding consultivo. P1 accolto: il caso della firma corrotta altera la firma SigV4 prodotta
  dall'adapter e attende `ACCESS_DENIED` da `initialize()`, con controllo positivo a firma intatta.

## Rollback

Revert dei commit di REM-0040: spariscono port, adapter, modulo di test e voci dell'allowlist; i record di
riqualifica precedenti tornano i più recenti. Nessun consumer, contratto, lock o migrazione coinvolti; gli oggetti del
bucket di test scadono con la loro retention.
