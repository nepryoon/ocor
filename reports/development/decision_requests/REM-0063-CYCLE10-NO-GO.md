# REM-0063-CYCLE10-NO-GO

Stato: `OPEN_PO_DECISION_REQUIRED`.
Livello: operativo. Unità: `OCOR-DEV-REM-0063`.
Verdetto: `OCOR-DEV-REM-0063-3b4894d181b7-10`, esito `NO_GO`, sha256 `f1d509cbcc61a0857b43014287ad9acd0eccc889012c140a730b4944cd9dbdf3`.
Head verificato: `3b4894d181b7dfbfbc929f54a83ae320bcf73666` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`.
Commit di esecuzione: `3ae284727c9829902e72bea25c2f07373e60d969`.
Base del ciclo: `f485dc964e47bde83842ecd5ba2627d8342612f9`.
Branch di produzione: `governed/ocor-dev-rem-0063-mcp-profile`, fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`.

## Contesto e perimetro

`REM-0063-CYCLE7-NO-GO (2026-11-15)` punto 4 e `REM-0063-CALCOLO-UNICO (2026-11-17)` punto 6 chiudono la sequenza autorizzata al ciclo 10. Un `NO_GO` del ciclo 10 non apre un ciclo 11 automatico. Questa è l'unica richiesta nuova. Finché è aperta l'unità non si modifica, non si integra e non si sigilla.

Il verdetto conferma chiusi, nei casi provati, VF-001 e VF-002 del verdetto `OCOR-DEV-REM-0063-f485dc964e47-9`: radici relative e `$id` annidati attraverso `const`, `default` ed `examples` concordi con le librerie sui due percorsi pubblici; limiti 4096/4097 valori e profondità 32/33; riferimenti verso le `$defs` del descriptor, un altro strumento o un altro campo rifiutati; descriptor della fixture accettato con chiusura esatta. La campagna a quattro corsie sull'HEAD esatto è PASS: `3b4894d181b7-1794958097`, 47779 test, 0 fallimenti, 0 errori, 0 skip, 3421.119 s. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` restano FAIL e non sono un PASS.

Il `NO_GO` deriva dai finding bloccanti VF-001–VF-006 di questo verdetto. La causa comune è che il calcolo unico richiesto da `REM-0063-CALCOLO-UNICO (2026-11-17)` punto 3 non copre ancora tutta la classe: il generatore non applica al descrittore emesso le regole del profilo, e profilo e generatore enumerano ancora le risorse contenute con due tabelle diverse. Tre rifiuti del profilo sono più severi di `referencing` 0.37.0 e `Draft202012Validator` e non hanno una fonte nel contratto. Due oracoli calcolano la base con una funzione di produzione.

Implementatori già dichiarati dell'unità, da riportare in ogni richiesta successiva: Grok Build `grok-4.7` (xAI) per il ciclo originale, le riparazioni 1–6, il completamento del ciclo 8, il ciclo 9 e il codice e il candidato del ciclo 10; Codex CLI `deepseek-flash` e `deepseek-v4-pro` (DeepSeek) per i cicli 7 e 8; Codex `gpt-6.1-sol` (OpenAI) per la fase A del ciclo 10. Verifier di questo verdetto: Claude Code, `claude-opus-5-5`, Anthropic, effort `max`, assegnato da `VERIFIER-CLAUDE-REM0063 (2026-11-16)`. Limite dichiarato: stesso fornitore del revisore preventivo Claude Code `claude-fable-5-2`, modello diverso. Nessun implementatore Anthropic.

## Prove

Finding bloccanti, tutti sul candidato `3b4894d181b7dfbfbc929f54a83ae320bcf73666`.

