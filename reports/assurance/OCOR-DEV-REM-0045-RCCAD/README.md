# OCOR-DEV-REM-0045-RCCAD — consolidamento della baseline del guard d'invarianza

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier scelto dal loop (fornitore né Anthropic né OpenAI), processo e contesto separati. Implementatore del task:
  Claude Code (Anthropic, `claude-opus-5-5`), implementatore di riserva della rotazione.
- **Fonte**: `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, punto 9: decision request
  `REM-0038-GUARD-BASELINE-CONSOLIDATION`, **opzione 1**. Non è un'unità del programma di conformità: la modifica del
  guard è autorizzata dalla decisione stessa; il registro non cambia.
- **Branch**: `governed/ocor-dev-rem-0045-guard-baseline-consolidation`; commit qualificato `1a98c1f89c060dbc3f9d62b734d4dda245c9c51d`.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo `DEC-*`.

## Contenuto

| File | Modifica |
|---|---|
| `reports/tests/test_kind_teardown_observation.py` | un solo proof corrente (`bytes-82b71d0`): ogni workflow e il supervisore byte-identici a `82b71d0`, stesso insieme di workflow, costanti dell'osservatore come a `82b71d0`, timeout delle sonde `{10}`; catena storica congelata su `git show 82b71d0`; 34 casi negativi ridiretti e nuove sonde |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti e self-hash |
| tre decision request decise dal PO | importate byte-identiche dai loro branch (punto 12 della decisione) |

Invariati: workflow, `scripts/run_qualifying_campaign.py`, `scripts/observe_kind_teardown.py`, tutto `ocor-runtime/`,
contratti, schemi, ADD, LLD, registri normativi, registro di conformità, `deploy/`, lock, limiti, finestre, cadenze e gate.

| Decision request | sha256 | Identica a |
|---|---|---|
| `reports/development/decision_requests/NORMATIVE-CONFORMANCE-PLAN.md` | `2859bbc42c8d5e6d…` | `origin/governed/decision-request-normative-conformance-plan` |
| `reports/development/decision_requests/OCOR-DEV-0060-BA-RUNTIME-GAPS.md` | `83d32410bfed5377…` | `origin/governed/decision-request-ocor-dev-0060-ba-runtime-gaps` |
| `reports/development/decision_requests/REM-0038-GUARD-BASELINE-CONSOLIDATION.md` | `d9b086ee1b8f9c87…` | `origin/governed/decision-request-rem0038-guard-consolidation` |

## TDD

- RED `56bb7bc`: `4 failed, 51 passed, 84 subtests passed in 3.99s` — ricollocazioni della costante e dei segnaposto di REM-0038, commento in
  coda e workflow aggiunto erano accettati dalla catena di normalizzazioni. Fingerprint `213a36709cf1`.
- GREEN `b689e8c`; task suite eseguita tre volte nella campagna (89 casi e 94 subtest per run).
- Sonda di mutazione: 6 mutanti del proof corrente, tutti uccisi oltre la baseline M0 (0 falliti), in una worktree di prova fuori dal candidato.

## Casi

| Caso | Elemento normativo | Casi passati | Esito |
|---|---|---|---|
| `OCOR-DEV-REM-0045-SINGLE-BASELINE-BYTE-IDENTITY` | NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 9; reports/development/decision_requests/REM-0038-GUARD-BASELINE-CONSOLIDATION.md option 1, first item (single current proof: every workflow and the supervisor byte-identical to 82b71d0, workflow set equal, observer constants against 82b71d0, probe timeouts {10}) and fact 6 (relocation and comment probes now rejected) | 27 | PASS |
| `OCOR-DEV-REM-0045-NEGATIVE-CASES-RETARGETED` | NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 9; reports/development/decision_requests/REM-0038-GUARD-BASELINE-CONSOLIDATION.md option 1, third item (the 34 negative cases kept and retargeted on the current proof: 8 + 5 of REM-0038, 12 of REM-0042, 9 of REM-0037) | 27 | PASS |
| `OCOR-DEV-REM-0045-FROZEN-HISTORICAL-CHAIN` | NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 9; reports/development/decision_requests/REM-0038-GUARD-BASELINE-CONSOLIDATION.md option 1, second item (normalisations 1-7 and DropExport/DiagnosticsOnly no longer applied to the working tree, frozen in a historical test run on git show 82b71d0) | 12 | PASS |
| `OCOR-DEV-REM-0045-OBSERVER-BEHAVIOUR-UNCHANGED` | NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 9 (supervisor, observer and workflows unchanged) | 105 | PASS |
| `OCOR-DEV-REM-0045-REM0034-REGISTRY-GUARD` | decision of the PO of 2026-10-15 (REM-0034 sealed synthetic secret registry), run with the guard module because it shares the historical workflow guard | 96 | PASS |
| `OCOR-DEV-REM-0045-MUTATION-PROBE` | NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 9; AGENTS.md (positive and negative cases, rejection for the right reason) | 7 | PASS |
| `OCOR-DEV-REM-0045-VALIDATION-CLOSURE-GUARDS-LOCAL` | PO REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26), condition b; PRE-CAMPAIGN-GATE (2026-10-26) | 437 | PASS |
| `OCOR-DEV-REM-0045-STACK-LIFECYCLE` | VERIFIER-ENV-STANDARD-BOOTSTRAP (2026-10-23), VERIFIER-ENV-CLEAN-SHELL (2026-10-24) | 9 | PASS |
| `OCOR-DEV-REM-0045-FULL-SUITE` | NORMATIVE-CONFORMANCE-PLAN (2026-10-30) point 9 (full cycle); LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26) point 7; LOCAL-FULL-SUITE-CAP-90 (2026-10-26); REM-0037-0006-NETWORK-RESIDUE-DISPOSITION (2026-10-28) point 4 (lane residue check clean, no allowlist or exclusion) | 3334 | PASS |

## Suite completa

- Modalità `TWO_LANE` (`scripts/run_local_lane_campaign.py --execute`, ammissione di memoria all'avvio).
- 3334/3334 PASS, zero skip, unione JUnit uguale alla raccolta
  (`aece5d924b34d44e…`).
- Durata complessiva 2445,579 s; margine dal tetto di 5400 s: 2954,421 s;
  margine dalla notifica di 3600 s: 1154,421 s.
  Soglia di decision request (5100 s) non raggiunta.
- Memoria: MemAvailable all'avvio 23809,2 MiB, minimo 15025,0 MiB;
  guardia di 3000 MiB rispettata.
- Alimentazione: rete elettrica per tutta la campagna (una lettura al minuto).

| Corsia | Casi | Durata della corsia (s) | Tempo dall'avvio della campagna (s) | Esito |
|---|---|---|---|---|
| 1 | 1028 | 1514,972 | 1640,302 | PASS |
| 2 | 2306 | 2306,259 | 2432,251 | PASS |

## Riqualifiche

| Task | Record | Supersede | Tipo |
|---|---|---|---|
| `OCOR-DEV-0005` | `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0045.json` | `OCOR-DEV-0005-requalified-rem0044-c90b99907f4f` | sola regressione |
| `OCOR-DEV-0050` | `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0045.json` | `OCOR-DEV-0050-requalified-rem0044-c90b99907f4f` | sola regressione |
| `OCOR-DEV-0082` | `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0045.json` | `OCOR-DEV-0082-requalified-rem0044-c90b99907f4f` | sola regressione |

`0005` e `0050` hanno fra gli input il modulo del guard e l'allowlist, `0082` l'allowlist: sola regressione, come
prevede il punto 9. Test invariati; record sigillati intatti; inserimenti chirurgici nei `MANIFEST.json`.

## Gate e revisione preventiva

- `PRE-CAMPAIGN-GATE` sul commit qualificato: 42/43 PASS; `drift` atteso
  (0005, 0050, 0082) prima delle riqualifiche, 0 all'head dell'evidenza.
- Revisione preventiva `OCOR-DEV-REM-0045-bc1f4e699c0d-pre` (sha256 dell'esito `911cad2120225339…`): revisore di riserva
  Codex CLI (OpenAI, `GPT-6`), esito `NO_BLOCKING_FINDINGS`, nessun finding.
  Limite d'indipendenza: implementatore principale nominale del loop, non avviato su questo task. Il commit qualificato
  differisce dall'head revisionato solo per il merge non distruttivo di `origin/main` (i tre file di stato).

## Rollback

Revert dei commit di REM-0045: il guard torna ai due proof storici con la catena di normalizzazioni; spariscono le voci
dell'allowlist e i file delle decision request; i record precedenti di 0005, 0050 e 0082 tornano i più recenti.
Nessun codice di runtime, consumer, contratto, lock o migrazione coinvolti.
