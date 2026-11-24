# FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO

Stato: `DECIDED_BY_PO`.
Disposition: opzione 1, con le precisazioni dei punti 1–6 della decisione `FUSEKI-ARCHIVE-COPY-20261123-CYCLE3-NO-GO (2026-11-24)`, decisa dal PO di persona, sezione scritta a mano. Il file pubblicato a `f68d7493607c977c1598abd682ef498dd33a050b` resta sha256 `0cc2971920a204c130c5e8be6a09f04362202b03d5ce845fda4c15084dbfb9f5`. Il testo delle opzioni non cambia. Il candidato `24633cc9d4c49749bd33a386020fe0d9f6cf5174` non si modifica e non si mergia. Non è un ciclo 4. L'unità nuova è `OCOR-DEV-REM-0069`, primo identificativo libero misurato su `origin/main` e sui nomi dei branch remoti. Questa pubblicazione non si integra. Claim invariati.

Livello: operativo. Nessun nuovo `DEC-*`.
Chi decide: il Product Owner di persona, come dispone il punto 4 di `DECISIONI-AL-PO (2026-11-16)`, perché la richiesta riguarda un ciclo di riparazione oltre il tetto e l'eventuale stop dell'unità. Nessuna opzione è applicata da questa pubblicazione.
Head di `origin/main` alla pubblicazione: `618e72c00f994e8ea8899914548cc38743aa4569`.
Candidato: branch `governed/fuseki-archive-copy-20261123`, HEAD `24633cc9d4c49749bd33a386020fe0d9f6cf5174`, parent `948479739127d33bc2f69a2c003a4acb5823d8b4`. Nessun commit è aggiunto sopra quell'HEAD da questa pubblicazione. Il candidato non si modifica e non si mergia.
Decisione già adottata per il ciclo 3: `FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO (2026-11-24)`, decisa dal PO di persona, sezione scritta a mano, opzione 2, punti 1–6. Il file pubblicato a `99d22adeea09e060507e7f9bc60f7f5380d37df5` resta sha256 `83620375c84d7cfd09383139314127dd5fbf3d0ef0eabd2b09aea3b72445276d`. Il punto 4 di quella decisione dice che un nuovo `NO_GO` non apre un ciclo 4 e apre una sola richiesta nuova. Questa è quella richiesta.
Implementatore dei cicli 0, 1, 2 e 3: Grok Build, modello `grok-4.7`, fornitore xAI. Verifier del ciclo 3: Codex, fornitore OpenAI, diverso da xAI, non avviato dall'implementatore. Implementatore di questa pubblicazione: Grok Build, modello `grok-4.7`, fornitore xAI.

## Contesto e perimetro

Il verdetto `FUSEKI-ARCHIVE-COPY-20261123-24633cc9d4c4-3` è `NO_GO` sull'HEAD `24633cc9d4c49749bd33a386020fe0d9f6cf5174`, base `618e72c00f994e8ea8899914548cc38743aa4569`, `repair_cycle` 3, creato `2026-11-24T10:36:06.575131Z`, sha256 del documento `38dd2db636c36862b6d5d88f6dbd00c2dc078f2e9b4412224f0364eb557f57de`. Non è un ciclo 4.

Il verdetto precedente dello stesso change set è `FUSEKI-ARCHIVE-COPY-20261123-948479739127-2`, `NO_GO` su `948479739127d33bc2f69a2c003a4acb5823d8b4`, creato `2026-11-24T00:33:43.439842Z`, sha256 `c167a90169ee4e6cdc20101cc670ae729e508ee20248e6ef3bff0723ad0c227d`. I cicli 0 e 1 sono anch'essi `NO_GO`. Il ciclo 3 era l'unico ciclo autorizzato dopo il budget ordinario. Questa pubblicazione non lo riapre.

