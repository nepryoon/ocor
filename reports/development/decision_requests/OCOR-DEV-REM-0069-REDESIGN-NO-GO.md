# OCOR-DEV-REM-0069-REDESIGN-NO-GO

Stato: `DECIDED_BY_PO`.
Disposition: opzione 1, con le precisazioni dei punti 1–8 della decisione `OCOR-DEV-REM-0069-REDESIGN-NO-GO (2026-11-25)`, decisa dal PO di persona, sezione scritta a mano. Il file pubblicato a `98ba5a86dc02d31e9da9f371178171b6272fa428` resta sha256 `356e23c1a5f5614fa0897bed214b9d4ec152a7acb383b52c649609920a8ccc9a`. Il testo delle opzioni non cambia. Il commit di registrazione è `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9`, parent `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f`, sul branch `governed/ocor-dev-rem-0069-fuseki-archive-copy`. L'unico percorso cambiato è `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`. Nessuna pull request del candidato. VF-004 resta `NOT_CORRECTED` e non è `PASS`.
Livello: operativo. Nessun nuovo `DEC-*`.
Chi decide: il Product Owner di persona, come dispone il punto 4 di `DECISIONI-AL-PO (2026-11-16)`, perché la richiesta riguarda lo stop di un'unità dopo il `NO_GO` dell'unico ciclo di riprogettazione. L'opzione 1 è adottata dalla sezione scritta a mano.
Head di `origin/main` alla pubblicazione: `618e72c00f994e8ea8899914548cc38743aa4569`.
Candidato: branch `governed/ocor-dev-rem-0069-fuseki-archive-copy`. Il commit di registrazione è `e70fa15f6c92e7a8e3364e42e5b42d0793de5ec9`, parent `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f`. L'unico percorso cambiato è `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`. Nessuna pull request. Il candidato non è su `origin/main`.
Decisione che impone questa richiesta: il punto 7 di `OCOR-DEV-REM-0069-REDESIGN (2026-11-25)`. Il file di `OCOR-DEV-REM-0069-REDESIGN` al commit `60012a42f365f401c940bddff061b5be906b45f6` resta sha256 `61025b5e3555f6b26e2e13bfa426d06615b2a3cd08d5b370ec7e91c7d4920f44`. L'opzione 1 di quella richiesta è già applicata. Questa pubblicazione non cambia quel file e non applica una nuova opzione.
Implementatore dell'unità: Grok Build, modello `grok-4.7`, fornitore xAI. Revisore preventivo di riserva: Cursor, modello `cursor-grok-4.6-xhigh`, fornitore xAI, stesso fornitore dell'implementatore, limite di indipendenza già dichiarato nel record. Verifier di questo verdetto: Codex, fornitore OpenAI, modello `NOT_EXPOSED_BY_RUNTIME`, diverso da xAI, non avviato dall'implementatore. Implementatore di questa pubblicazione: Grok Build, modello `grok-4.7`, fornitore xAI.

## Contesto e perimetro

Il verdetto `OCOR-DEV-REM-0069-7ba88cfb3eb0-0` è `NO_GO` sull'HEAD `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f`, creato `2026-11-25T15:09:57.916097Z`, sha256 del documento `f4b81ba58709603142419c7a8dec51647d0e62fd43b746f40ae51b46124654e2`. È la verifica dell'unico ciclo di riprogettazione autorizzato da `OCOR-DEV-REM-0069-REDESIGN (2026-11-25)`. La richiesta di verifica porta `repair_cycle` 0 del conteggio ripartito. Non è un ciclo ulteriore.

I blob di produzione restano quelli fissati, sull'HEAD rifiutato come sul commit di campagna `eaae5f0de47ce1b082e36257ac17c422ae78844a`: `scripts/acquire_fuseki_archive.py` è `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`; `reports/tests/test_fuseki_archive_acquisition.py` è `dee2ca8813565043b20798a634743edcf0fd5f20`. `git diff --name-status 80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c 7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f` contiene soltanto i quattro percorsi già ammessi: il record dell'unità, `reports/evidence/G2/MANIFEST.json`, `reports/evidence/G2/OCOR-DEV-0072.requalified-rem0069.json` e `reports/evidence/G2/OCOR-DEV-0072.requalified-rem0069.log`. Lo stdout di quel diff ha sha256 `c4b30a7459f096ed797683f44c2e4f60baedab2ce5cb603b823d25b405be7000`. `git diff --name-status c7ccdf86c90c872dc4b916c7cb840bb9e9451cad 7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f` contiene soltanto il record dell'unità.

