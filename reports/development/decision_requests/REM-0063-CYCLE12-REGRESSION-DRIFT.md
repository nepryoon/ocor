# REM-0063-CYCLE12-REGRESSION-DRIFT

Status: `DECIDED_BY_PO`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Revisione preventiva: `OCOR-DEV-REM-0063-49fc2d1adf0b-pre`, esito `BLOCKING_FINDINGS`, head rivisto `49fc2d1adf0b5fa5107087675264addf4279002f`, sha256 dell'esito `ae501632a3a46ae5e17dca796f16a5c10878054c3b9bff3d0571a7cf2b59f8e0`.
HEAD di comportamento del codice: `da754e862a2c2fba621cf5d4534fcc5396299b6a` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto

L'opzione 1 di `REM-0063-CYCLE11-NO-GO (2026-11-18)` è adottata, insieme all'opzione 1 di `REM-0063-CYCLE12-JSON-DEPTH (2026-11-19)` e all'opzione 1 di `REM-0063-CYCLE12-VISIT-KEY (2026-11-19)`. La frase letterale sulla chiave di visita senza identità del registro non è applicata: la chiave resta `(nodo, base, identità del registro)`. P1 e P2 della revisione `OCOR-DEV-REM-0063-49fc2d1adf0b-pre` sono già corretti su `da754e862a2c2fba621cf5d4534fcc5396299b6a`. P5 non è applicato. VF-008 non si corregge. Non c'è un ciclo 13.

P3 è questa richiesta. Il passo 6 ha aggiunto, nel commit `43fdba6d6bfd93bd215ea37cc3d28ea462341839`, due soli percorsi all'allowlist di `scripts/validate_ocor_development_plan.py`: il record di regressione del ciclo 12 di `OCOR-DEV-REM-0062` e il suo log. Lo sha256 di quel file è `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b`, uguale dall'head rivisto `49fc2d1adf0b5fa5107087675264addf4279002f` fino a `da754e862a2c2fba621cf5d4534fcc5396299b6a`. I record correnti di sola regressione di `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082` hanno ancora lo sha256 precedente `c210364d7dda6ac4739e1fbd89de868ce4f6b83d46b1bc767e86f082ac2024dd`.

L'opzione 1 di `REM-0063-CYCLE11-NO-GO` ratifica l'allowlist già pubblicata per la sonda e dice che non si allarga, salvo il percorso di un record nuovo del punto 6 se il validatore del piano lo rifiuta, e che in quel caso l'estensione sta nello stesso change set ed è limitata a quel percorso di evidenza. La stessa opzione dice che se l'attuazione richiede un file che l'opzione non nomina ci si ferma e si apre una sola richiesta nuova. I tre record di regressione non sono fra i file nominati. Le regole di riqualificazione già vigenti (`PRE-CAMPAIGN-REVIEW` controllo 7, `MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE` punto 4, `REM-0046-REGRESSION-REQUALIFICATION-RECORDS`) trattano quei tre record come da riallineare quando un loro input cambia. Ogni ulteriore modifica dell'allowlist cambia di nuovo l'impronta del validatore e rende stantio anche il record del ciclo 12 di `OCOR-DEV-REM-0062`, che cita già `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b`.

Questa pubblicazione non decide e non modifica l'allowlist. Il riallineamento del record di assurance è un change set di solo record e non è questa decisione. Il RED `bc6af772c09eabad698e4ac97fec425556a4466f` non si riscrive. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` non si rilanciano. `inputs/` non si tocca. I record sigillati non si riscrivono.

Implementatori già dichiarati dell'unità: Grok Build `grok-4.7` (xAI) per il ciclo originale, le riparazioni 1–6, il completamento del ciclo 8, il ciclo 9, il codice e il candidato del ciclo 10, il ciclo 11 e il ciclo 12; Codex CLI `deepseek-flash` e `deepseek-v4-pro` (DeepSeek) per i cicli 7 e 8; Codex `gpt-6.1-sol` (OpenAI) per la fase A del ciclo 10. Verifier assegnato: Claude Code `claude-opus-5-5` (Anthropic), effort `max`. Revisore di questa revisione: Claude Code `claude-fable-5-2` (Anthropic), effort `max`, stesso fornitore del verifier e modello diverso. Nessun implementatore Anthropic.

