# OCOR-DEV-REM-0037-RCCAD — suite completa locale in due corsie parallele

- **Status**: `CANDIDATE_AWAITING_INDEPENDENT_VERIFICATION`, ciclo 0.
  Verifier scelto dal loop (fornitore né Anthropic né OpenAI né Google), processo e contesto separati. Implementatori del task:
  Claude Code (Anthropic, `claude-opus-5-5`) e Codex (OpenAI, contato dal loop). Revisore preventivo:
  Antigravity CLI / `gemini-4-argon-high` (Google), escluso dalla verifica finale. Nessun verifier Anthropic,
  OpenAI o Google (`LOOP-IMPLEMENTER-ORDER-AUTH-FALLBACK`, `PRE-CAMPAIGN-REVIEW`, 2026-10-26).
- **Fonte**: `LOCAL-SUITE-SPLIT (2026-10-25)` come riattivata dalla decisione normativa del PO
  `LOCAL-SUITE-SPLIT-REACTIVATION (2026-10-26)`; `LOCAL-SUITE-SPLIT-MEMORY-DEFERRAL (2026-10-27)`;
  `REM-0037-0006-NETWORK-RESIDUE-DISPOSITION (2026-10-28)`, opzione 1; normalizzazione
  del guard secondo la condizione a di `REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26)`.
- **Branch**: `governed/ocor-dev-rem-0037-local-suite-split`; commit di codice `61654ea20771aafe890762b3531840e99ef12031`.

## Modifica

| File | Modifica |
|---|---|
| `scripts/run_local_lane_campaign.py` | orchestratore nuovo e aggiuntivo: importa il supervisore sigillato senza modificarlo; partizione, unione esatta, ammissione di memoria, sandbox delle corsie, runner per corsia, `--execute`, ripiego seriale |
| `reports/tests/test_local_lane_campaign.py` | modulo di guard ermetico dell'orchestratore |
| `reports/assurance/OCOR-DEV-REM-0037-RCCAD/lane_weights.json`, `preimplementation_measurement.json` | pesi per caso dalla misura seriale; misura di memoria e durata prima del codice |
| `.github/workflows/ocor-validation-closure.yml` | il modulo delle corsie aggiunto una volta allo step di guard; nessun altro byte |
| `reports/tests/test_kind_teardown_observation.py` | `normalize_rem0037_workflow` e `Rem0037GuardAdmission` con nove casi negativi; baseline invariate |
| `ocor-runtime/tests/tasks/test_ocor_dev_0006.py` | smontaggio del progetto Compose `ocor-missing-image-negative` (rete compresa) in un blocco `finally` di `test_missing_pinned_image_cannot_fall_back_to_public_pull`; nient'altro |
| `reports/tests/test_rem0037_0006_teardown_scope.py` | guard AST sul modello di REM-0023: unica differenza ammessa rispetto al test sigillato è lo smontaggio esatto |
| `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json` | allowlist dei percorsi esatti e self-hash |

Invariati: `scripts/run_qualifying_campaign.py` e le sue costanti, il controllo dei residui delle corsie (nessuna
deroga o esclusione di reti), codice e test di `ocor-runtime` salvo lo smontaggio autorizzato di 0006, `deploy/`,
`infra/`, parti e timeout della CI, guardia della memoria, comportamento predefinito a stack singolo. L'isolamento
è ottenuto a livello di demone (dockerd e namespace di rete privati per corsia): nessun letterale, porta, endpoint o
nome è cambiato.

## Prova d'equivalenza (stesso head)

- Raccolta: 3243 casi (`c5f8b9a5257d04d6…`).
- Suite seriale: 3243/3243 PASS, zero skip, 3684,968 s.
- Suite in due corsie: 3243/3243 PASS, zero skip, unione esatta
  (mancanti, duplicati, in più: nessuno), 2346,734 s complessivi.
- Stesso insieme di casi: digest d'identità eseguita identico nelle due corse (`545e67f8388a0d2b…`).

| Corsia | Casi | Durata della corsia (s) | Tempo dall'avvio della campagna (s) | Esito |
|---|---|---|---|---|
| 1 | 993 | 1531,441 | 1645,238 | PASS |
| 2 | 2250 | 2225,616 | 2333,692 | PASS |

