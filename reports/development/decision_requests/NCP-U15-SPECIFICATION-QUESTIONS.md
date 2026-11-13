# NCP-U15-SPECIFICATION-QUESTIONS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `NCP-U15` (ammissione dei claim e
risoluzione delle identità) e la sua specifica `docs/OCOR_LLD_v1.1_ADDENDUM_A.md`, proposta preparata fuori dal loop
di sviluppo su incarico del Product Owner. Aperta secondo il punto 3 della decisione
`FABLE52-EXTENSION-ASSESSMENT (2026-11-12)` («Tutti i quesiti stanno in una sola decision request di livello normativo,
con opzioni e raccomandazione, aperta prima del codice che ne dipende»). Autore: Claude Fable 5.2 (Anthropic).
Commit di `main` letto: `2278be4180de5d91d1fec9d7608027b0f287b545`.

## Contesto

Sigle: `ADD:n` è la riga `n` di `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md`; `LLD:n` è
la riga `n` di `docs/OCOR_LLD_v1.1.md`; `REG:n` è la riga `n` di
`ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md`; `SRC:percorso:n` è la
riga `n` di un file sotto `ocor-runtime/src/ocor_runtime/`. «Decisione» indica `FABLE52-EXTENSION-ASSESSMENT`.

- La decisione chiede che ogni record, campo, regola ed esito della specifica citi un elemento di ADD v1.3, LLD v1.1
  o Register, oppure il suo punto 4, e che ciò che la norma e la decisione non determinano diventi un quesito. Scrivendo
  la specifica sono rimaste dodici scelte senza ancora. Nell'addendum ciascuna è marcata con la sua sigla, da `Q-A` a
  `Q-L`, e riporta la sola opzione raccomandata, come proposta; le parti ancorate non dipendono da questi quesiti.