| ID | Gravità | Classe | Fatto |
| --- | --- | --- | --- |
| VF-001 | high | codice, regola 3 del profilo sul percorso generato | Uno schema con `$schema` draft-07 alla radice, in un nodo annidato o sulla radice di una risorsa annidata, oppure con `$dynamicRef` o `$recursiveRef`, viene emesso. `validate_mcp_descriptor` lo rifiuta. Le librerie accettano lo schema emesso. `_mcp` non applica la regola 3 prima di restituire gli artefatti. I test della regola 3 sono solo sul percorso consegnato. |
| VF-002 | high | codice e contratto, regole più severe senza fonte | Con la chiave letterale presente, le librerie risolvono e validano i gemelli di `#/$defs/x~2y`, `#/$defs/%ZZ`, `#/$defs/a%` e `#/$defs/%FF` (chiave U+FFFD). Il profilo rifiuta. Le tre regole (escape `~` di RFC 6901, percent-encoding, UTF-8 stretto) non sono nell'elenco del contratto con fonte ed errore. Il caso `~2` della matrice asserisce il rifiuto mentre il suo oracolo accetta. È il caso del punto 3 di `REM-0063-RIALLINEAMENTO-ALLA-LIBRERIA (2026-11-17)`. |
| VF-003 | high | codice, enumerazione delle risorse non condivisa | Il profilo usa la propria tabella di keyword, che include `additionalItems`. `referencing` 0.37.0 non indicizza `additionalItems`: in JSON Schema 2020-12 non è una keyword. Un `$anchor`, un `$id` non stringa, un `$ref` irrisolvibile o un `$id` sotto `additionalItems` divergono dalle librerie. Il generatore rifiuta `additionalItems` con `$id`. Nessuna di queste regole è nell'elenco del contratto. |
| VF-004 | high | test, oracolo dipendente dalla produzione | `_cycle6_schema_alone` (39 casi riallineati) e `_cycle10_static_library` (24 celle C1) calcolano la base con `operational_base` di `mcp_profile.py`. `REM-0063-CALCOLO-UNICO (2026-11-17)` punto 3 vieta che la risposta attesa venga da una funzione di produzione, compresa quella condivisa. Una riesecuzione con base indipendente concorda 48/48 sui casi riallineati: manca la proprietà di indipendenza, non è stata osservata una divergenza di bersaglio. |
| VF-005 | high | evidenza | `3ae28472` modifica di nuovo `scripts/run_local_lane_campaign.py` e `reports/tests/test_local_lane_campaign.py`. `REM-0063-CYCLE10-LANE-ARGV-LIMIT (2026-11-17)` opzione 1 richiede la riqualifica dei record sigillati i cui input includono il file cambiato. Restano senza record di supersessione `OCOR-DEV-REM-0056` e `OCOR-DEV-REM-0037` (record `OCOR-DEV-REM-0037.requalified-rem0056`). Il record dell'unità non inventaria `3ae28472`. |
| VF-006 | medium | gate | `git diff --check f485dc964e47..HEAD` segnala una riga vuota finale in `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py:1260`. `REM-0063-PINNED-FIXTURE-DIFF-CHECK` opzione 1 esenta solo la riga vuota della fixture ufficiale. |

Finding non bloccanti dello stesso verdetto, da chiudere nel lavoro completo oppure da tenere tracciati: VF-007 (riqualifiche di `OCOR-DEV-REM-0047`, `OCOR-DEV-REM-0062` e `OCOR-DEV-REM-0064`), VF-008 (definizione utente irraggiungibile conservata quando è una risorsa sotto un nodo non risorsa), VF-009 (collisione preesistente di `component_name` fra `type_id` distinti, già su `origin/main`, condivisa dagli altri generatori), VF-010 (righe di autocontrollo mancanti per tre parser del ciclo 10), VF-011 (record non allineato all'HEAD finale), VF-012 (controllo preventivo dello spazio di `/tmp`, già richiesto da `TMP-RESIDUI-CAMPAGNA (2026-11-11)` punto 2 e tenuto fuori dal change set dell'argv).

## Quesito

Come si porta a termine `OCOR-DEV-REM-0063` dopo il `NO_GO` del ciclo 10, senza un ciclo 11 automatico, così che ogni schema emesso e ogni schema consegnato diano lo stesso esito delle librerie fissate e del profilo, e che l'evidenza del candidato sia completa?

## Opzioni

