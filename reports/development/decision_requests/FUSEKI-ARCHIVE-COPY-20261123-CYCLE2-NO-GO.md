# FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO

Stato: `DECIDED_BY_PO`.
Disposition: opzione 2, con le precisazioni dei punti 1–6 della decisione `FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO (2026-11-24)`, decisa dal PO di persona, sezione scritta a mano. Il file pubblicato a `99d22adeea09e060507e7f9bc60f7f5380d37df5` resta sha256 `83620375c84d7cfd09383139314127dd5fbf3d0ef0eabd2b09aea3b72445276d`. Il testo delle opzioni non cambia. Questa pubblicazione non si integra. Claim invariati.

Livello: operativo. Nessun nuovo `DEC-*`.
Chi decide: il Product Owner di persona, come dispone il punto 4 di `DECISIONI-AL-PO (2026-11-16)`, perché la richiesta riguarda un ciclo di riparazione oltre il budget ordinario e l'eventuale estensione di un gate. Nessuna opzione è applicata da questa pubblicazione.
Head di `origin/main` alla pubblicazione: `618e72c00f994e8ea8899914548cc38743aa4569`.
Candidato: branch `governed/fuseki-archive-copy-20261123`, HEAD `948479739127d33bc2f69a2c003a4acb5823d8b4`. Nessun commit è aggiunto sopra quell'HEAD da questa pubblicazione. Il candidato non si modifica e non si mergia.
Decisione già adottata: `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`, decisa dal PO di persona, sezione scritta a mano. Quesito A: nessuna delle tre opzioni del file `reports/development/decision_requests/CI-FUSEKI-ARCHIVE-TIMEOUT-20261123.md` al commit `15a36bec1ceb3020ef075fc331dda22c9b173650`, sha256 `d63ff2aced89118c52b2262d9f468818bcc9ea08820b88034146a7d50c32831b`; è adottata la copia governata dei punti 1–8 di quella decisione. Quesito B: opzione B1. Il change set `FUSEKI-ARCHIVE-COPY-20261123` è quello del punto 2. I punti 5 e 6 restano: una campagna sull'HEAD finale e un solo tentativo CI nuovo dopo `GO_FOR_EVIDENCE_SEAL`, non prima.
Implementatore dei cicli 0, 1 e 2: Grok Build, modello `grok-4.7`, fornitore xAI. Verifier dei tre verdetti: Codex, fornitore OpenAI, diverso da xAI. Implementatore di questa pubblicazione: Grok Build, modello `grok-4.7`, fornitore xAI. Nessun verifier è stato avviato da chi la apre.

## Contesto e perimetro

Il verdetto `FUSEKI-ARCHIVE-COPY-20261123-948479739127-2` è `NO_GO` sull'HEAD `948479739127d33bc2f69a2c003a4acb5823d8b4`, base `618e72c00f994e8ea8899914548cc38743aa4569`, `repair_cycle` 2, creato `2026-11-24T00:33:43.439842Z`, sha256 del documento `c167a90169ee4e6cdc20101cc670ae729e508ee20248e6ef3bff0723ad0c227d`. Non è un ciclo 3.

I verdetti precedenti dello stesso change set sono anch'essi `NO_GO`: `FUSEKI-ARCHIVE-COPY-20261123-5b31e56f0bef-0` su `5b31e56f0bef` e `FUSEKI-ARCHIVE-COPY-20261123-273543f4b910-1` su `273543f4b910`. Il budget ordinario è di due cicli di riparazione. Il ciclo 2 è il secondo. Questa pubblicazione non lo riapre.

Due finding del ciclo 2 sono bloccanti.

VF-001 è di perimetro. Il diff `618e72c00f994e8ea8899914548cc38743aa4569..948479739127d33bc2f69a2c003a4acb5823d8b4` aggiunge 23 percorsi all'allowlist di `scripts/validate_ocor_development_plan.py` e aggiorna il digest in `reports/planning/OCOR_PLAN_RUN_STATE.json`. I punti 2 e 8 della decisione adottata ammettono `scripts/acquire_fuseki_archive.py`, `reports/tests/test_fuseki_archive_acquisition.py` e i record, i manifest e i log che il processo già prevede, e mantengono i gate invariati. Il PASS del validatore di scope del branch `governed/` è più ampio di quel perimetro. I 23 percorsi sono:

