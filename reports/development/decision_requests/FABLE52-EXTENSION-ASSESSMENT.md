# FABLE52-EXTENSION-ASSESSMENT

Status: `DECIDED_BY_PO`. Livello: normativo. Questo file è il riferimento di
`po_decision_ref` delle voci `NCR-C3-008`, `NCR-C3-009` e `NCR-PLAN-007`.
Scritto dall'unità `OCOR-DEV-REM-0064` secondo il punto 8 di
`FABLE52-EXTENSION-ASSESSMENT (2026-11-12)` e il punto 4 di
`FABLE52-EXTENSION-NCP-U15-ID-COLLISION (2026-11-13)`.
Implementatore: Grok Build (xAI), modello grok-4.7.

La relazione esterna «OCOR — Independent Assessment of the Extension Proposal (Annex A)»
del 2026-11-12, preparata da Claude Fable 5.2 (Anthropic) sul commit
`1be8dd6ad73c1af94cb6726c70b8243ec8498ad3` di `main` (sha256 del file consegnato al PO
`fc90b6bb781ef43ec773090138f62ba34d2908bbce43498ae3dcc9be008eacd0`), non è in questo
repository. Le opzioni non adottate restano in quella relazione ed entrano nel
repository con l'unità di attuazione di NCP-U16. La relazione non è evidenza, non
verifica requisiti e non chiude gate. Non si aggiunge una voce aperta in `blockers`.

## Richieste e opzione adottata

Il PO adotta l'opzione 1 di ciascuna delle quattro richieste della sezione 10 della
relazione. I punti della decisione, dove differiscono dalla relazione, prevalgono.

1. **IDENTITY-RESOLUTION-AND-CLAIM-ADMISSION-SPEC.** Opzione 1, resa operativa dal
   punto 3 della decisione: un'unità del programma di conformità che specifica e poi
   attua l'handler `AdmitClaim` di C3 e la risoluzione delle identità, dopo
   l'integrazione di NCP-U12, sul backend reale già usato da C3, C4 e C6. Per la
   collisione sotto, l'identificativo di plan unit è `NCP-U16`, non `NCP-U15`.
2. **IDENTITY-NO-MATCH-DECISION-SEMANTICS.** Opzione 1, resa operativa dal punto 4:
   `decision outcome` di `IdentityResolutionDecision` assume uno fra `MERGE`, `SPLIT`,
   `NO_MATCH` e `DEFERRED`. Una decisione `NO_MATCH` lega l'insieme delle Source
   Identity considerate e il digest dell'insieme di evidenze, è bitemporale e si
   rovescia solo con una decisione nuova. La regola di non riapertura si pianifica
   ora e si realizza dopo la decisione su G7.
3. **UPSTREAM-ACQUISITION-COMPONENT-BOUNDARY.** Opzione 1, resa operativa dal punto 6,
   confine dell'acquisizione a monte: l'estrazione da documenti e l'acquisizione sono
   un prodotto separato, in un repository proprio. Nulla di quel punto si esegue prima
   della decisione del PO su G7.
4. **INTEGRATION-READY-RELEASE-PROFILE.** Opzione 1, resa operativa dal punto 6,
   profilo «integration-ready»: è un profilo di rilascio con nome, non un claim, e un
   esito del PoC non lo dimostra. Nulla di quel punto si esegue prima della decisione
   del PO su G7.

## Collisione dell'identificativo di plan unit

Verifica in sola lettura sul WIP di `OCOR-DEV-REM-0060`, branch
`governed/ocor-dev-rem-0060-ncp-u12-tests`, commit
`b869cc9c0e92b6d23b386cf5162c07d3ebc12aec`: il registro di quel commit contiene le
plan unit `NCP-U01` … `NCP-U15`. `NCP-U15` resta l'unità dei reason code. Il WIP non
si rinomina. Il primo identificativo libero dopo quelli già presenti sul WIP è
`NCP-U16`. La decisione di collisione
(`reports/development/decision_requests/FABLE52-EXTENSION-NCP-U15-ID-COLLISION.md`,
branch `governed/decision-request-fable52-extension-assessment`, commit
`142514fa302f23a49ee5695a2e25da6bb3f4054a`, sha256
`ead04b383877358e820aa0e9bf8298aebf9578772f46dc11748f74516d868ca7`) sceglie
l'opzione 1. Le due voci `OPEN` usano quindi `plan_unit` `NCP-U16`, con stima 8,
dipendenza da `NCP-U12` e il backend reale già usato da C3, C4 e C6. La voce della
vista del mission thread resta `DECISION_REQUIRED`, senza `plan_unit`.