I blob di produzione del ciclo 3 sono identici a quelli dell'HEAD `48f8f2e54518eba6f740e06ecef723827270b5dd`: `scripts/acquire_fuseki_archive.py` blob `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`, sha256 `c25d013922a86a402e5a6131779a0375c5260ae9bff8b950b505874c8c0c3848`; `reports/tests/test_fuseki_archive_acquisition.py` blob `dee2ca8813565043b20798a634743edcf0fd5f20`, sha256 `9bb58c5880f05b8e0275ce06db97ac4f86ea12e759186aed0edbdfbe7cdd4ce9`. Il diff del ciclo 3 rispetto a `948479739127d33bc2f69a2c003a4acb5823d8b4` è il solo record `reports/assurance/FUSEKI-ARCHIVE-COPY-20261123/FUSEKI-ARCHIVE-COPY-20261123.json`.

Tre finding del ciclo 3 sono bloccanti. Due finding non lo sono.

VF-001 è di perimetro sul file di stato del piano. Il digest del validatore in `reports/planning/OCOR_PLAN_RUN_STATE.json` riga 17 è quello autorizzato, da `c284752fc081be0a9e7ee63da42460aa3e54fd79a562c32ab8bc98d329123827` a `aab5cdf9ec558b3b168e7529143e80663eab481a05630d1c2dbb94854b603da1`, e l'allowlist di `scripts/validate_ocor_development_plan.py` contiene esattamente le 23 voci ammesse dal punto 1 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO (2026-11-24)`. Lo stesso diff `618e72c00f994e8ea8899914548cc38743aa4569..24633cc9d4c49749bd33a386020fe0d9f6cf5174` cambia anche i byte restanti: alle righe 27 e 32 i caratteri `è` diventano la sequenza di escape `\u00e8`, e alle righe 81–82 le chiavi di `validation_summary` passano da `PASS` poi `NOT_EXECUTED` a `NOT_EXECUTED` poi `PASS`, con gli stessi valori 37 e 2. Sostituire soltanto il digest nella copia in memoria del blob di `origin/main` non riproduce i byte dell'HEAD. Il punto 1 di quella decisione limita le modifiche al digest e alle voci elencate.

VF-002 è di evidenza. In `reports/assurance/FUSEKI-ARCHIVE-COPY-20261123/FUSEKI-ARCHIVE-COPY-20261123.json`, `repair_cycle_2.pre_campaign_gate` indica `diagnostic_attempt.exit_file_absent` uguale a `true` per `guards` alla riga 1322, per `mermaid` alla riga 1396 e per `plan` alla riga 1434. I tre file `guards.exit`, `mermaid.exit` e `plan.exit` esistono fuori dal repository, ciascuno contiene `1`, e il log del runner contiene le tre righe di fine con codice 1. I 54 digest verificati dal verdetto corrispondono. Il punto 2a della decisione del ciclo 3 chiede la traccia fedele dei tentativi diagnostici.

VF-003 è di evidenza. Alla riga 45 il record ha `code_commit` `7416e8a128f24945da653756fa30a2488d75bbe3`. Alle righe 507–510 `inputs` fissa `reports/tests/test_fuseki_archive_acquisition.py` a `b24a30f630942f151d7e4697eeb91c70b4f87fc06ab528d71c3b5472f656b073` e `scripts/acquire_fuseki_archive.py` a `23046a9cc08a6b6dadc5a6aadd0e404b60bbe5014dbb205fea4f7906825eccef`. La campagna qualificante alla radice dichiara l'esecuzione `9b27e16cf810f7cf6c11ecd76b53b84b63668ed2`. Il gate del ciclo 2 è misurato su `48f8f2e54518eba6f740e06ecef723827270b5dd`. I digest del codice qualificato, `c25d013922a86a402e5a6131779a0375c5260ae9bff8b950b505874c8c0c3848` e `9bb58c5880f05b8e0275ce06db97ac4f86ea12e759186aed0edbdfbe7cdd4ce9`, stanno nel blocco del gate e non nei campi `inputs` della radice.

VF-004 non è bloccante. `reports/tests/test_schema_conformance.py` resta 97 PASS e 1 FAIL sul caso `CANONICAL_COMMIT` R1 senza Human Gate: atteso `REJECT`, ottenuto `ACCEPT`, a parità di output fra l'HEAD e `origin/main`. Il punto 3 della decisione del ciclo 3 lo mantiene `NOT_CORRECTED`. Non si corregge e non si segna `PASS`.