La campagna a quattro corsie `eaae5f0de47c-1795613672` sul commit `eaae5f0de47ce1b082e36257ac17c422ae78844a` resta quella registrata: 5826 test, 0 failure, 0 errori, 0 skip, durata 1890,81 s, `campaign_result.json` sha256 `9ba50b61daffc27fe28e12d44ee12e89ab1d4d41c8b8e47fd71e3eb4713d321a`. La verifica indipendente ha rieseguito la campagna sullo stesso HEAD. Il primo tentativo del verifier è fallito prima di avviare le corsie per quota del disco (`copy-fd: Disk quota exceeded`), senza asserzioni fallite, risultato sha256 `216ee2e3691c03e6e9329099a96a498060b2132bf9f26858ff564f01cc9cf976`. Il secondo tentativo è PASS: 4 corsie, 1871,145 s, 5826 test, 0 failure, 0 errori, 0 skip, ripartizione 1, 1854, 2436 e 1535, unione esatta, risultato sha256 `e8fcd9fb8d852134170d37306aa39189a5d4a77018277d874c1fa3d2a4372f71`. Non si ripete in questa pubblicazione.

Quattro finding sono bloccanti. Uno non lo è.

VF-001 è di evidenza ed è bloccante. Il punto 2 di `OCOR-DEV-REM-0069-REDESIGN (2026-11-25)` chiede un comando rieseguibile a ogni riga di prova. Nel record, la riga 127 invoca `python3 /tmp/rem0069_scan_roles.py` su un percorso fisso fuori dal commit nominato. Le righe 238, 247 e 255 contengono descrizioni, non comandi: «sha256 of the three manifests and the four rem0069 requalification records», «bind pregate-80a2c854/gates.json: commit, 50 commands, statuses, exit codes and log sha256 values» e «set environment.clean_shell true for the campaign process…». Gli hash dei dati sono controllabili. Queste quattro righe non permettono la replica fedele del comando sul commit dichiarato.

VF-002 è di evidenza ed è bloccante. Il punto 3 della stessa decisione richiede le quattro misure anche per la campagna sostitutiva. Il record riporta le misure b, c e d per `eaae5f0de47ce1b082e36257ac17c422ae78844a`. Le due righe `git grep` puntano entrambe a `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`, con stdout sha256 `c19f3e5e5ad5dd236d508bd559ccc8ea54dc53dd8e42f94781724a4151b2811e`. Il comando `git grep -n -I reports eaae5f0de47ce1b082e36257ac17c422ae78844a -- ocor-runtime/tests` produce stdout sha256 `82e17b296a90b15ae999f6c3377ffe629c4f68ac6c3ac894bb02b637c51cf0a4`. Quel legame fra comando, commit ed esito manca dal record.

VF-003 è di evidenza ed è bloccante. `redesign.gates_json_sha256` è `f6d2f7cb5e09f7830eacc2c0d4a16564733f892ae04b0ea0c48bc9a234303e3d` e corrisponde a `pregate-eaae5f0/gates.json`. Quel file lega 50 passi a comando, stato, codice di uscita e nome del log, e zero passi contengono lo sha256 del log. L'oggetto `repair_cycle_1.fast_gate` resta eseguito su `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`, con `gates_json_sha256` `36f86d94f4613fb898eb0038800a21abb4366794a78c97dbebc50867b9c79de6`. Il vincolo del gate rapido del contratto precedente resta applicabile alla campagna sostitutiva.

VF-004 non è bloccante. È il difetto preesistente già disposto come `NOT_CORRECTED`. L'esecuzione indipendente ha prodotto 97 PASS e 1 FAIL. `CANONICAL_COMMIT` R1 senza Human Gate attende `REJECT` e ottiene `ACCEPT`. Non si corregge e non si segna `PASS`.

VF-005 è di evidenza ed è bloccante. L'opzione 1 chiede un blocco separato con `git diff --name-status` e il suo sha256 contro ogni commit di esecuzione. La tabella delle prove nomina cinque commit di esecuzione: `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` (16 righe), `7cf4c23e91b49b34a28ead075f25094254556764` (11), `86a8a2b5a6c14334a773fdd139ae986c373ef308` (2), `eaae5f0de47ce1b082e36257ac17c422ae78844a` (7) e `c7ccdf86c90c872dc4b916c7cb840bb9e9451cad` (2). Il blocco `redesign` non elenca i cinque delta contro l'HEAD di registrazione. Contro `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f`, il delta del commit di campagna storico ha sha256 `c4b30a7459f096ed797683f44c2e4f60baedab2ce5cb603b823d25b405be7000`; il delta di ciascuno degli altri quattro ha lo stesso stdout, soltanto il record dell'unità, sha256 `8523fac6b656bfed7eebc9be03159f21f55dee7e444c6e5dade52c2095488c83`. Il `name-status` non dipende dai byte del record: un commit successivo che cambia solo quel percorso lascia invariati questi due stdout.