## Disposition

Il testo integrale delle due decisioni del PO, riportato senza modifiche, è la
disposition. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`. Claim invariati: `E1=0`,
`E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

### Testo integrale di FABLE52-EXTENSION-ASSESSMENT (2026-11-12)

## FABLE52-EXTENSION-ASSESSMENT (2026-11-12) — decisione normativa del PO

Decisione **di livello normativo**, presa dal PO con istruzione esplicita il 2026-11-12, dopo la valutazione indipendente di una proposta di estensione di OCOR: relazione «OCOR — Independent Assessment of the Extension Proposal (Annex A)» del 2026-11-12, preparata da Claude Fable 5.2 (Anthropic) sul commit `1be8dd6ad73c1af94cb6726c70b8243ec8498ad3` di `main`; sha256 del file consegnato al PO `fc90b6bb781ef43ec773090138f62ba34d2908bbce43498ae3dcc9be008eacd0`. Il PO adotta l'opzione 1 di ciascuna delle quattro richieste della sezione 10 della relazione: `IDENTITY-RESOLUTION-AND-CLAIM-ADMISSION-SPEC`, `IDENTITY-NO-MATCH-DECISION-SEMANTICS`, `UPSTREAM-ACQUISITION-COMPONENT-BOUNDARY` e `INTEGRATION-READY-RELEASE-PROFILE`. I punti che seguono le rendono operative e, dove differiscono dalla relazione, prevalgono. La relazione è un resoconto di revisione: non è evidenza, non verifica requisiti e non chiude gate. ADD v1.3, LLD v1.1, contratti, schemi e registri del dossier, Register, backlog, piano di tracciabilità, test esistenti, limiti e claim non cambiano. Nessun nuovo `DEC-*`, salvo che la procedura vigente lo richieda.

1. **Divergenze.** Ricontrolla ciascuna all'head prima di registrarla. Se una non si riproduce, registrala `REFUTED` con la prova e non attuare i punti che la riguardano.
   - **Ammissione dei claim.** ADD v1.3 assegna a C3 l'handler di ammissione e il port `AdmitClaim` (riga 284), ne fissa la regola (riga 342: C3 accetta `AdmitClaim` solo con `Decision` e `Authority ref` validi, non scaduti e coerenti con il `GatePackage`) e stabilisce che l'ammissione genera una Canonical Assertion collegata alla Claim sorgente (riga 2048). `FR-053` e `FR-054` (Register righe 175 e 176: P0, PoC) chiedono il workflow di ammissione e la traccia di adjudication. In `ocor-runtime/src` nessun simbolo realizza `AdmitClaim` e LLD v1.1 non lo specifica.
   - **Risoluzione delle identità.** `FR-012`, `FR-030`, `FR-150` e `NFR-055` (Register righe 65, 120, 335 e 336: P0, PoC) e ADD v1.3 §3.6 (righe 2010–2015 e 2051) chiedono candidate match, decisioni di merge e split reversibili e membership bitemporali. Il codice contiene solo le shape di validazione (`ocor-runtime/src/ocor_runtime/c4/shacl.py`) e i nomi degli output del ruolo Fusion/Identity (`ocor-runtime/src/ocor_runtime/c8/orchestrator.py`); LLD v1.1 non specifica né i record né le operazioni.
   - **Vista del mission thread.** `FR-166` (Register riga 411: P0, PoC) e LLD v1.1 §2.9 (riga 246) chiedono una vista governata del mission thread. Nessun simbolo la realizza, e il piano di tracciabilità la assegna al task della FSM (`OCOR-DEV-0043`), che non la consegna.
