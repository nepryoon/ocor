# REM-0063-CYCLE12-NO-GO

Stato: `OPEN_PO_DECISION_REQUIRED`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Verdetto: `OCOR-DEV-REM-0063-2beef60219ae-12`, esito `NO_GO`, sha256 `1ccbbc852f3a75227b473e4ea379641bb4f62e98939bc49d0f7771f63519bd04`.
Head verificato: `2beef60219ae83be6916f1c31cfd79a345cf9c1d` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`.
Commit di comportamento del codice: `da754e862a2c2fba621cf5d4534fcc5396299b6a`.
Impronta del validatore del piano su quell'HEAD: `a284aa5fa5127181ab40158c892a207c70256925835ed835f6bc3115a66166cc`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto e perimetro

`REM-0063-CYCLE11-NO-GO (2026-11-18)` opzione 1 ha autorizzato un solo ciclo, registrato come `repair_cycle` 12. La stessa opzione dice che dopo un `NO_GO` di questo ciclo non c'è un ciclo 13: si apre una sola richiesta nuova. Questa è quell'unica richiesta. Finché è aperta il candidato non si modifica, non si integra e non si sigilla. Non si apre un `repair_cycle` 13.

`REM-0063-CYCLE12-REGRESSION-DRIFT (2026-11-19)` opzione 1 è attuata: commit di allowlist `9d4c552041bb98122c655269e6ace44d38433840`, quattro record di sola regressione, `validate_evidence_input_drift.py` PASS. Quell'opzione non nomina i record step7b di `OCOR-DEV-REM-0037`, `OCOR-DEV-REM-0047`, `OCOR-DEV-REM-0056` e `OCOR-DEV-REM-0064`. Il `required_fix` del finding bloccante chiede di fermarsi e di aprire questa richiesta, non di riqualificarli senza una decisione.

La campagna `a3bd36d3ab51-1795089861` sull'HEAD `a3bd36d3ab51ba79e5ca8cec795237206c0944ce` è PASS: quattro corsie, 48013 test, 0 fallimenti, 0 errori, 0 skip, 3324,281 s. Il controllo distinto `a3bd36d3ab51-1795093212` è PASS, 410 test. Il PRE-CAMPAIGN-GATE su quello stesso head è PASS: 51 passi, 0 falliti, 6 `NOT_EXECUTED`, 946,087 s. Il record di campagna è `2beef60219ae83be6916f1c31cfd79a345cf9c1d`. Queste esecuzioni restano storiche: non sono il PASS di un HEAD successivo. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` restano FAIL e non sono un PASS.

Implementatori già dichiarati dell'unità, da riportare in ogni richiesta successiva: Grok Build `grok-4.7` (xAI) per il ciclo originale, le riparazioni 1–6, il completamento del ciclo 8, il ciclo 9, il codice e il candidato del ciclo 10, il ciclo 11, il ciclo 12 e questa richiesta; Codex CLI `deepseek-flash` e `deepseek-v4-pro` (DeepSeek) per i cicli 7 e 8; Codex `gpt-6.1-sol` (OpenAI) per la fase A del ciclo 10. Verifier di questo verdetto: Claude Code, `claude-opus-5-5`, Anthropic, effort `max`. Revisore preventivo del ciclo 12: Claude Code, `claude-fable-5-2`, Anthropic, effort `max`, stesso fornitore del verifier e modello diverso, limite autorizzato da `VERIFIER-CLAUDE-REM0063 (2026-11-16)`. Nessun implementatore Anthropic.

## Prove

Finding bloccante, sull'HEAD `2beef60219ae83be6916f1c31cfd79a345cf9c1d`.

