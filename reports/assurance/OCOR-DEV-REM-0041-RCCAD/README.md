# OCOR-DEV-REM-0041-RCCAD — adapter TerminusDB di C3 dietro i port sigillati

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier scelto dal loop (fornitore né Anthropic né OpenAI né Google), processo e contesto separati. Implementatori del task:
  Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal loop). Revisore preventivo:
  Antigravity CLI / `gemini-4-argon-high` (Google), escluso dalla verifica finale
  (`LOOP-IMPLEMENTER-ORDER-AUTH-FALLBACK`, `PRE-CAMPAIGN-REVIEW`, 2026-10-26).
- **Fonte**: decisione normativa del PO `OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26)`, opzione 2, change set d:
  TerminusDB diventa l'archivio canonico `VersionedAssertedState` di C3 (ADD v1.3 Parte I §2.2/§2.4); PostgreSQL resta
  l'adapter di verifica dell'atomicità (LLD v1.1 §5.2), mai un fallback implicito (`DEC-201`).
- **Branch**: `governed/ocor-dev-rem-0041-terminusdb-c3-adapter`; commit di codice `6a2dba8655d517b93bcc7fe0cc7e5723a64348bf`.
- **Stato**: TerminusDB, adapter e servizio restano `Candidate Implementation` fino alla qualifica di `OCOR-DEV-0060`.
  Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Modifica

| File | Modifica |
|---|---|
| `ocor-runtime/src/ocor_runtime/c3/adapters/terminusdb.py` | nuovo: unico modulo di C3 che parla con TerminusDB (HTTP della libreria standard, nessuna dipendenza nuova, `uv.lock` invariato); schema di sei classi, fence del writer, commit come transazione WOQL condizionata, relay solo da `main` con `C3DeliveryAttempt` separati, reconcile; controllo completo delle definizioni dello schema all'inizializzazione |
| `ocor-runtime/src/ocor_runtime/c3/terminusdb_service.py` | nuovo: `TerminusDBC3Service` implementa invariati i cinque port sigillati di C3 (`OCOR-DEV-0013`) |
| `ocor-runtime/tests/tasks/test_ocor_dev_rem_0041.py` | nuovo modulo del task, 33 casi su TerminusDB e TypeDB reali |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti e self-hash |

Invariati: port di C3, `PostgresC3Service`, `c3.recovery`, `c4.rebuild` e ogni consumer (nessun consumer ricollegato:
passano con `OCOR-DEV-0060`); contratti, schemi, reason code; `deploy/`, lock, `uv.lock`; script di campagna, workflow,
limiti, timeout, soglie e gate.

## Conformità BA-01 (colonna di ADD v1.3 Parte I §2.6)

| Caso | Requisito citato | Casi passati (3 corse) | Esito |
|---|---|---|---|
| `OCOR-DEV-REM-0041-CONFINEMENT-AND-NO-FALLBACK` | NFR-064 | 15 | PASS |
| `OCOR-DEV-REM-0041-ATOMIC-GOVERNED-COMMIT` | NFR-058 | 18 | PASS |
| `OCOR-DEV-REM-0041-BA01-CRASH-WINDOWS` | NFR-058 | 15 | PASS |
| `OCOR-DEV-REM-0041-BA01-STALE-WRITER-AND-RACES` | NFR-058 | 21 | PASS |
| `OCOR-DEV-REM-0041-BA01-FORK-WITHOUT-DELIVERY-ATTEMPT` | NFR-058 | 6 | PASS |
| `OCOR-DEV-REM-0041-RECOVERY-AND-LIFECYCLE` | NFR-058 | 24 | PASS |
| `OCOR-DEV-REM-0041-VALIDATION-CLOSURE-GUARDS-LOCAL` | NFR-073 | 428 | PASS |
| `OCOR-DEV-REM-0041-STACK-LIFECYCLE` | NFR-073 | 9 | PASS |
| `OCOR-DEV-REM-0041-FULL-SUITE` | NFR-073 | 3276 | PASS |