- `reports/assurance/FUSEKI-ARCHIVE-COPY-20261123/FUSEKI-ARCHIVE-COPY-20261123.json`
- `reports/evidence/G0/OCOR-DEV-0005.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G0/OCOR-DEV-0005.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G2/OCOR-DEV-0072.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G2/OCOR-DEV-0072.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G2/OCOR-DEV-0082.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G2/OCOR-DEV-0082.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G2/OCOR-DEV-REM-0018.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G2/OCOR-DEV-REM-0018.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G2/OCOR-DEV-REM-0022.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G2/OCOR-DEV-REM-0022.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G2/OCOR-DEV-REM-0037.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G2/OCOR-DEV-REM-0037.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G2/OCOR-DEV-REM-0038.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G2/OCOR-DEV-REM-0038.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G4/OCOR-DEV-REM-0053.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G4/OCOR-DEV-REM-0053.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G5/OCOR-DEV-0050.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G5/OCOR-DEV-0050.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G5/OCOR-DEV-REM-0023.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G5/OCOR-DEV-REM-0023.requalified-fuseki-archive-copy-20261123.log`
- `reports/evidence/G5/OCOR-DEV-REM-0036.requalified-fuseki-archive-copy-20261123.json`
- `reports/evidence/G5/OCOR-DEV-REM-0036.requalified-fuseki-archive-copy-20261123.log`

VF-002 è di evidenza. Il blocco del ciclo 2 non riporta, per l'HEAD `48f8f2e54518eba6f740e06ecef723827270b5dd` della fase precedente alla campagna, l'elenco dei passi rapidi, gli esiti e le impronte dei log originali. Il blocco che contiene quegli esiti resta legato a un HEAD precedente, con un digest di script diverso da quello della campagna finale. I log esistono fuori dal repository. Il record di assurance non li vincola.

VF-003 non è bloccante. Il revisore preventivo è un modello Grok di generazione diversa dall'implementatore, stesso fornitore xAI. Il record non dichiara il ruolo di riserva né il limite di indipendenza. Il verifier del ciclo 2 è OpenAI.

VF-004 non è bloccante e non entra in questa richiesta. `reports/tests/test_schema_conformance.py` resta 97 PASS e 1 FAIL sul caso `CANONICAL_COMMIT` R1 senza Human Gate: atteso `REJECT`, ottenuto `ACCEPT`. Test e input normativo sono identici fra l'HEAD e `origin/main`. Non si corregge e non si segna `PASS`.

Il punto 9 della decisione adottata vieta, finché il change set non è integrato, un branch di codice dell'unità che separa l'etichetta Fuseki della CI. Il contratto di quell'unità è già pubblicato su `governed/ocor-dev-rem-0067-fuseki-ci-label-contract` all'HEAD `1ac9d2846624b55b5472d4d91d10104098ef3f99`. La revisione del progetto su `88d526421d77cbe8db4f1a1546b41dcb929a7156` ha finding bloccanti. Questa pubblicazione non apre codice di quell'unità e non chiede una seconda revisione del progetto.

`REM-0066-CYCLE3-NO-GO` resta aperta, bozza PR #772, commit `171708381416e03d3c217efdcb60328e158f5b84`, sha256 `e44221eb591f62640098bf50295ebdf74d6999880e48803c2f8ba4064e724fcb`. Nessuna sua opzione è applicata. Non è un ciclo 4. Il candidato `3b2ee600ee5d9e3055e3d916628d958635fefff3` non si modifica e non si mergia.

Non si rilanciano i run `45139159711`, `45139159581`, `45139159701`, `45116784337` e `45147805219`. Non si apre una pull request di stato: il provisioning di una pull request ripeterebbe il fallimento già osservato, e il punto 6 della decisione adottata ammette un solo tentativo CI nuovo dopo il GREEN del change set, sull'HEAD di quel change set. Non si tocca la PR #722 né il commit `7b0b90ee79bdae51b22365faca2a54159502a44f`. Non si apre un `repair_cycle` 14. Non si avvia `OCOR-DEV-REM-0060`.

## Quesito

Il ciclo 2 è `NO_GO` e il budget ordinario di due cicli di riparazione è esaurito. Si autorizza un solo ciclo 3, e con quale perimetro sull'allowlist del validatore del piano?

## Opzioni

