# REM-0063-CYCLE12-UNIT-RECORD-INPUTS

Status: `DECIDED_BY_PO`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Decisione che genera lo stop: `REM-0063-CYCLE12-NO-GO (2026-11-19)` opzione 1, commit `60981e9a069327b8ceecfbba7c2c167fdcc8eeba`, sha256 `31e33b67c7025c8cc4811a2a0065969a6ac1234ae5dbdb33cb68a352daf27160`.
Head di campagna misurato: `698b944a1de4ef78a39346a034bed1a5e6fe4b10`.
Head pubblicato dopo il record di quella esecuzione: `aaf98a282f4c6787f1c4753ea86199f2808f7a72` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`.
Commit di comportamento del codice: `da754e862a2c2fba621cf5d4534fcc5396299b6a`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto e perimetro

L'opzione 1 di `REM-0063-CYCLE12-NO-GO` è già attuata per allowlist, settle, otto record `cycle12c` e riallineamento VF-002/VF-004. Quegli otto record non si rifanno. Non c'è un ciclo 13. VF-003 non si corregge. VF-008 non si corregge. Il rifiuto del surrogato isolato di P5 non è applicato.

La stessa opzione dice che, prima di `verify_request.json`, `scripts/check_execution_commit_inputs.py` deve passare su ogni record di evidenza aggiunto dal branch rispetto al merge-base `3c11b6125fc22f4d2af81eca73a4c7503237fff1`, oppure il record deve essere superseduto da un successore distinto dello stesso `task_id` che passa. Se un record aggiunto dal branch fallisce e il suo task non è fra gli otto nominati, ci si ferma e si apre una sola richiesta nuova: non lo si riqualifica in questa unità.

Il gate, la campagna e il controllo distinto sull'HEAD `698b944a1de4ef78a39346a034bed1a5e6fe4b10` sono PASS e non si rilanciano. Il commit `aaf98a282f4c6787f1c4753ea86199f2808f7a72` registra soltanto quei risultati nel record dell'unità. Non cambia `ocor-runtime/src/`, il validatore, `reports/planning/OCOR_PLAN_RUN_STATE.json`, `codegen.py` né gli otto record `cycle12c`.

`verify_request.json` non è scritta.

## Prove

1. PRE-CAMPAIGN-GATE su `698b944a1de4ef78a39346a034bed1a5e6fe4b10`: 51 passi, 0 falliti, 6 `NOT_EXECUTED` (`mandatory-gates`, `integration-postgresql`, `qualifying-campaign-shards`, `fuseki-actions-cache`, `conditional-0049-aggregator`, `auto-merge`), durata sommata 980,622 s. `gates.json` sha256 `d4aa42a981e6bf7ef89113701e45aad4921142f1410043e18d1860cc89c725af`. Log sha256 `21491c8fd8ddf4a048dd1e8f9dda02ad08629269dd41e72c219eca36e48876ef`. Base `3c11b6125fc22f4d2af81eca73a4c7503237fff1`. Inizio 2026-11-19T18:32:25Z, fine 2026-11-19T18:48:47Z.

2. Campagna a quattro corsie `698b944a1de4-1795114196`: PASS, `FULL_SUITE`, 48013 test, 0 fallimenti, 0 errori, 0 skip, 3386,267 s, sotto la notifica di 3600 s. `po_decision_required` false. Residui vuoti. Teardown PASS. Corsie 42187, 972, 2423, 2431. `campaign_result.json` sha256 `20a89114a53724dafc6d8f9b43c5fd2d7d60df968cbf22a3e4a1e164badfe8ff`. Log sha256 `1f6409e8735380365a05cfff461176ffd11308d5d7428e650b9a63735d3af708`. Raccolta sha256 `d8f571fb59d47e07a320f01b59e895e651647110e64125631069d8d2779496e7`. Download residui prima della campagna `100;w=3600`, soglia 95. Alimentazione `MAINS` all'inizio e alla fine. Inizio 2026-11-19T18:49:55Z, fine 2026-11-19T19:46:22Z. Non è un rilancio di `a3bd36d3ab51-1795089861` e non ne trasferisce i conteggi.

3. Controllo distinto `698b944a1de4-1795117669`: PASS, non qualificante, selezione `tests/tasks/test_ocor_dev_0048.py`, `tests/tasks/test_ocor_dev_0005.py`, `tests/tasks/test_ocor_dev_0050.py`, `tests/tasks/test_ocor_dev_0082.py`, 410 test, 0 fallimenti, 0 errori, 0 skip, 374,752 s. Risultato sha256 `fae32cd23d207e049a96331257fbeafd5116888f99e8aa43f4668f726338f340`. Log sha256 `cd99c3913b0d850119dca3f6db98c8936e8bc28aa82aa4d0c999da31eff47baf`. Download residui prima del controllo `100;w=3600`, soglia 50. Non è un rilancio di `a3bd36d3ab51-1795093212`.

4. Sui 38 record sotto `reports/evidence` aggiunti dal branch, `scripts/check_execution_commit_inputs.py` all'HEAD `aaf98a282f4c6787f1c4753ea86199f2808f7a72` dà 8 PASS e 30 FAIL. I FAIL restano confinati a `OCOR-DEV-0005`, `OCOR-DEV-0050`, `OCOR-DEV-0082`, `OCOR-DEV-REM-0037`, `OCOR-DEV-REM-0047`, `OCOR-DEV-REM-0056`, `OCOR-DEV-REM-0062` e `OCOR-DEV-REM-0064`. Ciascuno di quegli otto task ha il record `cycle12c` che passa. Nessun `cycle12c` fallisce. Stdout sha256 `b4d83b91e911ba606f03b47375a3435bc402d5cb00a4ea43ff49fa35c0ab7dc9`. Il rilancio precedente sull'HEAD `698b944a1de4ef78a39346a034bed1a5e6fe4b10` aveva stdout sha256 `2f08ac11699ecd94dfd341432e46c70b29acdf60df1e80dc691fdc5ab7d7f817`.

5. Lo stesso controllo sul record dell'unità `reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json`, con il commit dichiarato dal record `a3bd36d3ab51ba79e5ca8cec795237206c0944ce`, esce 1 sull'HEAD `aaf98a282f4c6787f1c4753ea86199f2808f7a72`. Quattro finding, due percorsi: `reports/planning/OCOR_PLAN_RUN_STATE.json` e `scripts/validate_ocor_development_plan.py`, entrambi «changed between the execution commit and HEAD» e «working tree differs from the execution commit». Sono i file cambiati dall'allowlist `2b8a9c333c95b6a12608fd7973413d5f56e99843` e dal settle `673656f343d7df4fe25ca206fef307a7103dd464`. Il task del record è `OCOR-DEV-REM-0063`, che non è fra gli otto nominati. Non esiste un successore distinto di questo record che passi. Il fallimento c'era già su `698b944a1de4ef78a39346a034bed1a5e6fe4b10`, prima del commit che registra la campagna.

6. `scripts/validate_evidence_input_drift.py` resta PASS: 75 task, 241 input, 0 drift. Il suo ambito è `completed_evidence_tasks` e non vede questo record.

## Quesito

Il record dell'unità fallisce `scripts/check_execution_commit_inputs.py` perché l'allowlist e il settle dell'opzione 1 hanno cambiato due input dopo il commit dichiarato `a3bd36d3ab51ba79e5ca8cec795237206c0944ce`. L'opzione vieta di riqualificare qui un task fuori dagli otto e vieta di scrivere `verify_request.json` finché il controllo non passa o un successore distinto non passa. Come si chiude questo unico scarto, senza rifare gli otto record `cycle12c` e senza un ciclo 13?

## Opzioni

1. **Un solo successore del record dell'unità, poi la verifica.** Si autorizza un solo commit sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`, dopo `aaf98a282f4c6787f1c4753ea86199f2808f7a72`, che non modifica `ocor-runtime/src/`, `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json`, `codegen.py`, gli otto record `cycle12c`, i manifest se non per una voce in append, `inputs/`, i record sigillati, i gate, le soglie o i claim. Il commit rimisura nel record dell'unità soltanto gli hash di input che il controllo trova diversi fra `a3bd36d3ab51ba79e5ca8cec795237206c0944ce` e l'HEAD, e sposta il commit dichiarato su quell'HEAD di misurazione. Gli altri byte di input restano misurati, non copiati. Poi `scripts/check_execution_commit_inputs.py` sul record dell'unità deve uscire 0. I 38 record sotto `reports/evidence` devono restare 8 PASS e 30 FAIL confinati agli stessi otto task. Quindi si scrive `verify_request.json` su quel nuovo HEAD. La campagna `698b944a1de4-1795114196` e il controllo distinto `698b944a1de4-1795117669` non si rilanciano. Non c'è un ciclo 13.