| ID | Gravità | Classe | Fatto |
| --- | --- | --- | --- |
| VF-001 | high | evidenza, teste correnti fuori da `completed_evidence_tasks` | `scripts/check_execution_commit_inputs.py` fallisce sui quattro record step7b di commit `30034095fbe8a76fa483cc09215d22b295f16e15`: `OCOR-DEV-REM-0037-requalified-rem0063-step7b-30034095fbe8`, `OCOR-DEV-REM-0047-requalified-rem0063-step7b-30034095fbe8`, `OCOR-DEV-REM-0056-requalified-rem0063-step7b-30034095fbe8`, `OCOR-DEV-REM-0064-requalified-rem0063-step7b-30034095fbe8`. Nessun successore li supersede. Gli input divergenti sono `scripts/validate_ocor_development_plan.py` (hash registrato `c210364d7dda6ac4739e1fbd89de868ce4f6b83d46b1bc767e86f082ac2024dd`, cambiato da `43fdba6d` e `9d4c5520`) e `reports/planning/OCOR_PLAN_RUN_STATE.json` (hash registrato `3ce861b6b3a396a80e8ba5bb22962beb290d5aa5e66dc1946dab7f08ffe65553`, cambiato da `43fdba6d` e `a3bd36d3`). Per `OCOR-DEV-REM-0047` diverge anche `ocor-runtime/src/ocor_runtime/c1/codegen.py` (cambiato da `b1cd0832` e `da754e86`). Sull'HEAD del ciclo 11 gli stessi record passavano. `validate_evidence_input_drift.py` non li vede: il suo ambito è `completed_evidence_tasks`. I quattro record del ciclo 12 che quello script vede passano: `OCOR-DEV-0005`, `OCOR-DEV-0050`, `OCOR-DEV-0082` `cycle12` e `OCOR-DEV-REM-0062` `cycle12b`, commit di esecuzione `9d4c552041bb98122c655269e6ace44d38433840`, validatore `a284aa5f`. Quei quattro citano il validatore e non citano `OCOR_PLAN_RUN_STATE.json`. |