## Prove

Su `da754e862a2c2fba621cf5d4534fcc5396299b6a`, `ocor-runtime/.venv/bin/python scripts/validate_evidence_input_drift.py --root .` esce 1. Controlla 75 task e 241 input. Tre input sono in deriva, tutti su `scripts/validate_ocor_development_plan.py`: `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082`. Uscita sha256 `f7f3579f5cb4b255eeed4f7bba9974e7ec500f48669afed0494c0e13e96c058d`. Per ciascuno, l'hash all'head è `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b` e l'hash registrato è `c210364d7dda6ac4739e1fbd89de868ce4f6b83d46b1bc767e86f082ac2024dd`.

`select_most_recent` in `scripts/validate_evidence_input_drift.py` sceglie il record il cui `record_id` non compare in alcun `supersedes`; a parità usa `created_at`. I record correnti da supersedere, senza riscriverli, sono:

- `OCOR-DEV-0005-requalified-rem0063-step7b-30034095fbe8`, creato `2026-11-18T09:06:26Z`, commit `30034095fbe8a76fa483cc09215d22b295f16e15`, stato `CANDIDATE`, kind `regression`.
- `OCOR-DEV-0050-requalified-rem0063-step7b-30034095fbe8`, stesso istante e stesso commit.
- `OCOR-DEV-0082-requalified-rem0063-step7b-30034095fbe8`, stesso istante e stesso commit.
- `OCOR-DEV-REM-0062-requalified-rem0063-cycle12-43fdba6d6bfd`, creato `2026-11-19T05:17:14Z`, commit `43fdba6d6bfd93bd215ea37cc3d28ea462341839`. Il suo input `scripts/validate_ocor_development_plan.py` è già `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b`.

Il comando già registrato per i tre task, eseguito a `30034095fbe8a76fa483cc09215d22b295f16e15`, è `ocor-runtime/.venv/bin/python -m pytest -p no:cacheprovider -q -rfEs --tb=line ocor-runtime/tests/tasks/test_ocor_dev_0005.py ocor-runtime/tests/tasks/test_ocor_dev_0050.py ocor-runtime/tests/tasks/test_ocor_dev_0082.py`: 214 passed, 0 skipped, 4,9 s. Il comando già registrato per `OCOR-DEV-REM-0062`, eseguito a `43fdba6d6bfd93bd215ea37cc3d28ea462341839`, è `ocor-runtime/.venv/bin/python -m pytest -p no:cacheprovider -q -rfEs --tb=line reports/tests/test_check_execution_commit_inputs.py reports/tests/test_validate_post_poc_plan.py`: 25 passed, 0 skipped, 0,62 s. Quei log restano storici. Un record nuovo misura un log nuovo.

Il punto 2 di `PRE-CAMPAIGN-GATE (2026-10-26)` non fa partire la campagna finché la deriva non passa. Per questo il gate, la campagna a quattro corsie, il controllo distinto e la richiesta di verifica non partono su questo head.

## Quesito

Come si chiude la deriva dei tre record di regressione di `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082` quando l'opzione 1 adottata vieta di allargare ancora l'allowlist senza una richiesta nuova, e ogni percorso nuovo cambia di nuovo l'impronta del validatore?

## Opzioni

