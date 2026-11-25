# OCOR-DEV-REM-0069-REGISTRATION-NO-GO

Stato: `OPEN_PO_DECISION_REQUIRED`.
Livello: operativo. Nessun nuovo `DEC-*`.
Chi decide: decisione operativa sull'unità, perché il punto 7 di `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)` ammette una sola richiesta nuova dopo il `NO_GO` dell'unico commit di registrazione e non ammette un altro ciclo. Nessuna opzione si applica in questa pubblicazione.
Head di `origin/main` alla pubblicazione: `618e72c00f994e8ea8899914548cc38743aa4569`.
Candidato: branch `governed/ocor-dev-rem-0069-fuseki-archive-copy`, HEAD `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9`, parent `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f`. Nessun commit è aggiunto sopra quell'HEAD da questa pubblicazione. Il candidato non si modifica e non si mergia.
Decisione che impone questa richiesta: il punto 7 di `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)`. Il file di quella richiesta al commit `98ba5a86dc02d31e9da9f371178171b6272fa428` resta sha256 `356e23c1a5f5614fa0897bed214b9d4ec152a7acb383b52c649609920a8ccc9a`. L'opzione 1 di quella richiesta è già applicata. La disposition è il commit `24d660ca13d41ceb0d360d81182447dd4594db22`, sha256 `abbe7423a2d9395cddb56f904096d2e5a52681a23d3da079569a9fe54ea3d983`, branch `governed/decision-request-ocor-dev-rem-0069-redesign-nogo`. Questa pubblicazione non cambia quel file e non applica una nuova opzione.
Implementatore dell'unità e di questa pubblicazione: Grok Build, modello `grok-4.7`, fornitore xAI. Revisore preventivo di riserva: Cursor, modello `cursor-grok-4.6-xhigh`, fornitore xAI, stesso fornitore dell'implementatore, limite di indipendenza già dichiarato nel record. Verifier di questo verdetto: Codex, fornitore OpenAI, modello `NOT_EXPOSED_BY_RUNTIME`, diverso da xAI, non avviato dall'implementatore.

## Contesto e perimetro

Il verdetto `OCOR-DEV-REM-0069-e70fa15f6c92-1` è `NO_GO` sull'HEAD `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9`, creato `2026-11-25T21:19:54Z`, sha256 del documento `4b13cad50fbbc167053f73298e7957baee386cacb29fc3236adf174f87d753a3`. È la verifica dell'unico commit di registrazione autorizzato da `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)`. La richiesta di verifica porta `repair_cycle` 1. Non è un ciclo ulteriore di codice.

`git diff --name-status 7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9` contiene soltanto `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`. I blob di produzione restano quelli fissati: `scripts/acquire_fuseki_archive.py` è `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`; `reports/tests/test_fuseki_archive_acquisition.py` è `dee2ca8813565043b20798a634743edcf0fd5f20`.

La campagna a quattro corsie `eaae5f0de47c-1795613672` sul commit `eaae5f0de47ce1b082e36257ac17c422ae78844a` resta quella registrata: `campaign_result.json` sha256 `9ba50b61daffc27fe28e12d44ee12e89ab1d4d41c8b8e47fd71e3eb4713d321a`. Non si ripete in questa pubblicazione. Il verifier non ha avviato una campagna nuova. VF-004 non è bloccante: 97 PASS e 1 FAIL, `CANONICAL_COMMIT` R1 senza Human Gate attende `REJECT` e ottiene `ACCEPT`, codice 1, stdout sha256 `cadf3a414a3833681f45f7bd9007a9be05dc252de470af7e1de1a484e7c5a936`. La disposition registrata e prescritta è `NOT_CORRECTED`. Non si corregge e non si segna `PASS`.