2. **Registro, nello state sync che registra questa decisione.** Solo lì, e senza altre modifiche del registro di conformità:
   - tre voci nuove, ciascuna con il primo identificativo libero della sua serie verificato in sola lettura, tutti i campi delle voci esistenti, `norm_refs` alle righe del punto 1, `verification` con comando ed esito reali all'head, `po_decision_ref` al file del punto 8:
     - ammissione dei claim: serie `NCR-C3`, `MISSING`, `HIGH`, `requirement_ids` `FR-053` e `FR-054`, stato `OPEN`, `plan_unit` `NCP-U15`;
     - risoluzione delle identità: serie `NCR-C3`, `MISSING`, `HIGH`, `requirement_ids` `FR-012`, `FR-030`, `FR-150` e `NFR-055`, stato `OPEN`, `plan_unit` `NCP-U15`;
     - vista del mission thread: serie `NCR-PLAN`, `MISSING`, `HIGH`, `requirement_ids` `FR-166`, stato `DECISION_REQUIRED`, senza `plan_unit`, con le `decision_options` del punto 5;
   - `blocks` di ogni voce: ogni task G6 non ancora avviato i cui `requirement_ids`, nel backlog all'head, comprendono un requisito della voce. Sul commit analizzato sono `OCOR-DEV-0060` e `OCOR-DEV-0063` per la prima, `OCOR-DEV-0063` e `OCOR-DEV-0065` per la seconda, `OCOR-DEV-0063` per la terza. Aggiungi l'identificativo della voce all'elenco `blocking_register_entries` di `g6_g7_proposals.tasks` per ciascuno di quei task;
   - `plan_units` riceve `NCP-U15` con tutti i campi richiesti dal test d'integrità: `scope`, `resolves` con le prime due voci, `acceptance_criteria` e `red_tests` per ciascuna con le ancore del punto 1 e i criteri del punto 3, `estimate_iterations` 8, `status` `PROPOSED`, `required_backend` lo stack reale che C3, C4 e C6 già usano, `depends_on_units` `["NCP-U12"]`. `plan_order` lo aggiunge in coda; `plan_summary` si aggiorna; il test d'integrità passa.
3. **Unità `NCP-U15`: ammissione dei claim e risoluzione delle identità.** È un'unità del programma di conformità, aggiunta al piano approvato da questa decisione. Risolve le prime due voci del punto 2 e nient'altro. Si esegue dopo l'integrazione di NCP-U12 e prima del primo task G6 che una delle due voci blocca. Stima: 8 iterazioni; vale il punto 2 di `NCP-THROUGHPUT-RULES (2026-11-05)`. Segue il ciclo completo e le regole delle unità del programma (punti 5–8 della decisione del programma; punti 2, 5 e 7 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`).
   - **Specifica prima del codice.** La specifica è il file nuovo `docs/OCOR_LLD_v1.1_ADDENDUM_A.md`, «Addendum A a LLD v1.1: ammissione dei claim e risoluzione delle identità». È subordinata ad ADD v1.3 e a LLD v1.1, che non cambiano e prevalgono. Definisce, e solo questo: l'handler `AdmitClaim` di C3 e il suo record di comando; i record chiusi `CandidateMatch`, `MatchEvidence`, `IdentityResolutionDecision` con `MergeDecision` e `SplitDecision`, e `ClusterMembershipAssertion`, con i campi di ADD v1.3 righe 2010–2015; i tipi d'azione di C6 che portano ammissione, merge e split come decisioni con `effect_class` `CANONICAL_COMMIT` (ADD v1.3 riga 342); gli output del ruolo Fusion/Identity di C8; il ritiro o il ricalcolo delle derivazioni dipendenti dopo uno split (ADD v1.3 riga 2051); un matcher deterministico, con versione fissata, per le sole fixture sintetiche; il reason code di ogni rifiuto, preso dai contratti esistenti. Ogni record, campo, regola ed esito cita l'elemento di ADD v1.3, LLD v1.1 o Register che realizza, con file e riga, oppure il punto 4 di questa decisione.
   - **Origine della specifica.** Il PO la fa preparare fuori dal loop da Claude Fable 5.2 (Anthropic) e la pubblica, insieme alla relazione, sul branch `governed/fable52-extension-package-20261112` con una pull request in bozza. Se all'avvio dell'unità il branch è su `origin`, porta nell'unità i suoi file senza cambiarne il senso: una correzione chiesta da un controllo del repository è un commit a parte, annotato nel record. Dichiara Anthropic fra gli autori dell'unità nella richiesta di verifica e, a integrazione avvenuta, chiudi la pull request in bozza con il riferimento. Se il branch non c'è, scrivi tu la specifica nella prima iterazione dell'unità, con gli stessi vincoli: l'unità non attende.
   - **Quesiti.** Ciò che la specifica deve fissare e che né ADD v1.3, né LLD v1.1, né il Register, né questa decisione determinano è un quesito di norma. Tutti i quesiti stanno in una sola decision request di livello normativo, con opzioni e raccomandazione, aperta prima del codice che ne dipende, come chiede `NORMATIVE-QUESTIONS-EARLY-DR (2026-11-09)`. Il lavoro sulle parti che hanno un'ancora prosegue.
   - **Attuazione.** RED prima del codice, in un modulo di test nuovo; backend reali, nessuno skip; nessuna nuova dipendenza: se ne serve una, fermati e apri una decision request. Il matcher sta dietro un port del ruolo Fusion/Identity, così che dopo la decisione su G7 un altro matcher possa sostituirlo senza cambiare record né decisioni. Prima della decisione su G7: nessun matcher probabilistico, nessuna estrazione da documenti.
   - **Criteri.** (a) La specifica nomina ogni record con un insieme chiuso di campi. (b) Una fixture con omonimie e claim contraddittori conserva candidate separate fino all'adjudication. (c) Un merge seguito da uno split ricostruisce entrambe le viste bitemporali e ritira o ricalcola ogni derivazione che dipendeva dal merge. (d) Un candidate match senza decisione accettata non produce membership, link né inferenze: caso negativo. (e) L'ammissione di un claim senza `Decision` e `Authority ref` validi è rifiutata con il reason code della norma e non scrive nulla. (f) Ogni esito di una decisione, rigetti compresi, è registrato con adjudicator, razionale e versione dell'insieme di evidenze.
   - **Strumento di tracciabilità.** Nella stessa unità, un validatore nuovo sotto `scripts/`, in sola lettura, con i suoi test sotto `reports/tests/`. Per ogni riga del piano di tracciabilità con profilo di campagna PoC dice se l'identificativo del requisito compare sotto `ocor-runtime/src`, `ocor-runtime/tests` o `reports/tests`; un file di esenzioni dà un motivo per ogni identificativo escluso; uscita JSON; esce con 0 in modalità predefinita e con 1, con `--strict`, se un identificativo non è né citato né esente. Non entra nei workflow e non cambia l'esito di alcun controllo esistente. Il record dell'unità ne riporta l'esito prima e dopo per `FR-012`, `FR-030`, `FR-150` e `NFR-055`.
   - **Registro e piano.** Nell'unità le due voci passano a `IN_REMEDIATION` con `remediation_unit`, `remediation_record` e la prova. Backlog e piano di tracciabilità non cambiano: il record dell'unità dichiara quali requisiti realizza.
