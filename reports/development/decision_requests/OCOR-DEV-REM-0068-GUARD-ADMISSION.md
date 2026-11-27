# OCOR-DEV-REM-0068-GUARD-ADMISSION

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`.

Una sola domanda, di livello normativo: come si ammette, nel proof di byte
`bytes-82b71d0`, il solo comando che il contratto di `OCOR-DEV-REM-0068` aggiunge
a `.github/workflows/ocor-tooling-bootstrap.yml`. La baseline
`82b71d0db410bcdb8124e8ec8a8235631ecfa1fa` non si sposta in nessuna opzione.
Nessun limite, timeout, finestra, cadenza, timer, partizione o selezione di casi
cambia. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
PoC e Production `NO-GO`. Nessun nuovo `DEC-*`.

## Contesto

`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` punto 9 fissa il proof corrente di
`reports/tests/test_kind_teardown_observation.py` come identità di byte con
`82b71d0`. Il testo del proof dice che una differenza futura richiede una
normalizzazione esatta su quella baseline, autorizzata da una decisione del PO,
oppure un nuovo consolidamento deciso dal PO. La condizione a di
`REM-0038-CAMPAIGN-GUARD-ADMISSION (2026-10-26)` autorizza quello schema senza
una nuova richiesta solo per `OCOR-DEV-REM-0042`, `0039`, `0040` e `0041`.
`OCOR-DEV-REM-0068` non è nell'elenco. `PRE-CAMPAIGN-GATE (2026-10-26)` punto 4
e il divieto di indebolire un test per ottenere il verde escludono di cambiare
il proof dentro il gate.

Il contratto rivisto di `OCOR-DEV-REM-0068` richiede, nella fase di codice, un
solo comando nello step di drift già presente:
`ocor-runtime/.venv/bin/python scripts/validate_current_evidence_head.py --root .`,
accanto al comando di drift invariato. Nessun altro edit del workflow.

## Fatti

Misurati sul branch `governed/ocor-dev-rem-0068-current-head`, HEAD
`47dc7e06fbbc232b190eee4b224dc1c0e94d79ef`, merge-base con `origin/main`
`23e6b62c36627de91cb85329b9a1164f3219cd53`. Il commit `1e36db6b780746c25882849d40bb153a1c1323a4`
restringe i tipi del parser (`remaining_head` a `str`, filtro dei manifest tenuto
come lista). Il commit `47dc7e06` aggiorna solo il pin di
`reports/assurance/OCOR-DEV-REM-0068-RCCAD/OCOR-DEV-REM-0068.json`. Implementatore:
Grok Build, `grok-4.7`, xAI.

1. Su `origin/main` `23e6b62c` il workflow di tooling è byte-identico a `82b71d0`.
   L'unico delta del branch è questo blocco, al posto della riga unica
   `run: ocor-runtime/.venv/bin/python scripts/validate_evidence_input_drift.py --root .`:

   ```yaml
         run: |
           ocor-runtime/.venv/bin/python scripts/validate_evidence_input_drift.py --root .
           ocor-runtime/.venv/bin/python scripts/validate_current_evidence_head.py --root .
   ```

2. `PRE-CAMPAIGN-GATE` su `47dc7e06` (uscita
   `~/.ocor-codex/ocor-dev-rem-0068/pregate-47dc7e06/gates.json`, avvio
   `2026-11-27T18:02:06Z`, fine `2026-11-27T18:02:55Z`): un solo fallimento non
   atteso, `guards`. `reports/tests/test_kind_teardown_observation.py`: 5 failed,
   624 passed, 94 subtests passed, 39.89s. I cinque casi sono
   `Rem0038GuardAdmission`, `Rem0042GuardAdmission` e `Rem0037GuardAdmission`
   (delta esatto ammesso) e `GuardBaselineConsolidation` (proof corrente e albero
   di lavoro). Messaggio: `Byte drift from 82b71d0: .github/workflows/ocor-tooling-bootstrap.yml`,
   proof `bytes-82b71d0`. `mypy` PASS. Drift PASS, 75 task, zero input drift.
   `scripts/check_execution_commit_inputs.py` PASS sul record dell'unità con
   commit di esecuzione `1e36db6b` e sui tre record di riqualifica con commit
   `8f52865f2277e05236b3f820285ca3fad22c91ea`. VF-004 resta `NOT_CORRECTED`, non
   `PASS`. Albero pulito. La suite completa non è stata avviata. Nessuna
   `prereview_request.json`.

3. Fra i task di `completed_evidence_tasks`, le teste selezionate da
   `select_most_recent` che fissano `reports/tests/test_kind_teardown_observation.py`
   all'hash `a66158bb1d1f42c13abf4aed1a58a1a99191156edde328b090a15f923d6607b4` sono
   solo `OCOR-DEV-0005` (`OCOR-DEV-0005-requalified-rem0068-8f52865f2277`) e
   `OCOR-DEV-0050` (`OCOR-DEV-0050-requalified-rem0068-8f52865f2277`).
   `OCOR-DEV-0082` non fissa quel file. Nessuna testa selezionata di quei 75 task
   fissa il workflow. `OCOR-DEV-REM-0038` non è in `completed_evidence_tasks`.

4. I proof storici (`bootstrap_probe_proof`, `observation_only_proof`) leggono il
   contenuto di `82b71d0`, non l'albero di lavoro. Su questo HEAD non falliscono.
   Fallisce solo il proof corrente, che legge l'albero di lavoro.

## Opzioni

1. Ammettere il delta esatto nel solo proof corrente, senza spostare `82b71d0`.
   In `reports/tests/test_kind_teardown_observation.py` una normalizzazione
   sostituisce, una sola volta e con conteggio verificato, il blocco del fatto 1
   con la riga unica di `82b71d0`, e solo in
   `.github/workflows/ocor-tooling-bootstrap.yml`. Il comando
   `validate_current_evidence_head.py` occorre una sola volta. Dopo la
   sostituzione i byte coincidono con `82b71d0`. Manca il blocco, il blocco è
   duplicato o alterato, oppure resta qualunque altro byte: il proof fallisce.
   I casi negativi già presenti restano. Si aggiungono casi sul testo reale del
   workflow: comando assente, duplicato, riscritto, spostato, o presente in un
   altro workflow. Non si toccano supervisore, osservatore, altri workflow,
   limiti e timeout. Sul branch di codice seguono le riqualifiche di sola
   regressione di `OCOR-DEV-0005` e `OCOR-DEV-0050`, perché fissano il file del
   proof. `OCOR-DEV-0082` non si riqualifica per questo file. Poi
   `PRE-CAMPAIGN-GATE` sull'HEAD nuovo e, solo a gate passato, la revisione
   preventiva. Questo file resta su questo branch: non entra nel branch di codice
   e non modifica `scripts/validate_ocor_development_plan.py`.

2. Togliere il comando dal workflow e non eseguirlo in CI. Il proof di byte torna
   verde senza modificare il test. Il contratto rivisto, che chiede quel comando
   nello step di drift, non è soddisfatto. Lo script resta eseguibile in locale.

3. Non ammettere il delta e non togliere il comando. Il proof resta rosso, la
   revisione preventiva e la campagna di `OCOR-DEV-REM-0068` non partono, e la
   baseline si rivaluta solo con un consolidamento deciso a parte dopo il merge.

## Raccomandazione

Opzione 1.

## Impatto

- Si blocca la revisione preventiva e la campagna di `OCOR-DEV-REM-0068` fino
  alla decisione. Nessun altro task si blocca. `OCOR-DEV-REM-0060` non parte.
- L'opzione 1 cambia il proof e richiede le due riqualifiche del punto 1.
  L'opzione 2 contraddice il contratto già rivisto. L'opzione 3 lascia l'unità
  ferma.
- `scripts/validate_ocor_development_plan.py` e
  `reports/planning/OCOR_PLAN_RUN_STATE.json` non cambiano in questo commit. Il
  validatore del piano non ammette ancora questo percorso: il file entra
  nell'allowlist con il change set che applica la decisione, non prima.
- Claim invariati. VF-004 non si segna `PASS`.