VF-001 è di evidenza ed è bloccante. Il punto 3 di `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)` limita le righe corrette e nuove a file del commit di esecuzione e a strumenti di sistema o del venv del repository. Il punto 4 della stessa decisione chiede, per ciascuno dei 50 passi di `pregate-eaae5f0/gates.json`, comando, stato, codice di uscita e sha256 del log. Quei file non stanno nel commit nominato: `git cat-file -e 80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c:pregate-80a2c854/gates.json` e `git cat-file -e eaae5f0de47ce1b082e36257ac17c422ae78844a:pregate-eaae5f0/gates.json` restituiscono 128. Il ricalcolo indipendente sui file originali conferma le impronte. Il comando resta dipendente dallo stato locale fuori dal commit.

Tre righe di `proof_table` sono quelle del finding.

| Riga | Commit di esecuzione | Comando | Esito registrato | stdout sha256 |
| --- | --- | --- | --- | --- |
| 115 | `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` | `python3 /home/luca/.ocor-codex/ocor-dev-rem-0069/pregate-80a2c854/record_exit_read.py` | exit 0, `PASS` | `ccfd69e96d82d9d7c649dfae86fb6aea4b3adb59afbc0c035d9eef54278d83c7` |
| 265 | `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` | lettura di `pregate-80a2c854/gates.json` e dei log nominati dai passi | exit 0, `RECORDED` | `6d1cd5bfd764a82dc8bfe9ee35a36b2ae824c5efb848318ec6c8de0885aad612` |
| 463 | `eaae5f0de47ce1b082e36257ac17c422ae78844a` | lettura di `pregate-eaae5f0/gates.json` e dei 50 log | exit 0, `RECORDED` | `43be2ebd738ee60da25f11c532be7c2456aefab04295a625896dd967817df2c3` |

`gates.json` di `pregate-80a2c854` ha sha256 `36f86d94f4613fb898eb0038800a21abb4366794a78c97dbebc50867b9c79de6`. `gates.json` di `pregate-eaae5f0` ha sha256 `f6d2f7cb5e09f7830eacc2c0d4a16564733f892ae04b0ea0c48bc9a234303e3d`. Ciascun file ha 50 passi. I log nominati esistono tutti: 132651 byte per `pregate-80a2c854` e 132303 byte per `pregate-eaae5f0`. Le directory `pregate-*` occupano circa 997 MiB ciascuna perché contengono `supply-archive`. Quel contenuto non entra in questa richiesta.

La correzione richiesta dal verdetto è: citare prove riproducibili con i soli file del rispettivo commit e gli strumenti autorizzati; conservare il confronto degli artefatti originali e dei loro digest come controllo esplicito a parte, secondo il punto 4, con il perimetro del Product Owner.

Classi dei finding bloccanti. La classe è il controllo obbligatorio del verifier.

| Verdetto | Finding | Classe | Bloccante |
| --- | --- | --- | --- |
| `OCOR-DEV-REM-0069-38e15d2cb337-0` | VF-001, VF-002 | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-001, VF-002 | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-005 | Ambiente del verifier | sì |
| `OCOR-DEV-REM-0069-7ba88cfb3eb0-0` | VF-001, VF-002, VF-003, VF-005 | Evidenza | sì |
| `OCOR-DEV-REM-0069-e70fa15f6c92-1` | VF-001, righe 115, 265 e 463 fuori dal commit | Evidenza | sì |

La causa comune della classe Evidenza, in questo verdetto, è il contrasto fra due punti della stessa decisione. Il punto 3 vieta un comando che legge un file fuori dal commit. Il punto 4 chiede lo sha256 di log che non sono nel commit. Il codice di acquisizione e la campagna verde non cambiano. Il ricalcolo dei digest è già stato fatto dal verifier e coincide. Manca la separazione, nel record, fra le righe rieseguibili e il controllo storico degli artefatti.

`OCOR-DEV-REM-0066` resta senza ciclo 4 finché l'unità del punto 4 di `CONFINE-G6 (2026-11-20)` non è integrata. Il branch di codice di `OCOR-DEV-REM-0068` non parte finché `OCOR-DEV-REM-0069` non è su `origin/main`. Il contratto di `OCOR-DEV-REM-0067` è già pubblicato su `governed/ocor-dev-rem-0067-fuseki-ci-label-contract` all'HEAD `1ac9d2846624b55b5472d4d91d10104098ef3f99`; il suo branch di codice non parte prima dell'integrazione di questa unità. Il launcher `governed/rem-0063-ci-argv-launcher` resta `69c3877caf58f82ebf4ea9e6e39df6560ad1ff8b`. Il candidato `24633cc9d4c49749bd33a386020fe0d9f6cf5174` non si modifica e non si mergia. Il candidato `3b2ee600ee5d9e3055e3d916628d958635fefff3` non si modifica e non si mergia.

