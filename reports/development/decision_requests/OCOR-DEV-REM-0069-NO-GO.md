# OCOR-DEV-REM-0069-NO-GO

Stato: `OPEN_PO_DECISION_REQUIRED`.
Disposition: nessuna. Nessuna opzione è applicata da questa pubblicazione. Il candidato non si modifica e non si mergia. Non è un ciclo di riparazione. Questa pubblicazione non si integra. Claim invariati.

Livello: operativo. Nessun nuovo `DEC-*`.
Chi decide: il Product Owner di persona, come dispone il punto 4 di `DECISIONI-AL-PO (2026-11-16)`, perché la richiesta riguarda un ciclo di riparazione e l'eventuale stop dell'unità. Nessuna opzione è applicata da questa pubblicazione.
Head di `origin/main` alla pubblicazione: `618e72c00f994e8ea8899914548cc38743aa4569`.
Candidato: branch `governed/ocor-dev-rem-0069-fuseki-archive-copy`, HEAD `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`, parent `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`. Nessun commit è aggiunto sopra quell'HEAD da questa pubblicazione. Il candidato non si modifica e non si mergia.
Decisione che impone questa richiesta: punto 5 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24)`, decisa dal PO di persona, sezione scritta a mano. Il file pubblicato a `f68d7493607c977c1598abd682ef498dd33a050b` resta sha256 `0cc2971920a204c130c5e8be6a09f04362202b03d5ce845fda4c15084dbfb9f5`. Quel punto dice che dopo un `NO_GO` dell'unità nuova c'è una sola richiesta nuova. Questa è quella richiesta. Il candidato precedente `24633cc9d4c49749bd33a386020fe0d9f6cf5174` non si modifica e non si mergia. Non è un ciclo 4 di quel change set.
Implementatore dell'unità: Grok Build, modello `grok-4.7`, fornitore xAI. Revisore preventivo di riserva: Cursor, modello `cursor-grok-4.6-xhigh`, fornitore xAI, stesso fornitore dell'implementatore, limite di indipendenza già dichiarato nel record. Verifier: Codex, fornitore OpenAI, modello `NOT_EXPOSED_BY_RUNTIME`, diverso da xAI, non avviato dall'implementatore. Implementatore di questa pubblicazione: Grok Build, modello `grok-4.7`, fornitore xAI.

## Contesto e perimetro

Il verdetto `OCOR-DEV-REM-0069-38e15d2cb337-0` è `NO_GO` sull'HEAD `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`, creato `2026-11-24T14:36:54.951438Z`, sha256 del documento `996851f078775d08f9465a28800e6a5cbc505e6e3ef46c2763c6ecd5df6ada63`. L'identificativo della richiesta finisce con `-0`. Il documento del verdetto non ha un campo `repair_cycle`. È la prima verifica dell'unità, non un ciclo di riparazione.

L'unità `OCOR-DEV-REM-0069` prende il posto del change set `FUSEKI-ARCHIVE-COPY-20261123`, come dispone il punto 1 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24)`. I blob di produzione sono gli stessi su `34a66b063b7867ed938828f9f5affbc0d35f1d52`, su `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` e sull'HEAD rifiutato: `scripts/acquire_fuseki_archive.py` è `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`; `reports/tests/test_fuseki_archive_acquisition.py` è `dee2ca8813565043b20798a634743edcf0fd5f20`.

Il commit di campagna è `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`, albero `b8ceda7a88933cbc0c4c1732e2680fa3bebe406c`. La campagna a quattro corsie è PASS: 5826 test, 0 failure, 0 errori, 0 skip, corsie 1, 1854, 2436 e 1535, durata 1867,554 s, `campaign_result.json` sha256 `5f525930ddb6d929b61375642c76e9a44161a01e263d325a208f59b55067c4ea`. Il comando della campagna fissa `--expected-head 80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`. Il controllo distinto di unione è PASS, stdout sha256 `e9220cfd0f43fa0b62eb1d0e239eac11a030499795270df30ff0a87d8137f709`.