VF-005 non è bloccante. `self_check.role_scan` riporta comando, nove campi, esiti e SHA-256, e non indica l'HEAD della scansione. `RECORD-ROLES-COHERENCE-SCAN (2026-11-09)` chiede quell'HEAD. Il verifier conferma Grok Build e Cursor di xAI e il ruolo di riserva di Cursor.

Il verdetto registra anche una lettura della quota Docker Hub eseguita dopo l'avvio delle corsie. Non è un finding bloccante. Non autorizza da sola un'altra campagna.

Classi dei finding bloccanti, affiancate. La classe è il controllo obbligatorio del verifier. Per un controllo aggiunto da una decisione del PO, la classe è l'identificativo di quella decisione.

| Verdetto | Finding | Classe | Bloccante |
| --- | --- | --- | --- |
| `FUSEKI-ARCHIVE-COPY-20261123-948479739127-2` | VF-001, 23 voci e digest fuori dal perimetro dei punti 2 e 8 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)` | `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123` | sì |
| `FUSEKI-ARCHIVE-COPY-20261123-948479739127-2` | VF-002, esiti del gate non legati a `48f8f2e54518eba6f740e06ecef723827270b5dd` | Evidenza | sì |
| `FUSEKI-ARCHIVE-COPY-20261123-24633cc9d4c4-3` | VF-001, byte del piano oltre il digest e le 23 voci del punto 1 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO (2026-11-24)` | `FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO` | sì |
| `FUSEKI-ARCHIVE-COPY-20261123-24633cc9d4c4-3` | VF-002, `exit_file_absent` vero mentre i file di uscita esistono | Evidenza | sì |
| `FUSEKI-ARCHIVE-COPY-20261123-24633cc9d4c4-3` | VF-003, `code_commit` e `inputs` della radice non sono il codice qualificato | Evidenza | sì |

La classe Evidenza compare in entrambi i verdetti `NO_GO`. Il punto 2 di `DECISIONI-AL-PO (2026-11-16)` non concede un altro ciclo di riparazione: l'unità torna al progetto. Il punto 4 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO (2026-11-24)` dice la stessa cosa per questo change set. La causa comune è la registrazione: il codice di acquisizione è lo stesso blob fra `48f8f2e54518eba6f740e06ecef723827270b5dd`, `9b27e16cf810f7cf6c11ecd76b53b84b63668ed2` e `24633cc9d4c49749bd33a386020fe0d9f6cf5174`, e i due `NO_GO` del ciclo 2 e del ciclo 3 rifiutano il modo in cui il record e il file di stato del piano fissano quella prova.

`REM-0066-CYCLE3-NO-GO (2026-11-24)` è decisa dal PO di persona, sezione scritta a mano: opzione 3 e, dopo l'integrazione dell'unità che quell'opzione anticipa, opzione 1, con le precisazioni dei punti 1–6. Il file pubblicato a `171708381416e03d3c217efdcb60328e158f5b84` resta sha256 `e44221eb591f62640098bf50295ebdf74d6999880e48803c2f8ba4064e724fcb`. Il candidato `3b2ee600ee5d9e3055e3d916628d958635fefff3` non si modifica e non si mergia. Non è un ciclo 4 di `OCOR-DEV-REM-0066`. Questa pubblicazione non apre il codice dell'unità del punto 4 di `CONFINE-G6 (2026-11-20)`.