Non si rilanciano i run `45139159711`, `45139159581`, `45139159701`, `45116784337` e `45147805219`. Non si apre una pull request del candidato. Non si tocca la PR #722 né il commit `7b0b90ee79bdae51b22365faca2a54159502a44f`. Non si apre un `repair_cycle` 14. Non si avvia `OCOR-DEV-REM-0060`. Non si modifica `scripts/validate_ocor_development_plan.py` né `reports/planning/OCOR_PLAN_RUN_STATE.json`. VF-004 resta `NOT_CORRECTED` e non è `PASS`.

## Quesito

L'unico commit di registrazione di `OCOR-DEV-REM-0069` è `NO_GO` sulla classe Evidenza. Il punto 7 di `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)` non ammette un altro ciclo senza una nuova disposizione. Il candidato resta fermo. Si autorizza un solo commit che toglie dalle righe rieseguibili i tre comandi fuori dal commit e li sostituisce con un controllo storico dei digest già confermati; si ferma l'unità senza integrazione; oppure si portano nel repository i soli file letti da quelle tre righe, così che un commit di esecuzione li contenga?

## Opzioni

1. **Un solo commit di registrazione e un controllo storico separato.** Non si attua in questa pubblicazione. Il Product Owner autorizza un solo commit nuovo sopra `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9`, con quel parent, senza rebase, reset o force-push. L'unico percorso cambiato è `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`. I due blob di acquisizione restano `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` e `dee2ca8813565043b20798a634743edcf0fd5f20`. Non parte una campagna nuova. La campagna `eaae5f0de47c-1795613672` e `campaign_result.json` sha256 `9ba50b61daffc27fe28e12d44ee12e89ab1d4d41c8b8e47fd71e3eb4713d321a` restano la prova di comportamento. VF-004 resta `NOT_CORRECTED` e non è `PASS`. Nel record, le righe di `proof_table` che oggi sono le righe 115, 265 e 463 del file `OCOR-DEV-REM-0069.json` a `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9` cessano di essere comandi rieseguibili. Al loro posto il record contiene un solo blocco `historical_artifact_control`, che non è una riga di `proof_table`. Il blocco riporta, per `pregate-80a2c854` e per `pregate-eaae5f0`: sha256 di `gates.json` già citati; per ogni passo, nome, comando, stato, codice di uscita e sha256 del log, trascritti dall'esecuzione che ha prodotto gli stdout `6d1cd5bfd764a82dc8bfe9ee35a36b2ae824c5efb848318ec6c8de0885aad612` e `43be2ebd738ee60da25f11c532be7c2456aefab04295a625896dd967817df2c3`; per `record_exit_read.py`, l'esito exit 0 e lo stdout sha256 `ccfd69e96d82d9d7c649dfae86fb6aea4b3adb59afbc0c035d9eef54278d83c7`, insieme al fatto che il verifier ha controllato gli exit file originali. Il blocco nomina il commit di esecuzione di ciascuna misura e lo sha256 dello stdout da cui la misura è trascritta. Non nomina un comando che apra un percorso fuori da quel commit. Prima del commit, in un worktree pulito al commit di esecuzione di ciascuna riga di `proof_table` che resta un comando, si rieseguono quelle righe, tranne la campagna e i passi del gate rapido, e si confrontano codice di uscita e sha256. Si fa il commit solo se coincidono. Una riga rimasta che apre un percorso fuori dal commit si sposta nello stesso blocco storico soltanto se il suo stdout è già un rapporto di digest di file conservati; altrimenti ci si ferma e si apre una sola richiesta, senza un altro commit. Il verifier riesegue ogni riga di `proof_table` rimasta, sul commit di esecuzione nominato, e confronta comando, esito e sha256. Per `historical_artifact_control` non riesegue un comando: ricalcola lo sha256 dei file conservati e lo confronta con il blocco. Un digest diverso è `NO_GO`. Un file conservato assente ferma la verifica con una sola richiesta: non si ricostruisce. Questo controllo è il perimetro del punto 4 e non è soggetto al punto 3 di `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)`. `supply-archive` non si copia e non entra nel blocco. Poi una sola verifica, con un verifier di fornitore diverso da xAI non avviato dall'implementatore. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un altro ciclo: una sola richiesta nuova. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: `scripts/acquire_fuseki_archive.py`, blob `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`, chiede per prima la copia governata in modo anonimo, verifica lo SHA-512 del lock e solo dopo prova le fonti Apache; il consumatore è il record del commit di registrazione, che nomina la campagna `eaae5f0de47c-1795613672` come prova di comportamento e, nel blocco storico, i digest dei due `gates.json` già confermati dal verifier. Costo stimato: due iterazioni, una per il record e una per la verifica. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit di questa pubblicazione sopra `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9` | `git rev-parse` del branch prima del commit di registrazione |
| Un solo commit, senza rebase | parent uguale a `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9` |
| Unico percorso cambiato: il record dell'unità | `git diff --name-status` contro `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9` |
| I due blob di acquisizione restano quelli citati | `git rev-parse` dei due path |
| Nessuna campagna nuova | assenza di un `campaign_result.json` diverso da `9ba50b61daffc27fe28e12d44ee12e89ab1d4d41c8b8e47fd71e3eb4713d321a` per la prova di comportamento |
| Le tre righe non sono più comandi di `proof_table` | il record non contiene quei tre comandi come righe rieseguibili |
| Il blocco storico riporta i digest già misurati | sha256 dei due `gates.json` e i due stdout citati |
| Le righe rimaste si rieseguono prima del commit | codice di uscita e sha256 uguali alla riga |
| Il verifier ricalcola i file conservati e non riesegue il blocco come comando | verdetto sull'HEAD esatto |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| Una sola verifica, verifier di fornitore diverso da xAI | verdetto sull'HEAD esatto |
| Nessun ciclo ulteriore dopo un nuovo `NO_GO` | una sola richiesta nuova |

