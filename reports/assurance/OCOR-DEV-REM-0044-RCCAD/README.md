# OCOR-DEV-REM-0044-RCCAD — registro di conformità normativa (unità del registro)

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier scelto dal loop (fornitore né Anthropic né OpenAI), processo e contesto separati. Implementatori del task:
  Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal loop). Revisione preventiva `SKIPPED`
  dal loop: nessun revisore di un fornitore ammesso disponibile (`PRE-CAMPAIGN-REVIEW`, punto 6).
- **Fonte**: `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`, punto 4 (a–g), con l'aggiunta
  `NORMATIVE-CONFORMANCE-PROGRAMME-SUPPLEMENT (2026-10-29)` (registro non ancora su `main`, limite di otto iterazioni)
  e `REM-0043-NCP-SUSPENSION (2026-10-29)`, punto 2.
- **Branch**: `governed/ocor-dev-rem-0044-normative-conformance-register`; commit qualificato `c90b99907f4f67d7a9134dd7c1ce0429592f20a9`.
- Il registro non è evidenza: nessuna voce rende `Verified` un requisito. Claim invariati: `E1=0`, `E2=0`,
  `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo `DEC-*`.

## Contenuto

| File | Modifica |
|---|---|
| `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json` | nuovo registro, 83 voci (sha256 `1b9b0885e19fdb13…`) |
| `reports/tests/test_normative_conformance_register.py` | test d'integrità (punto 4.c e punto 2 dell'aggiunta), unico test nuovo; fuori dalla CI |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti e self-hash |

Invariati: tutto `ocor-runtime/` (codice, test, schemi, `uv.lock`), slice legacy, contratti, ADD, LLD, registri
normativi, backlog, piano di tracciabilità, `deploy/`, lock, workflow, guard, script di campagna, limiti e gate.

## Registro

- Gravità: `HIGH` 59, `LOW` 3, `MEDIUM` 21. Stato: `DECISION_REQUIRED` 8, `OPEN` 73, `REFUTED` 2. Tipo: `CONFLICT` 4, `DIVERGENT` 47, `EXTRA` 3, `MISSING` 29.
- Copertura: elenco iniziale 59/59, elenco integrativo 11/11, osservazioni 6/6.
- `DECISION_REQUIRED`: `NCR-C1-007`, `NCR-C2-008`, `NCR-C3-005`, `NCR-C3-007`, `NCR-C7-002`, `NCR-C7-006`, `NCR-C8-006`, `NCR-LEGACY-001`. `REFUTED`: `NCR-C2-010`, `NCR-C7-007`.
- Piano (4.e): 13 unità `NCP-Uxx` in ordine di dipendenza (NCP-U13 → NCP-U01 → NCP-U02 → NCP-U03 → NCP-U04 → NCP-U06 → NCP-U05 → NCP-U07 → NCP-U08 → NCP-U09 → NCP-U10 → NCP-U11 → NCP-U12), che risolvono
  73 voci `OPEN`; stima 48 iterazioni (dato di pianificazione).
- Proposte (4.f) per `OCOR-DEV-0060`, `OCOR-DEV-0062`, `OCOR-DEV-0063`, `OCOR-DEV-0064`, `OCOR-DEV-0065`, `OCOR-DEV-0066`, `OCOR-DEV-0067`: solo proposte, backlog e piano di tracciabilità invariati.
- Voce di `OCOR-DEV-REM-0043`: `NCR-C8-007`, `OPEN`, blocca OCOR-DEV-0062.
- Voci risolte: nessuna (l'unità del registro non ne risolve; `resolved_register_entries` vuoto).

| Componente | Voci | Gravità | Stato |
|---|---|---|---|
| C1 | 10 | HIGH 7, MEDIUM 3 | DECISION_REQUIRED 1, OPEN 9 |
| C2 | 12 | HIGH 11, LOW 1 | DECISION_REQUIRED 1, OPEN 10, REFUTED 1 |
| C3 | 7 | HIGH 3, MEDIUM 4 | DECISION_REQUIRED 2, OPEN 5 |
| C4 | 3 | HIGH 1, MEDIUM 2 | OPEN 3 |
| C5 | 3 | HIGH 3 | OPEN 3 |
| C6 | 14 | HIGH 11, MEDIUM 3 | OPEN 14 |
| C7 | 7 | HIGH 5, MEDIUM 2 | DECISION_REQUIRED 2, OPEN 4, REFUTED 1 |
| C8 | 7 | HIGH 7 | DECISION_REQUIRED 1, OPEN 6 |
| EVIDENCE | 2 | HIGH 2 | OPEN 2 |
| GOVERNANCE | 1 | MEDIUM 1 | OPEN 1 |
| LEGACY | 1 | LOW 1 | DECISION_REQUIRED 1 |
| MEMORY | 5 | HIGH 3, MEDIUM 2 | OPEN 5 |
| PLAN | 6 | HIGH 5, MEDIUM 1 | OPEN 6 |
| TESTS | 5 | HIGH 1, LOW 1, MEDIUM 3 | OPEN 5 |

## Casi

| Caso | Elemento normativo | Casi passati | Esito |
|---|---|---|---|
| `OCOR-DEV-REM-0044-REGISTER-SCHEMA-IDS-AND-VALUES` | NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29) point 4.b (fields, severity, type, status) and point 4.c first item (schema, unique ids, allowed values); canonical JSON | 12 | PASS |
| `OCOR-DEV-REM-0044-NORMATIVE-ANCHORS-RESOLVE` | NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29) point 4.b (norm_refs, code_refs, test_refs with commit) and point 4.c second item (anchors resolvable at the head) | 6 | PASS |
| `OCOR-DEV-REM-0044-SEED-AND-SUPPLEMENT-COVERAGE` | NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29) point 4.c third item (seed_coverage, 59 distinct ids); NORMATIVE-CONFORMANCE-PROGRAMME-SUPPLEMENT (2026-10-29) point 2 (supplement_coverage, 11 distinct ids) | 6 | PASS |
| `OCOR-DEV-REM-0044-STATUS-RULES` | NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29) point 4.b (blocks / blocks_none_reason rule) and point 4.c fourth to sixth items | 12 | PASS |
| `OCOR-DEV-REM-0044-PLAN-AND-PROPOSALS` | NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29) points 4.e (remediation plan) and 4.f (G6/G7 proposals) | 6 | PASS |
| `OCOR-DEV-REM-0044-RESOLVED-ENTRIES-COMPUTED` | NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29) point 4.c last paragraph and the definition of 'voce risolta' | 3 | PASS |
| `OCOR-DEV-REM-0044-INTEGRITY-TEST-NEGATIVE-CONTROLS` | NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29) point 4.c (the integrity checks must reject a non-conforming register); AGENTS.md (positive and negative cases, rejection for the right reason) | 17 | PASS |
| `OCOR-DEV-REM-0044-VALIDATION-CLOSURE-GUARDS-LOCAL` | NFR-073 | 428 | PASS |
| `OCOR-DEV-REM-0044-STACK-LIFECYCLE` | NFR-073 | 9 | PASS |
| `OCOR-DEV-REM-0044-FULL-SUITE` | NFR-073 | 3334 | PASS |

Il test d'integrità gira tre volte (15 casi e 861 subtest per run).
Controlli negativi: 15 manomissioni del registro, in una worktree di prova fuori dal
candidato, ciascuna rifiutata dal test mirato; registro intatto e ripristinato verdi.

## Suite completa

- Modalità `TWO_LANE` (`scripts/run_local_lane_campaign.py --execute`, ammissione di memoria all'avvio).
- 3334/3334 PASS, zero skip, unione JUnit uguale alla raccolta
  (`aece5d924b34d44e…`).
- Durata complessiva 2445,122 s; margine dal tetto di 5400 s: 2954,878 s;
  margine dalla notifica di 3600 s: 1154,878 s.
  Soglia di decision request (5100 s) non raggiunta.
- Memoria: MemAvailable all'avvio 25081,3 MiB, minimo 18980,6 MiB;
  guardia di 3000 MiB rispettata.
- Alimentazione: rete elettrica per tutta la campagna (una lettura al minuto).

| Corsia | Casi | Durata della corsia (s) | Tempo dall'avvio della campagna (s) | Esito |
|---|---|---|---|---|
| 1 | 1028 | 1874,113 | 1989,957 | PASS |
| 2 | 2306 | 2300,930 | 2434,347 | PASS |

## Riqualifiche

| Task | Record | Supersede | Tipo |
|---|---|---|---|
| `OCOR-DEV-0005` | `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0044.json` | `OCOR-DEV-0005-requalified-rem0041-overlay-621c0a41ffe1` | sola regressione |
| `OCOR-DEV-0050` | `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0044.json` | `OCOR-DEV-0050-requalified-rem0041-overlay-621c0a41ffe1` | sola regressione |
| `OCOR-DEV-0082` | `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0044.json` | `OCOR-DEV-0082-requalified-rem0041-overlay-621c0a41ffe1` | sola regressione |

`0005`, `0050` e `0082` hanno fra gli input `scripts/validate_ocor_development_plan.py` (allowlist): sola regressione,
come prevede il punto 4.g. Test invariati; record sigillati intatti; inserimenti chirurgici nei `MANIFEST.json`.

## Gate e revisione preventiva

- `PRE-CAMPAIGN-GATE` sul commit qualificato: 41/42 PASS; `drift` atteso
  (0005, 0050, 0082) prima delle riqualifiche, 0 all'head dell'evidenza.
- Revisione preventiva `OCOR-DEV-REM-0044-775bc07408b1-pre`: `SKIPPED` (nessun revisore disponibile di fornitore diverso dagli implementatori (claude,codex) e dal verifier previsto (cursor)). Il commit qualificato differisce
  dall'head revisionato solo per il merge non distruttivo di `origin/main` (i tre file di stato).

## Rollback

Revert dei commit di REM-0044: spariscono registro, test d'integrità e voci dell'allowlist; i record precedenti di
0005, 0050 e 0082 tornano i più recenti. Nessun codice di runtime, consumer, contratto, lock o migrazione coinvolti.