Classi dei finding bloccanti. La classe è il controllo obbligatorio del verifier.

| Verdetto | Finding | Classe | Bloccante |
| --- | --- | --- | --- |
| `OCOR-DEV-REM-0069-38e15d2cb337-0` | VF-001, prove non attestate sull'HEAD finale | Evidenza | sì |
| `OCOR-DEV-REM-0069-38e15d2cb337-0` | VF-002, gate rapido non vincolato al record | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-001, prove attestate sul parent | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-002, letture di `reports/` e equivalenza dichiarata | Evidenza | sì |
| `OCOR-DEV-REM-0069-86a8a2b5a6c1-1` | VF-005, HTTP 429, ammissione preventiva non eseguita | Ambiente del verifier | sì |
| `OCOR-DEV-REM-0069-7ba88cfb3eb0-0` | VF-001, righe 127, 238, 247 e 255 non rieseguibili | Evidenza | sì |
| `OCOR-DEV-REM-0069-7ba88cfb3eb0-0` | VF-002, `git grep` della campagna sostitutiva assente | Evidenza | sì |
| `OCOR-DEV-REM-0069-7ba88cfb3eb0-0` | VF-003, gate rapido di `eaae5f0` senza sha256 dei log | Evidenza | sì |
| `OCOR-DEV-REM-0069-7ba88cfb3eb0-0` | VF-005, cinque delta non riuniti contro l'HEAD di registrazione | Evidenza | sì |

La causa comune della classe Evidenza resta la registrazione. Il codice sotto prova e la campagna verde non cambiano. Mancano comandi rieseguibili e i vincoli della campagna sostitutiva. Una prova che legge il record non può nominare come esecuzione il commit che contiene la propria impronta. Il `name-status` può farlo, perché il testo del diff non cambia quando cambiano solo i byte di un percorso già presente.

`OCOR-DEV-REM-0066` resta senza ciclo 4 finché l'unità del punto 4 di `CONFINE-G6 (2026-11-20)` non è integrata. Il candidato `3b2ee600ee5d9e3055e3d916628d958635fefff3` non si modifica e non si mergia. Il branch di codice di `OCOR-DEV-REM-0068` non parte finché `OCOR-DEV-REM-0069` non è su `origin/main`. Il launcher `governed/rem-0063-ci-argv-launcher` resta `69c3877caf58f82ebf4ea9e6e39df6560ad1ff8b`. Il candidato `24633cc9d4c49749bd33a386020fe0d9f6cf5174` non si modifica e non si mergia.

Non si rilanciano i run `45139159711`, `45139159581`, `45139159701`, `45116784337` e `45147805219`. Non si apre una pull request del candidato. Non si tocca la PR #722 né il commit `7b0b90ee79bdae51b22365faca2a54159502a44f`. Non si apre un `repair_cycle` 14. Non si avvia `OCOR-DEV-REM-0060`. Non si modifica `scripts/validate_ocor_development_plan.py` né `reports/planning/OCOR_PLAN_RUN_STATE.json`. VF-004 resta `NOT_CORRECTED` e non è `PASS`.

## Quesito

L'unico ciclo di riprogettazione di `OCOR-DEV-REM-0069` è `NO_GO` sulla classe Evidenza. Il punto 7 di `OCOR-DEV-REM-0069-REDESIGN (2026-11-25)` non ammette un altro ciclo senza una nuova disposizione. Il candidato resta fermo. Si autorizza un solo commit di registrazione che chiude VF-001, VF-002, VF-003 e VF-005 senza ripetere la campagna già verde; si ferma l'unità senza integrazione; oppure si autorizza una sola campagna nuova dopo quel record?

## Opzioni