2. **Stop senza integrazione.** Non si attua in questa pubblicazione. Il Product Owner non autorizza altri commit sul candidato. `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9` non si modifica e non si mergia. Non si apre la pull request. La campagna `eaae5f0de47c-1795613672` resta storica e non diventa un sigillo. VF-001 resta aperto. VF-004 resta `NOT_CORRECTED` e non è `PASS`. I due blob restano quelli citati. Le unità che partono solo quando `OCOR-DEV-REM-0069` è su `origin/main` restano ferme. Non si apre un altro ciclo. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: lo stesso produttore e gli stessi blob dell'opzione 1; il consumatore non è un record sigillato. Il candidato rifiutato resta l'HEAD pubblicato del branch e non entra in `origin/main`. Costo stimato: un'iterazione, questa pubblicazione. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit sopra `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9` | `git rev-parse` del branch |
| Nessuna pull request del candidato | assenza di una PR con quell'HEAD |
| Nessun merge | `git merge-base --is-ancestor` contro `origin/main` fallisce |
| Campagna resta storica | lo stesso sha256, non trasferito a un sigillo |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| I due blob restano quelli citati | `git rev-parse` dei due path |
| Nessun ciclo ulteriore | nessun commit di riparazione |

3. **Due commit: i file letti dalle tre righe entrano nel repository.** Non si attua in questa pubblicazione. Il Product Owner autorizza due commit nuovi sopra `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9`, senza rebase, reset o force-push. Il primo aggiunge soltanto `gates.json` e i file di log nominati dai 50 passi di `pregate-80a2c854` e di `pregate-eaae5f0`, più `record_exit_read.py`, sotto `reports/assurance/OCOR-DEV-REM-0069-RCCAD/historical-gates/`. Non aggiunge `supply-archive` né alcun altro file delle directory `pregate-*`. Prima di quel commit uno scan dei file aggiunti deve terminare senza segreti; se lo scan fallisce, il primo commit non si fa e si applica l'opzione 1. Il secondo commit cambia soltanto il record dell'unità: le tre righe diventano comandi che leggono i percorsi relativi aggiunti dal primo commit, con commit di esecuzione uguale al primo commit. `git diff --name-status` fra i due commit contiene soltanto il record. I due blob di acquisizione restano quelli citati. Non parte una campagna nuova. VF-004 resta `NOT_CORRECTED` e non è `PASS`. Sono ammesse le voci di allowlist strettamente necessarie ai percorsi aggiunti e l'aggiornamento corrispondente del digest in `reports/planning/OCOR_PLAN_RUN_STATE.json`, e nessun'altra modifica a quei due file. Se l'allowlist richiede riqualifiche oltre questo perimetro, ci si ferma e si apre una sola richiesta. Poi una sola verifica, con un verifier di fornitore diverso da xAI non avviato dall'implementatore. Il verifier riesegue le tre righe sul primo commit. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un altro ciclo: una sola richiesta nuova. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: lo stesso produttore e gli stessi blob dell'opzione 1; il consumatore è il record del secondo commit, che legge `historical-gates/` dal primo commit e non da un percorso fuori dal repository. Costo stimato: tre iterazioni, una per i due commit, una per l'allowlist se serve, una per la verifica. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Due commit sopra `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9`, senza rebase | parent del primo uguale a quell'HEAD; parent del secondo uguale al primo |
| Il primo commit aggiunge solo i file letti dalle tre righe | `git diff --name-status` senza `supply-archive` |
| Lo scan dei file aggiunti non trova segreti | esito dello scan registrato nel record |
| Il secondo commit cambia solo il record | `git diff --name-status` fra i due commit |
| Le tre righe leggono percorsi del primo commit | riesecuzione sul primo commit, esito e sha256 |
| I due blob restano quelli citati | `git rev-parse` dei due path |
| Nessuna campagna nuova | lo stesso `campaign_result.json` |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| Una sola verifica, verifier di fornitore diverso da xAI | verdetto sull'HEAD esatto |
| Nessun ciclo ulteriore dopo un nuovo `NO_GO` | una sola richiesta nuova |