1. **Chiusura completa della classe, un solo ciclo autorizzato da questa richiesta.** Raccomandata. Non è il ciclo 11 automatico escluso dalle decisioni citate: è un ciclo nuovo, autorizzato solo se questa opzione viene adottata. Parte dall'HEAD `3b4894d181b7dfbfbc929f54a83ae320bcf73666` con commit nuovi, senza rebase, reset o force-push. Il branch di produzione resta fermo a `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8` fino a un'integrazione successiva. Il record chiama questo ciclo `repair_cycle` 11 solo come successore del verdetto, con il riferimento a questa richiesta.

   Semantica invariata: `MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)`, `MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)`, `REM-0063-CALCOLO-UNICO (2026-11-17)` punti 3 e 7, `REM-0063-RIALLINEAMENTO-ALLA-LIBRERIA (2026-11-17)`. L'oracolo resta `referencing` 0.37.0 e `Draft202012Validator` sullo schema dello strumento da solo, senza modifiche, con la base già fissata. Le regole più severe che il contratto elenca già con fonte ed errore restano. Le tre regole di VF-002 non hanno quella fonte: si seguono le librerie e si toglie il rifiuto. `additionalItems` si tratta come le librerie, che non lo indicizzano. Non si aggiungono regole più severe nuove.

   File del ciclo di profilo e generatore, e solo questi per il codice: `ocor-runtime/src/ocor_runtime/c1/mcp_profile.py` (funzioni condivise; nessun file nuovo sotto `ocor-runtime/src/`); la funzione `_mcp` di `ocor-runtime/src/ocor_runtime/c1/codegen.py` e gli helper che le servono per chiamare quelle funzioni; `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`; `reports/assurance/OCOR-DEV-REM-0063-RCCAD/`. La fixture ufficiale resta identica byte per byte. `inputs/` non si tocca. I record sigillati non si riscrivono. I manifest ricevono solo voci nuove.

   Ordine:

   1. Test RED, prima di ogni modifica sotto `ocor-runtime/src/`, per VF-001, VF-002, VF-003, VF-004 e VF-008. Falliscono per la ragione del finding. Il log RED si conserva.
   2. Una sola enumerazione delle risorse contenute, in `mcp_profile.py`, usata da profilo e generatore: quella della libreria. Il generatore chiama la funzione pubblica del profilo, con `C1Error` tipizzato, prima di restituire gli artefatti. La risoluzione resta quella di `referencing` 0.37.0, senza un secondo risolutore scritto a mano. I limiti 4096/4097 e 32/33 restano una sola funzione condivisa.
   3. Gli oracoli dei 63 casi di VF-004 usano un calcolo di base indipendente, senza importare codice di produzione. RED e GREEN di quei casi si ripetono. Il riallineamento di `~2` e degli altri casi pre-ciclo-10 che oggi rifiutano ciò che le librerie accettano è un commit separato dai commit di produzione, con la tabella e la sonda richieste da `REM-0063-RIALLINEAMENTO-ALLA-LIBRERIA (2026-11-17)` punto 4. Nessuna cella della matrice si toglie.
   4. Si toglie la riga vuota finale di `mcp_profile.py`. Il record riporta `git diff --check` da `f485dc964e47` all'HEAD finale, con la sola eccezione della fixture.
   5. Il record si allinea all'HEAD finale: righe di autocontrollo di VF-010 con i casi negativi; scansioni rieseguite; decisioni `REM-0063-CYCLE10-LANE-ARGV-LIMIT` e `REM-0063-CYCLE10-INOTIFY-INSTANCES` segnate come decise e applicate; inventario che sostituisce il testo della fase A; voce di `3ae28472` con il RED della campagna `8037040f14cc-1794928763`.
   6. Revisione preventiva con `prereview_request.json`, poi gate locale, campagna a quattro corsie nuova e controllo distinto, poi `verify_request.json`. Soglie di pull invariate: almeno 95 download residui prima della campagna, almeno 50 prima del controllo distinto. Tetti, timer, partizioni, immagini e digest invariati. Zero skip. Le tre campagne diagnostiche non si rilanciano.
   7. Sullo stesso HEAD finale, riqualifiche di sola regressione con supersessione esplicita, record nuovi: `OCOR-DEV-REM-0037` e `OCOR-DEV-REM-0056` (VF-005); `OCOR-DEV-REM-0047`, `OCOR-DEV-REM-0062` e `OCOR-DEV-REM-0064` (VF-007). L'estensione dell'allowlist per i nuovi percorsi di evidenza sta nello stesso change set, con la riqualifica di regressione che la regola dell'allowlist già impone.

   Criteri di accettazione:

   | ID | Criterio | Prova |
   | --- | --- | --- |
   | VF-001 | Ogni `inputSchema` e `outputSchema` emesso passa le regole del profilo applicabili a uno schema, compresi il dialetto 2020-12 e il rifiuto di `$dynamicRef` e `$recursiveRef`, sulla radice, su un nodo annidato e sulla radice di una risorsa annidata. Il gemello consegnato ha lo stesso esito. Il fallimento del generatore è `C1Error`. | Dimensione nuova della matrice, RED poi GREEN. Oracolo: librerie fissate sullo schema da solo. |
   | VF-002 | `~2`, `%ZZ`, `%` finale e `%FF` con chiave piantata seguono le librerie, sulle origini raggiungibili. Una regola più severa senza fonte nel contratto non resta. | Test differenziale. Tabella di riallineamento nel record. |
   | VF-003 | Profilo e generatore usano la stessa enumerazione. `additionalItems` non è indicizzato. I quattro contenuti del verdetto concordano con le librerie su entrambe le origini. | Dimensione nuova, casi positivi e negativi. |
   | VF-004 | I 63 oracoli calcolano la base senza codice di produzione. | RED e GREEN ripetuti. |
   | VF-005 | Record nuovi di supersessione per `OCOR-DEV-REM-0037` e `OCOR-DEV-REM-0056`. Voce di `3ae28472` nel record. | Record e manifest. |
   | VF-006 | Nessuna riga vuota finale in `mcp_profile.py`. `git diff --check` registrato. | Uscita del comando nel record. |
   | VF-007 | Record nuovi di supersessione per `OCOR-DEV-REM-0047`, `OCOR-DEV-REM-0062` e `OCOR-DEV-REM-0064`. | Record e manifest. |
   | VF-008 | Una definizione utente irraggiungibile è omessa anche se è una risorsa sotto un nodo non risorsa. | Celle: sibling semplice o risorsa con `$id`, sotto la radice o sotto un nodo annidato non risorsa. |
   | VF-010 | Righe di autocontrollo e casi negativi per i tre parser, scansione sull'HEAD finale. | Tabella nel record. |
   | VF-011 | Record, inventario e scansioni descrivono l'HEAD finale. | Diff del record. |

   Esempio dal produttore al consumatore. Un contratto il cui schema contiene `$dynamicRef` oppure `$schema` di draft-07 fa fallire `_mcp` con `C1Error` prima che un artefatto sia restituito. Lo stesso descriptor, consegnato a `validate_mcp_descriptor`, fallisce con la stessa regola condivisa. Uno schema che le librerie accettano, con un puntatore `~2` verso una chiave letterale piantata e con un nodo sotto `additionalItems`, è accettato dal generatore e dal profilo, e `referencing` 0.37.0 più `Draft202012Validator` sullo schema da solo dà lo stesso esito.

   Dopo il `GO_FOR_EVIDENCE_SEAL` di questo ciclo, e non dentro i suoi commit di profilo, si aprono due unità distinte con il primo identificativo `OCOR-DEV-REM-*` libero verificato al momento: VF-009, `C1Error` tipizzato sulla collisione di `component_name` fra `type_id` distinti, per ogni generatore che condivide la mappa, con test positivo e negativo; VF-012, il controllo preventivo di spazio e quota di `/tmp` in `scripts/run_local_lane_campaign.py`, con test RED/GREEN, come `TMP-RESIDUI-CAMPAGNA (2026-11-11)` punto 2. Se una delle due non può aprirsi senza un quesito ulteriore, si apre una sola richiesta nuova. Non si saltano in silenzio.

   Costo: cinque iterazioni fino al candidato nuovo (RED, GREEN, revisione preventiva, campagna e controllo distinto, record), poi la verifica indipendente e uno state sync di integrazione. Un `NO_GO` successivo segue il tetto di riparazione già vigente e non è contato in questa stima. Le riqualifiche stanno nell'iterazione della campagna.

   Se l'attuazione richiede un file, una dipendenza, una versione, un gate, un tetto o una cella della matrice che questa opzione non nomina, ci si ferma e si apre una sola richiesta nuova. L'opzione non si applica finché questa richiesta è aperta.