1. **Un solo commit di allowlist nomina gli otto percorsi, poi quattro record di sola regressione su quell'impronta congelata.** Raccomandata. È la chiusura completa. Il parent del commit di allowlist è l'HEAD del branch di campagna nel momento in cui l'opzione si applica. Quel parent deve avere ancora lo sha256 `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b` di `scripts/validate_ocor_development_plan.py`. Un commit che cambia solo il record di assurance non cambia quei byte e non è un motivo per fermarsi. Se lo sha256 del validatore è diverso, ci si ferma e non si inventa un'altra modifica dell'allowlist.

   L'unico cambiamento di quel commit sono esattamente questi otto percorsi, e nessun altro:

   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12.json`
   - `reports/evidence/G0/OCOR-DEV-0005.requalified-rem0063-cycle12.log`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12.json`
   - `reports/evidence/G5/OCOR-DEV-0050.requalified-rem0063-cycle12.log`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12.json`
   - `reports/evidence/G2/OCOR-DEV-0082.requalified-rem0063-cycle12.log`
   - `reports/evidence/G2/OCOR-DEV-REM-0062.requalified-rem0063-cycle12b.json`
   - `reports/evidence/G2/OCOR-DEV-REM-0062.requalified-rem0063-cycle12b.log`

   Il quarto record è il successore del ciclo 12 di `OCOR-DEV-REM-0062`: il commit di allowlist cambia l'hash del validatore, quindi il record che cita `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b` diventa stantio e va superseduto, non riscritto. L'HEAD di comportamento del codice resta `da754e862a2c2fba621cf5d4534fcc5396299b6a`. Nessun file sotto `ocor-runtime/src/` e nessun test cambiano.

   Subito dopo, sullo stesso head congelato, si scrivono i quattro record. Si rimisura ogni hash di input su quell'head: non si copia un hash senza misurarlo. Si ricalcolano `drifted_inputs` e `tests_unchanged_from_base`. I manifest ricevono solo voci nuove in append. `select_most_recent` deve scegliere i quattro record nuovi. I record superseduti restano com'erano. I comandi pytest sono quelli già citati, con skip zero e log nuovi. I quattro record citano lo sha256 del validatore misurato sul commit di allowlist. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

   Accettazione: `scripts/validate_evidence_input_drift.py` esce 0 e `drifted_inputs` è 0; il diff dell'allowlist rispetto a `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b` è esattamente le otto stringhe; nessun record sigillato è riscritto; nessun test, gate, soglia o claim cambia; il record `OCOR-DEV-REM-0062-requalified-rem0063-cycle12-43fdba6d6bfd` resta storico ed è superseduto. Poi, e solo poi: `PRE-CAMPAIGN-GATE`, la campagna a quattro corsie, il controllo distinto e la richiesta di verifica. Non c'è una seconda revisione preventiva. P5 e VF-008 non fanno parte di questa decisione. Il RED `bc6af772c09eabad698e4ac97fec425556a4466f` non si riscrive. Il branch di produzione resta fermo.

   Costo: due iterazioni di implementazione dopo la decisione. La prima è il commit di impronta e i quattro record brevi. La seconda è il gate, la campagna, il controllo distinto e la richiesta di verifica, poi la verifica indipendente. Se la campagna non entra nel tempo dell'iterazione, il resto è l'unità successiva e i record non si rifanno.

2. **Si tolgono le due righe di allowlist del ciclo 12 e l'impronta del validatore torna a quella registrata dai tre record.** Si rimuovono i due percorsi aggiunti in `43fdba6d6bfd93bd215ea37cc3d28ea462341839`, così lo sha256 di `scripts/validate_ocor_development_plan.py` torna a `c210364d7dda6ac4739e1fbd89de868ce4f6b83d46b1bc767e86f082ac2024dd`. I tre record di `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082` tornano allineati. Il record del ciclo 12 di `OCOR-DEV-REM-0062` cita ancora `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b` e i suoi due percorsi escono dall'allowlist: la deriva si sposta su `OCOR-DEV-REM-0062` e il validatore del piano fallisce. Il passo 6 resta disfatto. File: solo `scripts/validate_ocor_development_plan.py`. Costo: un'iterazione che non chiude la deriva. Non raccomandata.

3. **Nessun codice e nessun record.** L'allowlist resta com'è su `da754e862a2c2fba621cf5d4534fcc5396299b6a`. La deriva resta FAIL sui tre task. Il punto 2 di `PRE-CAMPAIGN-GATE (2026-10-26)` continua a impedire la campagna. Costo: zero iterazioni di codice. La classe resta aperta. Non raccomandata.

## Raccomandazione

Opzione 1. Chiude la deriva con un solo commit di allowlist, nominato prima dei record, e con quattro record misurati sull'impronta che quel commit produce, compreso il successore di `OCOR-DEV-REM-0062` che altrimenti diventerebbe stantio. L'opzione 2 riallinea i tre record disfacendo il passo 6 e sposta la deriva su `OCOR-DEV-REM-0062`. L'opzione 3 lascia la deriva FAIL e la campagna ferma. Nessuna opzione di questa richiesta è applicata da chi la apre.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CANONICAL-R1-HUMAN-GATE`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`. `AGENTIC-RISK-MAP-PARTIAL-GAPS` non blocca alcun task.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.

## Disposition

Decisa per conto del PO, modello `claude-fable-5-2`, effort `max`. Decisione `REM-0063-CYCLE12-REGRESSION-DRIFT (2026-11-19)`. Opzione 1 adottata. Le opzioni 2 e 3 non sono applicate.

Il preambolo `~/.ocor-codex/openhands_preamble.md`, sha256 `03692b1bc9a1296eec2def2cc7d134df560bf15152c3a7bcf139a3bdd054bf35`, contiene la sezione `## REM-0063-CYCLE12-REGRESSION-DRIFT (2026-11-19) — decisione del PO, su delega completa`. Adotta l'opzione 1 al commit `497f661cbfcd5939f5e9e83150ba357eb0b551a4`. Lo sha256 del file a quel commit è `64f989b4dba329b58ec20e1702fec4fedd5475fdefb739aaf916ffcec573e851`, verificato con `git cat-file -e`, `git merge-base --is-ancestor` e `sha256sum`.