2. **La verifica parte da `aaf98a282f4c6787f1c4753ea86199f2808f7a72` senza un successore.** Si dichiara che il controllo dei 38 record sotto `reports/evidence` è quello richiesto dall'opzione 1 e che il fallimento del record dell'unità sui due file dell'allowlist è l'effetto già deciso, coperto dai successori `cycle12c`, non un task nuovo. Si scrive `verify_request.json` su `aaf98a282f4c6787f1c4753ea86199f2808f7a72`. Nessun file del candidato cambia. Il verifier che riesegue il controllo sul record dell'unità ottiene gli stessi quattro finding.

3. **Nessun file ulteriore e nessuna verifica.** L'HEAD pubblicato resta `aaf98a282f4c6787f1c4753ea86199f2808f7a72`. `OCOR-DEV-REM-0063` resta bloccato su questa richiesta. Non c'è un ciclo 13. La campagna misurata resta un PASS storico di `698b944a1de4ef78a39346a034bed1a5e6fe4b10` e non si rilancia.

## Raccomandazione

Opzione 1. È l'unico modo in cui il record dell'unità passa il controllo sull'HEAD finale senza rifare gli otto record e senza trattare il fallimento come assente. L'opzione 2 consegna al verifier lo stesso FAIL. L'opzione 3 lascia il PASS di campagna senza verifica. Nessuna opzione di questa richiesta è applicata da chi la apre.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CANONICAL-R1-HUMAN-GATE`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Il percorso di questa richiesta non è nell'allowlist del validatore del piano: l'estensione dell'allowlist è un change set a parte e non fa parte di questa pubblicazione. La PR resta bozza e non è un percorso di integrazione.