- **Quesito A, rifiuti di C3 che la norma non mappa.** ADD:342 fissa la regola (C3 accetta `AdmitClaim` e
  `CommitAggregate` solo con `Decision` e `Authority ref` validi, non scaduti e coerenti con il `GatePackage`) senza
  indicare un reason code. ADD:2569 mappa in modo deterministico solo precondizione, invariante, revisione e
  `GatePackage`, e aggiunge che su quel percorso non è ammesso un reason code generico. Le uscite di
  `CANONICAL_COMMIT_PENDING` sono due: `ACT-T31a` con `PRECONDITION_FAILED` o `INVARIANT_VIOLATION` (ADD:2902) e
  `ACT-T31b` con `REVISION_CONFLICT`, `GATE_PACKAGE_MISMATCH` o `GOVERNED_CONTEXT_MISMATCH` (ADD:2903). L'insieme
  chiuso dei codici è in ADD:2329-2352; LLD:67 aggiunge `MARKING_UNRESOLVED` per un marking non risolvibile. Restano
  aperti cinque punti. (1) Il codice, e la transizione di C6, per una Decision o un'Authority non valide, un'Evidence
  non risolvibile, un record non chiuso, un branch diverso da `main`, un binding o un delta fuori profilo, un marking
  meno restrittivo del join (ADD:2054) e per `IDEMPOTENCY_CONFLICT`, che LLD:97 nomina senza dire quale transizione
  percorre C6. (2) LLD:97 elenca la revisione fra i controlli che precedono la transazione, mentre LLD:132 la
  confronta dentro la transazione. (3) L'ordine fra revisione, precondizioni e invarianti nella transazione: REG:186
  fissa solo che l'idempotenza viene prima. (4) Il fence: ADD:3430 chiede a C3 di validare `writer_epoch`, Policy e
  Authority; ADD:3443 chiede HEAD canonico compatibile, versione dell'aggregate, release attiva, writer epoch e chiave
  di idempotenza correnti; il record di ADD:3448-3458 porta anche un commit di base, uno stop epoch e una scadenza;
  LLD:97 non colloca questi controlli e il comando non porta né commit di base né scadenza (LLD:88-94). L'insieme
  chiuso ha `RELEASE_MISMATCH` (ADD:2339) ed `EMERGENCY_STOP_ACTIVE` (ADD:2340), ma nessun codice per un writer epoch
  superato (ADD:271). (5) L'istante rispetto al quale si giudica una scadenza, e l'esito per un identificativo di
  precondizione o di invariante che C3 non conosce. Sul commit letto C3 usa già, per ogni commit canonico,
  `POLICY_DENIED` per la Decision (SRC:c3/admission.py:323), `AUTHORITY_MISSING` per l'Authority
  (SRC:c3/admission.py:336), `CONTRACT_REJECTED` per l'Evidence (SRC:c3/admission.py:356), `EMERGENCY_STOP_ACTIVE` per
  lo stop (SRC:c3/admission.py:361) e `RELEASE_MISMATCH` per la release (SRC:c3/admission.py:367), prima della
  transazione e rispetto a un solo istante; tratta un identificativo ignoto come precondizione o invariante non
  soddisfatto (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0050.py`, righe 710-737). Il record di comando integrato
  restituisce invece `COMMIT_CONTRACT_INVALID` per un record non chiuso (SRC:c3/ports.py:29),
  `SINGLE_WRITER_VIOLATION` per un branch diverso da `main` (SRC:c3/ports.py:189) e `REVISION_CONFLICT` per una
  revisione negativa (SRC:c3/ports.py:158); i test integrati lo asseriscono
  (`ocor-runtime/tests/tasks/test_ocor_dev_0013.py`, righe 136 e 152), e asseriscono `SINGLE_WRITER_VIOLATION` anche
  per un writer superato (`ocor-runtime/tests/tasks/test_ocor_dev_rem_0050.py`, riga 791). I primi due codici non
  compaiono in alcun contratto del dossier.
- **Quesito B, registrazione di `NO_MATCH` e `DEFERRED`.** Il punto 4 della decisione fissa i quattro esiti, chiede
  che `NCP-U15` realizzi esiti e record, e aggiunge che le shape di ADD §3.6 non cambiano in `NCP-U15`: se un esito
  richiede di estenderle, è un quesito. Il record è bitemporale e il system time lo assegna solo il writer dello stato
  canonico (ADD:2052, ADD:426). Ogni scrittura di C3 passa da un tipo d'azione, e il contratto elenca le classi che un
  commit canonico può produrre (`CanonicalAssertion`, `ClusterMembershipAssertion`, `MergeDecision`, `SplitDecision`,
  `RetractionAssertion`: ADD:2144-2148) senza prevederne una per una decisione priva di membership; anche la verifica
  di forma che ADD:2059 chiede riguarda le sole decisioni di merge e di split. Nessuna strada rispetta insieme questi
  vincoli e la frase «NCP-U15 realizza gli esiti e il record».
- **Quesito C, aggregate e limiti di merge e split.** L'unico comando mutativo di C3 riguarda un solo aggregate
  (LLD:85, LLD:97). ADD:2013 dà a `MergeDecision` una sola Canonical Entity e membership da creare e da chiudere;
  ADD:2014 dà a `SplitDecision` membership da chiudere e da creare; ADD:2051 chiede che uno split riferisca la
  decisione invertita e le membership impattate. Il contratto dà a ogni tipo d'azione una sola classe prodotta
  (ADD:2142) ed elenca `ClusterMembershipAssertion` come classe a sé (ADD:2145). La norma non dice: quale aggregate
  ospita decisioni e membership; come nasce una Canonical Entity, che compare solo come campo; se una Source Identity
  possa avere due membership in vigore; in quali casi un merge chiude membership e uno split ne crea; se uno split
  possa chiudere solo una parte delle membership del merge che inverte; se il tipo d'azione di un merge scriva anche
  le membership.
- **Quesito D, `reversibility`.** ADD:2013 elenca fra i campi di `MergeDecision` i «reversibility metadata» senza
  darne la struttura. Il criterio (a) della decisione chiede un insieme chiuso di campi per ogni record.
- **Quesito E, ritiro o ricalcolo delle derivazioni.** ADD:2051 parla di derivazioni «da ritirare/ricalcolare»,
  ADD:2057 di asserzioni derivate e proiezioni «da ritirare o ricostruire», REG:336 chiede di ritirare o ricalcolare il
  cento per cento delle derivazioni impattate. Nessuna riga dice quando vale l'una o l'altra cosa, in quale forma si
  registra un ritiro, chi ritira le derivazioni che non stanno in una proiezione, né come una lettura mostri un link
  ritirato: il contratto del gateway dà uno stato di verità all'oggetto (ADD:1152), non al singolo link (ADD:1214). Il
  contratto dei tipi d'azione nomina una classe `RetractionAssertion` (ADD:2148) che il metamodello di ADD §3.6 non
  definisce.
- **Quesito F, matcher deterministico.** Il punto 3 della decisione chiede un matcher deterministico, con versione
  fissata, per le sole fixture sintetiche. ADD:2010 chiede pin, score e semantica dello score; il contratto del
  gateway elenca i valori di `score_semantics` (ADD:1178) e di `Uncertainty.semantics` (ADD:1164); il pin del registro
  è `VersionPin` (ADD:1412-1417). Il record d'ingresso di una Source Identity, l'algoritmo, la regola dei riferimenti,
  il significato dei due digest del pin, il contenuto su cui si calcola il digest di una `MatchEvidence` e il valore
  dell'incertezza non sono in alcuna fonte.
- **Quesito G, output tipizzati.** ADD:3059 nomina `FusionIdentityFinding@1`, `CandidateMatchSet@1` e
  `ResolutionProposal@1` «con uncertainty e provenance» e non ne elenca i campi. Di `CandidateMatchSet@1` è ancorato
  solo il contenuto, cioè `CandidateMatch` e `MatchEvidence` (ADD:2010, ADD:2011).
- **Quesito H, conservazione e lettura di Claim e candidati.** ADD:148 colloca Claim ed Evidence in record di
  evidenza e provenance e non nomina il componente che li possiede. ADD:342 dice che C5 recapita a C3 solo input
  semantico non canonico. ADD:2053 chiede che i `CandidateMatch` non adjudicati restino interrogabili. Il gateway ha
  un `EvidenceReadPort` (LLD:113) e il campo `identity_candidates` (ADD:1225), i cui elementi portano un `ResourceRef`
  (ADD:1175). ADD:2048 collega la Canonical Assertion alla Claim sorgente senza dire se proposizione e world debbano
  coincidere. Nessuna riga dice dove stanno le Claim non ancora ammesse, i `CandidateMatch` e le `MatchEvidence`, da
  quale registro C3 risolve una Claim e che cosa confronta, né da dove il gateway legge i candidati. Sul commit letto
  C3 registra i binding Claim/source senza risolvere la Claim, e il gateway restituisce `identity_candidates` sempre
  vuoto (SRC:c2/gateway.py:591).
- **Quesito I, invio senza risposta e retry.** Da `CANONICAL_COMMIT_PENDING` escono solo `ACT-T30`, `ACT-T31a` e
  `ACT-T31b` (ADD:2901, ADD:2902, ADD:2903); l'unico retry della FSM, `ACT-T19`, parte da `COMMAND_READY` (ADD:2882).
  ADD:297 prevede, per un crash prima del commit locale, il retry della richiesta con la stessa chiave; LLD:354
  ammette il retry solo prima dell'effetto o con idempotenza comprovata. Ogni invio passa da `EMISSION-FENCE`
  (ADD:2854), e `G-FRESHNESS` confronta `expected_revision` con il valore corrente (ADD:2851): dopo un commit riuscito
  la cui receipt si è persa, un reinvio sarebbe invalidato prima di partire, e l'azione risulterebbe invalidata benché
  il commit esista. C3 espone `GetCommit` (ADD:284) e C6 ha un modulo di riconciliazione (ADD:287). La norma non
  compone queste regole.
- **Quesito J, valori del contratto lasciati aperti.** ADD:2565 fissa per ogni mutazione canonica il minimo
  `R2_CONTROLLED` e l'approvazione umana, e LLD:317 chiede per una mutazione canonica Decision, Authority, percorso di
  C6 ed `EMISSION-FENCE`. ADD:2365 ammette `R2_CONTROLLED` e `R3_HIGH_IMPACT`; ADD:3304 descrive la prima come
  mutazione interna reversibile e confinata, con un approvatore; ADD:3305 descrive la seconda come decisione
  interagenzia, fra compartimenti, irreversibile o critica, con due approvatori. Il contratto dà solo l'elenco dei
  valori ammessi per `approval.timeout_action` (ADD:2283), `compensation.mode` (ADD:2258),
  `compensation.irreversibility_class` (ADD:2381), `idempotency.scope` (ADD:2249) e lascia libero
  `requires_accepted_from_claim` per merge e split (ADD:2151). La norma non classifica ammissione, merge e split.
- **Quesito K, campi derivati dalla `Decision`.** ADD:2012 dà a una decisione di identità adjudicator, razionale e
  Policy Decision; ADD:2005 dà a una Canonical Assertion la decisione e l'Authority che l'hanno accettata. Sono valori
  che chi propone non può fornire: nascono con la `Decision` (ADD:2871) e con lo snapshot di policy (ADD:2863). Il
  `GatePackage` è congelato per l'approvazione (ADD:3334) e il digest del comando deve coincidere con esso
  (ADD:2852): se quei valori stessero nel delta, il delta dipenderebbe dalla `Decision` e la `Decision` dal
  `GatePackage` che copre il delta. La norma non dice chi li scrive nel record, quali campi espongono i record di C6
  da cui si leggono (ADD:2868, ADD:2869 e ADD:2870 nominano i record senza elencarne i campi), né su quale documento
  si risolvono i percorsi che ADD:2559 lega allo schema dei parametri per valori che chi propone non fornisce. Sul
  commit letto il record `Decision` usato da C3 non porta né razionale né Principal firmatario
  (SRC:c3/admission.py:79).
- **Quesito L, stato di adjudication servito.** ADD:1180 elenca i valori `UNADJUDICATED`, `ACCEPTED`, `REJECTED` e
  `SPLIT`; ADD:1171 dice che un candidato non adjudicato non implica appartenenza al cluster; REG:335 vieta l'ingresso
  nel cluster senza decisione accettata; ADD:2010 dà a `CandidateMatch` un campo di stato; il punto 4 della decisione
  parla di «un candidato sullo stesso insieme». Nessuna riga dice come lo stato derivi dalle decisioni, né se il campo
  del record si aggiorni.
- Nessuna opzione raccomandata chiede di cambiare, dentro `NCP-U15`, ADD v1.3, LLD v1.1, le shape di §3.6, un
  contratto, uno schema, il backlog, il piano di tracciabilità o un test esistente. Dove un'opzione richiede un
  cambiamento governato successivo, o lascia una divergenza del codice esistente, è scritto.

## Opzioni

Quesito A: reason code e transizione dei rifiuti di C3 non mappati, lettura di LLD:97 sulla revisione, ordine nella
transazione, fence. Quesito B: come si registra una decisione `NO_MATCH` o `DEFERRED`. Quesito C: aggregate di una
decisione di identità e limiti di merge e split. Quesito D: struttura di `reversibility`. Quesito E: quando una
derivazione si ritira e quando si ricalcola, in quale forma e a cura di chi. Quesito F: matcher deterministico.
Quesito G: campi dei tre output del ruolo Fusion/Identity. Quesito H: dove stanno Claim e candidati e come si leggono.
Quesito I: invio senza risposta e retry. Quesito J: valori del contratto dei tre tipi d'azione. Quesito K: chi scrive
i campi derivati dalla `Decision`. Quesito L: stato di adjudication servito.

### Opzioni del quesito A

A1. **Codici dell'insieme chiuso, come C3 li usa già; ordine e fence come oggi (raccomandata).** C3 rifiuta con
   `POLICY_DENIED` una Decision non risolvibile, non firmata, non `ACCEPT` o scaduta; con `AUTHORITY_MISSING`
   un'Authority non risolvibile, non valida o scaduta; con `CONTRACT_REJECTED` un'Evidence o una Claim non
   risolvibile, un binding o un delta fuori profilo e un marking meno restrittivo del join; con
   `EMERGENCY_STOP_ACTIVE` uno stop attivo o uno stop epoch cambiato; con `RELEASE_MISMATCH` una release non attiva;
   con `GATE_PACKAGE_MISMATCH` ogni incoerenza con il `GatePackage`. Un identificativo di precondizione o di invariante
   ignoto vale come non soddisfatto. Revisione: prima della transazione si verifica solo che sia un intero non
   negativo, e una revisione malformata produce `REVISION_CONFLICT`; nella transazione l'ordine è idempotenza,
   revisione, precondizioni, invarianti. Fence: si valuta dopo le
   Evidence e prima della transazione, per stop e release; versione dell'aggregate e chiave di idempotenza sono già
   passi della transazione; C3 non valuta altro del fence, perché il comando non porta commit di base né scadenza. Le
   scadenze si giudicano rispetto a un solo istante, letto all'inizio delle validazioni. In C6 ogni rifiuto non
   mappato chiude l'azione con `ACT-T31b`, e la transizione registra il codice che C3 ha restituito, senza tradurlo;
   un identificativo ignoto chiude con `ACT-T31a`. Un rifiuto di un writer superato non è un esito dell'azione: C6 lo
   tratta come invio senza risposta (quesito I). Per un record non chiuso e per un branch diverso da `main` il codice
   dell'insieme chiuso è `CONTRACT_REJECTED`; il record di comando già integrato restituisce
   `COMMIT_CONTRACT_INVALID` e `SINGLE_WRITER_VIOLATION`, che non stanno in alcun contratto: è una divergenza del
   codice esistente, che `NCP-U15` non corregge e che va registrata e pianificata a parte. Effetto: un solo
   comportamento per i due port che ADD:342 regola insieme; nessun test integrato cambia in `NCP-U15`; ogni rifiuto ha
   un solo codice; uno stop accettato dopo il controllo di C3 non ferma il commit, perché la norma dà precedenza allo
   stop solo prima dell'emissione (ADD:2905). Criterio verificabile: nei casi del criterio (e) il test asserisce il
   codice che C3 restituisce, indicato qui, la transizione `ACT-T31b` con lo stesso codice e l'assenza di ogni
   scrittura.
A2. **Solo i codici del percorso canonico.** Ogni rifiuto di C3 che non sia precondizione, invariante o revisione
   restituisce `GATE_PACKAGE_MISMATCH`, e C6 chiude con `ACT-T31b`. È la lettura più letterale di ADD:2569 e
   ADD:2903. Effetto: il comportamento di C3 già integrato va riallineato con una voce nuova del registro di
   conformità e con la modifica di test già integrati, fuori dall'ambito di `NCP-U15`; il motivo del rifiuto si perde
   nel codice. Criterio verificabile: nei casi del criterio (e) il test asserisce `GATE_PACKAGE_MISMATCH`.
A3. **Come A1, con le violazioni di struttura del delta trattate come invarianti.** Un delta fuori profilo e un
   marking meno restrittivo del join producono `INVARIANT_VIOLATION` e C6 chiude con `ACT-T31a`. Effetto: l'azione
   termina in `EXECUTION_FAILED` invece che in `INVALIDATED`; un comando malformato e uno stato che viola un
   invariante non si distinguono più dal codice, e il caso negativo del criterio (d) non distingue più il controllo
   della decisione accettata dal controllo di forma. Criterio verificabile: come A1, con `INVARIANT_VIOLATION` nel
   caso del delta fuori profilo.
A4. **Come A1, con il fence dentro la transazione e la policy fra i controlli.** Stop, stop epoch e release si
   valutano nella transazione, dopo l'idempotenza, e C3 verifica anche che il bundle di policy del Governed Context
   sia quello corrente, con `POLICY_DENIED`. Effetto: la finestra fra il controllo e la scrittura si riduce, ma non
   scompare, perché lo stop vive in un altro componente; si aggiunge a C3 un controllo che oggi fa solo C6 prima
   dell'emissione (ADD:2851). Criterio verificabile: come A1, più uno stop accettato durante la transazione che
   produce `EMERGENCY_STOP_ACTIVE` e nessuna scrittura.

### Opzioni del quesito B

B1. **Record ed esiti in `NCP-U15`; scrittura canonica di `NO_MATCH` e `DEFERRED` dopo un'estensione governata
   (raccomandata).** `NCP-U15` definisce il record chiuso `IdentityResolutionDecision` con i quattro esiti, scrive
   `MERGE` e `SPLIT`, e registra ogni merge non accettato con la `Decision` di rifiuto della FSM. La scrittura del
   record `NO_MATCH` o `DEFERRED` è un commit canonico con un tipo d'azione dedicato: richiede un valore in più fra le
   classi producibili (ADD:2144-2148) e una shape per la decisione senza membership, cioè un change set approvato a
   parte. Cede: la frase del punto 4 «NCP-U15 realizza gli esiti e il record» vale per il record e per i due esiti che
   il contratto già permette di scrivere; il PO la conferma in questa forma o indica un'altra opzione. Non cede alcuna
   riga di ADD v1.3 o di LLD v1.1. Effetto: fino al change set un candidato rifiutato resta `UNADJUDICATED` nelle
   letture e il rifiuto si legge nella traccia dell'azione. Criterio verificabile: il test del criterio (a) asserisce
   i campi del record base; il test del criterio (f) trova, per un merge non accettato, la `Decision` di rifiuto con
   chi ha deciso, razionale e digest delle evidenze; nessun record `NO_MATCH` è scritto in `NCP-U15`.
B2. **Record scritto da C6 con la decisione di rifiuto, senza commit canonico.** Se l'Authority non accetta un merge,
   la `Decision` di `ACT-T10a` porta anche l'esito `NO_MATCH` o `DEFERRED`, e C6 scrive il record
   `IdentityResolutionDecision` nel proprio registro, nella transazione della transizione. Cede: il system time del
   record non lo assegna il writer canonico (ADD:2052, ADD:426), e `ACT-T10a` produce un record in più rispetto a
   «Decision + rationale» (ADD:2870). Sono due scostamenti da ADD v1.3. Effetto: i quattro esiti sono realizzati in
   `NCP-U15` senza toccare contratti né shape, ma il record non è stato canonico e la sua ricostruzione dipende dal
   registro di C6. Criterio verificabile: dopo una decisione `NO_MATCH` il record esiste con insieme delle Source
   Identity e digest delle evidenze; il candidato è servito come `REJECTED`; nessuna revisione di aggregate è
   cambiata.
B3. **Estensione del contratto dentro `NCP-U15`.** Come B1, ma il valore in più e la shape entrano nella stessa unità.
   Cede: la decisione, che tiene invariati contratti e shape in `NCP-U15`; serve una decisione nuova del PO che lo
   autorizzi. Effetto: i quattro esiti sono scritti come stato canonico già in `NCP-U15`. Criterio verificabile: il
   contratto esteso supera i propri test; una decisione `NO_MATCH` produce un commit canonico con il record, e il
   candidato è servito come `REJECTED`.
B4. **Solo la traccia della FSM, senza record.** Nessun `IdentityResolutionDecision` per `NO_MATCH` e `DEFERRED`, né
   ora né dopo. Cede: il punto 4 della decisione; la regola di non riapertura prevista dopo la decisione su G7 non
   avrebbe un record su cui poggiare. Elencata per escluderla.

### Opzioni del quesito C

C1. **Aggregate uguale alla Canonical Entity; membership esclusive; merge che crea e split che chiude; inversione
   completa (raccomandata).** L'aggregate di un merge è la Canonical Entity che la decisione nomina; quello di uno
   split è la Canonical Entity del merge che inverte. La Canonical Entity non ha un record proprio: il suo aggregate
   nasce con il primo merge che la nomina, da revisione 0. Il tipo d'azione di classe `MergeDecision` o
   `SplitDecision` scrive nello stesso commit anche le membership del proprio delta; nessun tipo produce da sola una
   `ClusterMembershipAssertion`. In `NCP-U15` un merge non chiude membership e uno split non ne crea: per spostare una
   Source Identity, o per lasciarne unite alcune dopo uno split, servono uno split e poi un merge. Uno split chiude
   tutte le membership in vigore create dal merge che inverte, e solo quelle. Una Source Identity ha al più una
   membership in vigore nell'ownership boundary: lo garantisce una constraint unica nella stessa transazione locale
   del commit, che vale fra aggregate diversi, e il merge che la violerebbe è rifiutato con `PRECONDITION_FAILED`.
   Effetto: ogni decisione è un solo commit su un aggregate piccolo; nessuna membership nasce sotto la forma di uno
   split; ogni membership si può chiudere invertendo il merge che l'ha creata. Criterio verificabile: due merge
   concorrenti che assegnano la stessa Source Identity a due entità diverse producono un commit e un
   `PRECONDITION_FAILED`; uno split che chiude solo una delle due membership di un merge è rifiutato con
   `PRECONDITION_FAILED`; un merge con membership da chiudere e uno split con membership da creare sono rifiutati
   prima della transazione.
C2. **Un aggregate per tipo di entità e ownership boundary.** Tutte le decisioni e le membership di un tipo stanno in
   un solo aggregate; un merge può chiudere la membership di un'altra entità dello stesso tipo e uno split può
   crearne, purché riguardino le Source Identity del merge invertito. Effetto: atomicità ed esclusività sono
   immediate, ma tutte le decisioni di quel tipo si serializzano e lo stato dell'aggregate cresce con il numero delle
   membership; adatto alle fixture, sconsigliato per i requisiti di scala successivi al PoC. Criterio verificabile:
   come C1, con `REVISION_CONFLICT` nel caso concorrente e uno spostamento di Source Identity in un solo commit.
C3. **Come C1, con lo split parziale.** Uno split può chiudere un sottoinsieme delle membership del merge che
   inverte; il merge resta in vigore per le altre. Effetto: una correzione parziale richiede una sola azione, ma «in
   vigore» diventa una proprietà delle singole membership e non della decisione, e un merge può essere invertito più
   volte. Criterio verificabile: uno split che chiude una delle due membership di un merge è scritto; la seconda
   resta in vigore e un secondo split la chiude.
C4. **Aggregate uguale alla Source Identity.** Ogni Source Identity porta la storia delle proprie membership. Effetto:
   un merge di due Source Identity richiede due commit, quindi non è atomico; contrasta con LLD:97 e con la regola che
   lega decisione e membership. Elencata per escluderla.

### Opzioni del quesito D

D1. **Oggetto minimo ricavato dal tipo d'azione (raccomandata).** `reversibility` è l'oggetto chiuso
   `{irreversibility_class, reversing_action_type_id}`: la classe dichiarata dal tipo d'azione (ADD:2381) e
   l'identificativo del tipo d'azione di split. Se la decisione sia stata invertita non si scrive nel record: si
   ricava dagli `SplitDecision` che la nominano. Effetto: nessun dato duplicato; lo stato precedente si ricostruisce
   dalla storia dei commit. Criterio verificabile: il test del criterio (a) asserisce i due campi; il test del criterio
   (c) ricostruisce lo stato precedente senza leggere `reversibility`.
D2. **Oggetto con copia dello stato precedente.** Come D1, più l'elenco delle membership in vigore, prima del merge,
   per le Source Identity interessate. Effetto: lo split non dipende dalla lettura della storia, ma il record duplica
   dati che la storia già conserva e che possono divergere. Criterio verificabile: come D1, più l'uguaglianza fra la
   copia e lo stato al commit precedente.

### Opzioni del quesito E

E1. **Ricalcolo per ciò che ha una definizione deterministica, ritiro per il resto, segno di ritiro nella
   proiezione (raccomandata).** Si ricalcolano i fatti delle proiezioni, che si ricostruiscono dallo stato canonico
   (ADD:272), e le derivazioni prodotte da una `DerivedDefinition` attiva nella release (ADD:427), valutata sullo
   stato successivo allo split. Si ritirano, senza ricalcolo automatico, le derivazioni prodotte da un ruolo d'agente
   o da un modello. Il ritiro si registra nella proiezione della provenance, con un segno che cita la derivazione, le
   membership chiuse, lo split e il suo commit, scritto insieme al watermark; in `NCP-U15` non si scrivono
   `RetractionAssertion` canoniche. Un link o un valore derivato ritirato non compare più nelle letture servite dopo
   la chiusura; il segno di ritiro si legge nel lineage, secondo policy. Ambito in `NCP-U15`: le derivazioni che una
   proiezione materializza; per quelle conservate da un altro componente vale la stessa regola, a cura di chi le
   conserva, dal momento in cui quel componente usa la vista unita. Effetto: lo split non avvia modelli né agenti; il
   ricalcolo è ripetibile; una proiezione ricostruita arriva agli stessi ritiri. Criterio verificabile: dopo lo split,
   nella fixture, i due link e l'inferenza dipendenti non sono più in vigore, ciascuno ha un segno di ritiro che cita
   lo split, e una proiezione ricostruita da zero dà lo stesso risultato.
E2. **Solo ritiro.** Ogni derivazione impattata è ritirata; il ricalcolo è sempre un'azione nuova ed esplicita.
   Effetto: più semplice, ma le proiezioni restano prive dei fatti che la norma dice ricostruibili finché qualcuno non
   avvia la ricostruzione. Criterio verificabile: dopo lo split tutte le derivazioni impattate hanno un segno di
   ritiro e nessuna è ricalcolata.
E3. **Ritiro come commit canonico.** Ogni derivazione ritirata produce una `RetractionAssertion` scritta da C3 con un
   tipo d'azione dedicato (ADD:2148). Effetto: il ritiro entra nello stato canonico e nel suo audit, ma ogni split
   genera tante azioni governate quante sono le derivazioni, e il record va prima definito, perché ADD §3.6 non lo
   descrive: serve un'altra decisione. Criterio verificabile: dopo lo split esiste una `RetractionAssertion` per ogni
   derivazione impattata.
E4. **Ricalcolo di tutto, nel commit dello split.** Ogni derivazione impattata è ricalcolata in modo sincrono prima
   che lo split sia confermato. Effetto: lega il commit canonico alla disponibilità di proiezioni, modelli e agenti;
   contrasta con la propagazione asincrona di ADD:293. Elencata per escluderla.

### Opzioni del quesito F

F1. **Accordo sulle caratteristiche (raccomandata).** Matcher `urn:ocor:matcher:feature-agreement`, versione `1.0.0`.
   Ingresso: per ogni Source Identity il record chiuso `{source_identity_ref, entity_type_id, features}`, dove
   `features` associa a ogni caratteristica un valore JSON scalare. Configurazione: il record chiuso `{matcher_id,
   version, entity_type_id, feature_refs}`. Pin: `resource_id` e `semantic_version` sono identificativo e versione
   del matcher; `artifact_digest` è il digest della configurazione; `contract_digest` è il digest del record chiuso
   che elenca i campi dell'ingresso e il nome dell'output. Per ogni coppia di Source Identity del tipo configurato e
   per ogni caratteristica l'esito è `SUPPORTS` se i due valori sono presenti e uguali come valori JSON, `REFUTES` se
   presenti e diversi, `NEUTRAL` se ne manca uno; nessuna normalizzazione. Si emette un `CandidateMatch` se almeno un
   esito è `SUPPORTS`, e solo per le coppie emesse un `MatchEvidence` per caratteristica. Lo score è il numero di
   `SUPPORTS` diviso per la somma di `SUPPORTS` e `REFUTES`, con `score_semantics` `MATCH_CONFIDENCE`: è una quota di
   accordo, non una probabilità. Il riferimento di un candidato deriva dallo SHA-256 di pin e coppia; il digest del
   contenuto di una `MatchEvidence` si calcola sul record chiuso `{candidate_match_ref, feature_ref, method_ref,
   stance, assessor_pin, score_semantics}`. `uncertainty.semantics` è `QUALITATIVE_SCALE`, con i livelli
   `CONTRADICTED` e `UNCONTRADICTED`. Effetto: nessuna dipendenza; gli omonimi con una caratteristica discordante
   restano candidati con score inferiore a uno; una riesecuzione dà gli stessi riferimenti. Criterio verificabile:
   sulla fixture di tre omonimi il matcher produce tre candidati con score `1.0`, `0.5` e `0.5` e sei evidenze; due
   esecuzioni danno gli stessi byte nei campi deterministici.
F2. **Uguaglianza su tutte le caratteristiche.** Stesso ingresso e stesso pin; si emette un candidato solo se tutte le
   caratteristiche presenti coincidono; lo score vale sempre `1.0`. Effetto: più semplice, ma gli omonimi discordanti
   non diventano candidati e la fixture del criterio (b) non esercita candidati in disaccordo. Criterio verificabile:
   sulla stessa fixture, un solo candidato.

### Opzioni del quesito G

G1. **Insiemi minimi (raccomandata).** `CandidateMatchSet@1`: `record_type`, `matcher_pin`,
   `input_source_identity_refs`, `candidate_matches`, `match_evidence`, `uncertainty`, `provenance_refs`.
   `FusionIdentityFinding@1`: `record_type`, `finding_ref`, `subject_source_identity_refs`, `candidate_match_refs`,
   `claim_refs`, `evidence_refs`, `uncertainty`, `provenance_refs`. `ResolutionProposal@1`: `record_type`,
   `resolution_proposal_ref`, `proposed_outcome` (`MERGE` oppure `SPLIT`), `source_identity_refs`,
   `candidate_match_refs`, `canonical_entity_ref`, `reverses_decision_ref`, `evidence_refs`, `uncertainty`,
   `provenance_refs`. `uncertainty` è l'oggetto `Uncertainty` del contratto del gateway (ADD:1158). Il ruolo non
   propone `DEFERRED`, che è una scelta dell'Authority, e non propone `NO_MATCH` finché il quesito B non ha un tipo
   d'azione che lo porti. Effetto: gli output portano solo ciò che serve a costruire una proposta d'azione e a
   propagare l'incertezza. Criterio verificabile: il test del criterio (a) asserisce i tre insiemi di campi e rifiuta
   un campo in più.
G2. **Solo `CandidateMatchSet@1` in `NCP-U15`.** Gli altri due output restano nomi ammessi dal ruolo, senza schema,
   finché un'unità successiva non li usa. Effetto: meno superficie ora, ma la decisione chiede che la specifica
   definisca gli output del ruolo, e una proposta di risoluzione senza schema non può alimentare un'azione. Criterio
   verificabile: il test del criterio (a) asserisce i campi di `CandidateMatchSet@1`; il ruolo rifiuta di emettere
   gli altri due output.

### Opzioni del quesito H

H1. **Registro di evidenza e provenance alimentato dal confine di ingestione (raccomandata).** Claim e insiemi di
   candidati entrano come envelope con `semantic_class` `CLAIM` (ADD:595); il payload è validato contro il proprio
   schema, che distingue una Claim da un insieme di candidati, e un fallimento va in quarantena (ADD:529); i record
   ammessi stanno in un registro di evidenza e provenance. C3 vi risolve Claim ed Evidence e verifica che
   proposizione e world della Canonical Assertion siano quelli della Claim; il gateway lo legge con
   `EvidenceReadPort` e mette in `identity_candidates`, per ogni candidato che comprende la Source Identity servita,
   un elemento per ciascuna delle altre, con lo stato del quesito L. In `NCP-U15` pubblica gli envelope il producer
   della fixture sintetica; la pubblicazione da parte di un ruolo d'agente in un run governato richiede uno strumento
   governato e resta fuori dall'unità. Da confermare con questa opzione: ADD:849 elenca ciò che un payload può creare
   e non nomina `CandidateMatch`; il PO conferma che un insieme di candidati viaggia come payload di classe `CLAIM` con
   un proprio schema, la stessa porta che il punto 6 della decisione prevede per un produttore a monte. Se la conferma
   richiedesse di toccare lo schema dell'envelope, vale H2 fino a quel change set. Effetto: una sola porta per le Claim
   e per i candidati, interni o a monte; nessun contratto cambia. Criterio verificabile: sulla fixture, la lettura di
   ciascuna delle tre Source Identity omonime restituisce le altre due in `identity_candidates`, con stato
   `UNADJUDICATED` prima del merge; un insieme con un `MatchEvidence` senza candidato va in quarantena; un'ammissione
   la cui proposizione differisce da quella della Claim è rifiutata.
H2. **Solo fixture in `NCP-U15`.** Claim e insiemi di candidati sono caricati dalle fixture nel registro da cui C3
   già risolve le Evidence; il gateway continua a restituire `identity_candidates` vuoto, e la lettura dei candidati
   passa a un'unità successiva. Effetto: i criteri da (b) a (f) si verificano sullo stato canonico e sulle proiezioni;
   la richiesta di ADD:2053, candidati interrogabili, non è realizzata in `NCP-U15`. Criterio verificabile: i casi dei
   criteri (b) e (d) asseriscono l'assenza di membership e di fatti uniti, senza letture dal gateway.
H3. **Candidati nello stato canonico.** Ogni `CandidateMatch` è scritto da C3. Effetto: un candidato non adjudicato
   diventerebbe un record canonico e servirebbe una classe producibile che il contratto non ha (ADD:2144-2148).
   Elencata per escluderla.

### Opzioni del quesito I

I1. **Riconciliazione con `GetCommit`; reinvio solo sotto `EMISSION-FENCE` (raccomandata).** Quando l'invio non riceve
   risposta, C6 chiede a C3 se esiste un commit per quell'aggregate e quella chiave. Se esiste con lo stesso digest
   di comando, conferma con `ACT-T30`. Se non esiste, C6 può reinviare lo stesso comando con la stessa chiave finché
   `EMISSION-FENCE` vale, entro il profilo di retry (ADD:2926). C6 chiude con `ACT-T31b` solo dopo un rifiuto di C3,
   oppure quando `GetCommit` non trova il commit e la `Decision` è scaduta: da quel momento C3 rifiuta il comando, e
   il commit non può più comparire. C3 mantiene l'ordine letterale di LLD:97. Cede: il reinvio non è una riga della
   tabella delle transizioni, perché non cambia stato; il codice che `ACT-T31b` registra alla scadenza va scelto, e la
   proposta è `GATE_PACKAGE_MISMATCH`, perché è superata la finestra di validità congelata nel `GatePackage`
   (LLD:320). Effetto: un commit avvenuto è sempre confermato e un'azione non è mai invalidata mentre il suo commit
   può ancora comparire. Criterio verificabile: receipt persa dopo il commit: l'azione termina in
   `EXECUTION_CONFIRMED` con la receipt originale e lo stato canonico ha un solo commit; invio perso prima di C3: il
   reinvio produce un solo commit; nessun commit e Decision scaduta: l'azione termina in `INVALIDATED` e C3 non ha
   commit.
I2. **Replay della receipt prima delle scadenze.** C6 reinvia sempre lo stesso comando; a un comando che ha la chiave
   e il digest di un commit già scritto C3 restituisce la receipt originale prima di valutare Decision e Authority.
   Cede: l'ordine di LLD:97, che mette Decision e Authority prima della transazione in cui vive l'idempotenza; e il
   reinvio deve superare `G-FRESHNESS`, che dopo il commit vede una revisione avanzata (ADD:2851). Effetto: C6 non
   interroga `GetCommit`, ma serve un'eccezione al fence per i reinvii. Criterio verificabile: receipt persa dopo il
   commit e Decision scaduta prima del reinvio: l'azione termina in `EXECUTION_CONFIRMED` con la receipt originale.

### Opzioni del quesito J

J1. **Minimo della norma per tutti e tre i tipi (raccomandata).** `risk_class` `R2_CONTROLLED`; `approval.mode`
   `HUMAN_GATE` con un approvatore indipendente e un ruolo di steward o adjudicator; `approval.timeout_action`
   `EXPIRE`; `compensation.irreversibility_class` `REVERSIBLE`; `compensation.mode` `NOT_APPLICABLE`, perché un
   commit canonico rifiutato non lascia effetti e l'inversione di un merge è una decisione nuova, non la compensazione
   di un'esecuzione fallita; `idempotency.scope` `RESOURCE`; `requires_accepted_from_claim` `false` per merge e
   split. Le azioni fra compartimenti non sono definite in `NCP-U15`. Per l'ammissione la classe `REVERSIBLE` è
   dichiarata perché una mutazione canonica non può essere irreversibile (ADD:2564), ma il percorso che ritira
   un'asserzione ammessa non è definito in `NCP-U15`. Effetto: le fixture hanno un proponente, un approvatore e un
   adjudicator distinti. Criterio verificabile: un tipo d'azione dei tre con classe inferiore o senza approvatore è
   rifiutato dal compilatore; l'azione approvata dallo stesso Principal che la propone è negata.
J2. **`R3_HIGH_IMPACT` e doppio controllo per merge e split.** Una fusione di identità è trattata come decisione
   critica (ADD:3305): `DUAL_CONTROL`, due approvatori indipendenti, separazione completa dei compiti; l'ammissione
   resta come in J1. Effetto: l'insieme delle approvazioni scade dieci minuti dopo la seconda firma (ADD:3334); le
   fixture e i tempi dei test crescono; il rigore è quello che un impiego operativo potrebbe chiedere. Criterio
   verificabile: un merge con una sola approvazione non raggiunge la Decision.

### Opzioni del quesito K

K1. **Li scrive C3, dalla `Decision` che risolve (raccomandata).** Il delta del comando contiene solo i campi che chi
   propone fornisce, ed è ciò che il `GatePackage` congela. Nella transazione del commit C3 completa il record: la
   decisione e l'Authority accettanti sono `decision_ref` e `authority_ref` del comando; adjudicator e razionale sono
   il Principal che ha firmato la `Decision` e il suo razionale; il riferimento alla Policy Decision è quello che la
   `Decision` riporta. I record di C6 che registrano un esito espongono chi ha deciso, o che nessuna persona ha
   deciso, il razionale o il reason code, e i riferimenti alle evidenze congelate. I percorsi del binding che
   riguardano Decision, Authority, digest del `GatePackage` e chiave di idempotenza si risolvono sul documento
   dell'istanza d'azione che C6 compone, non sui soli parametri di chi propone. Effetto: nessuna dipendenza circolare
   fra delta, `GatePackage` e `Decision`; chi propone non può dichiarare un adjudicator; il record `Decision` deve
   esporre razionale e Principal firmatario, che sul commit letto non porta, e come farlo senza cambiare i test
   esistenti è lavoro dell'unità. Criterio verificabile: un delta che contiene `adjudicator_principal_id` è rifiutato
   prima della transazione; nel record scritto adjudicator e razionale sono quelli della `Decision`; il test del
   criterio (f) legge le tre informazioni da ogni record della tabella degli esiti.
K2. **Li scrive C6 nel delta, alla formazione del comando.** C6 aggiunge i valori quando forma il comando; il
   `GatePackage` copre solo la parte di chi propone, e C3 confronta i valori aggiunti con la `Decision`. Cede: il
   digest del comando non coincide più per intero con ciò che il `GatePackage` ha congelato (ADD:2852), e il
   `GatePackage` già integrato, che lega il digest dell'intero delta, va cambiato. Effetto: C3 non completa record, ma
   deve comunque leggere razionale e firmatario dalla `Decision` per il confronto. Criterio verificabile: un comando in
   cui l'adjudicator del delta differisce dal firmatario della `Decision` è rifiutato prima della transazione.

### Opzioni del quesito L

L1. **Stato calcolato da membership e decisioni; record immutabile (raccomandata).** Il campo `status` del record
   resta `UNADJUDICATED`. Lo stato servito a un commit è: `ACCEPTED` se tutte le Source Identity del candidato hanno
   una membership in vigore nella stessa Canonical Entity; altrimenti quello della decisione più recente che tocca il
   candidato, per system time e, a parità, per ordine dei commit del branch: `SPLIT` per uno split che ha chiuso
   membership di tutte le sue Source Identity nella stessa entità, `REJECTED` per un `NO_MATCH` e `UNADJUDICATED` per
   un `DEFERRED` sullo stesso insieme di Source Identity; `UNADJUDICATED` se nessuna decisione lo tocca. Effetto: un
   candidato è `ACCEPTED` esattamente quando le sue Source Identity sono unite, anche se sono entrate nel cluster con
   decisioni diverse; lo stato a un commit passato si ricalcola. Criterio verificabile: sulla fixture il candidato
   della coppia unita è `ACCEPTED` dopo il merge e `SPLIT` dopo lo split, e gli altri due restano `UNADJUDICATED`; se
   un secondo merge aggiunge la terza Source Identity alla stessa entità, tutti e tre i candidati sono `ACCEPTED`.
L2. **Stato per inclusione nella decisione.** Una decisione tocca ogni candidato le cui Source Identity stanno tutte
   nel suo insieme, e lo stato è quello della più recente: `ACCEPTED` per un merge, `SPLIT`, `REJECTED`,
   `UNADJUDICATED`. Effetto: più semplice, ma un `NO_MATCH` su tre Source Identity respinge anche le tre coppie, cosa
   che la decisione non afferma, e due Source Identity unite da decisioni diverse restano `UNADJUDICATED` pur essendo
   nello stesso cluster. Criterio verificabile: sulla fixture gli stessi stati di L1 nei primi due passi;
   `UNADJUDICATED` per le coppie unite da merge successivi.
L3. **Stato scritto nel record.** Chi conserva i candidati aggiorna il campo `status` a ogni decisione. Effetto: la
   lettura non calcola nulla, ma il record non è più immutabile, lo stato a un commit passato non si legge dal record,
   e l'aggiornamento è un secondo scrittore da tenere allineato allo stato canonico. Criterio verificabile: dopo ogni
   commit di decisione il campo del record riporta lo stato atteso da L1.

## Raccomandazione

Opzioni A1, B1, C1, D1, E1, F1, G1, H1, I1, J1, K1 e L1. A1 mantiene il comportamento che C3 ha già per ogni commit
canonico e dà a ogni rifiuto un solo codice dell'insieme chiuso; lascia aperta, e dichiarata, la divergenza del record
di comando su due codici che nessun contratto prevede. B1 è la sola opzione che non contrasta con ADD v1.3 né con la
decisione sulle shape; lascia fuori da `NCP-U15` la scrittura di due esiti su quattro, e per questo chiede al PO di
confermare la lettura del punto 4. C1 tiene ogni decisione in un commit su un aggregate piccolo, impedisce che una
membership nasca sotto la forma di uno split e rende ogni membership reversibile. D1 non duplica ciò che la storia dei
commit conserva. E1 separa ciò che si ricostruisce in modo deterministico da ciò che è un nuovo output di un ruolo, e
non introduce un record canonico che la norma non definisce. F1 e G1 sono i minimi che permettono alla fixture dei
criteri (b), (c) e (d) di esercitare candidati discordanti e una proposta di risoluzione. H1 realizza la lettura dei
candidati che ADD:2053 chiede, ma dipende da una conferma del PO su ADD:849: senza quella conferma la scelta prudente è
H2. I1 è la sola opzione compatibile con il fence che la norma impone a ogni invio. J1 è il minimo della norma; se il
PO prevede un impiego in cui una fusione errata è critica, J2 è la scelta coerente e conviene prenderla ora, perché
cambia le fixture. K1 elimina la dipendenza circolare fra delta, `GatePackage` e `Decision`. L1 fa coincidere lo stato
`ACCEPTED` con l'appartenenza effettiva al cluster.

## Impatto e lavoro bloccato

- Non bloccati: l'handler `AdmitClaim` con le validazioni mappate da ADD:2569; i record `CandidateMatch`,
  `MatchEvidence`, `IdentityResolutionDecision`, `MergeDecision`, `SplitDecision` e `ClusterMembershipAssertion` nei
  campi ancorati; i tre tipi d'azione nei valori che la norma fissa; l'invariante che vieta una membership senza la
  propria decisione nello stesso commit, con i casi negativi del criterio (d); la garanzia che nessuna derivazione
  materializzata da una proiezione resti in vigore dopo la chiusura di una membership; il validatore di tracciabilità.
- Bloccati in attesa della decisione: i codici asseriti dal test del criterio (e), l'ordine nella transazione e il
  fence (quesito A); la scrittura di `NO_MATCH` e `DEFERRED` (quesito B); l'aggregate, l'esclusività, i limiti di
  merge e split e l'inversione completa (quesito C); il campo `reversibility` (quesito D); la distinzione fra ritiro e
  ricalcolo e il segno di ritiro (quesito E); il matcher e le fixture che ne dipendono (quesito F); gli schemi dei tre
  output del ruolo (quesito G); la risoluzione della Claim in C3 e le letture dei candidati (quesito H); il
  comportamento su invio senza risposta (quesito I); i valori aperti del contratto (quesito J); chi scrive adjudicator,
  razionale e riferimenti di accettazione (quesito K); lo stato servito (quesito L).
- Effetto sull'addendum: con le opzioni raccomandate nessuna sezione cambia, salvo togliere la dicitura «proposta»;
  con un'opzione diversa cambiano le sezioni che l'addendum elenca accanto a ciascun quesito e l'atteso
  corrispondente del suo allegato.
- Nessun nuovo `DEC-*`; ADD v1.3, LLD v1.1, contratti, schemi, shape di §3.6, registri, backlog, piano di
  tracciabilità, limiti e claim invariati (`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production
  `NO-GO`).