L'HEAD di evidenza è `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`, albero `0714e19a93a3bbda8049824a3e952fd7477ca8bb`. `git diff --name-status 80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c 38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5` cambia solo quattro percorsi: `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`, `reports/evidence/G2/MANIFEST.json`, `reports/evidence/G2/OCOR-DEV-0072.requalified-rem0069.json` e `reports/evidence/G2/OCOR-DEV-0072.requalified-rem0069.log`.

Due finding sono bloccanti. Tre non lo sono.

VF-001 è di evidenza. Il punto 4 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24)` chiede comando, esito e SHA-256 di ogni prova della tabella sull'HEAD finale. Nel record pubblicato le otto prove eseguite non nominano, nella riga, il commit su cui il comando è stato eseguito. La riga della campagna fissa il padre `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`. I digest di candidato, blob, piano, ruoli ed exit sono stati verificati dal verifier, e la tabella non li attesta come eseguiti su `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`. La prova indipendente sull'HEAD non colma la lacuna di provenienza.

VF-002 è di evidenza. Il record attesta la lettura dei tre exit file e non vincola `gates.json` del gate rapido, con i 50 passi, gli esiti `EXPECTED_FAIL`, `PASS_AFTER_RERUN` e `NOT_CORRECTED`, il commit e i digest dei log. Nel record non c'è la traccia comando, esito e SHA-256 di `scripts/check_execution_commit_inputs.py` sui quattro record di riqualifica. Il verifier ha rieseguito quel controllo e il validatore del piano, entrambi PASS.

VF-003 non è bloccante. `environment.clean_shell` è false. Il lancio sotto `env -i` è attestato dalla stessa stringa e dallo script conservato. Il record non distingue il wrapper esterno dal processo della campagna.

VF-004 non è bloccante. È il difetto preesistente già disposto come `NOT_CORRECTED`. `CANONICAL_COMMIT` R1 senza Human Gate attende `REJECT` e ottiene `ACCEPT`. 97 PASS, un FAIL, exit 1, stdout sha256 `cadf3a414a3833681f45f7bd9007a9be05dc252de470af7e1de1a484e7c5a936`. Test e ADD v1.1 sono identici alla base. Non si corregge e non si segna `PASS`.

VF-005 non è bloccante. L'inventario dei percorsi nel record elenca i file di codice, di test e del validatore. Non attesta la prova, prima della campagna, dei record e dei manifest pubblicati, con HEAD, esito e digest del log.

Il verdetto registra anche, fra i controlli non eseguiti, l'ispezione diretta dell'etichetta host di Fuseki prima del provisioning. Non è un finding. Non autorizza da sola un'altra campagna.

Classi dei finding bloccanti. La classe è il controllo obbligatorio del verifier. Per un controllo aggiunto da una decisione del PO, la classe è l'identificativo di quella decisione.

| Verdetto | Finding | Classe | Bloccante |
| --- | --- | --- | --- |
| `FUSEKI-ARCHIVE-COPY-20261123-948479739127-2` | VF-002, esiti del gate non legati all'HEAD di esecuzione | Evidenza | sì |
| `FUSEKI-ARCHIVE-COPY-20261123-24633cc9d4c4-3` | VF-002 e VF-003, traccia diagnostica e `inputs` della prova corrente | Evidenza | sì |
| `OCOR-DEV-REM-0069-38e15d2cb337-0` | VF-001, prove non attestate sull'HEAD finale | Evidenza | sì |
| `OCOR-DEV-REM-0069-38e15d2cb337-0` | VF-002, gate rapido e autocontrollo non vincolati al record | Evidenza | sì |

La classe Evidenza è la stessa dei due `NO_GO` del change set sostituito. Quei verdetti non sono verdetti di `OCOR-DEV-REM-0069`. Per questa unità il punto 2 di `DECISIONI-AL-PO (2026-11-16)` vede un solo `NO_GO` e ammetterebbe un ciclo di riparazione. Il punto 5 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24)` non lo fa partire: chiede prima questa richiesta. La causa è ancora la registrazione. I blob di acquisizione non cambiano fra il commit di codice, il commit di campagna e l'HEAD rifiutato. Il comando di campagna deve conoscere l'HEAD prima di produrre il risultato, quindi il commit che registra il risultato è successivo all'HEAD di esecuzione. Senza una disposizione sull'equivalenza di quel commit, la prova non sta sull'HEAD che il verifier legge.

