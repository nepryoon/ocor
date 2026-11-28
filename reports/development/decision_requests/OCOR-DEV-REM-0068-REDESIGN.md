# OCOR-DEV-REM-0068-REDESIGN

Stato: `DECIDED_BY_PO`.
Disposition: opzione 1 di `OCOR-DEV-REM-0068-REDESIGN (2026-11-28)`, registrata nella sezione Disposition. La pubblicazione `af3eb66ef9a40fc24c72ab63864e878f36e785cb` non applicava alcuna opzione. Questo commit registra la decisione e non attua il codice. Claim invariati.

Livello: normativo. La questione sceglie la proprietà di accettazione del gate della testa corrente. Nessun nuovo `DEC-*`.
Chi decide: il programma delle decisioni per conto del PO, secondo `DECISIONI-A-FABLE (2026-11-17)`. La richiesta riguarda il ritorno al progetto dopo due `NO_GO` della stessa classe, come dispongono i punti 2 e 3 di `DECISIONI-AL-PO (2026-11-16)`. Nessuna opzione è applicata da questa pubblicazione.
Head di `origin/main` alla pubblicazione: `23ab3aa776c8071321e7fa2399179d215bbd19a5`.
Candidato: branch `governed/ocor-dev-rem-0068-current-head`, HEAD `83c91b6775dd779d30fee608b26c91f11a808ae3`, merge-base con `origin/main` `23e6b62c36627de91cb85329b9a1164f3219cd53`. Nessun commit è aggiunto sopra quell'HEAD da questa pubblicazione. Il candidato non si modifica e non si mergia.
Decisione che impone questa richiesta: il punto 2 di `DECISIONI-AL-PO (2026-11-16)`. Il ciclo 0 è `NO_GO`. Il ciclo di riparazione 1 è `NO_GO`. I due verdetti hanno finding bloccanti della classe Copertura dei criteri. Non c'è un ciclo 2. Questa è la richiesta `-REDESIGN`.
Implementatore dell'unità e di questa pubblicazione: Grok Build, modello `grok-4.7`, fornitore xAI. Revisore preventivo di riserva: Cursor CLI, modello `cursor-grok-4.6-xhigh`, fornitore xAI, escluso dalla verifica. Verifier dei due `NO_GO`: Codex, fornitore OpenAI, modello `NOT_EXPOSED_BY_RUNTIME`, effort `xhigh`, non avviato dall'implementatore.

## Contesto e perimetro

Il verdetto `OCOR-DEV-REM-0068-83c91b6775dd-1` è `NO_GO` sull'HEAD `83c91b6775dd779d30fee608b26c91f11a808ae3`, creato `2026-11-28T04:34:48+00:00`, sha256 del documento `e6c6e8d0024731d235ee8d968ca52add9cdaae73f00203bf721032310049080e`. È il ciclo di riparazione 1. Il verdetto del ciclo 0, `OCOR-DEV-REM-0068-c6410c0c7c31-0`, è `NO_GO` sull'HEAD `c6410c0c7c31b6d28f28eefb59c5351ec76b1c7d`, creato `2026-11-28T01:32:36+00:00`, sha256 `be97116e5c14ddcdc3f63097c93c743167f8b9c7d3359b113a9158da630d6aad`. `7594851f3a2eb6b0ee81e8691992f1fe7cbc17d0` è un antenato di entrambi. La campagna del ciclo 0 è il commit di evidenza `c6410c0c7c31b6d28f28eefb59c5351ec76b1c7d`. La campagna del ciclo 1 è eseguita sull'HEAD `8a4020b1d04afe9d8549112d52094fd742da916f` e registrata dal commit di evidenza `83c91b6775dd779d30fee608b26c91f11a808ae3`. Questa pubblicazione non riesegue le campagne e non trasferisce i loro esiti.