4. **Esiti delle decisioni di identità.** `decision outcome` di `IdentityResolutionDecision` (ADD v1.3 riga 2012) assume uno fra `MERGE`, `SPLIT`, `NO_MATCH` e `DEFERRED`. Una decisione `NO_MATCH` lega l'insieme delle Source Identity considerate e il digest dell'insieme di evidenze; è bitemporale; si rovescia solo con una decisione nuova. NCP-U15 realizza gli esiti e il record. La regola di non riapertura si pianifica ora e si realizza dopo la decisione su G7 (punto 6): finché la decisione è in vigore, un candidato sullo stesso insieme con lo stesso digest non si riapre e resta interrogabile come soppresso, con il riferimento alla decisione; un digest diverso lo riapre. Le shape di ADD v1.3 §3.6 non cambiano in NCP-U15: se un esito richiede di estenderle, è un quesito del punto 3.
5. **Vista del mission thread.** La terza voce resta `DECISION_REQUIRED`: decide il PO, a parte. `decision_options`: 1. contratto di lettura governato, senza interfaccia grafica: un read model tipizzato servito dal gateway, che collega gli stadi del mission thread a provenance e decision trace, verificato con dimostrazione da riga di comando, test di controllo degli accessi e ispezione delle trace; 2. come la 1, più un client operatore minimo nel PoC; 3. nessuna unità dedicata: la realizza il task che la verifica. Fino alla decisione la voce blocca solo i task del suo `blocks`.
6. **Dopo la decisione su G7.** Nulla di questo punto si esegue prima della decisione del PO su G7. Entra nel piano dopo il PoC, alle regole dei punti 3 e 4 di `FABLE52-POST-POC-PROGRAMME (2026-11-11)`: file nuovi, task `PLANNED_NOT_ACTIVE`, piano approvato intatto. Se quella sezione non è in questo file, questo punto resta registrato e non autorizza alcuna unità.
   - **Profilo «integration-ready».** È un profilo di rilascio con nome. Il piano lo definisce come le regole d'ingresso e l'ambito del MVP (`BR-016` e `BR-017`, Register righe 434 e 435) più questo elenco: superficie di servizio del runtime (listener di rete, immagini e identità di workload per gateway, ingestione e sottomissione delle azioni, che oggi `ocor-runtime/src` non ha); runtime di ammissione e identità di NCP-U15 irrobustito; kit di contratto per connettori e per adapter d'azione, con suite di conformità; superfici operatore (coda di adjudication, console di quarantena e dead letter, vista del mission thread); percorso di upgrade, migrazione e rollback; un sottoinsieme dichiarato di evidenze di recovery, sicurezza e SLO. Non è un claim e un esito del PoC non lo dimostra (`BR-012`, `NFR-050`).
   - **Identità.** La regola di non riapertura del punto 4 e un matcher probabilistico come modulo sostituibile dietro il port del ruolo Fusion/Identity, con ogni dipendenza soggetta a `docs/development_methodology/OCOR_EXTERNAL_DEPENDENCY_POLICY.md` e a `NFR-073`.
   - **Confine dell'acquisizione a monte.** L'estrazione da documenti e l'acquisizione sono un prodotto separato, in un repository proprio: non entra in questo repository, non scrive stato né proiezioni e consegna solo envelope di ingestione con `semantic_class` `CLAIM` e candidate match. OCOR riceve due sole voci: un profilo di estrazione generato da C1 a partire dall'IR, con controllo di drift, e una superficie di lettura autorizzata dello stato degli item in C5. La seconda aggiunge un port di C5 (ADD v1.3 riga 286) e richiede, dopo G7, una decision request di livello normativo.