Il parent del commit di allowlist è `8394d359b3fd2568b828d8d43a3ec68e1973e442`. A quel parent `scripts/validate_ocor_development_plan.py` ha ancora sha256 `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b`. Il commit di allowlist `9d4c552041bb98122c655269e6ace44d38433840` cambia solo quel file e aggiunge esattamente gli otto percorsi. Lo sha256 misurato del validatore su quel commit è `a284aa5fa5127181ab40158c892a207c70256925835ed835f6bc3115a66166cc`. Il diff rispetto a `0d5e0eef97ac64479c0744cb40063b77bf6f2f91fa82b0e4ee6b86284e09411b` è esattamente le otto stringhe.

Sull'impronta congelata i quattro record di sola regressione sono il commit `d2aed94dd99af8a72aca5b449e1dd72bd68119ca` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`. `select_most_recent` sceglie `OCOR-DEV-0005-requalified-rem0063-cycle12-9d4c552041bb`, `OCOR-DEV-0050-requalified-rem0063-cycle12-9d4c552041bb`, `OCOR-DEV-0082-requalified-rem0063-cycle12-9d4c552041bb` e `OCOR-DEV-REM-0062-requalified-rem0063-cycle12b-9d4c552041bb`. I record superseduti restano byte-identici. `scripts/validate_evidence_input_drift.py` esce 0: 75 task, 241 input, `drifted_inputs` 0. Pytest dei tre task: 214 passed, 0 skipped, 4,95 s. Pytest di `OCOR-DEV-REM-0062`: 25 passed, 13 subtests passed, 0 skipped, 0,63 s. L'HEAD di comportamento del codice resta `da754e862a2c2fba621cf5d4534fcc5396299b6a`. Nessun file sotto `ocor-runtime/src/` e nessun test è cambiato. Il RED `bc6af772c09eabad698e4ac97fec425556a4466f` non è riscritto.

`PRE-CAMPAIGN-GATE`, la campagna a quattro corsie, il controllo distinto e la richiesta di verifica non sono in questa pubblicazione: sono l'unità successiva e i record non si rifanno. Non c'è una seconda revisione preventiva. P5 e VF-008 non fanno parte di questa decisione. Il branch di produzione resta `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` non sono state rilanciate.

Il testo sopra questa sezione, esclusa la riga di stato, resta quello del commit `497f661cbfcd5939f5e9e83150ba357eb0b551a4`, sha256 `64f989b4dba329b58ec20e1702fec4fedd5475fdefb739aaf916ffcec573e851`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo `DEC-*`.
