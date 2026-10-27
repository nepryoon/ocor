# OCOR-DEV-REM-0042-RCCAD — tetto della suite completa locale a 90 minuti

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier richiesto: Cursor CLI / Grok (xAI), processo e contesto separati. Implementatori del task:
  Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal loop). Revisore preventivo:
  Antigravity CLI / `gemini-4-argon-high` (Google), escluso dalla verifica finale. Nessun verifier Anthropic,
  OpenAI o Google (`LOOP-IMPLEMENTER-ORDER-AUTH-FALLBACK`, `PRE-CAMPAIGN-REVIEW`, 2026-10-26).
- **Fonte**: decisioni normative del PO `LOCAL-FULL-SUITE-CAP-90 (2026-10-26)` e
  `LOCAL-FULL-SUITE-CAP-90-AMENDMENT (2026-10-26)`; normalizzazione del guard secondo la condizione a di
  `REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26)`.
- **Branch**: `governed/ocor-dev-rem-0042-full-suite-cap-90`; commit di codice `6ef0c33d23a2af8b61507abbaa8be76336953958`.

## Modifica

| File | Modifica |
|---|---|
| `scripts/run_qualifying_campaign.py` | `FULL_SUITE_LIMIT_SECONDS` da 4500 a 5400 e docstring del modulo «90-minute»; messaggio di scadenza e timeout dell'osservatore seguono la costante |
| `reports/tests/test_qualifying_campaign_guard.py` | solo i due test di confine: 5399/5400/5401 e «90-minute»; rinomino in `test_full_suite_budget_is_90_minutes_and_60_minutes_requires_decision` |
| `reports/tests/test_kind_teardown_observation.py` | `normalize_rem0042_campaign` (costante e docstring, ciascuno esattamente una volta) e `Rem0042GuardAdmission` con 12 casi negativi |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei nove percorsi esatti di questo record e self-hash |

Invariati: notifica oltre 60 minuti (3600 s), parti della CI (2700 s e 1800 s), suite del task a 45 minuti,
timeout dei job della CI, guardia della memoria, baseline `9b4d3be`/`7cd5f7a` e normalizzazioni esistenti,
test, casi, timer, timeout, soglie, partizioni e gate.

## TDD

- RED al commit `fa4721ad9e98ad3e49746d4ebe893701465a0b8b`: 15 failed, 177 passed nei due moduli di guardia, tutti per la costante
  ancora a 4500 (fingerprint `b58c3de133245ea2980b57f30dbc8ae6c9da32acd5f784e1d4db395ad841e5b5`).
- GREEN al commit di codice: moduli di guardia tre volte nella campagna, portfolio dei report, suite completa.
- Mutation probe `NOT_EXECUTED`: l'ammissione è fissata da casi negativi espliciti.

## Inventario e riqualifiche

Inventario in sola lettura al commit di codice: derivano soltanto i record di `OCOR-DEV-0005`, `0050` e `0082`.
Riqualifiche di **sola regressione** (`.requalified-rem0042`, `supersedes` esplicito dei record
`.requalified-rem0038-repair1`), test dei task invariati; nessuna riqualifica sostanziale. Interpretazione
registrata nel record (`normative_interpretations`): la modifica del modulo di guardia è quella prescritta dal
punto 3 dell'AMENDMENT, quindi rientra nell'esenzione del punto 4.

## Gate e revisione preventiva

- `PRE-CAMPAIGN-GATE` al commit di codice: 42 passi ricavati dai workflow, tutti PASS
  salvo il drift, che elenca esattamente le tre riqualifiche (attese) ed è 0 all'head dell'evidenza.
- `PRE-CAMPAIGN-REVIEW`: `OCOR-DEV-REM-0042-6ef0c33d23a2-pre`, esito `NO_BLOCKING_FINDINGS`, zero finding (sha256 dell'esito
  `18b6fbfc4483a283482645b503bca3e28fff00654ec718c7f863f737c39b23a8`).

## Campagna

- Shell pulita (`env -i`, PATH del lock verificato per sha256), `scripts/bootstrap_ci_environment.py --execute
  --timeout 600`, stack a 15 container, 11 servizi tipizzati READY prima e dopo il reset.
- Tentativo `a0` non qualificante: SDK TypeScript non costruito nel worktree del candidato (1 failed, 1 skipped nel
  portfolio dei report). Stack smontato, SDK costruito con node/npm del lock, campagna rieseguita da capo. Mai
  contato come PASS o FAIL.
- Suite completa seriale: 3224/3224, zero skip, unione JUnit esatta, 3964,402 s
  (364,402 s sopra la notifica di 3600 s; margine calcolato dal tetto di 5400 s:
  1435,598 s; rispetto al tetto precedente di 4500 s: 535,598 s).
  Smontaggio con zero residui. Alimentazione: rete elettrica a inizio e fine corsa (una lettura al minuto).

## Vincoli rispettati

- `inputs/` intatto; nessun nuovo `DEC-*`; nessun test indebolito; nessun limite cambiato oltre al tetto autorizzato.
- `E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production
  readiness `NO-GO`.