1. **Un solo commit di registrazione, campagna già verde ammessa.** Non si attua in questa pubblicazione. Il Product Owner autorizza un solo commit nuovo sopra `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f`, senza rebase, reset o force-push. L'unico percorso cambiato è `reports/assurance/OCOR-DEV-REM-0069-RCCAD/OCOR-DEV-REM-0069.json`. I due blob di acquisizione restano `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded` e `dee2ca8813565043b20798a634743edcf0fd5f20`. Non parte una campagna nuova. La campagna `eaae5f0de47c-1795613672` e il replay indipendente `e8fcd9fb8d852134170d37306aa39189a5d4a77018277d874c1fa3d2a4372f71` restano le prove di comportamento. Nel record, le righe 127, 238, 247 e 255 diventano comandi di sola lettura citati per intero, con commit di esecuzione, codice di uscita e sha256 dello stdout. La riga 127 non invoca un file fuori dal commit nominato. Si aggiunge `git grep -n -I reports eaae5f0de47ce1b082e36257ac17c422ae78844a -- ocor-runtime/tests`, eseguito su quel commit, stdout sha256 `82e17b296a90b15ae999f6c3377ffe629c4f68ac6c3ac894bb02b637c51cf0a4`. Per ciascuno dei 50 passi di `pregate-eaae5f0/gates.json` (sha256 `f6d2f7cb5e09f7830eacc2c0d4a16564733f892ae04b0ea0c48bc9a234303e3d`) il record riporta comando, stato, codice di uscita e sha256 del file di log nominato dal passo; le 50 impronte di `repair_cycle_1.fast_gate`, eseguite su `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c`, restano storiche e non sostituiscono queste. Un solo blocco elenca, per i cinque commit di esecuzione, `git diff --name-status <commit> HEAD` e lo sha256 dello stdout. HEAD è il commit di registrazione. I due stdout attesi, finché l'unico percorso ulteriore è il record, restano `c4b30a7459f096ed797683f44c2e4f60baedab2ce5cb603b823d25b405be7000` per `80a2c854cfad9eeac22fa8f6cbd8efdf26d2962c` e `8523fac6b656bfed7eebc9be03159f21f55dee7e444c6e5dade52c2095488c83` per gli altri quattro. VF-004 resta `NOT_CORRECTED` e non è `PASS`. Poi una sola verifica, con un verifier di fornitore diverso da xAI non avviato dall'implementatore. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un altro ciclo: una sola richiesta nuova. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: `scripts/acquire_fuseki_archive.py`, blob `debf96c90a7ea6ffd89b0c10c92c93ed985d6ded`, chiede per prima la copia governata in modo anonimo, verifica lo SHA-512 del lock e solo dopo prova le fonti Apache; il consumatore è il record del commit di registrazione, che nomina `eaae5f0de47ce1b082e36257ac17c422ae78844a` come esecuzione della campagna `eaae5f0de47c-1795613672` e, nello stesso blocco, i cinque `name-status` contro il proprio HEAD. Costo stimato: due iterazioni, una per il record e una per la verifica. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit di questa pubblicazione sopra `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f` | `git rev-parse` del branch prima del commit di registrazione |
| Un solo commit, senza rebase | parent uguale a `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f` |
| Unico percorso cambiato: il record dell'unità | `git diff --name-status` contro `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f` |
| I due blob di acquisizione restano quelli citati | `git rev-parse` dei due path |
| Nessuna campagna nuova | assenza di un `campaign_result.json` diverso da `9ba50b61daffc27fe28e12d44ee12e89ab1d4d41c8b8e47fd71e3eb4713d321a` per la prova di comportamento |
| Le quattro righe diventano comandi citati per intero | righe del record, senza `/tmp/rem0069_scan_roles.py` |
| `git grep` della campagna sostitutiva | comando, commit `eaae5f0de47ce1b082e36257ac17c422ae78844a`, sha256 `82e17b296a90b15ae999f6c3377ffe629c4f68ac6c3ac894bb02b637c51cf0a4` |
| Cinquanta log del gate di `eaae5f0` vincolati | comando, stato, uscita e sha256 del log per ogni passo |
| Cinque delta nello stesso blocco | due sha256 di `name-status` citati sopra |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| Una sola verifica, verifier di fornitore diverso da xAI | verdetto sull'HEAD esatto |
| Nessun ciclo ulteriore dopo un nuovo `NO_GO` | una sola richiesta nuova |