## Raccomandazione

L'opzione 1. Il codice sotto prova è invariato, la campagna è verde e il verifier ha già ricalcolato i digest dei file conservati. VF-001 nasce dal contrasto fra il punto 3 e il punto 4 di `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)`, non da un byte diverso dell'acquisizione. L'opzione 1 toglie i tre comandi dalle righe rieseguibili e lascia il confronto dei digest come controllo separato, che è la correzione richiesta dal verdetto. L'opzione 2 lascia non integrata una copia governata già qualificata sul comportamento. L'opzione 3 rende i tre controlli indipendenti dalla directory esterna, ma aggiunge file, uno scan, l'allowlist e un secondo commit; se lo scan fallisce torna comunque all'opzione 1. Non è necessaria per chiudere il finding, e i log contengono percorsi locali che il repository non ha bisogno di conservare.

## Effetto sulle unità

Blocca solo `OCOR-DEV-REM-0069` finché una sezione non adotta un'opzione. Non blocca un'unità che non dipende dal merge di `OCOR-DEV-REM-0069`. Il branch di codice di `OCOR-DEV-REM-0067`, il branch di codice di `OCOR-DEV-REM-0068`, la continuazione del launcher e il ciclo 4 di `OCOR-DEV-REM-0066` dipendono da integrazioni già decise e restano fermi. Nessuna opzione di questa richiesta è applicata.

## Controllo di formato

Comando, eseguito sul file di questa pubblicazione prima del push: `grep -cE '^[A-Z]?[0-9]{1,2}\. \*\*'`. Esito atteso: 3. Le opzioni sono numerate da 1 a 3, senza salti, sotto `## Opzioni`.