2. **Solo i finding meccanici.** Si correggono VF-004, VF-005, VF-006 e VF-011 sullo stesso HEAD, con gli stessi vincoli di storia e di file di evidenza. VF-001, VF-002, VF-003 e VF-008 restano. Il generatore può ancora emettere uno schema che il profilo rifiuta, e il profilo può ancora rifiutare uno schema che le librerie accettano. Le decisioni `MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)` e `MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)` restano insoddisfatte su quelle celle. Costo: due iterazioni fino a un candidato parziale, che la verifica successiva può chiudere di nuovo con `NO_GO` sulla stessa classe. Non raccomandata.

3. **Nessun'altra modifica.** Il candidato non si integra. I branch restano agli HEAD indicati. `main` non riceve gli schemi MCP autonomi già richiesti da `MCP-TOOL-SCHEMA-AUTONOMO (2026-11-15)` e da `MCP-TOOL-SCHEMA-AUTONOMO-GENERATORE (2026-11-15)`. I finding bloccanti restano sul branch non integrato. Costo: zero iterazioni di codice. Non raccomandata.

## Raccomandazione

Opzione 1. È l'unica che toglie la causa (due calcoli, e rifiuti più severi delle librerie senza fonte) e chiude tutti i finding bloccanti senza indebolire test, gate, tetti o celle della matrice. L'opzione 2 lascia la stessa classe al verdetto successivo. L'opzione 3 lascia irrealizzato su `main` il comportamento normativo già adottato.