2. **Stop senza integrazione.** Non si attua in questa pubblicazione. Il Product Owner non autorizza altri commit sul candidato. `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f` non si modifica e non si mergia. Non si apre la pull request. La campagna `eaae5f0de47c-1795613672` e il replay `e8fcd9fb8d852134170d37306aa39189a5d4a77018277d874c1fa3d2a4372f71` restano storici e non diventano un sigillo. VF-001, VF-002, VF-003 e VF-005 restano aperti. VF-004 resta `NOT_CORRECTED` e non è `PASS`. I due blob restano quelli citati. Le unità che partono solo quando `OCOR-DEV-REM-0069` è su `origin/main` restano ferme. Non si apre un altro ciclo. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: lo stesso produttore e gli stessi blob dell'opzione 1; il consumatore non è un record sigillato. Il candidato rifiutato resta l'HEAD pubblicato del branch e non entra in `origin/main`. Costo stimato: un'iterazione, questa pubblicazione. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit sopra `7ba88cfb3eb0640bd4281a124eba8b4c72e49e1f` | `git rev-parse` del branch |
| Nessuna pull request del candidato | assenza di una PR con quell'HEAD |
| Nessun merge | `git merge-base --is-ancestor` contro `origin/main` fallisce |
| Campagna e replay restano storici | gli stessi sha256, non trasferiti a un sigillo |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| I due blob restano quelli citati | `git rev-parse` dei due path |
| Nessun ciclo ulteriore | nessun commit di riparazione |

3. **Un solo commit di registrazione e una sola campagna nuova.** Non si attua in questa pubblicazione. Il Product Owner non ammette la campagna `eaae5f0de47c-1795613672` come prova dell'HEAD che chiede la verifica. Autorizza prima il commit di registrazione dell'opzione 1, con gli stessi vincoli sui blob, sul percorso unico, su VF-004 e sui comandi. Poi una sola campagna a quattro corsie, con `--expected-head` uguale a quel commit di registrazione, dopo la misura dei pull residui richiesta da `PULL-BUDGET-CORSIE-SOGLIE (2026-11-15)`. Il commit successivo, che registra il risultato, è ammesso solo se `git diff --name-status` contro il commit di campagna è limitato al record dell'unità. La campagna `9ba50b61daffc27fe28e12d44ee12e89ab1d4d41c8b8e47fd71e3eb4713d321a` non si trasferisce e resta storica. Poi una sola verifica, con un verifier di fornitore diverso da xAI non avviato dall'implementatore. Con `GO_FOR_EVIDENCE_SEAL` seguono la pull request e l'unico tentativo CI del punto 6 di `CI-FUSEKI-ARCHIVE-TIMEOUT-20261123 (2026-11-23)`. Con un nuovo `NO_GO` non c'è un altro ciclo: una sola richiesta nuova. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: lo stesso produttore e gli stessi blob dell'opzione 1; il consumatore è il record del commit di registrazione del risultato, che nomina il commit su cui `--expected-head` ha accettato la campagna nuova e il delta limitato al record dell'unità. Costo stimato: tre iterazioni, una per il record, una per la campagna e una per la verifica. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Il commit di registrazione rispetta l'opzione 1 | gli stessi criteri della tabella dell'opzione 1, prima della campagna |
| Una sola campagna nuova | `--expected-head` uguale a quel commit, conteggi e zero skip |
| Il commit del risultato cambia solo il record | `git diff --name-status` contro il commit di campagna |
| La campagna `eaae5f0de47c-1795613672` non si trasferisce | sha256 `9ba50b61daffc27fe28e12d44ee12e89ab1d4d41c8b8e47fd71e3eb4713d321a` resta storico |
| I due blob restano quelli citati | `git rev-parse` dei due path |
| VF-004 resta `NOT_CORRECTED` | stesso FAIL, non segnato `PASS` |
| Una sola verifica, verifier di fornitore diverso da xAI | verdetto sull'HEAD esatto |
| Nessun ciclo ulteriore dopo un nuovo `NO_GO` | una sola richiesta nuova |

## Raccomandazione

L'opzione 1. Il codice sotto prova è invariato, la campagna dell'implementatore è verde e il verifier l'ha riprodotta al secondo tentativo, senza asserzioni fallite. I quattro finding bloccanti sono vincoli di registrazione. Il `name-status` contro l'HEAD attuale è già misurato e non cambia se l'unico percorso ulteriore è il record. Una campagna nuova non esercita un codice diverso. L'opzione 2 lascia non integrata una copia governata già qualificata sul comportamento. L'opzione 3 è il ramo più costoso e serve solo se la campagna già verde non è ammessa.

## Effetto sulle unità

Blocca solo `OCOR-DEV-REM-0069` finché una sezione non adotta un'opzione. Non blocca un'unità che non dipende dal merge di `OCOR-DEV-REM-0069`. Il branch di codice di `OCOR-DEV-REM-0068`, la continuazione del launcher e il branch di codice di `OCOR-DEV-REM-0067` dipendono da quel merge e restano fermi. `OCOR-DEV-REM-0066` resta senza ciclo 4 per la decisione già citata. Nessuna opzione di questa richiesta è applicata.