Il contratto vigente è `reports/assurance/OCOR-DEV-REM-0068-RCCAD/README.md` sull'HEAD rifiutato. La proprietà, in quel file, è: per ogni task di `completed_evidence_tasks` il gate valida esattamente una testa corrente, per intero, oppure emette un finding che nomina il task e un codice. Un input presentato non è mai saltato. `scripts/validate_evidence_input_drift.py` resta byte-identico, `select_most_recent` compreso. L'identità canonica è `record_id`. Un record senza `record_id` riceve l'identità solo da un record di riconciliazione fuori da `reports/evidence`, nel percorso `reports/assurance/OCOR-DEV-REM-0068-RCCAD/reconciliation/<OCOR-DEV-NNNN>.json`. Dopo l'unità, un record nuovo senza `record_id` è un finding. La matrice dichiarata è 3 ingressi per 17 classi, 51 celle. L'oracolo è un selettore di riferimento indipendente e il codice di produzione è il soggetto, non l'oracolo.

I verdetti non portano un campo classe. La classe usata qui è quella del punto 1 di `DECISIONI-AL-PO (2026-11-16)`: il controllo obbligatorio del verifier a cui il finding bloccante appartiene. Il controllo Gate è passato nei due verdetti nel senso che i test del candidato sono verdi. I finding bloccanti sotto descrivono proprietà del contratto che quei test non raggiungono: la classe è Copertura dei criteri. L'unico bloccante che non entra in quella classe è il VF-006 del ciclo 0: il proof di `OCOR-DEV-REM-0068-GUARD-ADMISSION (2026-11-27)` accetta il ripristino dell'intero workflow di `82b71d0db410bcdb8124e8ec8a8235631ecfa1fa`. La classe di quel finding è l'identificativo di quella decisione. Il ciclo 1 non ha un finding bloccante in quella classe. La classe condivisa Copertura dei criteri basta a chiudere i cicli.