`OCOR-DEV-REM-0066` resta senza ciclo 4 finché l'unità del punto 4 di `CONFINE-G6 (2026-11-20)` non è integrata, come dispone `REM-0066-CYCLE3-NO-GO (2026-11-24)`. Il candidato `3b2ee600ee5d9e3055e3d916628d958635fefff3` non si modifica e non si mergia. Il contratto di quell'unità, revisione `OCOR-DEV-REM-0068-6c52de0657a6-pre`, esito `BLOCKING_FINDINGS`, sha256 `e959a0de2fb2ab1297d2bd16218b51ceb91c33d5af163f8611df4020664c4b95`, non è un branch di codice. Questa pubblicazione non lo modifica. Non si apre il branch di codice di `OCOR-DEV-REM-0068` finché `OCOR-DEV-REM-0069` non è su `origin/main`. Non si avvia la sua campagna qualificante.

Non si rilanciano i run `45139159711`, `45139159581`, `45139159701`, `45116784337` e `45147805219`. Non si apre una pull request del candidato: il punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)` ammette un solo tentativo CI nuovo dopo `GO_FOR_EVIDENCE_SEAL`, e questo verdetto non è `GO_FOR_EVIDENCE_SEAL`. Non si tocca la PR #722 né il commit `7b0b90ee79bdae51b22365faca2a54159502a44f`. Non si apre un `repair_cycle` 14. Non si avvia `OCOR-DEV-REM-0060`.

## Quesito

Il primo verdetto di `OCOR-DEV-REM-0069` è `NO_GO` sulla registrazione della prova. Il candidato resta fermo. Si autorizza un solo ciclo di sola registrazione che conserva la campagna già eseguita sul padre, con equivalenza esplicita del commit di sola evidenza; si autorizza un solo ciclo che ripete la campagna e applica la stessa regola al commit successivo del risultato; oppure ci si ferma senza riparazione?

## Opzioni

1. **Un solo ciclo di registrazione, campagna del padre ammessa.** Non si attua in questa pubblicazione. Il Product Owner dispone l'equivalenza del commit di sola evidenza per la campagna già eseguita. L'albero di esecuzione è `b8ceda7a88933cbc0c4c1732e2680fa3bebe406c` del commit `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`. L'albero di evidenza rifiutato è `0714e19a93a3bbda8049824a3e952fd7477ca8bb`. Il delta ammesso fra i due è soltanto i quattro percorsi elencati nel contesto. L'unione JUnit ammessa è 5826 raccolti, 5826 eseguiti, corsie 1, 1854, 2436 e 1535, zero skip, `campaign_result.json` sha256 `5f525930ddb6d929b61375642c76e9a44161a01e263d325a208f59b55067c4ea`, controllo distinto stdout sha256 `e9220cfd0f43fa0b62eb1d0e239eac11a030499795270df30ff0a87d8137f709`. `scanned_head` resta `34a66b063b7867ed938828f9f5affbc0d35f1d52`. Il commit di campagna e l'HEAD di evidenza restano valori distinti. Un solo `repair_cycle` 1 parte da `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`, con commit nuovi, senza rebase, reset o force-push. Non modifica `scripts/acquire_fuseki_archive.py` né `reports/tests/test_fuseki_archive_acquisition.py`. Non modifica `scripts/validate_ocor_development_plan.py` né `reports/planning/OCOR_PLAN_RUN_STATE.json`. Non rilancia la campagna. Corregge VF-001 e VF-002 nel record: ogni prova nomina il commit di esecuzione, il comando, l'esito e lo SHA-256; un blocco separato nomina l'HEAD finale, il `git diff --name-status` contro il commit di esecuzione e lo SHA-256 di quel diff. Il gate rapido è vincolato con commit, comandi, esiti e impronte, e i tentativi diagnostici restano distinti dai risultati accettati. I quattro record di riqualifica hanno comando, esito e SHA-256 di `scripts/check_execution_commit_inputs.py`. VF-003 e VF-005 si correggono nello stesso record, senza segnarli `PASS` prima della correzione. VF-004 resta `NOT_CORRECTED` e non è `PASS`. Se la correzione richiede un percorso nuovo o un file di produzione, ci si ferma e si apre una sola richiesta secondo la regola vigente per le decision request. Poi una sola verifica, verifier di fornitore diverso da xAI, non avviato dall'implementatore. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un ciclo 2: una sola richiesta nuova. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: `scripts/acquire_fuseki_archive.py`, blob `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`, chiede per prima la copia governata in modo anonimo, verifica lo SHA-512 del lock e solo dopo prova le fonti Apache; il consumatore è il record sull'HEAD del ciclo 1, che nomina il commit `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` come esecuzione della campagna e l'HEAD finale come commit di registrazione, con il delta dei quattro percorsi. Costo stimato: due iterazioni, una per il record e una per la verifica. La campagna non si ripete. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit di questa pubblicazione sopra `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5` | `git rev-parse` del branch prima del ciclo 1 |
| Un solo ciclo 1, senza rebase | parent del primo commit nuovo |
| I due blob di acquisizione restano quelli citati | `git rev-parse` dei due path |
| Nessuna campagna nuova | assenza di un `campaign_result.json` diverso da `5f525930ddb6d929b61375642c76e9a44161a01e263d325a208f59b55067c4ea` |
| Ogni prova nomina il proprio commit di esecuzione | righe della tabella del record |
| L'HEAD finale è un blocco separato, con il diff e il suo SHA-256 | blocco del record, distinto da `scanned_head` e dal commit di campagna |
| Gate rapido e autocontrollo dei quattro record sono vincolati | comando, esito e SHA-256 nel record |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| Una sola verifica, verifier di fornitore diverso da xAI | verdetto sull'HEAD esatto |
| Nessun ciclo 2 | un nuovo `NO_GO` apre una sola richiesta |

2. **Un solo ciclo con campagna nuova, stessa regola sul commit del risultato.** Non si attua in questa pubblicazione. Il Product Owner non ammette la campagna già eseguita come prova dell'HEAD finale. Autorizza un solo `repair_cycle` 1 da `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`, con commit nuovi, senza rebase, reset o force-push. Prima della campagna il record corregge VF-001, VF-002, VF-003 e VF-005 nei limiti dell'opzione 1, e VF-004 resta `NOT_CORRECTED`. La campagna a quattro corsie è una sola e gira sul commit che contiene già quelle correzioni. Il commit successivo, che registra il risultato, è ammesso solo se il suo `git diff --name-status` contro il commit di campagna è limitato ai campi di risultato del record dell'unità e ai log della campagna già previsti, senza file di produzione e senza un'altra modifica di `scripts/validate_ocor_development_plan.py` o di `reports/planning/OCOR_PLAN_RUN_STATE.json`. Quel delta, l'albero del commit di campagna, l'albero del commit di registrazione e l'unione JUnit si fissano nel record come valori distinti da `scanned_head`. I blob `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` e `dee2ca8813565043b20798a634743edcf0fd5f20` restano. La campagna `5f525930ddb6d929b61375642c76e9a44161a01e263d325a208f59b55067c4ea` non si trasferisce e resta storica. Poi una sola verifica, verifier di fornitore diverso da xAI, non avviato dall'implementatore. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un ciclo 2: una sola richiesta nuova. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: lo stesso produttore e gli stessi blob dell'opzione 1; il consumatore è il record del commit di registrazione, che nomina il commit su cui `--expected-head` ha accettato la campagna nuova e, in un blocco separato, il proprio HEAD e il delta ammesso. Costo stimato: tre iterazioni, una per il record, una per la campagna, una per la verifica. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Un solo ciclo 1 da `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5` | parent del primo commit nuovo e assenza di rebase |
| Campagna nuova sul commit che contiene le correzioni del record | `--expected-head` uguale a quel commit, conteggi e zero skip |
| Il commit del risultato ha solo il delta ammesso | `git diff --name-status` contro il commit di campagna |
| I due blob di acquisizione restano quelli citati | `git rev-parse` dei due path |
| `scanned_head`, commit di campagna e HEAD di registrazione sono distinti | tre campi del record |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| La campagna precedente non trasferisce conteggi | resta nominata come storica |
| Una sola verifica | verdetto sull'HEAD esatto |
| Nessun ciclo 2 | un nuovo `NO_GO` apre una sola richiesta |

3. **Stop senza riparazione.** Non si attua in questa pubblicazione. Il branch resta `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5` e non si mergia. Non c'è un ciclo 1. VF-001 e VF-002 restano aperti. VF-004 resta `NOT_CORRECTED`. Il contratto che ne risulta non aggiunge criteri: l'acquisizione su `origin/main` resta quella precedente a `OCOR-DEV-REM-0069`. Esempio dal produttore al consumatore: il provisioning chiede ancora le tre fonti Apache nell'ordine attuale, con il termine per fonte già fissato; la copia governata non è la prima fonte nel codice di `origin/main`; il record rifiutato non entra nel sigillo. Non è la soluzione completa: il provisioning che ha esaurito il termine di 120 s sulla fonte Apache ancora viva resta quello di `origin/main`. Costo stimato: zero iterazioni di implementazione. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit sopra `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5` | `git rev-parse` del branch |
| Nessun merge dell'unità | `origin/main` senza quel commit |
| VF-004 non è `PASS` | nessuna marcatura nel record sigillato |
| Nessuna campagna nuova e nessun ciclo 1 | assenza di un repair cycle e di un `campaign_result.json` nuovo |

## Raccomandazione

Opzione 1. L'unità ha un solo `NO_GO`, i blob di acquisizione sono identici fra codice, campagna e HEAD rifiutato, e la campagna già eseguita è verde. Il punto 5 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24)` chiede questa richiesta prima di ogni riparazione, e l'azione indicata dal verifier per la campagna sul padre è proprio la disposizione di equivalenza che l'opzione 1 contiene. L'opzione 2 ripete una campagna di 5826 test il cui codice sotto prova non cambia, e deve comunque ammettere un commit di risultato successivo all'esecuzione. L'opzione 3 lascia il provisioning fermo sul termine già esaurito. La raccomandazione non dipende dal numero di comandi. Chi apre questa richiesta non ne applica nessuna opzione.

## Impatto

Unità bloccata da questa richiesta finché è aperta: `OCOR-DEV-REM-0069`. Finché la richiesta è aperta non si modifica né si mergia `38e15d2cb3379aecd62e2a7e4c20b5888e4ecae5`, non si apre la sua pull request, non si apre un ciclo 1 e non si apre il branch di codice di `OCOR-DEV-REM-0068`. Il contratto di `OCOR-DEV-REM-0068` già pubblicato non è modificato da questa pubblicazione. `OCOR-DEV-REM-0066` resta senza ciclo 4 finché l'unità del punto 4 di `CONFINE-G6 (2026-11-20)` non è integrata. `OCOR-DEV-REM-0060` non si avvia.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim da questa pubblicazione. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.
