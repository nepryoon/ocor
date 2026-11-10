# NCP-U12-TEST-REALIGNMENT-SCOPE

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0060`
(NCP-U12 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, test; branch `governed/ocor-dev-rem-0060-ncp-u12-tests`, base
`913b43d59017468ba694c1f638ec370c889c8bfb`, RED `6604033`) e le voci `NCR-TESTS-001`, `NCR-TESTS-003` e
`NCR-TESTS-004` di `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Aperta all'avvio dell'unità secondo
`NORMATIVE-QUESTIONS-EARLY-DR (2026-11-09)` e `NORMATIVE-QUESTIONS-EARLY-DR-PO-CONSTRAINTS (2026-11-09)`: ogni
quesito si risolve solo scegliendo fra due letture del piano approvato e dei punti 5 e 7 delle decisioni
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` e `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)` (decisioni normative del
PO). Le questioni sono raccolte in un'unica richiesta perché tutte riguardano le differenze che l'unità può portare ai
test esistenti. Implementatore: Claude Code (Anthropic), implementatore di riserva.

## Contesto

- Il piano approvato assegna a NCP-U12 (`plan_units.NCP-U12` del registro) l'ambito «Tests: mission thread through
  the retained C1-C8 components (no legacy classes, no spike adapters or oracles); closed-record, exact-field-set and
  negative-corpus meta-tests ...; schema integrity over the LLD v1.1 §0.2 contracts; reason-code assertions in
  negative tests; technique routing», con `code_paths` vuoto e un solo test esistente da adattare:
  `ocor-runtime/tests/mission_thread/test_first_governed_slice.py`, tipo `ADAPT_CONSTRUCTION`, `red_required`
  `false`, valore prescritto «the retained C1-C8 components and real adapters; syntax-tree comparison (same
  functions, assertions, raises, parametrisations)». `NCP-U01-RETAINED-C1-BUILDERS (2026-11-01)` punto 4 aggiunge la
  pipeline conforme di C1 (sorgente OaC e firmatario) e la riqualifica con supersession di `OCOR-DEV-0031`.
- Il punto 5 di `NORMATIVE-CONFORMANCE-PLAN` ammette, oltre al piano, il riallineamento con RED di un test che
  «asserisce un valore o un comportamento che contraddice l'elemento normativo chiuso che la voce realizza» (caso 1),
  l'aggiornamento di una sha256 fissata (caso 2) e l'adattamento della costruzione senza RED (caso 3); fuori da
  questi casi l'unità si ferma e apre una decision request. Il punto 7 della decisione del programma vieta, nella
  funzione riallineata, ogni altra modifica e ogni allentamento.
- **Tipi legacy richiesti dai componenti mantenuti.** Le firme dei componenti mantenuti richiedono oggi oggetti di
  classi della slice legacy: `IdentityRegistry` (`ocor-runtime/src/ocor_runtime/c2/gateway.py` righe 209 e 883,
  `c2/provisioning.py` riga 144, `c6/composition.py` riga 190, `c6/human_gate.py` righe 174 e 474, `c6/safety.py` riga
  609), `EmissionFence` (`c6/composition.py` riga 262, `c6/engine.py` riga 595), `CapabilityAuthority`
  (`c8/orchestrator.py` riga 790), `MarkingSet` (`c2/gateway.py` riga 846, `c4/object_projection.py` riga 150,
  `c8/tool_runtime.py` righe 1095-1096) e `MarkingSchemeDefinition` (`memory/model.py` riga 1256). Un mission thread
  che compone i componenti mantenuti deve quindi costruire quegli oggetti; l'ambito «no legacy classes» non dice se
  ciò sia ammesso, e la sostituzione di quei tipi nei componenti è codice di runtime, fuori da `code_paths`.
- **Asserzioni del mission thread che i componenti mantenuti rendono non conformi.** Nel file al commit `913b43d`:
  riga 431 `assert receipts.causal_outcome.status == "IDENTIFIED"`, mentre il runtime causale mantenuto restituisce
  `ESTIMATED` (`ocor-runtime/src/ocor_runtime/c7/runtime.py` riga 51; ADD v1.3
  `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md` riga 2981; voce `NCR-C7-003`); righe 241 e
  430 `... is AgentDecision.IDENTIFY`, dove `AgentDecision` è l'enum della classe legacy `c8_agent.AgentKernel`
  (`ocor-runtime/src/ocor_runtime/c8_agent.py` riga 411), che il kernel C8 corrente non produce (il ruolo
  `Fusion/Identity` del kernel produce output tipizzati, ADD v1.3 righe 3057-3064, e il ciclo del task è quello di ADD
  v1.3 righe 3101-3106); riga 429 `assert len(receipts.kafka_record_digest) == 64`, cioè l'hex grezzo dell'oracolo
  spike `KafkaCli`, mentre l'envelope di C5 porta `integrity.payload_digest` nella forma `sha256:<hex>`
  (`ocor-runtime/src/ocor_runtime/c5/envelope.py` righe 10-11; LLD v1.1 `docs/OCOR_LLD_v1.1.md` riga 154). Con i
  componenti mantenuti queste asserzioni non possono restare identiche: l'adattamento di sola costruzione richiede
  «same assertions», il caso 1 parla di un elemento normativo «che la voce realizza» e `NCR-TESTS-001` realizza
  FR-172 (Register v1.1 riga 427) e LLD v1.1 riga 409, non gli stati di C7, C8 o C5.
- **Altre asserzioni dello stesso tipo (emendamento del 2026-11-10).** Una composizione di prova del thread con i
  componenti mantenuti, eseguita sullo stack reale dopo l'apertura della richiesta (i cinque test del modulo passano
  con le sostituzioni descritte qui), mostra altre quattro asserzioni dello stesso file al commit `913b43d` che non
  possono restare identiche, omesse nella prima stesura: righe 161 `assert outcome.status is
  ResolutionStatus.IDENTIFIED` e 162 `assert outcome.canonical_id is not None`, perché la risoluzione dell'identità del
  componente mantenuto (`IdentityBackedAuthority.resolve`, `ocor-runtime/src/ocor_runtime/c2/gateway.py` righe
  200-215) restituisce l'identificativo canonico come stringa, oppure il valore `ABSTAIN`, e non l'esito della classe
  legacy; righe 432 `assert receipts.causal_outcome.lineage["correlation_id"] == correlation_id` e 433 `assert
  receipts.causal_outcome.lineage["causation_id"] == receipts.action_event_id`, perché il runtime causale mantenuto
  tiene gli identificativi di traccia fuori dalla lineage e dal digest di riproducibilità, nel campo `trace` del
  risultato (`ocor-runtime/src/ocor_runtime/c7/runtime.py` righe 21-22, 450 e 695; voce `NCR-C7-005`; Register v1.1
  riga 61, NFR-007; la lineage di LLD v1.1 riga 177 e di ADD v1.3 righe 2980-2990 non comprende la traccia). Gli
  altri cambiamenti richiesti dalla composizione sono di sola costruzione e non toccano asserzioni: gli input della
  query causale sono un SCM registrato con il suo insieme fattuale (il modello dello spike non è un SCM ammesso dal
  runtime mantenuto); il valore di un record letto dal backbone di C5 è il `payload` dell'evento consegnato, così le
  righe 577 e 583 restano identiche; la proiezione TypeDB non ancora allineata al commit si ottiene osservando il
  commit senza applicarlo, così la riga 567 resta identica.
- **Test di integrità degli schemi.** `ocor-runtime/tests/schemas/test_schema_integrity.py` righe 18-19 legge
  `ocor-runtime/schemas` (artefatti della slice legacy) e alla riga 46 asserisce `"no normative JSON schemas found"`,
  cioè presenta quell'insieme come normativo; la voce `NCR-TESTS-003` chiede che l'integrità parta dai sei contratti di
  LLD v1.1 §0.2 (righe 20-31). Il test non è nell'elenco del piano. Un test nuovo sui contratti manifestati
  (`ocor-runtime/tests/schemas/test_materialised_contract_integrity.py`, RED in `6604033`) non richiede decisione; la
  qualificazione come legacy del test esistente sì.
- **Reason code nei test negativi.** Al commit `913b43d` la sonda della voce `NCR-TESTS-004` conta 301 occorrenze di
  `pytest.raises(..., match=...)` in `ocor-runtime/tests` e `reports/tests`, 293 senza un'asserzione su `reason_code`
  nei 600 caratteri successivi, in 44 moduli (nessuno della slice legacy), quasi tutti di task chiusi e sigillati. Il
  riferimento normativo della voce è `docs/development_methodology/OCOR_TEST_STRATEGY.md` righe 28-29 («Sono
  obbligatori requisiti, invarianti, guard, 44 transizioni, failure codes e rollback»). Aggiungere un'asserzione alle
  funzioni esistenti non rientra nei casi 1-3 (un `match=` sul messaggio non contraddice la norma) e il punto 7 vieta
  di cambiare altro nella funzione; un test nuovo lascia invariato il conteggio della sonda.
- Budget: iterazione 1 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2).

## Opzioni

Quesito A: tipi legacy richiesti dalle firme dei componenti mantenuti. Quesito B: asserzioni del mission thread non
conformi con i componenti mantenuti. Quesito C: qualificazione del test di integrità degli schemi legacy. Quesito D:
come si risolve `NCR-TESTS-004`.

### Opzioni del quesito A

A1. **Solo come argomenti richiesti da una firma mantenuta (raccomandata).** Il mission thread esercita ogni
   capability (risoluzione dell'identità, deliberazione, autorità, emissione, marking) attraverso il componente
   mantenuto; può importare dalla slice legacy soltanto le classi che una firma di un componente mantenuto richiede
   come argomento (oggi `IdentityRegistry` e `IdentityRecord`, `EmissionFence`, `CapabilityAuthority`, `MarkingSet` e
   `MarkingSchemeDefinition`), ciascuna con un commento che la qualifica come legacy e cita file e riga della firma.
   Nessun metodo di quelle classi è chiamato dal test per ottenere un esito del thread. Il test RED dell'unità
   ammette esattamente quell'elenco, adattato prima di ogni GREEN e registrato nel record; l'elenco entra fra le
   dipendenze residue della decision request `NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT`. Nessun modulo `spikes.*`.
A2. **Nessuna classe legacy nel test, sostituzione nei componenti.** NCP-U12 sostituisce nelle firme dei componenti
   mantenuti i tipi legacy con tipi dei pacchetti correnti, con RED/GREEN e ancore; `code_paths` dell'unità si estende
   a `c2/gateway.py`, `c2/provisioning.py`, `c4/object_projection.py`, `c6/composition.py`, `c6/engine.py`,
   `c6/human_gate.py`, `c6/safety.py`, `c8/orchestrator.py`, `c8/tool_runtime.py` e `memory/model.py`, con le
   riqualifiche dei task i cui ultimi record li hanno fra gli input. La slice legacy non cambia.

### Opzioni del quesito B

B1. **Riallineamento al valore del componente mantenuto, con RED (raccomandata).** Le asserzioni delle righe 161,
   162, 241, 429, 430, 431, 432 e 433 si riallineano come nel caso 1 del punto 5 del piano, ciascuna con la citazione
   della norma in un commento, RED con fingerprint sul thread con i componenti mantenuti e GREEN: riga 431
   `== "ESTIMATED"` (ADD v1.3 riga 2981); righe 241 e 430 l'esito tipizzato dell'identità prodotto dal ruolo
   `Fusion/Identity` del kernel C8 corrente sopra la risoluzione del gateway, uguale all'identità canonica risolta (ADD
   v1.3 righe 3057-3064 e 3101-3106); righe 161 e 162 l'identità canonica restituita dalla risoluzione del gateway,
   uguale a quella registrata e diversa da `ABSTAIN` (`c2/gateway.py` righe 200-215); riga 429 `payload_digest` nella
   forma `sha256:` seguita da 64 cifre esadecimali minuscole (LLD v1.1 riga 154); righe 432 e 433 gli stessi
   identificativi letti dal campo `trace` del risultato causale invece che dalla lineage (`NCR-C7-005`, Register v1.1
   riga 61). Numero di funzioni e di asserzioni invariato, nessun valore accettato in più; tutte le altre righe sono
   adattamenti di sola costruzione con confronto dell'albero sintattico. La riqualifica di `OCOR-DEV-0031` resta con
   supersession, qualificante per i soli requisiti legabili secondo `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)`.
B2. **Asserzioni invariate, modulo nuovo.** Il modulo esistente resta invariato e qualificato come legacy nella
   docstring; un modulo nuovo, `ocor-runtime/tests/mission_thread/test_retained_mission_thread.py`, esegue il
   thread con i componenti mantenuti e asserisce i valori prescritti. Nessuna asserzione esistente cambia; la
   riqualifica di `OCOR-DEV-0031` è di sola regressione; il modulo nuovo porta l'evidenza dell'unità.

### Opzioni del quesito C

C1. **Qualificazione come legacy, senza cambiare i controlli (raccomandata).** In
   `ocor-runtime/tests/schemas/test_schema_integrity.py` cambiano soltanto la docstring del modulo e il messaggio
   dell'asserzione della riga 46, che dichiarano gli schemi di `ocor-runtime/schemas` artefatti della slice legacy
   non normativi (citando LLD v1.1 righe 20-31); funzioni, condizioni delle asserzioni, input e controlli restano
   identici, verificati con il confronto dell'albero sintattico. L'integrità normativa la prova il test nuovo sui sei
   contratti manifestati. Riqualifica di sola regressione dei task i cui ultimi record hanno il file fra gli input.
C2. **Nessuna modifica del test esistente.** Il test resta com'è; la voce si risolve con il solo test nuovo e il
   record dell'unità annota che il test esistente riguarda la slice legacy, da ritirare con
   `NORMATIVE-CONFORMANCE-LEGACY-RETIREMENT`.

### Opzioni del quesito D

D1. **Copertura dei failure code con test nuovi (raccomandata).** L'unità inventaria i reason code chiusi che ADD
   v1.3, LLD v1.1 e i contratti di LLD v1.1 §0.2 definiscono per i componenti C1-C8 e la memoria governata, con file e
   riga, e per ciascuno verifica che almeno un test negativo della suite asserisca `reason_code` uguale a quel codice
   (controllo statico nel modulo dell'unità); per ogni codice senza un tale test aggiunge, nel modulo dell'unità, un
   test negativo che lo provoca sul componente mantenuto e lo asserisce, con RED dove il codice non è prodotto. I
   test esistenti non cambiano. La prova di risoluzione della voce è la copertura completa dei codici inventariati,
   non il conteggio della sonda, che il record riporta come diagnostico.
D2. **Asserzione aggiunta ai test esistenti.** In ognuno dei 293 punti si aggiunge, dopo il `pytest.raises`,
   l'asserzione del reason code prescritto, con la citazione della norma; è un'estensione del caso 1 del punto 5 del
   piano, senza RED dove il codice è già prodotto; riqualifiche con supersession dei task interessati.
D3. **Rinvio.** La voce, di gravità `LOW` e senza `blocks`, diventa `DEFERRED_BY_PO` fino al ritiro della slice
   legacy; NCP-U12 non la risolve.

## Raccomandazione

Opzioni A1, B1, C1 e D1. A1 rispetta il confine dell'unità (solo test) e rende verificabile «no legacy classes»
come assenza di uso diretto delle capability legacy, lasciando la sostituzione dei tipi al ritiro della slice già
approvato in linea di principio; B1 è la lettura che il piano dà dell'adattamento del thread e asserisce i valori
che la norma prescrive ai componenti che il thread deve attraversare; C1 elimina la sola affermazione non conforme
senza toccare i controlli; D1 lega la voce all'obbligo normativo (copertura dei failure code) senza riscrivere 44
moduli sigillati.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: il GREEN di `NCR-TESTS-001` (adattamento del mission thread), il RED e il
  GREEN di `NCR-TESTS-004`, la parte di `NCR-TESTS-003` sul test esistente; quindi gate, revisione preventiva, campagna
  qualificante e verifica dell'unità.
- Non bloccati: i GREEN di `NCR-TESTS-002` (meta-test dei contratti) e `NCR-TESTS-005` (instradamento delle
  tecniche), il test nuovo di `NCR-TESTS-003` e l'inventario dei componenti del thread.
- Riqualifiche: `OCOR-DEV-0005`, `0050` e `0082` di sola regressione; `OCOR-DEV-0031` secondo il quesito B; con C1
  quelle di sola regressione dei task che hanno `test_schema_integrity.py` fra gli input; con A2 o D2 quelle dei
  task toccati.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, registri normativi, limiti e claim invariati
  (`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`).