Finding non bloccanti dello stesso verdetto, non corretti da questa pubblicazione: VF-002 (manca la riga di autocontrollo di `assert_walkable_schema_resource` e alcune motivazioni citano ancora `_mcp_bounds`), VF-003 (collisione preesistente di `component_name`, già tracciata e non corretta come prevede l'opzione 1 punto 7 di `REM-0063-CYCLE11-NO-GO`), VF-004 (il record non descrive l'HEAD finale: disposition di P3 e P5, stato di `REM-0063-CYCLE12-REGRESSION-DRIFT`, puntatore del record di regressione, precheck dell'allowlist, scansione dei ruoli).

## Quesito

Come si chiudono le teste correnti step7b di `OCOR-DEV-REM-0037`, `OCOR-DEV-REM-0047`, `OCOR-DEV-REM-0056` e `OCOR-DEV-REM-0064`, quando l'opzione 1 già adottata non le nomina e ogni percorso nuovo di allowlist cambia di nuovo l'impronta del validatore citata dai quattro record del ciclo 12?

## Opzioni

1. **Otto record di sola regressione su un'impronta congelata, più il controllo di ogni record aggiunto dal branch.** Raccomandata. È la chiusura completa del finding bloccante e della cascata che il commit di allowlist produce. Non è un ciclo 13 e non modifica codice sotto `ocor-runtime/src/`. Parte dall'HEAD `2beef60219ae83be6916f1c31cfd79a345cf9c1d` con commit nuovi, senza rebase, reset o force-push. Il parent del commit di allowlist deve avere ancora lo sha256 `a284aa5fa5127181ab40158c892a207c70256925835ed835f6bc3115a66166cc` di `scripts/validate_ocor_development_plan.py`. Se è diverso, ci si ferma e non si inventa un'altra modifica dell'allowlist.

   L'unico cambiamento del commit di allowlist sono esattamente questi sedici percorsi, e nessun altro:

   - `reports/evidence/G2/OCOR-DEV-REM-0037.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0037.requalified-rem0063-cycle12c.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0047.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0047.requalified-rem0063-cycle12c.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0056.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0056.requalified-rem0063-cycle12c.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0064.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0064.requalified-rem0063-cycle12c.log`
   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12c.log`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12c.log`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12c.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0062.requalified-rem0063-cycle12c.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0062.requalified-rem0063-cycle12c.log`

   I quattro record `cycle12` e `cycle12b` citano il validatore `a284aa5f` e diventano stantii quando l'allowlist cambia. Vanno superseduti, non riscritti. I quattro step7b vanno superseduti perché sono le teste correnti che falliscono. Se il validatore del piano riscrive soltanto l'hash in `reports/planning/OCOR_PLAN_RUN_STATE.json`, quel settle è il commit successivo e non cambia i byte del validatore. Gli otto record si misurano sull'HEAD congelato dopo allowlist e settle. Il commit di esecuzione è quell'HEAD. Si rimisura ogni hash di input: non si copia un hash senza misurarlo. I manifest ricevono solo voci nuove in append. `select_most_recent` deve scegliere gli otto record nuovi. I record superseduti restano byte-identici. I comandi pytest sono quelli già registrati nel record superseduto di ciascun task, con skip zero e log nuovi. I quattro record REM rimisurano anche `reports/planning/OCOR_PLAN_RUN_STATE.json` e, per `OCOR-DEV-REM-0047`, `codegen.py`.

   Prima di `verify_request.json` si esegue `scripts/check_execution_commit_inputs.py` su ogni record di evidenza aggiunto dal branch rispetto al merge-base con `origin/main`. Ciascuno passa sull'HEAD finale, oppure il suo `record_id` è superseduto da un record distinto dello stesso `task_id` che passa. Comando, HEAD e sha256 dello stdout stanno nel record dell'unità. `scripts/validate_evidence_input_drift.py` non si modifica e il suo ambito resta `completed_evidence_tasks`. Se un record aggiunto dal branch fallisce e il suo task non è fra gli otto nominati, ci si ferma e si apre una sola richiesta nuova: non lo si riqualifica qui.

   Nello stesso ciclo di evidenza, e solo nel record `reports/assurance/OCOR-DEV-REM-0063-RCCAD/OCOR-DEV-REM-0063.json`, si riallineano VF-002 e VF-004: riga di `assert_walkable_schema_resource`, inventario e scansione delle celle sull'HEAD di codice `da754e862a2c2fba621cf5d4534fcc5396299b6a`, motivazioni che non citano più `_mcp_bounds`, disposition di P3 e P5, stato dell'opzione 1 di `REM-0063-CYCLE12-REGRESSION-DRIFT`, puntatore al record `cycle12c` di `OCOR-DEV-REM-0062`, precheck dell'allowlist con i sedici percorsi e scansione dei ruoli con l'HEAD del record finale. Quel commit non cambia il validatore, `OCOR_PLAN_RUN_STATE.json` né `codegen.py`. VF-003 non si corregge. Il registro di conformità non riceve la voce. Non c'è una seconda revisione preventiva.

   Poi, e solo poi: `PRE-CAMPAIGN-GATE`, la campagna a quattro corsie, il controllo distinto e la richiesta di verifica, sull'HEAD finale. La campagna `a3bd36d3ab51-1795089861` non si rilancia e non trasferisce conteggi. I record non si rifanno se la campagna non entra nell'iterazione. Il branch di produzione resta fermo. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

   Accettazione: il diff dell'allowlist rispetto a `a284aa5fa5127181ab40158c892a207c70256925835ed835f6bc3115a66166cc` è esattamente le sedici stringhe; gli otto record nuovi sono le teste scelte da `select_most_recent`; `check_execution_commit_inputs.py` passa su ogni record aggiunto dal branch o sul suo successore distinto; nessun file sotto `ocor-runtime/src/` cambia; nessun record sigillato è riscritto; nessun test, gate, soglia o claim cambia.

   Costo: due iterazioni di implementazione dopo la decisione. La prima è il commit di impronta, l'eventuale settle, gli otto record e il riallineamento del record dell'unità. La seconda è il gate, la campagna, il controllo distinto e la richiesta di verifica, poi la verifica indipendente.

2. **Decisione di ambito: i quattro step7b restano fuori dal controllo.** Non si estende l'allowlist e non si scrivono record. Si dichiara che `validate_evidence_input_drift.py`, limitato a `completed_evidence_tasks`, è l'unico controllo di deriva e che i quattro step7b non vi rientrano. Le teste correnti restano FAIL per `check_execution_commit_inputs.py`. Il verifier che riesegue quel controllo ottiene di nuovo VF-001. VF-002 e VF-004 restano aperti. Costo: zero iterazioni di evidenza. La classe resta aperta. Non raccomandata.

3. **Nessun file cambia.** L'HEAD resta `2beef60219ae83be6916f1c31cfd79a345cf9c1d`. `OCOR-DEV-REM-0063` resta bloccato su questa richiesta. Non c'è un ciclo 13. Costo: zero. Il `NO_GO` resta senza chiusura. Non raccomandata.

## Raccomandazione

Opzione 1. Chiude le quattro teste che il verdetto ha trovato in deriva e i quattro record del ciclo 12 che la nuova impronta renderebbe stantii, con un solo commit di allowlist nominato prima dei record. Aggiunge il controllo sul perimetro che il verifier ha già rieseguito, senza allargare `validate_evidence_input_drift.py` a record che questa richiesta non nomina. Riallinea il record dell'unità sui finding non bloccanti di evidenza, senza toccare il codice. L'opzione 2 lascia le teste correnti in FAIL e la verifica successiva riproduce VF-001. L'opzione 3 non chiude il `NO_GO`. Nessuna opzione di questa richiesta è applicata da chi la apre.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CANONICAL-R1-HUMAN-GATE`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.