1. **Un solo ciclo 3 dentro il perimetro già adottato.** Si autorizza un solo ciclo di riparazione sul branch `governed/fuseki-archive-copy-20261123`, a partire da `948479739127d33bc2f69a2c003a4acb5823d8b4`, senza merge prima di un nuovo `GO_FOR_EVIDENCE_SEAL`. Il ciclo toglie dal change set le 23 voci di allowlist e l'aggiornamento del digest di `reports/planning/OCOR_PLAN_RUN_STATE.json`. Registra nel record di assurance del ciclo qualificante, sull'HEAD della fase precedente alla campagna, l'elenco dei passi, gli esiti, le impronte dei log originali, i tentativi diagnostici e i passi non eseguiti, e dichiara il ruolo di riserva del revisore preventivo e il limite di indipendenza per il fornitore condiviso. File di produzione ammessi restano soltanto `scripts/acquire_fuseki_archive.py` e `reports/tests/test_fuseki_archive_acquisition.py`, più i record, i manifest e i log che il processo già prevede senza modificare l'allowlist. Se un record non entra senza quella modifica, il ciclo si ferma e non estende l'allowlist: si apre una sola richiesta nuova. VF-004 non si corregge e non si segna `PASS`. Nessun altro file di produzione. Poi una sola verifica, `repair_cycle` 3, verifier di fornitore diverso da xAI. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 della decisione già adottata. Con un nuovo `NO_GO` non c'è un ciclo 4. Non è applicata da questa pubblicazione. Claim invariati.

2. **Il Product Owner ammette le 23 voci e un solo ciclo 3 di evidenza.** Si autorizza in modo esplicito l'estensione dell'allowlist di `scripts/validate_ocor_development_plan.py` alle 23 voci elencate sopra e il digest corrispondente di `reports/planning/OCOR_PLAN_RUN_STATE.json`, come eccezione al punto 8 della decisione già adottata, limitata a quei percorsi. Un solo ciclo 3 registra gli esiti del gate precedente alla campagna e il limite di indipendenza del revisore, senza altre modifiche di produzione e senza togliere le 23 voci. VF-004 non si corregge e non si segna `PASS`. Verifica, eventuale integrazione e divieto di un ciclo 4 sono quelli dell'opzione 1. Non è applicata da questa pubblicazione. Claim invariati.

3. **Nessun ciclo 3 e nessuna integrazione.** Il branch resta `948479739127d33bc2f69a2c003a4acb5823d8b4` e non si mergia. La copia governata dell'archivio non entra su `origin/main`. Il codice dell'unità che separa l'etichetta Fuseki della CI non parte. VF-001, VF-002 e VF-003 restano aperti. Non è la soluzione completa: il provisioning ufficiale in CI resta quello che ha esaurito il termine di 120 s sulla fonte Apache ancora viva. Non è applicata da questa pubblicazione. Claim invariati.

## Raccomandazione

Opzione 1. La decisione già adottata ammette i file di acquisizione e i record che il processo prevede, e lascia i gate invariati. L'estensione dell'allowlist è il difetto che il verdetto chiede di riportare nel perimetro, oppure di sottoporre al Product Owner se resta necessaria. L'opzione 1 prova prima il perimetro già scritto e si ferma se l'evidenza non entra. L'opzione 2 allarga un gate prima di aver dimostrato che l'opzione 1 è impossibile. L'opzione 3 lascia il provisioning ufficiale fermo. La raccomandazione non dipende dal numero di comandi. Chi apre questa richiesta non ne applica nessuna opzione.

## Impatto

Task e change set bloccati da questa richiesta finché è aperta: il change set `FUSEKI-ARCHIVE-COPY-20261123` e, per il punto 9 della decisione già adottata, il codice dell'unità che separa l'etichetta Fuseki della CI. `OCOR-DEV-REM-0066` resta bloccato da `REM-0066-CYCLE3-NO-GO`, che questa richiesta non modifica. `OCOR-DEV-REM-0060` non si avvia. Gli altri task non sono bloccati, salvo quelli che dipendono dall'integrazione di questo change set o dalla chiusura di `OCOR-DEV-REM-0063`.

Finché la richiesta è aperta non si apre il ciclo 3, non si modifica né si mergia `948479739127d33bc2f69a2c003a4acb5823d8b4`, non si apre la sua pull request, non si rilanciano i run di provisioning già falliti e non si apre una pull request di solo stato.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim da questa pubblicazione. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.