| Verdetto | Finding | Classe | Bloccante |
| --- | --- | --- | --- |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-001, stato assente, chiave assente o task completato senza record: uscita 0 senza testa | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-002, percorso non ASCII scartato: E2 valida una delle due teste | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-003, `supersedes` irrisolto e autosupersessione storica accettati | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-004, la riconciliazione ritira un ramo e E1 valida un record estraneo | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-005, record canonico senza manifest di gate: manca `MANIFEST_UNLISTED` | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-006, il proof corrente passa se manca l'intero blocco ammesso | `OCOR-DEV-REM-0068-GUARD-ADMISSION` | sì |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-007, i grafi generati confrontano l'oracolo con se stesso | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-c6410c0c7c31-0` | VF-008, la coppia E2 incompleta esegue E1, e `--manifest` ignora E2 | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-83c91b6775dd-1` | VF-001, E3 legge ogni record e, senza stato, emette `UNREADABLE_JSON` prima del manifest | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-83c91b6775dd-1` | VF-002, il suffisso `.reconciliation.json` è saltato e due teste danno PASS | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-83c91b6775dd-1` | VF-003, il prefisso `reports/evidence` include `reports/evidence-archive` | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-83c91b6775dd-1` | VF-004, l'identità legacy segue il solo commit di esecuzione | Copertura dei criteri | sì |
| `OCOR-DEV-REM-0068-83c91b6775dd-1` | VF-005, profondità oltre la ricorsione: traceback e stdout vuoto | Copertura dei criteri | sì |

Non bloccanti, e non sono la causa dello stop. Ciclo 0: VF-009 e VF-010, bassi, tracce di autocontrollo e di allowlist assenti dal record. Ciclo 1: VF-006, medio, la cella `missing_file_or_key` dice insieme vuoto mentre E1 emette `UNREADABLE_JSON`; VF-007 e VF-008, bassi, comandi e impronte di autocontrollo e l'elenco misurato dei percorsi di allowlist assenti dal record. La classe di questi quattro è Evidenza. Non si segnano `PASS`.

Il verdetto del ciclo 1 registra che i casi RED del ciclo 0 sono verdi sul candidato finale. Questa pubblicazione non li riesegue. Un'opzione adottata non riapre e non indebolisce quei test.

La causa comune della classe Copertura dei criteri è una sola. L'oracolo e il codice di produzione sono stati scritti contro la matrice di 51 celle estesa a mano. Il VF-007 del ciclo 0 ha trovato che i grafi generati confrontavano l'oracolo con se stesso. Il ciclo 1 ha corretto quel confronto per i grafi che il generatore produce. Fixture indipendenti, fuori da quel generatore, trovano ancora buchi: l'ambito di E3, il suffisso di riconciliazione dentro l'albero di evidenza, il perimetro di directory, l'identità legacy appesa al solo commit, la ricorsione del caricamento. Un'altra toppa enumerata sui soli finding dell'ultimo verdetto lascia la stessa causa.

`scripts/validate_evidence_input_drift.py` non si modifica in nessuna opzione. Nessun record sigillato si riscrive. `vf004_schema_conformance` resta `NOT_CORRECTED` e non è `PASS`. Le sette teste residue dichiarate nel contratto non si riqualificano qui. `OCOR-DEV-REM-0060` non parte. Fino all'integrazione di questa unità nessuna altra unità avvia una campagna qualificante locale; le sincronizzazioni di stato restano fuori da quella pausa, come dice la sezione Sequence del contratto. Il ciclo 4 di `OCOR-DEV-REM-0066` e ogni unità che cambia `scripts/validate_ocor_development_plan.py` o `reports/tests/test_kind_teardown_observation.py` restano fermi, salvo le riqualifiche di sola regressione che il contratto di questa unità già prevede per `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082` quando un'opzione adottata entra nella fase di codice. `EVIDENCE-INPUTS-AND-RETENTION` non si apre in questa pubblicazione: `OCOR-DEV-REM-0068` non è su `origin/main`.

Il percorso di questo file non è nell'allowlist di `scripts/validate_ocor_development_plan.py`. Questa pubblicazione non modifica quel validatore. Non si apre una pull request.

## Quesito

I due `NO_GO` di `OCOR-DEV-REM-0068` condividono la classe Copertura dei criteri e il tetto di `DECISIONI-AL-PO (2026-11-16)` è esaurito. Il candidato `83c91b6775dd779d30fee608b26c91f11a808ae3` resta fermo. Si sostituisce la matrice estesa a mano con un solo selettore puro, le cui proiezioni sono E1, E2 ed E3, così che ogni input presentato entri nel grafo o produca un finding; si correggono solo i cinque finding del ciclo 1; oppure si restringe il contratto alle forme che i test generati già coprono?

## Opzioni

1. **Selettore unico sul grafo esplicito.** Non si attua in questa pubblicazione. Sopra `83c91b6775dd779d30fee608b26c91f11a808ae3`, senza rebase, reset o force-push, un commit di contratto riscrive solo `reports/assurance/OCOR-DEV-REM-0068-RCCAD/README.md` e sostituisce la matrice estesa a mano con la proprietà che segue. Poi RED, GREEN, una revisione preventiva, una campagna a quattro corsie sull'HEAD finale e una verifica. Il codice di produzione espone una sola funzione pura sul grafo esplicito. E1, E2 ed E3 sono proiezioni di quella funzione, non tre scan. I nodi di evidenza sono solo i discendenti della directory `reports/evidence/`, per componenti di percorso: `reports/evidence-archive` non è un nodo. E2 elenca i percorsi Git terminati da NUL e conserva il nome del blob fino alla lettura, anche se non è UTF-8. Un `--record` fuori da quel perimetro è un finding con codice `OUTSIDE_EVIDENCE`, che nomina il task se il JSON lo porta, altrimenti il percorso presentato; non è PASS. La riconciliazione è un archivio separato: directory esatta `reports/assurance/OCOR-DEV-REM-0068-RCCAD/reconciliation/` e nome esatto `<OCOR-DEV-NNNN>.json`. Un file il cui nome finisce in `.reconciliation.json`, dovunque sotto `reports/evidence`, è un record di evidenza: entra nel grafo o produce un finding. Non si salta per suffisso. L'identità è `record_id` se presente. Altrimenti è la mappa `reconciles` del record di riconciliazione, con chiave uguale alla stringa storica esatta che il contratto già elenca (percorso, percorso con `@sha256`, forma storica lunga, commit), e la chiave designa un solo record elencato. Il solo commit di esecuzione non è un'identità. Un record nuovo senza `record_id` e senza una chiave unica è un finding `RECONCILIATION_ABSENT`. Due record che ricevono la stessa chiave sono un finding `AMBIGUOUS_IDENTITY`. Il caricamento è iterativo, con un limite di profondità scritto nel commit di contratto: il limite è strettamente sopra la profondità massima misurata sui JSON di evidenza della base del branch, e la misura entra nel README. Oltre il limite l'esito è JSON con finding `UNREADABLE_JSON` che nomina il task e il codice, mai `RecursionError` e mai stdout vuoto. E3 riceve solo il manifest richiesto e i file che quel manifest elenca, non legge `EXECUTION_STATE.json` e non emette `MANIFEST_UNLISTED` per un task di un altro gate. E1 continua ad ammettere ogni manifest e a emettere i finding di grafo. L'oracolo resta indipendente, usa solo la libreria standard, non importa il codice di produzione e include le forme dei due verdetti insieme alle celle di perimetro di directory, di suffisso, di collisione sul commit, di profondità e di isolamento di E3. Le 51 celle restano il minimo. Le celle nuove si aggiungono e il conteggio si scrive nel commit di contratto. I test del ciclo 0 che il verdetto del ciclo 1 registra verdi non si tolgono e non si indeboliscono. Il proof di `OCOR-DEV-REM-0068-GUARD-ADMISSION (2026-11-27)` resta: l'assenza del blocco fa fallire il proof. Lo script di drift resta byte-identico. Nessun record sigillato si riscrive. Le riqualifiche di sola regressione di `OCOR-DEV-0005`, `OCOR-DEV-0050` e `OCOR-DEV-0082`, e le voci di allowlist che il contratto già elenca per la fase di codice, restano in quella fase e non in questa pubblicazione. `vf004_schema_conformance` resta `NOT_CORRECTED`. Con un nuovo `NO_GO` non c'è un altro ciclo: una sola richiesta nuova, per la regola vigente per le decision request. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore. Positivo: il produttore scrive in `reports/evidence/G0` il record `A` e il record `B` che supera `A`, e in `reports/evidence/G1` il record `C` del suo task; due manifest elencano ciascuno solo i propri file. Il consumatore E1 valida `B` per il task di `A` e `C` per il suo task. E3 sul solo manifest di G0 non legge lo stato e non emette `MANIFEST_UNLISTED` per `C`. Negativo: il produttore aggiunge, nello stesso task di `B`, un record canonico `D` nel file `second.reconciliation.json` sotto `reports/evidence`, elencato nel manifest. Il consumatore E1 ed E2 non danno PASS: `D` entra nel grafo, e il finding nomina il task e `MULTIPLE_HEADS`, oppure un altro codice del contratto. `D` non è saltato. Costo stimato: un commit di contratto, RED, GREEN, una revisione preventiva, una campagna e una verifica, da quattro a sei iterazioni. Non è la stima più breve. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Nessun commit di questa pubblicazione sopra `83c91b6775dd779d30fee608b26c91f11a808ae3` | `git rev-parse` del branch prima della ripartenza |
| Un solo selettore; E1, E2 ed E3 sono proiezioni | test che chiamano la funzione pura e i tre ingressi sullo stesso grafo |
| Perimetro di directory, non prefisso di stringa | fixture `reports/evidence-archive` su E1 e su E2 |
| Percorsi Git terminati da NUL, nome conservato fino alla lettura | il test non ASCII del ciclo 0 resta verde |
| `--record` fuori dal perimetro è `OUTSIDE_EVIDENCE` | E2 sul percorso sorella non è PASS |
| Riconciliazione solo per directory e nome esatti | il file `second.reconciliation.json` sotto l'evidenza non è saltato |
| Identità `record_id`, altrimenti chiave storica unica, mai il solo commit | due percorsi con lo stesso commit di esecuzione |
| Record nuovo senza `record_id` e senza chiave unica: `RECONCILIATION_ABSENT` | fixture del VF-004 del ciclo 1 |
| Chiave ambigua: `AMBIGUOUS_IDENTITY` | due record, una sola chiave |
| Caricamento iterativo; oltre il limite, JSON `UNREADABLE_JSON` | accettazione al limite e rifiuto sopra il limite, su ogni ingresso che carica |
| E3 legge solo il manifest richiesto e i file elencati | due manifest validi; un record estraneo non fa fallire E3; E3 senza stato non è `UNREADABLE_JSON` |
| Oracolo indipendente, soggetto il codice di produzione | l'oracolo non importa la produzione; le forme dei due verdetti sono celle |
| I test verdi del ciclo 0 restano | stessa attesa, nessun test tolto o allentato |
| Drift byte-identico; record sigillati non riscritti | `git diff` dello script di drift vuoto |
| `vf004_schema_conformance` non è `PASS` | stesso `NOT_CORRECTED` |
| Una campagna sull'HEAD finale e una verifica di fornitore diverso da xAI | verdetto sull'HEAD esatto, verifier non avviato dall'implementatore |
| Nessun ciclo ulteriore dopo un `NO_GO` | una sola richiesta nuova |

2. **Toppa enumerata dei soli VF-001, VF-002, VF-003, VF-004 e VF-005 del ciclo 1.** Non si attua in questa pubblicazione. Sopra lo stesso HEAD, senza rebase, reset o force-push, si chiudono solo quei cinque finding, con una fixture per ciascuno e senza allargare il generatore alle forme che non ha prodotto. E3 si limita al manifest richiesto; il suffisso `.reconciliation.json` non si salta; il perimetro diventa la directory; l'identità legacy non segue il solo commit; il caricamento oltre il limite emette JSON. L'oracolo resta quello della matrice di 51 celle più quei cinque casi. I test verdi del ciclo 0 restano. Lo script di drift resta byte-identico. Non elimina la causa: la prossima fixture indipendente, su una forma che il generatore non ha emesso, trova un altro buco della stessa classe. Il punto 2 di `DECISIONI-AL-PO (2026-11-16)` vieta di farne un ciclo di riparazione senza questa decisione. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: il produttore consegna `second.reconciliation.json` come seconda testa elencata nel manifest; il consumatore E1 emette `MULTIPLE_HEADS` per quel task. Una forma non nominata dai cinque finding resta fuori dal contratto di questa opzione e può ancora dare PASS. Costo stimato: RED, GREEN, una revisione preventiva, una campagna e una verifica, circa tre iterazioni. È più breve dell'opzione 1 e lascia incompleta la proprietà «un input presentato non è mai saltato». Claim invariati.

| Criterio | Prova |
| --- | --- |
| I cinque finding del ciclo 1 hanno una fixture ciascuno | i cinque casi del verdetto `OCOR-DEV-REM-0068-83c91b6775dd-1` falliscono prima del codice e passano dopo |
| Nessuna cella oltre quei cinque e la matrice di 51 | il diff dei test non aggiunge il prodotto di dimensioni nuove |
| I test verdi del ciclo 0 restano | stessa attesa |
| Drift byte-identico | `git diff` dello script di drift vuoto |
| La causa resta | il contratto non obbliga l'oracolo a generare le forme fuori dai cinque finding |
| Una verifica di fornitore diverso da xAI | verdetto sull'HEAD esatto |

3. **Restringere il contratto alle forme già coperte dai test generati.** Non si attua in questa pubblicazione. Un commit di contratto, solo sul README, dichiara ammessi i cinque comportamenti che il ciclo 1 ha rifiutato: E3 può leggere ogni record e dipendere dallo stato; un nome che finisce in `.reconciliation.json` non è evidenza; il prefisso di stringa `reports/evidence` è il perimetro; l'identità legacy può essere il commit di esecuzione; oltre la profondità di ricorsione il processo può terminare senza JSON. I test non si allentano sui casi che già passano, ma la proprietà «un input presentato non è mai saltato» non vale più per quelle forme. Non soddisfa `OCOR-DEV-REM-0068-CURRENT-HEAD-READING (2026-11-24)` né il punto 4 di `CONFINE-G6 (2026-11-20)`, che chiedono una sola testa corrente senza saltare un input. Il contratto che ne risulta è la tabella sotto. Esempio dal produttore al consumatore: il produttore mette un record corretto in G0 e un record di un altro task fuori dal manifest di G0; il consumatore E3 di G0 emette `MANIFEST_UNLISTED` per il task estraneo e il contratto ristretto chiama quell'esito conforme. Il fail-closed resta incompleto. Costo stimato: un commit di contratto e una verifica, circa due iterazioni, senza campagna nuova. È la più breve e non consegna il gate dell'unità. Claim invariati.

| Criterio | Prova |
| --- | --- |
| Il README ammette i cinque comportamenti del ciclo 1 | diff limitato al README e rilettura delle cinque frasi |
| I test già verdi non si allentano | stesso insieme di asserzioni sui casi generati |
| La proprietà del perimetro e del salto silenzioso non è più quella del contratto rifiutato | il README non ripete «un input presentato non è mai saltato» per quelle forme |
| Nessuna campagna nuova | nessun commit di campagna sopra l'HEAD rifiutato |
| `vf004_schema_conformance` non è `PASS` | stesso `NOT_CORRECTED` |

## Raccomandazione

Opzione 1. È la sola che realizza per intero la proprietà già adottata ed elimina la causa: un solo selettore, ogni input presentato entra nel grafo o produce un finding, e l'oracolo non è il codice in prova. Non si raccomanda perché è la più breve. L'opzione 2 è più breve e lascia la causa: la copertura resta l'elenco dell'ultimo verdetto. L'opzione 3 è ancora più breve e lascia incompleto il fail-closed, perché cambia la proprietà invece di attuarla. Chi apre questa richiesta non ne applica nessuna opzione.

## Impatto

Unità bloccata da questa richiesta finché è aperta: `OCOR-DEV-REM-0068`. Finché la richiesta è aperta non si modifica né si mergia `83c91b6775dd779d30fee608b26c91f11a808ae3`, non si apre la sua pull request, non si apre un ciclo 2 e non si avvia una campagna. `OCOR-DEV-REM-0060` non si avvia. Il ciclo 4 di `OCOR-DEV-REM-0066` non parte. `EVIDENCE-INPUTS-AND-RETENTION` non si apre prima che `OCOR-DEV-REM-0068` sia su `origin/main`.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim da questa pubblicazione. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. L'estensione dell'allowlist per il percorso di questa richiesta è un change set a parte e non fa parte di questa pubblicazione: il validatore del piano non si modifica qui.

## Disposition

`OCOR-DEV-REM-0068-REDESIGN (2026-11-28)`. Decisa per conto del PO, modello `claude-fable-5-2`, effort `max`. Opzione adottata: 1. Vale come decisione del PO a ogni effetto.

Il file della richiesta al commit `af3eb66ef9a40fc24c72ab63864e878f36e785cb` ha sha256 `ba518f39ccc7a3e709e4dd4a834cd264d90db08b20b374348f3cc38fe4013195`. Le frasi di questo file che dicono che la richiesta è aperta e che nessuna opzione è applicata descrivono quella pubblicazione. Da questo commit non valgono più come blocco.

L'opzione 1 si attua sul branch `governed/ocor-dev-rem-0068-current-head`, sopra `83c91b6775dd779d30fee608b26c91f11a808ae3`, senza rebase, reset o force-push. Il commit di contratto è `44f2ca31c1266bf5f7df92ba208baf630c486858`: cambia solo `reports/assurance/OCOR-DEV-REM-0068-RCCAD/README.md`. Non è un ciclo di riparazione 2. Il passo successivo è RED. Non si apre la pull request del codice, non si avvia la campagna e non si scrive `verify_request.json` in questo commit. `OCOR-DEV-REM-0060` non parte. `EVIDENCE-INPUTS-AND-RETENTION` non si apre prima che `OCOR-DEV-REM-0068` sia su `origin/main`. Il ciclo 4 di `OCOR-DEV-REM-0066` e ogni unità che cambia `scripts/validate_ocor_development_plan.py` o `reports/tests/test_kind_teardown_observation.py` restano fermi. `vf004_schema_conformance` resta `NOT_CORRECTED` e non è `PASS`.

Nessun nuovo `DEC-*`. Nessuna modifica a `inputs/`, ai record sigillati, ai gate, alle soglie o ai claim. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