## Disposition

Decisa per conto del PO, modello `claude-fable-5-2`, effort `max`. Decisione `REM-0063-CYCLE12-UNIT-RECORD-INPUTS (2026-11-19)`. Opzione 1 adottata. Le opzioni 2 e 3 non sono applicate.

Il preambolo `~/.ocor-codex/openhands_preamble.md`, sha256 `59e98012251975769d5b859b926134655b2836d609ba8a438b6cb9f122b3ba7c`, contiene la sezione `## REM-0063-CYCLE12-UNIT-RECORD-INPUTS (2026-11-19) — decisione del PO, su delega completa`. Adotta l'opzione 1 al commit `8eb1d9bbe47a2591084a028c2b6bd6b9379415a1`. Lo sha256 del file a quel commit è `65948d4cf7551df910b3f165d90a13c542e42a8bc4e2b8c682a51a9dc83f90a7`, verificato con `git cat-file -e`, `git merge-base --is-ancestor` e `sha256sum`. Quel commit resta sul branch `origin/governed/decision-request-rem0063-cycle12-unit-record-inputs`. La PR #704 non si integra.

Il commit `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign` ha parent `aaf98a282f4c6787f1c4753ea86199f2808f7a72` e cambia solo `reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json`. Il commit dichiarato del record diventa `aaf98a282f4c6787f1c4753ea86199f2808f7a72`. Gli unici hash rimisurati sono `reports/planning/OCOR_PLAN_RUN_STATE.json` `723af7b47239eace4cb92c51b8e27b3c7101f291893a2a6b51411106e3e06563` e `scripts/validate_ocor_development_plan.py` `f06c2ebc0631d0ad4766d9e8109154fa030f9399501c0c8b79ff8bf37ad831a0`. Gli altri byte di input restano quelli già misurati. Nessun file sotto `ocor-runtime/src/`, nessun `codegen.py`, nessun record `cycle12c`, nessun manifest, nessun input e nessun claim è cambiato.

`scripts/check_execution_commit_inputs.py --execution-commit aaf98a282f4c6787f1c4753ea86199f2808f7a72 --record reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json` esce 0 sull'HEAD `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`: 0 finding, 17 input, stdout sha256 `ed91f1b82b6eaf87b8beaf52653b157f275e7b34ebdc768428ae24b296429f98`. I 38 record sotto `reports/evidence` aggiunti dal branch rispetto al merge-base `3c11b6125fc22f4d2af81eca73a4c7503237fff1`, un'invocazione per record con il commit dichiarato da quel record, restano 8 PASS e 30 FAIL. I FAIL restano confinati a `OCOR-DEV-0005`, `OCOR-DEV-0050`, `OCOR-DEV-0082`, `OCOR-DEV-REM-0037`, `OCOR-DEV-REM-0047`, `OCOR-DEV-REM-0056`, `OCOR-DEV-REM-0062` e `OCOR-DEV-REM-0064`. Lo stdout concatenato ha sha256 `a8092516edeaf07c9ac41e0739fb846a36dc9d385197fe45b23fc26b148b21d8`.

`verify_request.json` è scritta sull'HEAD `2e4a3e51220a35bfec8bbfd93202f52bbaca7f19`, request_id `OCOR-DEV-REM-0063-2e4a3e51220a-12`, sha256 `be95c7b464208e4bd62795f21e1eb8d42af7b8f69dfc69eb375773b433ebc6cf`. La campagna `698b944a1de4-1795114196` e il controllo distinto `698b944a1de4-1795117669` non sono rilanciati. Non c'è un ciclo 13. Il branch di produzione resta `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

Il testo sopra questa sezione, esclusa la riga di stato, resta quello del commit `8eb1d9bbe47a2591084a028c2b6bd6b9379415a1`, sha256 `65948d4cf7551df910b3f165d90a13c542e42a8bc4e2b8c682a51a9dc83f90a7`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo `DEC-*`.