Non si rilanciano i run `45139159711`, `45139159581`, `45139159701`, `45116784337` e `45147805219`. Non si apre una pull request di questo change set: il punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)` ammette un solo tentativo CI nuovo dopo `GO_FOR_EVIDENCE_SEAL`, e questo verdetto non è `GO_FOR_EVIDENCE_SEAL`. Non si tocca la PR #722 né il commit `7b0b90ee79bdae51b22365faca2a54159502a44f`. Non si apre un `repair_cycle` 14. Non si avvia `OCOR-DEV-REM-0060`.

## Quesito

Il ciclo 3 è `NO_GO`, il tetto non autorizza un ciclo 4 e la stessa classe Evidenza è bloccante nel ciclo 2 e nel ciclo 3. Il candidato resta fermo. Si apre una unità nuova che conserva i blob di acquisizione già uguali e corregge solo la registrazione; si autorizza in modo esplicito un solo ciclo 4 sullo stesso branch; oppure ci si ferma senza unità nuova?

## Opzioni

1. **Unità nuova, candidato fermo.** Non si attua in questa pubblicazione. `24633cc9d4c49749bd33a386020fe0d9f6cf5174` non riceve commit e non si mergia. Non è un ciclo 4. Una unità nuova, con il primo identificativo libero verificato al momento dell'avvio, parte da `origin/main` e porta gli stessi blob `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` e `dee2ca8813565043b20798a634743edcf0fd5f20`, senza modificarne il comportamento. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: `scripts/acquire_fuseki_archive.py` chiede per prima la copia governata in modo anonimo, accetta solo un redirect HTTPS verso `release-assets.githubusercontent.com`, verifica lo SHA-512 `ba65f5867d2d4741b2ed9e2af5a0d4fbb447909894ab2a0c6bc4dac8997f4fe339c87b13c48d45d054977769f0f8bf763ea346b1f7792d5cdc458041bd43a132` e solo dopo prova le tre fonti Apache; il record della prova corrente nomina il commit qualificato e, in `inputs`, i due digest `c25d013922a86a402e5a6131779a0375c5260ae9bff8b950b505874c8c0c3848` e `9bb58c5880f05b8e0275ce06db97ac4f86ea12e759186aed0edbdfbe7cdd4ce9`; i digest `23046a9cc08a6b6dadc5a6aadd0e404b60bbe5014dbb205fea4f7906825eccef` e `b24a30f630942f151d7e4697eeb91c70b4f87fc06ab528d71c3b5472f656b073` restano in un blocco storico nominato; `reports/planning/OCOR_PLAN_RUN_STATE.json` differisce da `origin/main` solo per il digest del validatore e per le 23 voci già ammesse. Costo stimato: tre iterazioni, una per il record e i byte del piano, una per la campagna a quattro corsie sull'HEAD nuovo, una per la verifica. La campagna già eseguita su `9b27e16cf810f7cf6c11ecd76b53b84b63668ed2` non si trasferisce. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Il candidato `24633cc9d4c49749bd33a386020fe0d9f6cf5174` non cambia e non si mergia | `git rev-parse` del branch e assenza di merge su `origin/main` |
| I due blob di acquisizione restano quelli citati | `git rev-parse` dei due path uguale a `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` e `dee2ca8813565043b20798a634743edcf0fd5f20` |
| Il file di stato del piano cambia solo nel digest autorizzato e nelle 23 voci | diff contro `origin/main` limitato a quei byte |
| `exit_file_absent` è falso quando il file di uscita esiste e contiene `1` | lettura del record sulle tre prove `guards`, `mermaid` e `plan`, distinta dal log del primo tentativo |
| `code_commit` e `inputs` della prova corrente sono il codice qualificato | sha256 dei due file all'HEAD della prova, digest storici in un blocco nominato |
| La scansione dei ruoli indica l'HEAD scandito | campo dell'HEAD nel record, VF-005 |
| VF-004 resta `NOT_CORRECTED` e non è `PASS` | stesso FAIL preesistente, non segnato `PASS` |
| Campagna nuova sull'HEAD dell'unità, zero skip | conteggi della campagna e controllo di unione |
| Una sola verifica, verifier di fornitore diverso da xAI | verdetto sull'HEAD esatto |

2. **Un solo ciclo 4 eccezionale sullo stesso branch.** Non si attua in questa pubblicazione. Il Product Owner autorizza in modo esplicito un solo `repair_cycle` 4, nonostante il punto 2 di `DECISIONI-AL-PO (2026-11-16)` e nonostante il punto 4 di `FUSEKI-ARCHIVE-COPY-20261123-CYCLE2-NO-GO (2026-11-24)`. Il ciclo parte da `24633cc9d4c49749bd33a386020fe0d9f6cf5174`, con commit nuovi, senza rebase, reset o force-push. Non modifica `scripts/acquire_fuseki_archive.py` né `reports/tests/test_fuseki_archive_acquisition.py`. Corregge solo VF-001, VF-002 e VF-003, e indica l'HEAD della scansione dei ruoli. VF-004 non si corregge e non si segna `PASS`. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: lo stesso produttore e gli stessi byte della copia governata dell'opzione 1; il consumatore è il record sullo stesso branch, con `code_commit` e `inputs` del codice qualificato, i tre `exit_file_absent` allineati ai file di uscita, e `reports/planning/OCOR_PLAN_RUN_STATE.json` diverso da `origin/main` solo per il digest e le 23 voci. Poi una sola verifica, verifier di fornitore diverso da xAI. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un ciclo 5: una sola richiesta nuova. Costo stimato: tre iterazioni, perché l'HEAD cambia e la campagna `9b27e16cf810-1795474948` non si trasferisce. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Un solo ciclo 4 da `24633cc9d4c49749bd33a386020fe0d9f6cf5174` | parent del primo commit nuovo e assenza di rebase |
| Nessun file di produzione di acquisizione cambia | blob identici a `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` e `dee2ca8813565043b20798a634743edcf0fd5f20` |
| Byte del piano limitati al digest e alle 23 voci | diff contro `origin/main` |
| Traccia diagnostica fedele e `inputs` della prova corrente | record sulle righe 45, 507–510, 1322, 1396 e 1434, digest storici in un blocco nominato |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| Campagna nuova sull'HEAD del ciclo 4, poi una sola verifica | conteggi e verdetto sull'HEAD esatto |
| Nessun ciclo 5 | un nuovo `NO_GO` apre una sola richiesta |

3. **Stop senza unità nuova.** Non si attua in questa pubblicazione. Il branch resta `24633cc9d4c49749bd33a386020fe0d9f6cf5174` e non si mergia. Non c'è un ciclo 4 e non si apre un'altra unità per la copia governata. VF-001, VF-002 e VF-003 restano aperti. VF-004 resta `NOT_CORRECTED`. Il contratto che ne risulta non aggiunge criteri: l'acquisizione su `origin/main` resta quella precedente a questo change set. Esempio dal produttore al consumatore: il provisioning chiede ancora le tre fonti Apache nell'ordine attuale, `archive.apache.org` ultima, con il termine per fonte già fissato; la copia governata non è la prima fonte nel codice di `origin/main`; il record rifiutato non entra nel sigillo. Non è la soluzione completa: il provisioning che ha esaurito il termine di 120 s sulla fonte Apache ancora viva resta quello di `origin/main`. Costo stimato: zero iterazioni di implementazione. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit sopra `24633cc9d4c49749bd33a386020fe0d9f6cf5174` | `git rev-parse` del branch |
| Nessun merge del change set | `origin/main` senza quel commit |
| VF-004 non è `PASS` | nessuna marcatura nel record sigillato |
| Nessuna unità nuova per la copia | nessun branch di codice nuovo di questa acquisizione |

## Raccomandazione

Opzione 1. I due `NO_GO` condividono la classe Evidenza, e le decisioni già adottate non concedono un ciclo 4. I blob di acquisizione sono già gli stessi fra il gate, la campagna e l'HEAD rifiutato: l'opzione 1 li conserva in un'unità nuova e corregge la registrazione, senza presentare il commit rifiutato come riparazione. L'opzione 2 è più corta solo se si conta il branch, e richiede una eccezione esplicita al tetto. L'opzione 3 lascia il provisioning fermo sul termine già esaurito. La raccomandazione non dipende dal numero di comandi. Chi apre questa richiesta non ne applica nessuna opzione.

## Impatto

Unità bloccata da questa richiesta finché è aperta: il change set `FUSEKI-ARCHIVE-COPY-20261123`. Finché la richiesta è aperta non si modifica né si mergia `24633cc9d4c49749bd33a386020fe0d9f6cf5174`, non si apre la sua pull request, non si apre un ciclo 4 e non si apre il branch di codice dell'unità che separa l'etichetta Fuseki della CI. Il contratto di quell'unità, già pubblicato, non è un branch di codice: questa richiesta non lo modifica. `OCOR-DEV-REM-0066` resta senza ciclo 4 finché l'unità del punto 4 di `CONFINE-G6 (2026-11-20)` non è integrata, come dispone `REM-0066-CYCLE3-NO-GO (2026-11-24)`. `OCOR-DEV-REM-0060` non si avvia.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim da questa pubblicazione. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.