Le cinque crash window di §2.3 sono iniettate da un processo OS separato che termina con `os._exit` nello stadio
richiesto; le finestre 4 e 5 usano TypeDB reale e `ProjectionDriftDetector`. Writer stale, corse concorrenti e fork
senza `DeliveryAttempt` (§2.5 regola 11) girano sul server dello stack. La qualifica di BA-01 resta a `OCOR-DEV-0060`.

## Misure su TerminusDB 12.0.7

- La data version dell'API documenti **non** è un compare-and-swap concorrente: 8 PUT concorrenti con la stessa
  `TerminusDB-Data-Version` sono stati tutti applicati. L'adapter non la usa mai come CAS.
- Le transazioni WOQL condizionate sono serializzate: su 8 concorrenti una sola applicata, le altre senza scrittura.
- I batch sono tutto-o-niente; un `InsertDocument` concorrente di un'identità esistente rifiuta l'intera transazione.

## Suite completa

- Modalità `TWO_LANE` (`scripts/run_local_lane_campaign.py --execute`, ammissione di memoria all'avvio).
- 3276/3276 PASS, zero skip, unione JUnit uguale alla raccolta
  (`9338f407a13c6698…`).
- Durata complessiva 2395,328 s; margine dal tetto di 5400 s: 3004,672 s;
  margine dalla notifica di 3600 s: 1204,672 s.
  Soglia di decision request (5100 s) non raggiunta.
- Memoria: MemAvailable all'avvio 25806,5 MiB (soglia 14340,6 MiB), minimo 15902,6 MiB;
  guardia di 3000 MiB rispettata.
- Alimentazione: rete elettrica per tutta la campagna (una lettura al minuto).

| Corsia | Casi | Durata della corsia (s) | Tempo dall'avvio della campagna (s) | Esito |
|---|---|---|---|---|
| 1 | 1039 | 2022,588 | 2141,932 | PASS |
| 2 | 2237 | 2260,234 | 2382,008 | PASS |

## Riqualifiche

| Task | Record | Supersede | Tipo |
|---|---|---|---|
| `OCOR-DEV-0005` | `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0041.json` | `OCOR-DEV-0005-requalified-rem0037-61654ea20771` | sola regressione |
| `OCOR-DEV-0050` | `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0041.json` | `OCOR-DEV-0050-requalified-rem0037-61654ea20771` | sola regressione |
| `OCOR-DEV-0082` | `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0041.json` | `OCOR-DEV-0082-requalified-rem0037-61654ea20771` | sola regressione |

L'unico input sigillato cambiato è `scripts/validate_ocor_development_plan.py` (allowlist):
riqualifiche di sola regressione secondo il punto 4 di `LOCAL-FULL-SUITE-CAP-90-AMENDMENT`; test invariati; record
sigillati intatti; inserimenti chirurgici nei `MANIFEST.json`.

## TDD, mutazioni, gate e revisione preventiva

- RED sul `main` di partenza: 28/28 casi falliti (fingerprint nel record). Il primo GREEN usava la data version come CAS
  e la corsa concorrente lo ha smentito: sostituito con transazioni WOQL condizionate.
- Sonda di mutazione all'head di codice: 9/10 mutanti uccisi; M2 equivalente (il server rifiuta
  l'inserimento concorrente della stessa identità).
- `PRE-CAMPAIGN-GATE` sull'head di codice: 41/42 PASS; `drift` atteso
  (0005, 0050, 0082) prima delle riqualifiche, 0 all'head dell'evidenza.
- Revisione preventiva `OCOR-DEV-REM-0041-63c6d5e8e094-pre` (Antigravity CLI, gemini-4-argon-high, Google):
  `NO_BLOCKING_FINDINGS`, 3 finding consultivi. P1: coordinamento con `REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION`
  registrato (`coordination_with_rem0040`; le operazioni di overlay di `ScenarioOverlayStore` seguono REM-0040 in
  un'unità separata). P2: corretto, con RED (4 casi di divergenza falliti) e GREEN 33/33 ×3; il mutante M10 è ucciso.
  P3: tupla dei tentativi tipizzata, `mypy --strict` sul modulo senza errori.

## Rollback

Revert dei commit di REM-0041: spariscono adapter, servizio, modulo di test e voci dell'allowlist; i record di
riqualifica precedenti tornano i più recenti. Nessun consumer, contratto, port, lock o migrazione coinvolti.