## Impatto

Task bloccato da questa richiesta: `OCOR-DEV-REM-0063`. Gli altri task non sono bloccati da questa richiesta. `OCOR-DEV-REM-0066` resta sullo stato della richiesta `REM-0066-GUARD-ADMISSION`. `OCOR-DEV-REM-0065` resta all'HEAD `583ea0024f18ebe0f63f4c5eaa8da8bc9a246f6c`. `AGENTIC-RISK-MAP-PARTIAL-GAPS` non blocca alcun task.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist del validatore del piano per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione.

## Disposition

Decisa per conto del PO, modello `claude-fable-5-2`, effort `max`. Decisione `REM-0063-CYCLE10-NO-GO (2026-11-18)`. Opzione 1 adottata. Le opzioni 2 e 3 non sono applicate.

Il primo passo dell'opzione è il test RED, prima di ogni modifica sotto `ocor-runtime/src/`. Commit `03e568886bef5bb3c9481628f485019de0c0092f` sul branch `governed/ocor-dev-rem-0063-cycle10-campaign`, senza rebase, reset o force-push, a partire da `3b4894d181b7dfbfbc929f54a83ae320bcf73666`. Il file cambiato è solo `ocor-runtime/tests/tasks/test_ocor_dev_rem_0063.py`. Pytest `-k cycle11_vf`: 30 failed, 7 passed, 41953 deselected, 2,01 s. Il log grezzo è `~/.ocor-codex/rem-0063/preserved/03e568886bef5bb3c9481628f485019de0c0092f/red.log.cycle11.raw`, sha256 `c0180d4474a23b5538bd81c8a14e0045cee4637506972df72fad33143982f66b`. I fallimenti sono la ragione dei finding: il generatore non rifiuta le regole di keyword del profilo (10), il profilo rifiuta ciò che le librerie accettano (14), il generatore rifiuta `additionalItems` (4), gli oracoli importano `operational_base` (1), una definizione utente irraggiungibile resta nello schema emesso (1).

Non sono ancora eseguiti i passi successivi dell'opzione: la modifica di produzione, il riallineamento separato degli oracoli, la riga vuota, il record, la revisione preventiva, la campagna, il controllo distinto, la verifica e le riqualifiche. Il branch di produzione `governed/ocor-dev-rem-0063-mcp-profile` resta `5ffc19bddca6bf0176575191e6bc3f0d4ea717d8`. Le campagne diagnostiche `5a1a8aaff6af-1794907944`, `8037040f14cc-1794928763` e `3ae284727c98-1794931254` non sono state rilanciate. `inputs/` non è stato modificato. Nessun record sigillato è stato riscritto.

Due contenuti di VF-003 sull'origine generata, l'ancora duplicata e il `$ref` irrisolvibile sotto `additionalItems`, non sono in questo RED: il compilatore dei contratti li rifiuta in `ir.py` prima di `_mcp`, e `ir.py` non è fra i file dell'opzione. L'origine consegnata copre quei due contenuti. Se il passo GREEN non può chiudere la tabella di accettazione senza quel file, si apre una sola richiesta nuova.

Il testo sopra questa sezione resta quello del commit `e8db497fe45df05b44569c50757751837fa3a2eb`, sha256 `c1106610cd737b1458f7440d52370497aabdd8bef550169492879dae58ca7c96`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo `DEC-*`.