7. **Pin esatti delle dipendenze.** I vincoli a intervallo di `ocor-runtime/pyproject.toml` passano alle versioni esatte già registrate in `uv.lock`, senza cambiare alcuna versione risolta. Non è un change set a sé: si fa nella prima unità che modifica già quel file per una ragione autorizzata, con le riqualifiche che quell'unità comporta comunque. Per quella sola modifica è ammessa la variazione di `uv.lock` che ne deriva.
8. **Registrazione e claim.** Al primo state sync scrivi `reports/development/decision_requests/FABLE52-EXTENSION-ASSESSMENT.md` con stato `DECIDED_BY_PO`: le quattro richieste per nome, l'opzione adottata di ciascuna come la descrivono i punti di questa decisione, e il testo integrale di questa decisione come disposition. Le opzioni non adottate stanno nella relazione, che entra nel repository con l'unità `NCP-U15`. È il riferimento di `po_decision_ref` (percorso e sha256) ed entra nell'elenco dei percorsi del validatore del piano; non aggiungere per esso una voce aperta in `blockers`. Registra la decisione in `po_normative_decisions_registered` di `EXECUTION_STATE.json`, con livello `NORMATIVE` e `taken_by` «Product Owner, explicit instruction 2026-11-12», e nell'`ITERATION_LOG.md`. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

### Testo integrale di FABLE52-EXTENSION-NCP-U15-ID-COLLISION (2026-11-13)

## FABLE52-EXTENSION-NCP-U15-ID-COLLISION (2026-11-13) — decisione del PO

Decisione normativa del PO sulla decision request `FABLE52-EXTENSION-NCP-U15-ID-COLLISION` (branch `governed/decision-request-fable52-extension-assessment`, commit `142514fa302f23a49ee5695a2e25da6bb3f4054a`, path `reports/development/decision_requests/FABLE52-EXTENSION-NCP-U15-ID-COLLISION.md`, sha256 `ead04b383877358e820aa0e9bf8298aebf9578772f46dc11748f74516d868ca7`), presa con istruzione esplicita del PO il 2026-11-13. Scelta: **opzione 1**, come raccomandato.

1. `NCP-U15` resta l'unità dei reason code, come sul WIP di `OCOR-DEV-REM-0060` (branch `governed/ocor-dev-rem-0060-ncp-u12-tests`, commit `b869cc9c0e92b6d23b386cf5162c07d3ebc12aec`). Il WIP non si rinomina.
2. Le due voci nuove di `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)`, ammissione dei claim e risoluzione delle identità, usano il primo identificativo di plan unit libero dopo quelli già presenti sul WIP, verificato in sola lettura. Hanno gli stessi campi che quella decisione assegnava a `NCP-U15`: stima 8, dipendenza da `NCP-U12`, le due sole voci, backend reale già usato da C3, C4 e C6.
3. La voce della vista del mission thread resta `DECISION_REQUIRED`, senza `plan_unit`.
4. È autorizzata la scrittura sul registro di conformità delle voci e della plan unit descritte dal punto 2 di `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)`, con l'identificativo del punto 2, come unità governata con revisione preventiva e verifica indipendente. Non tocca il backlog approvato né `OCOR-DEV-REM-0061`, e non ha la precedenza sul ciclo 5 di `OCOR-DEV-REM-0061`.
5. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`. Nessun nuovo `DEC-*`; nessuna modifica a `inputs/`.