Stima della partizione: 2218,664, 2218,666 s per corsia senza bootstrap; limite
inferiore 1329,129 s (caso Helm con l'attesa */15).

## Durate e limiti

- Seriale: 3684,968 s; margine calcolato dal tetto di 5400 s: 1715,032 s;
  oltre la notifica di 3600 s: 84,968 s.
- Due corsie (tempo complessivo): 2346,734 s; margine dal tetto di 5400 s:
  3053,266 s; margine dalla notifica di 3600 s: 1253,266 s.
- Risparmio: 1338,234 s (rapporto 1,570). Soglia di decision request (5100 s) non raggiunta.
- Alimentazione: rete elettrica per tutta la campagna (una lettura al minuto).

## Memoria

- Soglia di avvio delle due corsie: 14340,6 MiB (misura prima del codice); guardia invariata a 3000 MiB.
- All'avvio della campagna a due corsie: MemAvailable 24285,7 MiB, modalità `TWO_LANE`.
- Campionamento ogni 5 s: minimo 16762,5 MiB disponibili, occupazione di picco delle due corsie
  7523,2 MiB. La sospensione per memoria (`LOCAL-SUITE-SPLIT-MEMORY-DEFERRAL`) non si applica.

## Inventario e riqualifiche

Inventario prima del codice sullo stack a 15 container e drift al commit di codice: derivano soltanto i record di
`OCOR-DEV-0005`, `0006`, `0050` e `0082`. Nuovi record `.requalified-rem0037` con `supersedes` esplicito dei record
`.requalified-rem0039`; record sigillati invariati. `0005` e `0082` di sola regressione; `0050` sostanziale (punto 3 di
`LOCAL-SUITE-SPLIT-REACTIVATION`, test invariati) e `0006` sostanziale (punto 3 della disposition, test cambiato solo
dallo smontaggio): modulo del task, suite seriale e suite a due corsie dello stesso head.

## Smontaggio del test di 0006

- RED su Docker reale con il test sigillato: il test passa e lascia la rete `ocor-missing-image-negative_default`.
- GREEN con lo smontaggio in `finally`: nessuna rete, container o volume del progetto; anche il percorso di fallimento
  (copia scratch con asserzione invertita) non lascia residui. Guard AST: RED sul file sigillato, GREEN con 11 mutazioni
  rigettate. Fingerprint in `teardown_0006` e nel raw log.
- Le campagne a `b4ddd69` (seriale PASS, due corsie FAIL allo smontaggio della corsia 1) restano storiche e non
  qualificano questo head (`non_qualifying_attempts`).

## Gate e revisione preventiva

- `PRE-CAMPAIGN-GATE` al commit di codice: 44 passi ricavati dai workflow, tutti PASS salvo il drift,
  che elenca esattamente le quattro riqualifiche (attese) ed è 0 all'head dell'evidenza. Il primo gate (`a80037c`) aveva
  rilevato `DYNAMIC_CODE_EXECUTION` nello scanner statico, corretto in `a87c6b4` prima della revisione.
- `PRE-CAMPAIGN-REVIEW`: `OCOR-DEV-REM-0037-61654ea20771-pre`, esito `NO_BLOCKING_FINDINGS`, un finding consultivo, nessun bloccante (sha256
  dell'esito `0fd7e8899019a86bf32c46bb991d56e64b840642b54aa40bca89a556080c0138`). Consultivo P1 accolto prima delle campagne: `uv sync` nel worktree candidato
  (solo ambiente non tracciato, nessun commit).

## TDD

RED prima del codice in ogni unità (partizionatore, ciclo di vita delle corsie, runner per corsia, orchestrazione
`--execute` e sua riparazione, peso allineato all'orologio, collegamento del guard in CI, smontaggio di 0006). Log RED/GREEN nel raw log
(integrali o estratti con sha256 del log completo); commit e fingerprint in `development_history`. Mutation probe
`NOT_EXECUTED`.

## Vincoli rispettati

- `inputs/` intatto; nessun nuovo `DEC-*`; nessun test indebolito; nessun limite, timeout o soglia cambiato.
- La modalità a due corsie è utilizzabile come qualifica soltanto dopo GO indipendente, sigillo e merge.
- `E1=0`, `E2=0`, nessun requisito `Verified`; runtime conformance `NOT_ESTABLISHED`, PoC-GO e Production
  readiness `NO-GO`.

## Sigillo (dopo GO indipendente)

- **Verdetto**: `OCOR-DEV-REM-0037-f08ad7599fc5-0`, `GO_FOR_EVIDENCE_SEAL`, zero finding, nulla `NOT_EXECUTED`
  (file sha256 `4ff1bf638b4c11884d976d0201bfa6849d3f089a4e420dbbeb88574e3bcd56fe`). Verifier: Cursor CLI /
  grok-4.7-high / xAI, contesto separato, shell pulite. Prova di equivalenza del verifier sullo stesso head:
  suite seriale 3243/3243, zero skip, 4252,115 s (652,115 s sopra la notifica di 3600 s; margine calcolato dal tetto
  di 5400 s 1147,885 s, dalla soglia di decision request di 5100 s 847,885 s); suite a due corsie 3243/3243 (993 e
  2250), zero skip, 2325,818 s (margine dal tetto di 5400 s 3074,182 s, dalla notifica di 3600 s 1274,182 s); unione
  esatta, digest delle identità eseguite identico, residui dell'host vuoti. Guard del task 305/305, guard di
  `validation-closure` 362/362, riqualifiche 227/227. Rete elettrica a inizio e fine di entrambe le suite (dato del
  verifier).
- **Allineamento**: HEAD verificato `f08ad75` unito in modo non distruttivo con `origin/main` `9fa7cae`
  (`927e6a9`); cambiano soltanto i tre file di stato, albero non di stato identico.
- **Sigillo**: `OCOR-DEV-REM-0037.json` e le 4 riqualifiche `.requalified-rem0037` (`OCOR-DEV-0005`, `0006`,
  `0050`, `0082`) passano a `SEALED`; i manifest G0, G2 e G5 puntano agli hash sigillati. In
  `OCOR-DEV-REM-0037.json` i `record_sha256` delle riqualifiche restano gli hash candidati verificati; gli hash
  sigillati sono affiancati in `independent_verification.sealed_requalification_records`. Raw log invariati; nessun
  record sigillato precedente modificato.
- **Ruoli**: implementatore e integrazione Claude Code (Anthropic, `claude-opus-5-5`); Codex (OpenAI) contato dal
  loop; revisore preventivo Antigravity/Gemini (Google). Da qui la modalità a due corsie è utilizzabile per la suite
  completa locale, con l'ammissione di memoria all'avvio. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime
  `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
