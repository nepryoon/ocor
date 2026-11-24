# OCOR-DEV-REM-0069-REDESIGN

Stato: `OPEN_PO_DECISION_REQUIRED`.
Disposition: nessuna. Nessuna opzione è applicata da questa pubblicazione. Il candidato non si modifica e non si mergia. Non è un ciclo di riparazione. Questa pubblicazione non si integra. Claim invariati.

Livello: operativo. Nessun nuovo `DEC-*`.
Chi decide: il programma delle decisioni per conto del PO, secondo `DECISIONI-A-FABLE (2026-11-17)`. La richiesta riguarda il ritorno al progetto dopo due `NO_GO` della stessa classe, come dispongono i punti 2 e 3 di `DECISIONI-AL-PO (2026-11-16)`. Nessuna opzione è applicata da questa pubblicazione.
Head di `origin/main` alla pubblicazione: `618e72c00f994e8ea8899914548cc38743aa4569`.
Candidato: branch `governed/ocor-dev-rem-0069-fuseki-archive-copy`, HEAD `86a8a2b5a6c14334a773fdd139ae986c373ef308`, parent `7cf4c23e91b49b34a28ead075f25094254556764`. Nessun commit è aggiunto sopra quell'HEAD da questa pubblicazione. Il candidato non si modifica e non si mergia.
Decisione che impone questa richiesta: il punto 5 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24)` e la frase dell'opzione 1 di `OCOR-DEV-REM-0069-NO-GO` «Con un nuovo `NO_GO` non c'è un ciclo 2: una sola richiesta nuova», adottata dai punti 1–5 di `OCOR-DEV-REM-0069-NO-GO (2026-11-24)`. Il file di quella richiesta al commit `a0d180df67d99175e522949089b9d507b9e2a1a8` resta sha256 `3275ead78b56ae10677350368227efe1a510c3f443e69863a43f6ec65b0041a9`. Il punto 2 di `DECISIONI-AL-PO (2026-11-16)` conferma che non c'è un altro ciclo: i due verdetti hanno finding bloccanti della classe Evidenza. Questa è la richiesta `-REDESIGN`. Il candidato precedente `24633cc9d4c49749bd33a386020fe0d9f6cf5174` non si modifica e non si mergia.
Implementatore dell'unità: Grok Build, modello `grok-4.7`, fornitore xAI. Revisore preventivo di riserva: Cursor, modello `cursor-grok-4.6-xhigh`, fornitore xAI, stesso fornitore dell'implementatore, limite di indipendenza già dichiarato nel record. Verifier del ciclo 1: Codex, fornitore OpenAI, modello `NOT_EXPOSED_BY_RUNTIME`, diverso da xAI, non avviato dall'implementatore. Implementatore di questa pubblicazione: Grok Build, modello `grok-4.7`, fornitore xAI.

## Contesto e perimetro

Il verdetto `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` è `NO_GO` sull'HEAD `86a8a2b5a6c14334a773fdd139ae986c373ef308`, creato `2026-11-24T19:37:06.564285Z`, sha256 del documento `360d29cf4a5c53a8819013aa3eb81056d55a9530bf260c5aa395aad798c3ced7`. È il ciclo di riparazione 1. Il verdetto del ciclo 0, `OCOR-DEV-REM-0069-38e15d2cb337-0`, è `NO_GO` sull'HEAD `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`, creato `2026-11-24T14:36:54.951438Z`, sha256 `996851f078775d08f9465a28800e6a5cbc505e6e3ef46c2763c6ecd5df6ada63`.

I blob di produzione sono gli stessi sul commit di campagna `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`, sul commit di contenuto `7cf4c23e91b49b34a28ead075f25094254556764` e sull'HEAD rifiutato: `scripts/acquire_fuseki_archive.py` è `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`; `reports/tests/test_fuseki_archive_acquisition.py` è `dee2ca8813565043b20798a634743edcf0fd5f20`. `git diff --name-status 80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c 86a8a2b5a6c14334a773fdd139ae986c373ef308` cambia solo quattro percorsi: `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`, `reports/evidence/G2/MANIFEST.json`, `reports/evidence/G2/OCOR-DEV-0072.requalified-rem0069.json` e `reports/evidence/G2/OCOR-DEV-0072.requalified-rem0069.log`. Il diff fra `7cf4c23e91b49b34a28ead075f25094254556764` e l'HEAD rifiutato cambia solo il record dell'unità.

La campagna a quattro corsie sul commit `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` resta quella già registrata: 5826 test, 0 failure, 0 errori, 0 skip, corsie 1, 1854, 2436 e 1535, durata 1867,554 s, `campaign_result.json` sha256 `5f525930ddb6d929b61375642c76e9a44161a01e263d325a208f59b55067c4ea`. Non si trasferisce da sola. Non si ripete in questa pubblicazione.

Tre finding del ciclo 1 sono bloccanti. Due non lo sono.

VF-001 è di evidenza ed è bloccante. Il punto 3 di `OCOR-DEV-REM-0069-NO-GO (2026-11-24)` chiede che i controlli sull'albero di evidenza e sul piano nominino l'HEAD finale come commit di esecuzione. Il record, alle righe 161, 170, 179, 188, 197, 206, 214 e 222, nomina `7cf4c23e91b49b34a28ead075f25094254556764`, che è il parent dell'HEAD. Il verifier ha rieseguito i due `scripts/check_execution_commit_inputs.py` sull'HEAD finale: PASS, con head `86a8a2b5a6c14334a773fdd139ae986c373ef308` e SHA-256 `395b840eb772ab8a5c436c923a5ed927572851a4d178aff1bb4a95f09f546f13` e `6eb252cc105a0646d6e68a3b1b89989d9406ec809a386d04077d9e21e652931c`, diversi da quelli attestati. Drift, i quattro validatori di manifest e il piano sono passati nella verifica indipendente. La causa è strutturale: l'impronta di una prova che legge il record non può stare dentro il commit che la prova nomina come esecuzione, perché scriverla cambia l'albero.

VF-002 è di evidenza ed è bloccante. Il punto 1 della stessa decisione dice che l'equivalenza non vale se un test raccolto legge dalla repository, e non da una directory temporanea, uno dei quattro percorsi, `reports/evidence/G2`, `reports/assurance/OCOR-DEV-REM-0069-RCCAD`, oppure l'albero `reports/`. Il `git grep` sul commit di campagna è riproducibile: 64 righe, stdout sha256 `c19f3e5e5ad5dd236d508bd559ccc8ea54dc53dd8e42f94781724a4151b2811e`. Il ciclo 1 ha registrato `EQUIVALENCE_HOLDS` restringendo l'esito ai quattro percorsi e a due directory. `ocor-runtime/tests/tasks/test_ocor_dev_0050.py` alle righe 71 e 74, sul commit di campagna, apre `reports/contracts/governed-memory-item.schema.json` e `reports/contracts/ocor-governed-memory.openapi.yaml`. Il verifier ha osservato entrambe le letture durante `pytest --collect-only`. Il modulo e `reports/contracts` sono identici fra il commit di campagna e l'HEAD. L'equivalenza dichiarata non regge la regola adottata.

VF-003 non è bloccante. Manca nel record la traccia del controllo preventivo sull'allowlist che associ tutti i percorsi dei manifest e dei quattro record, con HEAD, esito e digest del log.

VF-004 non è bloccante. È il difetto preesistente già disposto come `NOT_CORRECTED`. L'esecuzione indipendente ha prodotto 97 PASS e 1 FAIL. `CANONICAL_COMMIT` R1 senza Human Gate attende `REJECT` e ottiene `ACCEPT`. Il test e ADD v1.1 sono byte-identici a `origin/main`. Non si corregge e non si segna `PASS`.

VF-005 è bloccante ed è di ambiente. Dopo il bootstrap PASS, il modulo live di `OCOR-DEV-0049` ha registrato 43 errori di setup nella corsia 2 e 48 nella corsia 4. L'errore ripetuto è HTTP 429 da Docker Hub sulla risoluzione del digest di `python:3.11`. L'ammissione preventiva `PULL-BUDGET-CORSIE-SOGLIE` è `NOT_EXECUTED`: la misura è stata presa dopo l'avvio, alle 19:21:32 UTC, con 50 pull residui su 100 per ora. La suite live non è completa: mancano 2423 identificativi. Non è un fallimento di asserzione del codice di acquisizione. Non autorizza da solo un'altra campagna.

Classi dei finding bloccanti. La classe è il controllo obbligatorio del verifier. VF-005 non entra nel confronto di classe come Evidenza: è l'ambiente del verifier.

| Verdetto | Finding | Classe | Bloccante |
| --- | --- | --- | --- |
| `OCOR-DEV-REM-0069-38e15d2cb337-0` | VF-001, prove non attestate sull'HEAD finale | Evidenza | sì |
| `OCOR-DEV-REM-0069-38e15d2cb337-0` | VF-002, gate rapido e autocontrollo non vincolati al record | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-001, prove attestate sul parent e non sull'HEAD finale | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-002, letture di `reports/` e equivalenza dichiarata | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-005, HTTP 429 Docker Hub, ammissione preventiva non eseguita | Ambiente del verifier | sì |

La causa comune della classe Evidenza è una sola. Il commit che registra il risultato è successivo al commit su cui la prova è stata eseguita. Se la regola chiede che la prova nomini come esecuzione il commit che contiene la registrazione, la riesecuzione legge un albero diverso e l'impronta non coincide. La stessa regola, al punto 1, tratta ogni lettura di `reports/` come rottura dell'equivalenza anche quando i byte letti non fanno parte del delta.

`OCOR-DEV-REM-0066` resta senza ciclo 4 finché l'unità del punto 4 di `CONFINE-G6 (2026-11-20)` non è integrata. Il candidato `3b2ee600ee5d9e3055e3d916628d958635fefff3` non si modifica e non si mergia. Il branch di codice di `OCOR-DEV-REM-0068` non parte finché `OCOR-DEV-REM-0069` non è su `origin/main`. La decisione `OCOR-DEV-REM-0068-CURRENT-HEAD-READING (2026-11-24)` è un'altra unità: il file al commit `287c6a9f29b5123320185f579439b1dc95684b75` ha sha256 `17e9c2e73dc44f516d95fd8f55b5294419ea58c48cbdba8541092872e56202f6`. Questa pubblicazione non modifica quel file e non allinea il contratto.

Non si rilanciano i run `45139159711`, `45139159581`, `45139159701`, `45116784337` e `45147805219`. Non si apre una pull request del candidato. Non si tocca la PR #722 né il commit `7b0b90ee79bdae51b22365faca2a54159502a44f`. Non si apre un `repair_cycle` 14. Non si avvia `OCOR-DEV-REM-0060`. Non si modifica `scripts/validate_ocor_development_plan.py` né `reports/planning/OCOR_PLAN_RUN_STATE.json`.

## Quesito

I due `NO_GO` di `OCOR-DEV-REM-0069` condividono la classe Evidenza e il tetto di `DECISIONI-AL-PO (2026-11-16)` è esaurito. Il candidato resta fermo. Si riprogetta il legame fra commit di esecuzione e commit di registrazione, così che la prova sia rieseguibile sul commit che l'ha prodotta e la campagna del padre resti ammessa solo se i byte letti non cambiano; si ferma l'unità senza integrazione; oppure si cambia l'harness condiviso di ogni campagna?

## Opzioni

1. **Contratto a due commit, riesecuzione sul commit di esecuzione, campagna del padre ammessa solo sui byte identici.** Non si attua in questa pubblicazione. Il Product Owner supera, solo per `OCOR-DEV-REM-0069`, due frasi già adottate: nel punto 3 di `OCOR-DEV-REM-0069-NO-GO (2026-11-24)`, l'obbligo di nominare l'HEAD finale come commit di esecuzione di ogni prova; nel punto 1 della stessa decisione, la frase per cui ogni lettura dell'albero `reports/` fa cadere l'equivalenza. Il resto di quelle decisioni resta. Non è un ciclo 2. È la ripartenza del punto 4 di `DECISIONI-AL-PO (2026-11-16)`: il conteggio dei verdetti riparte. Un solo ciclo di riprogettazione aggiunge commit nuovi sopra `86a8a2b5a6c14334a773fdd139ae986c373ef308`, senza rebase, reset o force-push. Non modifica i due blob di acquisizione. Non modifica `scripts/validate_ocor_development_plan.py`, `reports/planning/OCOR_PLAN_RUN_STATE.json`, l'harness di campagna, i workflow, le soglie, i timeout o i gate. Il commit di esecuzione di ogni prova del punto 3 è un commit nominato nella riga, diverso dal commit di registrazione che contiene la riga. La campagna resta quella di `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` solo se, prima della richiesta di verifica, il record dimostra tre fatti: il `git grep` resta quello già misurato, sha256 `c19f3e5e5ad5dd236d508bd559ccc8ea54dc53dd8e42f94781724a4151b2811e`; ogni percorso letto dalla repository ha lo stesso blob sul commit di campagna e sul commit di registrazione; nessuno dei quattro percorsi del delta è fra le letture. Se uno di questi fatti manca, la campagna non si trasferisce: una sola campagna nuova sul commit di esecuzione, con la misura di `PULL-BUDGET-CORSIE-SOGLIE` prima dell'avvio, e poi un commit di registrazione il cui `git diff --name-status` contro il commit di esecuzione è limitato al record dell'unità, ai log della campagna e alle voci di manifest già previste. Il verifier riesegue ogni prova sul commit di esecuzione nominato nella riga e confronta comando, esito e SHA-256. Non riesegue quelle prove sul commit di registrazione. Il commit di registrazione è l'HEAD verificato e riporta, in un blocco separato, il `git diff --name-status` contro ogni commit di esecuzione e lo SHA-256 di quel diff. VF-003 si chiude nello stesso record con comando, esito e SHA-256 del controllo preventivo. VF-004 resta `NOT_CORRECTED` e non è `PASS`. VF-005 non si corregge nel codice: se la campagna non si ripete, resta diagnostico e non entra nei conteggi. Poi una sola verifica, verifier di fornitore diverso da xAI, non avviato dall'implementatore. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un altro ciclo: una sola richiesta nuova. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: `scripts/acquire_fuseki_archive.py`, blob `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`, chiede per prima la copia governata in modo anonimo, verifica lo SHA-512 del lock e solo dopo prova le fonti Apache; il consumatore è il record del commit di registrazione, che nomina `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` come esecuzione della campagna e, per ciascuna prova del punto 3, il commit su cui il comando è stato eseguito, e non nomina se stesso come commit di esecuzione. Costo stimato: due iterazioni se la prova dei byte identici passa, senza campagna nuova; quattro se la prova non passa e servono campagna e verifica. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit di questa pubblicazione sopra `86a8a2b5a6c14334a773fdd139ae986c373ef308` | `git rev-parse` del branch prima della ripartenza |
| I due blob di acquisizione restano quelli citati | `git rev-parse` dei due path |
| Ogni prova nomina un commit di esecuzione diverso dal commit di registrazione | righe della tabella del record |
| Il verifier riesegue la prova sul commit nominato | stesso comando, stesso esito, stesso SHA-256 |
| La campagna del padre è ammessa solo con i tre fatti sui byte | `git grep`, confronto dei blob, assenza dei quattro percorsi |
| Se i tre fatti mancano, una sola campagna nuova sul commit di esecuzione | `--expected-head` di quel commit e misura dei pull prima dell'avvio |
| Il diff del commit di registrazione è chiuso | `git diff --name-status` e il suo SHA-256 |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| Allowlist, harness, soglie e gate invariati | nessun altro path nel diff |
| Una sola verifica, verifier di fornitore diverso da xAI | verdetto sull'HEAD esatto |
| Nessun ciclo ulteriore dopo un `NO_GO` | una sola richiesta nuova |

2. **Stop senza integrazione.** Non si attua in questa pubblicazione. Il branch resta `86a8a2b5a6c14334a773fdd139ae986c373ef308` e non si mergia. Non c'è una ripartenza. VF-001 e VF-002 restano aperti. VF-004 resta `NOT_CORRECTED`. Il contratto che ne risulta non aggiunge criteri: l'acquisizione su `origin/main` resta quella precedente a `OCOR-DEV-REM-0069`. Esempio dal produttore al consumatore: il provisioning chiede ancora le tre fonti Apache nell'ordine attuale, con il termine per fonte già fissato; la copia governata non è la prima fonte nel codice di `origin/main`; il record rifiutato non entra nel sigillo. Non è la soluzione completa: il download da `archive.apache.org` misurato dal PO in 723 s resta oltre il tetto di 600 s, e la copia governata pubblicata dal PO non viene usata. Costo stimato: zero iterazioni di implementazione. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit sopra `86a8a2b5a6c14334a773fdd139ae986c373ef308` | `git rev-parse` del branch |
| Nessun merge dell'unità | `origin/main` senza quel commit |
| VF-004 non è `PASS` | nessuna marcatura nel record sigillato |
| Nessuna campagna nuova | assenza di un `campaign_result.json` diverso da quello storico |

3. **Harness condiviso: il risultato della campagna non entra nel commit di esecuzione.** Non si attua in questa pubblicazione. Si cambia `scripts/run_local_lane_campaign.py` e i test che fissano il modo in cui il risultato è registrato, così che ogni unità futura scriva il risultato fuori dall'albero che `--expected-head` ha accettato e il commit verificato sia il commit di esecuzione. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: l'harness esegue la campagna su un HEAD che non contiene il risultato; un artefatto esterno, con comando, esito e SHA-256, è l'unica prova del risultato; il record dentro il commit non può più essere la prova, perché la sua presenza cambia l'albero. Non è la soluzione di questa unità: tocca un harness citato dai record sigillati, riapre la classe dell'allowlist che ha fermato `FUSEKI-ARCHIVE-COPY-20261123`, e lascia la copia governata fuori da `origin/main` finché quella riprogettazione non è integrata. Costo stimato: una decision request normativa separata e più di sei iterazioni, senza chiudere `OCOR-DEV-REM-0069`. Claim invariati.

| Criterio | Prova |
| --- | --- |
| L'harness non scrive il risultato nel commit di esecuzione | diff di `scripts/run_local_lane_campaign.py` e test dedicati |
| Ogni record sigillato che fissa l'harness è riqualificato | inventario `select_most_recent` prima del codice |
| `OCOR-DEV-REM-0069` non si integra in questa opzione | `origin/main` senza l'HEAD rifiutato |
| Serve una richiesta normativa prima del codice | la richiesta nomina l'harness e i record sigillati |

## Raccomandazione

Opzione 1. Elimina la causa dentro l'unità: la prova si riesegue sul commit che l'ha prodotta, e la campagna del padre resta una prova solo se i byte letti non cambiano. I blob di acquisizione e l'harness condiviso restano. L'opzione 2 lascia il provisioning fermo sul termine di 600 s già superato e non consegna la copia governata. L'opzione 3 sposta la causa sull'harness di ogni unità, riapre l'allowlist e non integra questa unità. La raccomandazione non dipende dal numero di comandi. Chi apre questa richiesta non ne applica nessuna opzione.

## Impatto

Unità bloccata da questa richiesta finché è aperta: `OCOR-DEV-REM-0069`. Finché la richiesta è aperta non si modifica né si mergia `86a8a2b5a6c14334a773fdd139ae986c373ef308`, non si apre la sua pull request e non si apre un ciclo 2. Il branch di codice di `OCOR-DEV-REM-0068` non parte finché `OCOR-DEV-REM-0069` non è su `origin/main`. L'allineamento del contratto di `OCOR-DEV-REM-0068`, già deciso da `OCOR-DEV-REM-0068-CURRENT-HEAD-READING (2026-11-24)`, non è bloccato da questa richiesta e non è eseguito da questa pubblicazione. `OCOR-DEV-REM-0066` resta senza ciclo 4 finché l'unità del punto 4 di `CONFINE-G6 (2026-11-20)` non è integrata. `OCOR-DEV-REM-0060` non si avvia.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim da questa pubblicazione. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.
