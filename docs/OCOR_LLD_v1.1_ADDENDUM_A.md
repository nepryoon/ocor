# Addendum A a LLD v1.1: ammissione dei claim e risoluzione delle identità

## 0. Controllo del documento

| Campo | Valore |
|---|---|
| Titolo | Addendum A a LLD v1.1: ammissione dei claim e risoluzione delle identità |
| Stato | Proposta preparata fuori dal loop di sviluppo, su incarico del Product Owner. Non è approvata e non è evidenza |
| Efficacia | Diventa il riferimento dell'unità `NCP-U15` solo con l'integrazione governata di quell'unità |
| Subordinazione | ADD v1.3 e LLD v1.1 non cambiano e prevalgono su questo documento |
| Fonte di autorità | Decisione normativa del PO `FABLE52-EXTENSION-ASSESSMENT (2026-11-12)`, punti 3 e 4 |
| Commit letto | `2278be4180de5d91d1fec9d7608027b0f287b545` di `main` |
| Autore | Claude Fable 5.2 (Anthropic) |
| Quesiti di norma aperti | Dodici, da `Q-A` a `Q-L`, nel file `reports/development/decision_requests/NCP-U15-SPECIFICATION-QUESTIONS.md` |
| Claim | Invariati. Questo documento non dichiara requisiti verificati, gate chiusi o decisioni approvate |

### 0.1 Precedenza e perimetro

Questo addendum è subordinato ad ADD v1.3 e a LLD v1.1. Se una sua frase contraddice uno dei due documenti, vale il documento approvato e la frase dell'addendum è un difetto da correggere (LLD:16, LLD:18). Non modifica contratti, schemi, shape di ADD §3.6, registri, backlog, piano di tracciabilità, test o claim.

Il perimetro è quello del punto 3 della decisione, e solo quello: l'handler `AdmitClaim` di C3 e il suo record di comando; i record `CandidateMatch`, `MatchEvidence`, `IdentityResolutionDecision` con `MergeDecision` e `SplitDecision`, e `ClusterMembershipAssertion`; i tipi d'azione di C6 che portano ammissione, merge e split; gli output del ruolo Fusion/Identity di C8; il ritiro o il ricalcolo delle derivazioni dopo uno split; un matcher deterministico per le sole fixture sintetiche; il reason code di ogni rifiuto.

La sezione 7 descrive come i candidati arrivano nelle letture, perché l'incarico la chiede; il punto 3 della decisione non la elenca. Per questo fissa solo ciò che i contratti esistenti già dicono e marca il resto come proposta.

Restano fuori: la vista del mission thread (`FR-166`), il validatore di tracciabilità, il codice dell'unità e tutto ciò che la decisione rinvia a dopo la decisione su G7 (sezione 11).

### 0.2 Come si leggono le ancore

Ogni record, campo, regola ed esito cita l'elemento che realizza. Le ancore valgono sul commit letto.

| Sigla | File |
|---|---|
| `ADD:n` | riga `n` di `ocor-runtime/docs/governance_dossier/OCOR_ADD_v1.3_APPROVED_BASELINE.md` |
| `LLD:n` | riga `n` di `docs/OCOR_LLD_v1.1.md` |
| `REG:n` | riga `n` di `ocor-runtime/docs/governance_dossier/registers/OCOR_Requirement_Register_v1.1_APPROVED.md` |
| `SRC:percorso:n` | riga `n` di un file sotto `ocor-runtime/src/ocor_runtime/`; compare solo nelle note di realizzazione, che non sono norma |
| «decisione, punto 3» e «decisione, punto 4» | i punti della decisione del PO indicata in testa |
| `Q-A` … `Q-L` | un quesito di norma aperto: la scelta non è determinata né dalla norma né dalla decisione |

Un intervallo si scrive `ADD:2010-2015`. Dove un elemento dipende da un quesito, il testo lo dice e riporta la sola opzione raccomandata, marcata come «proposta»: fino alla decisione del PO quella parte non è riferimento per il codice, mentre il lavoro sulle parti ancorate prosegue (decisione, punto 3, «Quesiti»).

Questo addendum introduce alcuni nomi: gli identificativi dei tipi d'azione, delle precondizioni e degli invarianti, il nome del port del matcher, i campi `record_type` e i campi che finiscono in `_ref`. Sono rese di elementi ancorati e non aggiungono semantica: il PO può cambiarli senza altra conseguenza.

### 0.3 Convenzioni comuni dei record

1. **Record chiusi.** Ogni record ha un insieme esatto di campi. Proprietà ulteriori, alias di campo e coercizioni sono rifiutati (LLD:18, LLD:378).
2. **Tipo del record.** Nessun record è alias di un altro (LLD:171). Per tenerli distinti, ogni record definito nelle sezioni 1.3, 2 e 6.1 porta il campo `record_type`, uguale al proprio nome: è una scelta di resa.
3. **Digest.** Il digest di un record è lo SHA-256 della sua serializzazione JSON RFC 8785, scritto `urn:sha256:<64 cifre esadecimali minuscole>` (LLD:37). Un digest ricevuto è ricalcolato prima dell'uso; se non coincide l'operazione è rifiutata (LLD:40).
4. **Insiemi.** Un array che rappresenta un insieme è ordinato lessicograficamente prima del digest e non contiene duplicati (LLD:39).
5. **Tempo.** Gli istanti sono RFC 3339 in UTC (LLD:38). Un intervallo è l'oggetto `{from, to}`, semiaperto `[from, to)`; `to: null` indica un intervallo ancora aperto (ADD:1234). `valid_time` descrive il mondo; `system_time` descrive la conoscenza registrata e lo assegna soltanto il writer dello stato canonico, cioè C3 (ADD:2052, ADD:426).
6. **Riferimenti.** Un riferimento a un record è uno `stableId` con il pattern `^urn:ocor:[A-Za-z0-9._~:/-]{1,240}$` (ADD:717). Un'`Evidence` non ha fra i propri campi un identificativo distinto dal digest del contenuto (ADD:2006) ed è referenziata tramite SHA-256 (ADD:2056); nelle letture il gateway la serve come indirizzo per contenuto `urn:sha256:` (ADD:1224). Questo addendum non fissa la forma del riferimento a un'`Evidence` dentro il comando di C3, che LLD v1.1 non tipizza (LLD:91).
7. **Marking.** Dove un record ha un campo `marking_ref`, la forma è `urn:sha256:<marking_digest>` (ADD:398) e il valore non è mai meno restrittivo del join conservativo dei marking degli input (ADD:2054, LLD:67).
8. **Governed Context.** I record di questo addendum non ripetono il Governed Context: lo lega il vettore che li trasporta, cioè il comando di C3 (LLD:92, LLD:93) o l'`HandoffEnvelope` di C8 (ADD:3086, ADD:3087). Un record senza un proprio `marking_ref` ha il marking del Governed Context del suo vettore (ADD:181, ADD:188).
9. **Pin.** Un pin è il record `VersionPin` del contratto del registro di funzioni e modelli: `{resource_id, semantic_version, artifact_digest, contract_digest}` (ADD:1412-1417), con i due digest nella forma del punto 3.
10. **Origine dei campi.** Nelle tabelle dei record la colonna «Origine» dice chi valorizza il campo. «Proposta»: è fornito con la proposta d'azione ed è parte di ciò che il `GatePackage` congela (ADD:3334). «C3»: C3 lo completa nella transazione del commit, e il campo è assente dal `canonical_delta` del comando. Che anche i campi derivati dalla `Decision` li completi C3 è la proposta del quesito `Q-K`.

### 0.4 Quesiti di norma aperti

| Quesito | Tema | Sezioni che ne dipendono |
|---|---|---|
| `Q-A` | Reason code e transizione di C6 per i rifiuti di C3 che ADD:2569 non mappa; lettura di LLD:97 sulla revisione; ordine nella transazione; fence | 1.4, 1.5, 2.7, 3.3, 3.6, 5.2, 5.3, 9.4, 9.5 |
| `Q-B` | Come si registra una decisione `NO_MATCH` o `DEFERRED` | 2.3, 3.2, 3.6, 6.1, 9.6 |
| `Q-C` | Aggregate di una decisione di identità; esclusività; ciò che merge e split possono creare e chiudere; inversione completa; nascita della Canonical Entity | 1.4, 2.4, 2.5, 2.6, 2.7, 3.3, 5.1, 5.2, 8.2, 9.1, 9.3 |
| `Q-D` | Struttura del campo `reversibility` di `MergeDecision` | 2.4 |
| `Q-E` | Ritiro o ricalcolo delle derivazioni: regola, ambito, forma del ritiro e sua lettura | 4.3, 4.4, 9.3 |
| `Q-F` | Matcher deterministico: ingresso, algoritmo, score, incertezza, pin, contenuto di una `MatchEvidence` | 2.2, 6.3, 8.2, 9.1, 9.3 |
| `Q-G` | Campi dei tre output tipizzati del ruolo Fusion/Identity | 6.1, 9.2 |
| `Q-H` | Dove stanno le Claim non ammesse, i `CandidateMatch` e le `MatchEvidence`; come li leggono C3 e il gateway; confronti con la Claim | 1.3, 1.4, 2.1, 2.7, 6.4, 7, 9.3 |
| `Q-I` | Invio a C3 senza risposta e retry | 1.5, 1.9, 5.2, 5.3, 8.3 |
| `Q-J` | Valori del contratto dei tre tipi d'azione che la norma lascia aperti | 5.2, 9.1, 9.3, 9.6 |
| `Q-K` | Campi derivati dalla `Decision`: chi li valorizza, che cosa espongono i record di C6, su quale documento si risolvono i percorsi del binding | 0.3, 1.3, 1.6, 2.3, 3.6, 5.2 |
| `Q-L` | Stato di adjudication servito per un candidato | 2.1, 3.4, 7, 9.3 |

## 1. `AdmitClaim` in C3

### 1.1 Collocazione

1. `AdmitClaim` è un port di C3, servito dal modulo «Admission/adjudication handler» (ADD:284).
2. Lo invoca soltanto C6, alla transizione `ACT-T29` (ADD:2900, LLD:302), per un'`ActionInstance` con `action_target = CANONICAL_COMMIT` (ADD:2763) il cui tipo d'azione dichiara `produced_assertion_class = CanonicalAssertion` (ADD:2144).
3. Nessun altro subsystem, evento o adapter induce un'ammissione. C5 recapita a C3 soltanto input semantico non canonico, che non è ammissibile senza il percorso governato (ADD:342). Gli adapter di ingestione non scrivono stato canonico né proiezioni (ADD:529, REG:200).
4. L'ammissione percorre la stessa FSM, le stesse guardie e lo stesso Human Gate di ogni altra azione: non esiste un secondo percorso verso lo stato canonico (ADD:2789).

### 1.2 Record di comando

LLD v1.1 fissa che l'unico comando mutativo di C3 è `GovernedCanonicalCommitCommand` (LLD:85). `AdmitClaim` non ne introduce un secondo: riceve quel comando, con i suoi diciassette campi (LLD:88-94), e vi applica il *profilo di ammissione* descritto qui. I nomi dei campi sono quelli di LLD v1.1; LLD v1.1 non ne dà i tipi, che qui seguono i campi omonimi di ADD v1.3 dove esistono.

| Campo | Tipo e cardinalità nel record | Vincolo del profilo di ammissione | Ancora |
|---|---|---|---|
| `command_id` | stringa, 1 | nessuno | LLD:89 |
| `action_instance_id` | stringa, 1 | l'istanza d'azione di C6 che ha raggiunto `ACT-T29` | LLD:89, ADD:2900 |
| `aggregate_type` | `stableId`, 1 | l'`aggregate_type_id` dichiarato dal tipo d'azione | LLD:89, ADD:2141 |
| `aggregate_ref` | stringa, 1 | il valore indicato da `aggregate_ref_path` | LLD:89, ADD:2157 |
| `expected_revision` | intero non negativo, 1 | nessuno | LLD:90 |
| `canonical_delta` | oggetto, 1 | l'oggetto chiuso `{canonical_assertion}`: esattamente un record `CanonicalAssertion` (sezione 1.3), con i soli campi di origine «proposta» | LLD:90, ADD:2048 |
| `decision_ref` | stringa, 1 | la `Decision` di C6 con esito `ACCEPT` | LLD:90, ADD:342 |
| `authority_ref` | stringa, 1 | l'Authority che accetta | LLD:90, ADD:342 |
| `evidence_refs` | insieme di riferimenti a `Evidence`, 1..* | non vuoto | LLD:91, ADD:2179, ADD:2565 |
| `claim_source_bindings` | insieme di record chiusi `{claim_ref, source_ref, evidence_ref}`, 0..* | 1..*; tutte le voci hanno lo stesso `claim_ref`, perché un'ammissione riguarda una sola Claim; ogni `evidence_ref` appartiene a `evidence_refs` | LLD:91, LLD:142, ADD:2048, ADD:2765 |
| `precondition_bindings` | insieme di `stableId`, 1..* | quelli del tipo d'azione (sezione 5.2) | LLD:91, ADD:2159 |
| `invariant_bindings` | insieme di `stableId`, 1..* | quelli del tipo d'azione (sezione 5.2) | LLD:92, ADD:2163 |
| `idempotency_key` | stringa, 1 | nessuno | LLD:92 |
| `governed_context` | record chiuso di undici campi, 1 | nessuno | LLD:92, LLD:45 |
| `governed_context_digest` | digest, 1 | digest del record precedente | LLD:93, LLD:40 |
| `gate_package_digest` | digest, 1 | digest del `GatePackage` congelato da C6 | LLD:93, ADD:342 |
| `branch` | costante `main`, 1 | nessuno | LLD:93, LLD:97 |

L'aggregate di un'ammissione è quello che il tipo d'azione e i parametri dell'azione indicano (ADD:2141, ADD:2157): questo addendum non aggiunge una regola.

### 1.3 Il record `CanonicalAssertion`

La colonna «Origine» si legge come nella sezione 0.3, punto 10.

| Campo | Tipo e cardinalità | Origine | Ancora |
|---|---|---|---|
| `record_type` | costante `CanonicalAssertion`, 1 | proposta | sezione 0.3 |
| `assertion_ref` | `stableId`, 1 | proposta | ADD:2005, REG:333 |
| `proposition_ref` | `stableId`, 1 | proposta | ADD:2003 |
| `world_ref` | `stableId`, 1 | proposta | ADD:2003 |
| `valid_time` | intervallo, 1 | proposta | ADD:2003, ADD:2052 |
| `system_time` | intervallo, 1; `from` è l'istante del commit canonico, `to` è `null` | C3 | ADD:2003, ADD:2052 |
| `marking_ref` | marking, 1 | proposta | ADD:2003, ADD:2054 |
| `epistemic_status` | costante `CANONICAL`, 1 | proposta | ADD:2003, ADD:1152 |
| `accepted_from_claim` | `stableId` della Claim sorgente, 1; uguale al `claim_ref` dei binding | proposta | ADD:2005, ADD:2048 |
| `accepted_by_decision` | stringa, 1; uguale a `decision_ref` del comando | C3 (`Q-K`) | ADD:2005, LLD:90 |
| `accepting_authority_ref` | stringa, 1; uguale ad `authority_ref` del comando | C3 (`Q-K`) | ADD:2005, LLD:90 |
| `canonical_commit_ref` | stringa, 1; l'identificativo del commit canonico che scrive il record | C3 | ADD:2005, LLD:139 |

Se `proposition_ref` e `world_ref` debbano coincidere con quelli della Claim sorgente la norma non lo dice: dice che la Canonical Assertion è collegata alla Claim con `acceptedFromClaim` (ADD:2048). Proposta, parte di `Q-H`: coincidono, e C3 lo verifica sulla Claim che risolve.

Invarianti:

1. **CA-1.** L'ammissione genera una Canonical Assertion nuova. La Claim sorgente resta una Claim e non assume il tipo `CanonicalAssertion`: le due classi sono specializzazioni sorelle di `Assertion` (ADD:2048).
2. **CA-2.** Non esiste una Canonical Assertion priva di `accepted_from_claim` e di decisione di accettazione esplicita (ADD:2059, REG:175).
3. **CA-3.** Marking e provenance devono essere presenti già alla proposta (ADD:2847), e il marking della Canonical Assertion non è meno restrittivo del join dei marking della Claim e delle sue evidenze (ADD:2054).

### 1.4 Precondizioni e ordine delle validazioni

Le validazioni si eseguono in quest'ordine. La prima che fallisce decide l'esito e le successive non si valutano: lo stesso comando difettoso produce sempre lo stesso reason code (ADD:2569). Ogni regola di questo addendum è verificata in un solo passo.

Prima della transazione, nell'ordine di enunciazione di LLD:97:

1. **V1, record chiuso.** I diciassette campi, e solo quelli, con i tipi della sezione 1.2.
2. **V2, digest.** `governed_context_digest` è ricalcolato sul record `governed_context` (LLD:40).
3. **V3, branch.** `branch` vale `main`.
4. **V4, provenienza C6.** Il `GatePackage` indicato da `gate_package_digest` si risolve e, ricalcolato, ha quel digest (LLD:320); ciò che il comando porta coincide con ciò che il `GatePackage` ha congelato (ADD:342, ADD:2852).
5. **V5, Decision.** Nell'ordine: la `Decision` si risolve; è firmata; ha esito `ACCEPT` con `effect_class = CANONICAL_COMMIT`; non è scaduta (ADD:342, ADD:2850); infine riguarda la stessa azione e lo stesso `GatePackage`. L'ultimo controllo, se fallisce, è un'incoerenza con il `GatePackage`.
6. **V6, Authority.** Nell'ordine: l'`Authority ref` si risolve; è valido; non è scaduto (ADD:342, ADD:3430); infine è coerente con il `GatePackage`. L'ultimo controllo, se fallisce, è un'incoerenza con il `GatePackage`.
7. **V7, Evidence.** Ogni voce di `evidence_refs` si risolve in un record `Evidence` (ADD:2006).
8. **V8, revisione.** LLD:97 elenca la revisione fra i controlli che precedono la transazione; LLD:132 realizza il confronto dentro la transazione, come aggiornamento condizionato che con zero righe produce `REVISION_CONFLICT`. Proposta, parte di `Q-A`: prima della transazione si verifica solo che `expected_revision` sia un intero non negativo; il confronto con la revisione corrente è il passo T2.
9. **V9, binding e profilo.** Nell'ordine: (a) gli identificativi di `precondition_bindings` e di `invariant_bindings` sono noti a C3; l'esito per un identificativo ignoto fa parte di `Q-A`; (b) `claim_source_bindings` rispetta il profilo della sezione 1.2; (c) il `claim_ref` si risolve in una Claim e ogni `source_ref` è la fonte che l'ha asserita (ADD:2004); da quale registro C3 la risolve, e se qui confronta anche `proposition_ref` e `world_ref`, fa parte di `Q-H`; (d) il `canonical_delta` ha la forma che il port prevede (sezione 1.7) e ogni record è chiuso; (e) `accepted_from_claim` coincide con il `claim_ref` dei binding (ADD:2005); (f) il marking del record si risolve ed è confrontabile, altrimenti l'esito è `MARKING_UNRESOLVED` (LLD:67), e non è meno restrittivo del join richiesto da CA-3.

Fence. ADD v1.3 chiede inoltre che C3 validi `writer_epoch`, Policy e Authority (ADD:3430) e descrive un fence di mutazione: HEAD canonico compatibile, versione dell'aggregate, release ontologica attiva, writer epoch e chiave di idempotenza correnti (ADD:3443); il record `MutationFence` porta anche un commit di base, uno stop epoch e una scadenza (ADD:3448-3458). LLD:97 non colloca questi controlli nel proprio elenco, e il comando non porta né un commit di base né una scadenza (LLD:88-94). Che cosa C3 valuta del fence, in quale punto e con quale codice fa parte di `Q-A`. Proposta: un passo **VF**, subito dopo V7, in cui lo stop non è attivo, lo stop epoch è quello congelato nel `GatePackage` e la release ontologica del comando è quella attiva (LLD:320); versione dell'aggregate e chiave di idempotenza sono i passi T2 e T1; il writer epoch è una condizione interna a C3.

Istante di riferimento. Proposta, parte di `Q-A`: C3 legge un solo istante all'inizio delle validazioni e lo usa per ogni confronto di scadenza.

Nella transazione locale, con l'ordine dei lock di LLD:132 (aggregate, binding di idempotenza, commit, outbox):

1. **T1, idempotenza.** La constraint unica su `(tenant_id, aggregate_type, aggregate_ref, idempotency_key)` restituisce la receipt originale se il digest del comando coincide, e `IDEMPOTENCY_CONFLICT` altrimenti (LLD:97). T1 precede T2 perché un retry duplicato deve ricevere la stessa receipt anche se la revisione è nel frattempo avanzata (REG:186).
2. **T2, revisione.** Se `expected_revision` non è la revisione corrente dell'aggregate, l'esito è `REVISION_CONFLICT` (LLD:132).
3. **T3, precondizioni.** Si valutano sullo stato corrente dell'aggregate; se una non vale, l'esito è `PRECONDITION_FAILED` (ADD:2569, REG:186).
4. **T4, invarianti.** Si valutano sullo stato che il commit produrrebbe; se uno non vale, l'esito è `INVARIANT_VIOLATION` (ADD:2569, REG:186).
5. **T5, scrittura.** Sezione 1.6.

La norma fissa che T1 precede T2 (REG:186) e che T2 avviene nella transazione (LLD:132); che T2 preceda T3 e T4 è una proposta, parte di `Q-A`. T3 e T4 guardano lo stato dell'aggregate del comando; la sola regola che guarda fuori dall'aggregate è l'esclusività proposta in `Q-C`.

Le regole della sezione 2.7 non dipendono dai binding che il comando dichiara: C3 le applica sempre, ogni volta che il delta o lo stato contengono un record di questo addendum. I binding dichiarati dal tipo d'azione si aggiungono, non le sostituiscono.

### 1.5 Esiti e reason code

Ogni rifiuto lascia invariati stato canonico, revisione, commit, binding di idempotenza, outbox e binding delle fonti: l'ammissione rifiutata non scrive nulla (LLD:97, REG:186). I reason code vengono dall'insieme chiuso del contratto dei tipi d'azione (ADD:2329-2352) e da LLD v1.1.

| Esito | Validazione | Reason code | Ancora | Transizione di C6 |
|---|---|---|---|---|
| Ammissione | tutte superate | nessuno: C3 restituisce la receipt del commit | ADD:271, ADD:2901 | `ACT-T30` |
| Replay | T1, stesso digest | nessuno: receipt originale | LLD:97, REG:186 | `ACT-T30`, se l'azione è ancora in `CANONICAL_COMMIT_PENDING` |
| Rifiuto | T2 | `REVISION_CONFLICT` | LLD:132, ADD:2903 | `ACT-T31b` |
| Rifiuto | T3 | `PRECONDITION_FAILED` | ADD:2569, ADD:2902 | `ACT-T31a` |
| Rifiuto | T4 | `INVARIANT_VIOLATION` | ADD:2569, ADD:2902 | `ACT-T31a` |
| Rifiuto | V4, e l'ultimo controllo di V5 e di V6 | `GATE_PACKAGE_MISMATCH` | ADD:2569, ADD:2903 | `ACT-T31b` |
| Rifiuto | V2 | `GOVERNED_CONTEXT_MISMATCH` | LLD:40, ADD:199, ADD:2903 | `ACT-T31b` |
| Rifiuto | V9 (f): marking non risolvibile o non confrontabile | `MARKING_UNRESOLVED` | LLD:67 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | T1, digest diverso | `IDEMPOTENCY_CONFLICT` | LLD:97 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | V5: Decision non risolvibile, non firmata, non `ACCEPT`, scaduta | `Q-A`; proposta: `POLICY_DENIED` | ADD:342, ADD:2332 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | V6: Authority non risolvibile, non valida, scaduta | `Q-A`; proposta: `AUTHORITY_MISSING` | ADD:342, ADD:2333 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | V7: Evidence non risolvibile | `Q-A`; proposta: `CONTRACT_REJECTED` | ADD:2006, ADD:2331 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | V8: revisione non intera o negativa | `Q-A`; proposta: `REVISION_CONFLICT` | LLD:97, LLD:132 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | V9 (a): identificativo di precondizione o di invariante ignoto | `Q-A`; proposta: `PRECONDITION_FAILED` o `INVARIANT_VIOLATION` | ADD:2569 | `Q-A`; proposta: `ACT-T31a` |
| Rifiuto | VF: stop attivo o stop epoch cambiato | `Q-A`; proposta: `EMERGENCY_STOP_ACTIVE` | ADD:3448-3458, ADD:2340 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | VF: release ontologica non attiva | `Q-A`; proposta: `RELEASE_MISMATCH` | ADD:3443, ADD:2339 | `Q-A`; proposta: `ACT-T31b` |
| Rifiuto | V1, V3, V9 da (b) a (e), e marking meno restrittivo del join | `Q-A`; proposta: `CONTRACT_REJECTED` | LLD:97, ADD:2331 | `Q-A`; proposta: `ACT-T31b` |

ADD v1.3 fissa la regola (ADD:342) e mappa in modo deterministico soltanto quattro casi (ADD:2569); per gli altri non indica quale codice dell'insieme chiuso usare, né quale delle due uscite di `CANONICAL_COMMIT_PENDING` (ADD:2902, ADD:2903) percorre C6. È il quesito `Q-A`. Proposta, per i rifiuti che la tabella rimanda a `Q-A`: la transizione di C6 registra il codice che C3 ha restituito, senza tradurlo, così che ogni rifiuto abbia un solo codice. Un writer con epoch superato è respinto dal fencing (ADD:271) e l'insieme chiuso non ha un codice per quel caso: per C6 non è un esito dell'azione, e l'invio resta senza esito (sezione 1.9).

Nota di realizzazione, non normativa. Sul commit letto C3 applica già a ogni `GovernedCanonicalCommitCommand` i controlli da V4 a V7 e quelli di VF, con `POLICY_DENIED` per la Decision (SRC:c3/admission.py:323), `AUTHORITY_MISSING` per l'Authority (SRC:c3/admission.py:336), `CONTRACT_REJECTED` per l'Evidence (SRC:c3/admission.py:356), `EMERGENCY_STOP_ACTIVE` per lo stop (SRC:c3/admission.py:361) e `RELEASE_MISMATCH` per la release (SRC:c3/admission.py:367). Per V1, V3 e V8 il record di comando restituisce oggi `COMMIT_CONTRACT_INVALID` (SRC:c3/ports.py:29), `SINGLE_WRITER_VIOLATION` (SRC:c3/ports.py:189) e `REVISION_CONFLICT` (SRC:c3/ports.py:158): i primi due codici non compaiono in alcun contratto del dossier.

### 1.6 Atomicità, outbox e idempotenza

1. Nella stessa transazione locale C3 scrive lo stato canonico con la nuova Canonical Assertion, la nuova revisione, il commit canonico, il binding di idempotenza e l'outbox (LLD:97, ADD:293). Nella stessa transazione scrive le righe di `canonical_source_binding` con i riferimenti a Claim, fonte ed evidenza (LLD:142) e completa il record con i campi di origine «C3» (ADD:2052, ADD:2005).
2. Il commit canonico registra Decision, Authority, Evidence, Governed Context e `GatePackage` (LLD:139).
3. L'outbox contiene una voce del branch `main` (LLD:141). Il relay la pubblica almeno una volta come `canonical-state-committed`, con identificativo di evento stabile (ADD:3432, LLD:132).
4. Il broker non partecipa al commit e non esiste transazione distribuita (ADD:293, ADD:165).
5. La receipt di C3 è l'evidenza di conferma dell'azione (ADD:2067).

### 1.7 Rapporto con `CommitAggregate`

ADD v1.3 sottopone `AdmitClaim` e `CommitAggregate` alla stessa regola, nella stessa frase (ADD:342). LLD v1.1 non nomina i due port: definisce un solo comando mutativo (LLD:85) e un solo port di commit, `GovernedCommitPort` (LLD:132). Entrambi ricevono quindi lo stesso comando e applicano gli stessi passi da V1 a V8, VF e da T1 a T5.

Cambia il passo V9. `AdmitClaim` applica il profilo di ammissione e accetta solo un delta nella forma della sezione 1.2. `CommitAggregate` applica il profilo di identità della sezione 3.3 a ogni delta che contiene un `MergeDecision`, uno `SplitDecision` o una `ClusterMembershipAssertion`. Nessuna riga della norma assegna merge e split a uno dei due port: instradarli su `CommitAggregate` è una scelta di resa, senza effetto sul comportamento, perché il profilo dipende dalla forma del delta. Il comando non porta il tipo d'azione (LLD:88-94): la corrispondenza fra la classe che il tipo dichiara in `produced_assertion_class` (ADD:2142) e i record proposti è garantita a monte dallo schema dei parametri del tipo, che `G-CONTRACT` verifica (ADD:2847).

### 1.8 Che cosa nasce dall'ammissione

1. Una e una sola Canonical Assertion, collegata alla Claim sorgente da `accepted_from_claim` e alla decisione, all'Authority e al commit che l'hanno accettata (ADD:2005, ADD:2048).
2. La traccia di adjudication dell'accettazione (sezione 3.6).
3. Nelle letture, l'oggetto è servito con `epistemic_status.status = CANONICAL` e con `accepting_decision_ref` valorizzato (ADD:1149, ADD:1152).
4. Nessun Claim, output di modello, messaggio d'agente o memoria diventa canonico per altra via (REG:175).

Un'ammissione non accettata non produce nulla in C3. La registrano le transizioni di C6 che la fermano: `ACT-T05` con il reason code del diniego (ADD:2864), `ACT-T09a` con il record di rifiuto dell'approvazione (ADD:2868), `ACT-T09b` con il record di scadenza (ADD:2869), `ACT-T10a` con Decision e razionale (ADD:2870).

### 1.9 Invio senza risposta e retry

Da `CANONICAL_COMMIT_PENDING` escono solo `ACT-T30`, `ACT-T31a` e `ACT-T31b` (ADD:2901, ADD:2902, ADD:2903); l'unica transizione di retry della FSM, `ACT-T19`, parte da `COMMAND_READY` e riguarda il dispatch esterno (ADD:2882). Per un crash di C3 prima del commit locale ADD v1.3 prevede il retry della richiesta con la stessa chiave di idempotenza (ADD:297), e LLD v1.1 ammette il retry solo prima dell'effetto o con idempotenza comprovata (LLD:354). Ogni invio, retry compreso, passa da `EMISSION-FENCE` (ADD:2854), e `G-FRESHNESS` confronta `expected_revision` con il valore corrente (ADD:2851): dopo un commit riuscito la cui receipt si è persa, un reinvio sarebbe invalidato prima di partire. C3 espone `GetCommit` (ADD:284) e C6 ha un modulo di riconciliazione dello stato (ADD:287).

La norma non compone queste regole per il caso in cui l'invio a C3 non riceve risposta. È il quesito `Q-I`. Proposta: C6 chiede a C3, con `GetCommit`, se esiste un commit per quell'aggregate e quella chiave; se esiste con lo stesso digest di comando, conferma con `ACT-T30`; se non esiste, può reinviare lo stesso comando con la stessa chiave finché `EMISSION-FENCE` vale; chiude l'azione con `ACT-T31b` solo dopo un rifiuto di C3, oppure quando `GetCommit` non trova il commit e la `Decision` è scaduta, perché da quel momento C3 rifiuta il comando al passo V5; in quel caso la transizione registra `GATE_PACKAGE_MISMATCH`, perché è superata la finestra di validità congelata nel `GatePackage` (LLD:320).

## 2. Record di identità

I campi sono quelli di ADD:2010-2015. I nomi sono la resa in `snake_case` dei termini di quelle righe.

### 2.1 `CandidateMatch`

| Campo | Tipo e cardinalità | Ancora |
|---|---|---|
| `record_type` | costante `CandidateMatch`, 1 | sezione 0.3 |
| `candidate_match_ref` | `stableId`, 1 | ADD:2010, ADD:717 |
| `source_identity_refs` | insieme di `stableId`, 2..* | ADD:2010 |
| `matcher_pin` | pin, 1 | ADD:2010, ADD:1412-1417 |
| `score` | numero, 1 | ADD:2010, ADD:1176 |
| `score_semantics` | uno dei valori di ADD:1178, 1 | ADD:2010, ADD:1178 |
| `status` | uno dei valori di ADD:1180, 1 | ADD:2010, ADD:1180 |

Tempi: ADD:2010 non attribuisce a `CandidateMatch` né valid time né system time. È un output analitico di classe `R1_ANALYZE`, che non muta nulla (ADD:3303). Il suo marking è quello del Governed Context del vettore (sezione 0.3, punto 8).

Invarianti:

1. **CM-1.** Un `CandidateMatch` non produce membership, link né inferenze (REG:335, ADD:2059).
2. **CM-2.** Il matcher e il ruolo Fusion/Identity non adjudicano (ADD:3059): il record che producono ha `status = UNADJUDICATED`. Se il campo resti costante e lo stato servito si calcoli, o se qualcuno lo aggiorni, fa parte di `Q-L`. Proposta: il record è immutabile e lo stato servito è la funzione della sezione 3.4.
3. **CM-3.** Un `CandidateMatch` non adjudicato resta rappresentabile e interrogabile secondo policy (ADD:2053).
4. **CM-4.** Il matcher confronta solo le Source Identity che la policy ha filtrato per il Governed Context della chiamata (ADD:3059). Indici, cache e strutture di ricerca del matcher non sono condivisi fra tuple di isolamento incompatibili (ADD:201, LLD:220).

Chi conserva i `CandidateMatch` e come arrivano alle letture è il quesito `Q-H`.

### 2.2 `MatchEvidence`

`MatchEvidence` è una `Evidence` (ADD:2011): porta i campi obbligatori di `Evidence` (ADD:2006) e quelli propri. Come ogni `Evidence` non ha un identificativo distinto dal digest del contenuto e si cita come dice la sezione 0.3, punto 6.

| Campo | Tipo e cardinalità | Ancora |
|---|---|---|
| `record_type` | costante `MatchEvidence`, 1 | sezione 0.3 |
| `candidate_match_ref` | riferimento a un `CandidateMatch`, 1 | ADD:2011, ADD:2059 |
| `feature_ref` | `stableId` della caratteristica confrontata, 1 | ADD:2011 |
| `method_ref` | `stableId` del metodo di confronto, 1 | ADD:2011, ADD:2006 |
| `stance` | uno fra `SUPPORTS`, `REFUTES`, `NEUTRAL`, 1 | ADD:2011, ADD:2007 |
| `assessor_pin` | pin del matcher o del modello che ha valutato, 1 | ADD:2011, ADD:2059, ADD:1412-1417 |
| `score_semantics` | come in `CandidateMatch`, 1 | ADD:2059 |
| `content_digest` | digest del contenuto dell'evidenza, 1 | ADD:2006 |
| `source_refs` | insieme di riferimenti alle fonti dei valori confrontati, 1..* | ADD:2006 |
| `acquired_at` | istante, 1 | ADD:2006 |
| `acquirer_principal_id` | Principal che ha prodotto l'evidenza, 1 | ADD:2006 |
| `chain_of_custody` | sequenza ordinata di riferimenti, 1..* | ADD:2006 |
| `marking_ref` | marking, 1 | ADD:2006, ADD:2054 |
| `retention_until` | istante, 1 | ADD:2006 |

Tempi: quelli di `Evidence`, cioè `acquired_at` e `retention_until`. Invarianti: **ME-1**, ogni `MatchEvidence` riferisce esattamente un `CandidateMatch` esistente (ADD:2059); **ME-2**, il record è immutabile (ADD:2056). Su che cosa si calcola `content_digest` per una `MatchEvidence` la norma non lo dice: fa parte di `Q-F`.

Nota di realizzazione, non normativa. I nomi `content_digest`, `acquired_at`, `acquirer_principal_id`, `method_ref`, `chain_of_custody`, `marking_ref` e `retention_until` sono quelli del record `Evidence` già presente nel codice (SRC:kernel/governance.py:819), che ha anche un identificativo proprio e una sola fonte.

### 2.3 `IdentityResolutionDecision`

È il record base (ADD:2012). `MergeDecision` e `SplitDecision` ne ereditano tutti i campi (ADD:2038, ADD:2039).

| Campo | Tipo e cardinalità | Origine | Ancora |
|---|---|---|---|
| `record_type` | costante: `IdentityResolutionDecision`, `MergeDecision` o `SplitDecision`, 1 | proposta | sezione 0.3 |
| `identity_decision_ref` | `stableId`, 1 | proposta | ADD:2012, ADD:717 |
| `outcome` | uno fra `MERGE`, `SPLIT`, `NO_MATCH`, `DEFERRED`, 1 | proposta | ADD:2012; decisione, punto 4 |
| `adjudicator_principal_id` | stringa, 1; il Principal umano che ha firmato la `Decision` | C3 (`Q-K`) | ADD:2012, REG:176, ADD:153 |
| `rationale` | testo non vuoto, 1; il razionale della `Decision` | C3 (`Q-K`) | ADD:2012, REG:176, ADD:2871 |
| `evidence_refs` | insieme di riferimenti a `Evidence`, 1..* | proposta | ADD:2012 |
| `evidence_set_digest` | digest dell'insieme di evidenze, 1 | proposta | ADD:2056, REG:176; decisione, punto 4 |
| `source_identity_refs` | insieme delle Source Identity considerate, 1..* | proposta | decisione, punto 4 |
| `valid_time` | intervallo, 1 | proposta | ADD:2012, ADD:2052 |
| `system_time` | intervallo, 1; `from` è l'istante del commit canonico | C3 | ADD:2012, ADD:2052 |
| `policy_decision_ref` | stringa, 1; riferimento alla Policy Decision dell'azione, cioè al record `PolicyAuthorityDecision` di C6 | C3 (`Q-K`) | ADD:2012, LLD:171, ADD:2863 |

Regole:

1. **IRD-1.** `outcome` e `record_type` sono coerenti: `MERGE` solo in un `MergeDecision`, `SPLIT` solo in uno `SplitDecision`, `NO_MATCH` e `DEFERRED` solo nel record base (decisione, punto 4; ADD:2013, ADD:2014).
2. **IRD-2.** `evidence_set_digest` è il digest, calcolato secondo la sezione 0.3, dell'array ordinato e senza duplicati dei `content_digest` delle `Evidence` elencate in `evidence_refs` (ADD:2056, ADD:2006, LLD:37, LLD:39). Dipende dal contenuto delle evidenze e non dalla forma dei loro riferimenti: è la «versione dell'insieme di evidenze» di REG:176.
3. **IRD-3.** Una decisione non si modifica e non si cancella: si rovescia solo con una decisione nuova (ADD:2051; decisione, punto 4).
4. **IRD-4.** Per `NO_MATCH`, `source_identity_refs` contiene almeno due Source Identity: è l'insieme considerato, legato al digest dell'insieme di evidenze (decisione, punto 4). Per `MERGE` e `SPLIT` coincide con l'insieme delle Source Identity delle membership create o chiuse dalla decisione.
5. **IRD-5.** `adjudicator_principal_id` e `rationale` sono quelli della `Decision` firmata che C3 risolve al passo V5 (ADD:2871, ADD:2850): un adjudicator dichiarato da chi propone non vale (ADD:197, LLD:41). Chi li scrive nel record è il quesito `Q-K`. Proposta: li scrive C3, insieme a `policy_decision_ref`, e nessuno dei tre sta nel delta.
6. **IRD-6.** `evidence_refs` della decisione è uguale a `evidence_refs` del comando che la porta, così che ogni evidenza citata sia stata risolta al passo V7 (ADD:2059, LLD:91).

Come si registra il record base, cioè una decisione `NO_MATCH` o `DEFERRED`, è il quesito `Q-B`.

### 2.4 `MergeDecision`

Campi aggiuntivi rispetto alla sezione 2.3 (ADD:2013), tutti di origine «proposta»:

| Campo | Tipo e cardinalità | Ancora |
|---|---|---|
| `canonical_entity_ref` | `stableId` dell'unica Canonical Entity della decisione, 1 | ADD:2013 |
| `memberships_created` | insieme di riferimenti a `ClusterMembershipAssertion`, 1..* | ADD:2013, ADD:2059 |
| `memberships_ended` | insieme di riferimenti a `ClusterMembershipAssertion`, 0..* | ADD:2013 |
| `reversibility` | oggetto chiuso, 1; struttura: `Q-D` | ADD:2013 |

ADD:2013 nomina i «reversibility metadata» senza darne la struttura: è il quesito `Q-D`. Proposta: l'oggetto chiuso `{irreversibility_class, reversing_action_type_id}`, con la classe dichiarata dal tipo d'azione (ADD:2381) e l'identificativo del tipo d'azione di split della sezione 5.

ADD:2013 prevede che un merge possa anche chiudere membership, e non dice in quali casi. Proposta, parte di `Q-C`: in `NCP-U15` `memberships_ended` di un `MergeDecision` è vuoto.

Invarianti: **MD-1**, ogni membership creata riguarda `canonical_entity_ref` (ADD:2013); **MD-2**, il delta delle membership non è vuoto, cosa che la cardinalità di `memberships_created` già impone (ADD:2059); **MD-3**, un merge non cancella Source Identity né decisioni (ADD:2051).

### 2.5 `SplitDecision`

Campi aggiuntivi rispetto alla sezione 2.3 (ADD:2014), tutti di origine «proposta»:

| Campo | Tipo e cardinalità | Ancora |
|---|---|---|
| `reverses_decision_ref` | riferimento al `MergeDecision` invertito, 1 | ADD:2014, ADD:2051 |
| `memberships_ended` | insieme di riferimenti a `ClusterMembershipAssertion`, 1..* | ADD:2014, ADD:2059 |
| `memberships_created` | insieme di riferimenti a `ClusterMembershipAssertion`, 0..* | ADD:2014 |
| `impacted_derivations` | insieme di `stableId` dei nodi di lineage delle derivazioni dipendenti (sezione 4), 0..* | ADD:2014, ADD:2051, REG:333 |

ADD:2014 prevede che uno split possa anche creare membership, e non dice in quali casi né con quali limiti. Proposta, parte di `Q-C`: in `NCP-U15` `memberships_created` di uno `SplitDecision` è vuoto; chi vuole lasciare unite alcune Source Identity dopo uno split le riunisce con un merge nuovo.

Invarianti:

1. **SD-1, inversione completa.** La norma chiede che uno split riferisca la decisione invertita e le membership impattate (ADD:2051) e non dice se possa chiuderne solo una parte. Proposta, parte di `Q-C`: `memberships_ended` è esattamente l'insieme delle membership create dal `MergeDecision` invertito che sono in vigore nello stato corrente.
2. **SD-2.** Uno split non cancella Source Identity, membership né decisioni: la decisione invertita resta leggibile (ADD:2051).
3. **SD-3.** Lo split è a sua volta reversibile con una decisione nuova (ADD:2564): con la proposta di `Q-C`, un merge che ricrea le membership.
4. **SD-4.** `impacted_derivations` è informativo: C3 ne verifica solo la forma. Una derivazione elencata che non dipende dalle membership chiuse non subisce effetti; una dipendente che manca dall'elenco è ritirata o ricalcolata lo stesso (sezione 4.2).

### 2.6 `ClusterMembershipAssertion`

| Campo | Tipo e cardinalità | Origine | Ancora |
|---|---|---|---|
| `record_type` | costante `ClusterMembershipAssertion`, 1 | proposta | sezione 0.3 |
| `membership_ref` | `stableId`, 1 | proposta | ADD:2015, ADD:717 |
| `source_identity_ref` | `stableId`, 1 | proposta | ADD:2015 |
| `canonical_entity_ref` | `stableId`, 1 | proposta | ADD:2015 |
| `generating_decision_ref` | riferimento alla decisione che l'ha creata, 1 | proposta | ADD:2015, ADD:2059 |
| `valid_time` | intervallo, 1 | proposta | ADD:2015, ADD:2052 |
| `system_time` | intervallo, 1; `from` è l'istante del commit che crea la membership; `to` è `null` finché la membership è in vigore, poi l'istante del commit della decisione che la chiude | C3 | ADD:2015, ADD:2051, ADD:2052 |

Invarianti:

1. **CMA-1.** Una membership nasce solo nello stesso commit canonico che scrive la sua decisione generatrice: il suo `generating_decision_ref` è l'`identity_decision_ref` del record di decisione che lo stesso commit aggiunge. Una membership la cui origine è un `CandidateMatch`, una decisione assente, una decisione non accettata o una decisione già scritta in un commit precedente è rifiutata da C3 con `INVARIANT_VIOLATION` e non scrive nulla (ADD:2059, REG:335, ADD:2569).
2. **CMA-2.** Una membership non si cancella: si chiude. Chiuderla significa valorizzare `system_time.to`; la lettura dello stato al commit precedente la mostra ancora in vigore (ADD:2051).
3. **CMA-3.** Una membership è «in vigore» a un commit se è presente nello stato di quel commit con `system_time.to` uguale a `null`.

L'aggregate che ospita decisioni e membership, la nascita di una Canonical Entity e la regola per cui una Source Identity ha al più una membership in vigore non sono fissati dalla norma: sono il quesito `Q-C`. Proposta: l'aggregate è la Canonical Entity della decisione, che non ha un record proprio e nasce con il primo merge che la nomina; una Source Identity ha al più una membership in vigore nell'ownership boundary.

### 2.7 Dove si verifica ciascuna regola

Ogni regola ha un solo passo. C3 la applica a ogni comando il cui delta, o il cui stato, contiene un record di questo addendum, qualunque siano i binding dichiarati (sezione 1.4). Il passo V9 guarda il solo comando; T3 lo stato corrente dell'aggregate; T4 lo stato che il commit produrrebbe.

| Regola | Passo | Reason code | Ancora |
|---|---|---|---|
| Forma del delta; record chiusi, tipi, costanti e cardinalità, MD-2 compresa; IRD-1; IRD-2; IRD-6; MD-1; i riferimenti dei record di membership del delta sono esattamente `memberships_created` | V9 | `Q-A`; proposta: `CONTRACT_REJECTED` | LLD:97, LLD:378, ADD:2059 |
| Proposta di `Q-C`: `memberships_ended` non vuoto in un merge, `memberships_created` non vuoto in uno split | V9 | `Q-A`; proposta: `CONTRACT_REJECTED` | LLD:97 |
| Nell'aggregate esiste già un record con il riferimento di un record del delta | T3 | `PRECONDITION_FAILED` | ADD:2569, REG:186 |
| Una membership da chiudere non esiste o non è in vigore | T3 | `PRECONDITION_FAILED` | ADD:2569, ADD:2051 |
| La decisione indicata da `reverses_decision_ref` non è un `MergeDecision` presente nell'aggregate, oppure è già stata invertita | T3 | `PRECONDITION_FAILED` | ADD:2569, ADD:2014 |
| SD-1, proposta di `Q-C` | T3 | `PRECONDITION_FAILED` | ADD:2569 |
| Esclusività, proposta di `Q-C`: una Source Identity che riceve una membership ne ha già una in vigore | T3 | `PRECONDITION_FAILED` | ADD:2569 |
| CMA-1: una membership aggiunta dal commit non ha per decisione generatrice il record di decisione aggiunto dallo stesso commit | T4 | `INVARIANT_VIOLATION` | ADD:2569, ADD:2059, REG:335 |
| IRD-4: `source_identity_refs` di un merge o di uno split non coincide con le Source Identity delle membership create o chiuse | T4 | `INVARIANT_VIOLATION` | ADD:2569 |
| CA-2: una `CanonicalAssertion` dello stato è priva di `accepted_from_claim` o di `accepted_by_decision` | T4 | `INVARIANT_VIOLATION` | ADD:2569, ADD:2059 |

Per un comando che supera V9, CA-2 vale per costruzione: resta dichiarato perché il contratto chiede almeno un invariante per tipo d'azione (ADD:2163) e perché protegge lo stato da ogni altro percorso. Le regole ME-1 e CM-4 riguardano record che non passano da C3: le verifica chi li riceve, secondo `Q-H`.

## 3. Decisioni ed esiti

### 3.1 I quattro esiti

`outcome` assume uno fra `MERGE`, `SPLIT`, `NO_MATCH` e `DEFERRED` (decisione, punto 4).

| Esito | Significato | Record | Effetto sullo stato canonico |
|---|---|---|---|
| `MERGE` | le Source Identity indicate appartengono alla Canonical Entity indicata | `MergeDecision` | crea membership (ADD:2013) |
| `SPLIT` | un merge precedente è invertito | `SplitDecision` | chiude membership (ADD:2014) |
| `NO_MATCH` | le Source Identity considerate non sono la stessa entità | `IdentityResolutionDecision` | nessuna membership (decisione, punto 4) |
| `DEFERRED` | l'adjudication è rinviata; i candidati restano non adjudicati | `IdentityResolutionDecision` | nessuna membership (decisione, punto 4) |

### 3.2 Chi registra ciascun esito

1. `MERGE` e `SPLIT` sono mutazioni dello stato canonico. Le produce soltanto C6 con una `Decision = ACCEPT` di un tipo d'azione con `effect_class = CANONICAL_COMMIT` e le scrive soltanto C3 (ADD:342, ADD:2789). Il `system_time` lo assegna C3 (ADD:2052).
2. `NO_MATCH` e `DEFERRED` non creano membership né asserzioni. Due vincoli si incontrano. Il record è bitemporale e il system time lo assegna solo il writer canonico (ADD:2052, ADD:426). Ogni scrittura di C3 passa da un tipo d'azione, e il contratto elenca le classi che un commit canonico può produrre senza prevederne una per il record base (ADD:2144-2148); anche la verifica di forma che ADD §3.6 chiede riguarda le sole decisioni di merge e di split (ADD:2059). Contratto e shape non cambiano in `NCP-U15` (decisione, punto 4). Nessuna strada rispetta questi vincoli insieme alla frase del punto 4 per cui `NCP-U15` realizza gli esiti e il record. È il quesito `Q-B`.
3. Proposta per `Q-B`. `NCP-U15` definisce il record base e i quattro esiti, realizza `MERGE` e `SPLIT`, e registra ogni rifiuto attraverso la FSM (sezione 3.6). La scrittura del record `NO_MATCH` o `DEFERRED` avviene come commit canonico, con un tipo d'azione dedicato, dopo un'estensione governata del contratto e della shape, fuori da `NCP-U15`.

### 3.3 Delta delle membership e profilo di identità

1. Un `MergeDecision` crea almeno una membership; uno `SplitDecision` chiude almeno una membership (ADD:2013, ADD:2014, ADD:2059).
2. Decisione e membership del suo delta sono scritte nello stesso commit canonico, con un solo `GovernedCanonicalCommitCommand` su un solo aggregate (LLD:85, LLD:97): un candidato non entra nel cluster canonico senza una decisione accettata (REG:335). Una decisione non si distribuisce mai su più commit.
3. Il `canonical_delta` di un comando di merge o di split è l'oggetto chiuso `{decision, memberships}`: `decision` è l'unico record di decisione, con i soli campi di origine «proposta»; `memberships` è l'insieme dei record `ClusterMembershipAssertion` da creare, che è vuoto per uno split. Le membership da chiudere sono indicate da `memberships_ended` della decisione; C3 le chiude valorizzando `system_time.to` e completa i campi di origine «C3» (ADD:2052).
4. Le membership create hanno `generating_decision_ref` uguale all'`identity_decision_ref` della decisione dello stesso delta (ADD:2015): lo verifica l'invariante CMA-1, al passo T4.
5. Un comando di merge o di split non accetta alcuna Claim: nessun campo di decisione o di membership riferisce una Claim (ADD:2012, ADD:2013, ADD:2014, ADD:2015), e il riferimento al binding Claim/source è facoltativo nell'istanza d'azione (ADD:2765). Il suo `claim_source_bindings` è quindi vuoto. Il tipo d'azione dichiara comunque il percorso `claim_source_binding_path`, che il contratto richiede sempre (ADD:2128) e che si risolve in un array vuoto. `evidence_refs` resta obbligatorio e non vuoto: ogni mutazione canonica ha evidenze non vuote (ADD:2565, ADD:2376-2377).
6. Al passo V9 il profilo di identità verifica, nell'ordine: gli identificativi dei binding, come al punto (a) della sezione 1.4; `claim_source_bindings` vuoto; il delta nella forma del punto 3 e i record chiusi; poi le regole che la tabella 2.7 assegna a V9. I punti (c), (e) e (f) della sezione 1.4 non si applicano: decisioni e membership non hanno una Claim né un marking proprio (sezione 0.3, punto 8).

Nota di realizzazione, non normativa. Sul commit letto il record del comando rifiuta un `claim_source_bindings` vuoto (SRC:c3/ports.py:163): `NCP-U15` deve tenerne conto.

### 3.4 Stato di adjudication di un `CandidateMatch`

Il contratto del gateway fissa i valori di `adjudication_status` (ADD:1180) e dice che un'identità candidata non adjudicata non implica appartenenza al cluster canonico (ADD:1171); il Register vieta che un candidato entri nel cluster senza una decisione accettata (REG:335). La norma non dice come lo stato servito derivi dalle decisioni. È il quesito `Q-L`. Proposta: lo stato servito a un dato commit è questa funzione delle membership e delle decisioni registrate fino a quel commit.

1. Se a quel commit tutte le Source Identity del candidato hanno una membership in vigore nella stessa Canonical Entity, lo stato è `ACCEPTED`.
2. Altrimenti conta la più recente fra le decisioni che toccano il candidato, per `system_time.from` e, a parità, per ordine dei commit del branch. Una decisione tocca il candidato in due casi: è uno `SplitDecision` che ha chiuso membership di tutte le sue Source Identity nella stessa Canonical Entity; oppure è una decisione `NO_MATCH` o `DEFERRED` il cui `source_identity_refs` è uguale all'insieme delle Source Identity del candidato, perché la decisione parla di «un candidato sullo stesso insieme» (decisione, punto 4).
3. Lo stato è `SPLIT` se quella decisione è uno `SplitDecision`, `REJECTED` se ha esito `NO_MATCH`, `UNADJUDICATED` se ha esito `DEFERRED` o se nessuna decisione tocca il candidato.

Una decisione nuova rovescia la precedente, qualunque sia il suo esito: è il solo modo di rovesciare un `NO_MATCH` (decisione, punto 4).

### 3.5 Reversibilità

1. Merge e split sono reversibili per costruzione: un tipo d'azione canonico non può essere `IRREVERSIBLE` (ADD:2564).
2. Invertire significa registrare una decisione nuova. Nessuna decisione e nessuna membership è modificata in modo distruttivo o cancellata (ADD:2051, REG:132).
3. Un `MergeDecision` è «in vigore» finché nessuno `SplitDecision` lo nomina in `reverses_decision_ref`.
4. Un merge seguito da uno split ricostruisce gli stati precedenti: la vista al commit del merge e la vista al commit dello split sono entrambe leggibili (REG:120, REG:336, ADD:2745).
5. Una decisione `NO_MATCH` è bitemporale e si rovescia solo con una decisione nuova (decisione, punto 4).

### 3.6 Registrazione di ogni esito, rigetti compresi

Ogni esito di un'azione di ammissione, merge o split lascia un record da cui si leggono tre cose: chi ha deciso, oppure che nessuna persona ha deciso; il razionale, oppure il reason code; la versione dell'insieme di evidenze (REG:176; decisione, punto 3, criterio f). La versione dell'insieme di evidenze è sempre il digest calcolato con la regola IRD-2 sulle evidenze che il record indicato porta.

| Esito dell'azione | Record che lo registra | Chi ha deciso | Razionale | Evidenze su cui si calcola la versione | Ancora |
|---|---|---|---|---|---|
| Merge o split accettato e scritto | `MergeDecision` o `SplitDecision` nello stato canonico | `adjudicator_principal_id` | `rationale` | `evidence_refs` del record; il digest è già in `evidence_set_digest` | ADD:2012 |
| Ammissione accettata e scritta | `Decision` di `ACT-T10b` e commit canonico | chi firma la `Decision` | razionale della `Decision` | `evidence_refs` del commit canonico | ADD:2871, LLD:139 |
| Decisione di rifiuto | `Decision` di `ACT-T10a` | chi firma la `Decision` | razionale della `Decision` | evidenze congelate nel `GatePackage` | ADD:2870, ADD:3334 |
| Decisione scaduta | `Decision` di `ACT-T10a` | nessuna persona | la scadenza | evidenze congelate nel `GatePackage` | ADD:2870, ADD:3334 |
| Approvazione rifiutata | record di rifiuto di `ACT-T09a` | l'approvatore che rifiuta | quello del record di rifiuto | evidenze del work item di `ACT-T06` | ADD:2868, ADD:2865 |
| Approvazione scaduta | record di scadenza di `ACT-T09b` | nessuna persona | la scadenza | evidenze del work item di `ACT-T06` | ADD:2869, ADD:2865 |
| Diniego al controllo | reason code fail-closed di `ACT-T05` | nessuna persona | il reason code | evidenze registrate con la proposta in `ACT-T01` | ADD:2864, ADD:2860 |
| Conflitto di idempotenza alla proposta | reason code di `ACT-T03` | nessuna persona | il reason code | evidenze della proposta rifiutata | ADD:2862 |
| Drift o stop dopo la decisione | invalidazione di `ACT-T13`; annullamento di `ACT-T23a` o `ACT-T23b` | chi ha firmato la `Decision` | la causa del drift o dello stop | evidenze congelate nel `GatePackage` | ADD:2874, ADD:2893, ADD:2894 |
| Rifiuto o conflitto in C3 | reason code di `ACT-T31a` o `ACT-T31b` | chi ha firmato la `Decision` | il reason code | evidenze congelate nel `GatePackage` | ADD:2902, ADD:2903, ADD:3334 |

Il «conflitto» che REG:176 chiede di registrare è, per queste azioni, quello di revisione e di idempotenza. La norma nomina i record di C6 della tabella senza elencarne i campi: quali campi espongano le tre informazioni fa parte di `Q-K`. Con la proposta di `Q-B`, un merge non accettato lascia la `Decision` di rifiuto e non ancora un record `NO_MATCH` o `DEFERRED`.

### 3.7 Propagazione dell'incertezza fino al blocco dell'azione

`FR-012` chiede che l'incertezza raggiunga ipotesi, risultato causale e proposta, e che una condizione insufficiente produca blocco o astensione e nessun `ActionCommand` (REG:65). La catena è già normata; questo addendum non aggiunge soglie.

1. Ogni output del ruolo Fusion/Identity porta incertezza e provenance (ADD:3059).
2. Il ruolo Hypothesis riceve le identità candidate con le evidenze a favore e contro (ADD:3060); un dissent critico sull'ambiguità d'identità blocca la proposta ad alto impatto, e un dissent non critico irrisolto accompagna la proposta (ADD:3110).
3. La proposta di decisione che raggiunge il Human Gate conserva incertezza, astensioni, dissent e provenance, e non è eseguibile (ADD:3123).
4. Per un bersaglio canonico l'evidenza di proposta è obbligatoria, con almeno un elemento (ADD:2376-2377). Una proposta che non rispetta schema o contratto è fermata dal gate di pre-ammissione con `SCHEMA_VIOLATION` o `CONTRACT_REJECTED` e non crea un'`ActionInstance` (ADD:2753).
5. Authority insufficiente, policy contraria o servizi di controllo indisponibili portano a `DENIED` con `ACT-T05` (ADD:2864); il tetto di rischio della delega è una condizione di `G-AUTHORITY` (ADD:2848).
6. L'`ActionCommand` nasce soltanto in `ACT-T12` (ADD:2873). Ogni blocco precedente lascia quindi zero `ActionCommand`, come chiede REG:65.
7. Un `CandidateMatch` non adjudicato non propaga link né inferenze (REG:335): l'incertezza resta visibile come identità candidata nelle letture (sezione 7) e non diventa un fatto.

## 4. Derivazioni dipendenti dopo uno split

### 4.1 Che cosa conta come derivazione dipendente

Una derivazione dipende da una membership se il suo lineage passa per quella membership; dipende da un merge se dipende da una membership che quel merge ha creato. Il lineage è la catena che `FR-149` rende navigabile, nella quale la risoluzione dell'identità è un nodo fra l'asserzione e la regola o il modello che la usa (REG:333). Sono derivazioni: le asserzioni derivate, i link e le inferenze calcolati attraverso una membership (REG:336, REG:335), e i fatti delle proiezioni che materializzano la vista unita (ADD:2057).

### 4.2 Come si individua

1. **Obbligo di provenance.** Chi calcola una derivazione attraverso una membership ne cita il riferimento fra i propri input: ogni nodo del lineage ha un identificativo e un link al predecessore (REG:333, ADD:2017, ADD:2050). Una derivazione che usa la vista unita senza citare la membership viola questo obbligo.
2. **Chiave.** Dipende da una membership ogni derivazione la cui provenance la cita, direttamente o attraverso i propri input (ADD:2015, ADD:2017, ADD:2057).
3. **Elenco nello split.** `impacted_derivations` elenca le derivazioni dipendenti note a chi propone lo split (ADD:2014). Serve all'adjudicator e alla traccia: uno split evidenzia le dipendenze interessate (REG:120).
4. **L'elenco non limita l'effetto.** Va ritirata o ricalcolata ogni derivazione che dipende da una membership chiusa, anche se è nata dopo la proposta e non è nell'elenco (ADD:2057, REG:336).

### 4.3 Che cosa è garantito

Le garanzie valgono per ogni commit che chiude una membership. In `NCP-U15` quel commit è sempre uno split; merge e split devono in ogni caso ricalcolare link e inferenze dipendenti (REG:336).

1. **Chiusura.** Lo split chiude, nel proprio commit canonico, le membership che elenca (sezione 2.5). L'evento `canonical-state-committed` di quel commit raggiunge ogni projector almeno una volta (ADD:3432).
2. **Applicazione.** Ogni projector deduplica su `(target, branch, commit_id)` (ADD:3433). Quando applica il commit che chiude una membership, ritira o ricalcola ogni derivazione la cui provenance cita quella membership, insieme all'avanzamento del proprio watermark: nella stessa transazione locale, oppure con il dataset versionato e lo scambio atomico di puntatore che ADD v1.3 ammette in alternativa (ADD:3434, LLD:148, ADD:2057).
3. **Watermark.** Una lettura che chiede almeno un commit è servita solo con un watermark uguale o successivo a quel commit (ADD:3441): un projector non dichiara quindi un watermark uguale o successivo a un commit che non ha applicato. La norma garantisce l'ordine degli eventi solo per aggregate e per chiave di ordinamento (LLD:148, ADD:848). Questo addendum chiede perciò in modo esplicito che un evento di un altro aggregate, successivo alla chiusura nell'ordine dei commit ma arrivato prima, non lasci in vigore, a un watermark uguale o successivo alla chiusura, una derivazione calcolata attraverso la membership chiusa. Il projector può ottenerlo applicando gli eventi nell'ordine dei commit del branch, oppure ritirando alla chiusura anche le derivazioni nate da eventi successivi: il modo è dell'implementazione, l'esito no (REG:336).
4. **Lettura.** Di conseguenza nessuna lettura servita con watermark uguale o successivo al commit di chiusura mostra in vigore una derivazione materializzata da una proiezione che dipendeva da una membership chiusa. Una lettura che chiede quel commit prima che la proiezione lo abbia raggiunto riceve `PROJECTION_NOT_READY` o `STALE_CONTEXT`, non un dato vecchio (ADD:3445).
5. **Copertura.** La copertura richiesta è totale: il cento per cento delle derivazioni impattate è ritirato o ricalcolato (REG:336).
6. **Storia.** Una derivazione ritirata non è cancellata: resta leggibile nella storia (ADD:2051, REG:132). Un oggetto ritirato è servito con `epistemic_status.status = RETRACTED` (ADD:1152); come una lettura distingua un link o un valore derivato ritirato, a contratto invariato, fa parte di `Q-E`.
7. **Ricostruzione.** Una proiezione ricostruita dai commit arriva allo stesso insieme di derivazioni in vigore e di derivazioni ritirate: una proiezione è eliminabile e ricostruibile (ADD:272, LLD:148).

I punti da 2 a 4 coprono le derivazioni che una proiezione di C4 materializza. Le derivazioni conservate altrove, come gli output dei ruoli d'agente e i risultati causali, non stanno nella transazione di un projector: chi le ritira, con quale record e quando, fa parte di `Q-E`.

### 4.4 Quando si ritira e quando si ricalcola

La norma chiede che ogni derivazione impattata sia ritirata o ricalcolata (ADD:2051, ADD:2057, REG:336). Non dice quale delle due cose si fa per ciascuna, né in quale forma si registra il ritiro; il contratto dei tipi d'azione prevede fra le classi producibili una `RetractionAssertion` (ADD:2148) senza definirla altrove. È il quesito `Q-E`. Proposta:

1. si ricalcolano i fatti delle proiezioni e le derivazioni prodotte da una `DerivedDefinition` attiva nella release (ADD:427), valutata sullo stato successivo allo split;
2. si ritirano, senza ricalcolo automatico, le derivazioni prodotte da un ruolo d'agente o da un modello: non sono stato canonico (ADD:151);
3. il ritiro si registra nella proiezione della provenance con un segno di ritiro che cita la derivazione, le membership chiuse, lo split e il suo commit, scritto insieme al watermark; in `NCP-U15` non si scrivono `RetractionAssertion` canoniche;
4. un link o un valore derivato ritirato non compare più in `link_refs` né in `values` delle letture servite dopo la chiusura; il segno di ritiro si legge nel lineage di `GetProvenance`, secondo policy;
5. in `NCP-U15` l'ambito sono le derivazioni che una proiezione materializza; per quelle conservate da un altro componente vale la stessa regola, a cura di chi le conserva, dal momento in cui quel componente usa la vista unita.

Fino alla decisione vale la sola parte ancorata della sezione 4.3.

## 5. Tipi d'azione di C6

### 5.1 I tre tipi

Ammissione, merge e split sono decisioni con `effect_class = CANONICAL_COMMIT` e percorrono la FSM di tutte le azioni (ADD:2789; decisione, punto 3). Ciascuno è un `ActionType` conforme al contratto di ADD §3.7, che non cambia.

| Nome proposto (`action_type_id`) | Classe prodotta | Port di C3 |
|---|---|---|
| `urn:ocor:action-type:canonical:admit-claim` | `CanonicalAssertion` | `AdmitClaim` |
| `urn:ocor:action-type:identity:merge` | `MergeDecision` | `CommitAggregate` |
| `urn:ocor:action-type:identity:split` | `SplitDecision` | `CommitAggregate` |

Le classi prodotte sono tre dei valori ammessi da ADD:2144-2148. Il contratto dà a ogni tipo una sola classe prodotta (ADD:2142) ed elenca `ClusterMembershipAssertion` come classe a sé (ADD:2145); la norma chiede d'altra parte che merge e split creino o chiudano membership (ADD:2051). Proposta, parte di `Q-C`: il tipo d'azione di classe `MergeDecision` o `SplitDecision` scrive nello stesso commit anche le membership del proprio delta, e in `NCP-U15` nessun tipo d'azione produce da sola una `ClusterMembershipAssertion`.

### 5.2 Valori del contratto

Valori che la norma fissa, per tutti e tre i tipi salvo dove indicato:

| Campo del contratto | Valore | Ancora |
|---|---|---|
| `target` | `CANONICAL_COMMIT` | ADD:2117, ADD:2067 |
| `effect_class` | `CANONICAL_COMMIT` | ADD:2364 |
| `risk_class` | non inferiore a `R2_CONTROLLED` | ADD:2365, ADD:2565 |
| `approval.mode` | umano: `HUMAN_GATE` oppure `DUAL_CONTROL` | ADD:2368, ADD:2565 |
| `approval.independent_approver_count` e `approval.required_approver_roles` | almeno un approvatore e almeno un ruolo | ADD:2369, ADD:2370 |
| `approval.self_approval_allowed` | `false` | ADD:2271 |
| `evidence_requirements` | `proposal_evidence = REQUIRED`, `confirmation_evidence = REQUIRED`, `minimum_count` almeno `1` | ADD:2376-2377, ADD:2320 |
| `compensation.irreversibility_class` | `REVERSIBLE` oppure `COMPENSATABLE`, mai `IRREVERSIBLE` | ADD:2381, ADD:2564 |
| `idempotency.key_required` | `true` | ADD:2248 |
| `idempotency.duplicate_semantics` | `REPLAY_RECEIPT`: lo stesso comando con la stessa chiave riceve la receipt originale | ADD:2250, LLD:97 |
| `timeouts` | tutti espliciti | ADD:2563 |
| `canonical_commit_binding.produced_assertion_class` | secondo la tabella della sezione 5.1 | ADD:2142 |
| `canonical_commit_binding.requires_accepted_from_claim` e `requires_evidence_set`, per l'ammissione | `true` | ADD:2178, ADD:2179 |
| `canonical_commit_binding.requires_evidence_set`, per merge e split | `true`: ogni mutazione canonica ha evidenze non vuote | ADD:2565 |
| `canonical_commit_binding`, percorsi | tutti dichiarati; un percorso assente o non risolto produce `CONTRACT_REJECTED` | ADD:2153-2158, ADD:2559 |
| `precondition_binding_refs` e `invariant_binding_refs` | almeno un identificativo per gruppo | ADD:2159, ADD:2163 |
| `error_codes` | solo codici dell'insieme chiuso | ADD:2324, ADD:2329-2352 |

Valori che la norma lascia aperti. Sono il quesito `Q-J`, salvo la riga del retry che dipende da `Q-I`; la colonna centrale riporta la proposta.

| Campo del contratto | Proposta | Valori ammessi |
|---|---|---|
| `risk_class` | `R2_CONTROLLED`, mutazione interna reversibile e confinata | ADD:2365, ADD:3304, ADD:3305 |
| `approval.mode` e `independent_approver_count` | `HUMAN_GATE`, un approvatore | ADD:2368, ADD:3304 |
| `approval.required_approver_roles` | un ruolo di steward o di adjudicator dichiarato in OaC | ADD:2370, REG:335 |
| `approval.timeout_action` | `EXPIRE`, che è l'uscita `ACT-T09b` | ADD:2283, ADD:2869 |
| `compensation.irreversibility_class` | `REVERSIBLE` | ADD:2381 |
| `compensation.mode` | `NOT_APPLICABLE`: un commit canonico rifiutato non lascia effetti, e l'inversione di un merge è una decisione nuova | ADD:2258, LLD:97 |
| `idempotency.scope` | `RESOURCE`, perché la chiave è unica per aggregate | ADD:2249, LLD:97 |
| `retry.retry_safe` e `retry.max_attempts` | `true` e il valore del profilo temporale candidato del PoC | ADD:2225, ADD:2926 |
| `requires_accepted_from_claim`, per merge e split | `false`: non accettano una Claim | ADD:2151 |

Per l'ammissione la classe `REVERSIBLE` è dichiarata perché una mutazione canonica non può essere irreversibile (ADD:2564); il percorso che ritira un'asserzione ammessa non è definito in `NCP-U15`.

Gli altri campi obbligatori del contratto sono dati della release OaC che l'unità compila con C1 per le proprie fixture. Il contratto lega i percorsi di Claim/source, Decision, Authority, insieme di evidenze, aggregate, revisione, digest del `GatePackage` e chiave di idempotenza allo schema dei parametri (ADD:2559); una parte di quei valori non la fornisce chi propone. Su quale documento si risolvano quei percorsi fa parte di `Q-K`.

Un'azione il cui Governed Context non autorizza tutti i suoi input è negata al confine di compartimento con `POLICY_DENIED` (ADD:175), al controllo di `ACT-T05`. Le azioni fra compartimenti, che sarebbero di classe `R3_HIGH_IMPACT` (ADD:3305), non sono definite da questo addendum.

Precondizioni e invarianti. I tre tipi dichiarano gli identificativi seguenti, che nominano regole della tabella 2.7; C3 applica quelle regole in ogni caso (sezione 1.4).

| Identificativo proposto | Tipi | Regola della tabella 2.7 |
|---|---|---|
| `urn:ocor:precondition:canonical:record-ref-unused` | tutti | riferimento già presente nell'aggregate |
| `urn:ocor:invariant:canonical:assertion-accepted-from-claim` | ammissione | CA-2 |
| `urn:ocor:precondition:identity:memberships-in-force` | split | membership da chiudere in vigore |
| `urn:ocor:precondition:identity:reversed-decision-in-force` | split | decisione invertita presente e non già invertita |
| `urn:ocor:invariant:identity:membership-generated-by-accepted-decision` | merge, split | CMA-1 |
| `urn:ocor:invariant:identity:decision-covers-its-memberships` | merge, split | IRD-4 |

Con la proposta di `Q-C` si aggiungono `urn:ocor:precondition:identity:split-reverses-whole-merge` per lo split (SD-1) e `urn:ocor:precondition:identity:source-identity-unassigned` per il merge (esclusività).

### 5.3 Transizioni percorse

La FSM non cambia: le righe sono quelle di LLD §3.2 e di ADD §4.1.2.

| Percorso | Transizioni, in ordine | Ancora |
|---|---|---|
| Decisione accettata e scritta | `ACT-T01`, `ACT-T04`, `ACT-T06`, `ACT-T08`, `ACT-T26`, `ACT-T10b`, `ACT-T11`, `ACT-T12`, `ACT-T29`, `ACT-T30`, `ACT-T27`, poi `ACT-T22` oppure `ACT-T28` | LLD:262-305, ADD:2860-2903 |
| Stessa chiave di idempotenza, stessa proposta | `ACT-T02` | ADD:2861 |
| Stessa chiave, proposta diversa | `ACT-T03` | ADD:2862 |
| Diniego al controllo | `ACT-T05` | ADD:2864 |
| Approvazione rifiutata o scaduta | `ACT-T09a`, `ACT-T09b` | ADD:2868, ADD:2869 |
| Decisione di rifiuto o scaduta | `ACT-T10a` | ADD:2870 |
| Drift prima del comando | `ACT-T13` | ADD:2874 |
| Stop prima dell'emissione | `ACT-T23a`, `ACT-T23b`; lo stop precede `ACT-T29` | ADD:2893, ADD:2894, ADD:2905 |
| Rifiuto di C3 per precondizione o invariante | `ACT-T31a` | ADD:2902 |
| Rifiuto di C3 per revisione, `GatePackage` o Governed Context | `ACT-T31b` | ADD:2903 |
| Altri rifiuti di C3 | `Q-A`; proposta: `ACT-T31b` | ADD:2903 |
| Invio senza risposta | `Q-I` | ADD:2901, ADD:2903 |

`ACT-T07` non si percorre mai: vale solo per un bersaglio non canonico (ADD:2866). `ACT-T14` vale per il bersaglio esterno (ADD:2875). `EMISSION-FENCE` è valutata immediatamente prima dell'invio a C3 (ADD:2854, LLD:256).

Nota di realizzazione, non normativa. Sul commit letto il motore di C6 offre già il percorso di un commit canonico deciso da un consumatore composto (SRC:c6/engine.py:1101).

## 6. Ruolo Fusion/Identity di C8

### 6.1 Output tipizzati

Il ruolo riceve Observation, Claim, Evidence e Source Identity filtrate dalla policy e produce `FusionIdentityFinding@1`, `CandidateMatchSet@1` e `ResolutionProposal@1`, con incertezza e provenance (ADD:3059). Non esegue merge canonici e non adjudica (ADD:3059). I suoi output sono non autorevoli: non concedono Authority e non diventano asserzioni canoniche senza il percorso governato (ADD:3116). Il ruolo opera entro i tier del PoC e non possiede `approve` (ADD:3115). Ogni output viaggia in un `HandoffEnvelope` (ADD:3069) e ogni handoff attraversa il Kernel (ADD:3042).

La norma nomina i tre output e chiede che portino incertezza e provenance; non ne elenca i campi. È il quesito `Q-G`. Sono ancorati soltanto: la presenza di incertezza e provenance in ciascuno (ADD:3059); il contenuto di `CandidateMatchSet@1`, che è un insieme di `CandidateMatch` con le loro `MatchEvidence` (ADD:2010, ADD:2011). Proposta:

1. `CandidateMatchSet@1`: `record_type`, `matcher_pin`, `input_source_identity_refs` (1..*), `candidate_matches` (0..*, record `CandidateMatch`), `match_evidence` (0..*, record `MatchEvidence`), `uncertainty`, `provenance_refs` (1..*);
2. `FusionIdentityFinding@1`: `record_type`, `finding_ref`, `subject_source_identity_refs` (1..*), `candidate_match_refs` (0..*), `claim_refs` (0..*), `evidence_refs` (0..*), `uncertainty`, `provenance_refs` (1..*);
3. `ResolutionProposal@1`: `record_type`, `resolution_proposal_ref`, `proposed_outcome` (`MERGE` oppure `SPLIT`), `source_identity_refs` (1..*), `candidate_match_refs` (0..*), `canonical_entity_ref` (1), `reverses_decision_ref` (0..1, obbligatorio per `SPLIT`), `evidence_refs` (1..*), `uncertainty`, `provenance_refs` (1..*);
4. `uncertainty` è l'oggetto `Uncertainty` del contratto del gateway (ADD:1158).

Un `ResolutionProposal@1` non è eseguibile. Diventa un'azione solo quando un Principal autorizzato la sottopone a C6 come proposta di uno dei tipi della sezione 5 (ADD:287, ADD:3123). Finché `Q-B` non è decisa non esiste un tipo d'azione per `NO_MATCH`, e il ruolo non lo propone.

### 6.2 Port del matcher

1. Il matcher sta dietro un port del ruolo Fusion/Identity, chiamato qui `IdentityMatcherPort`, così che un altro matcher possa sostituirlo senza cambiare record né decisioni (decisione, punto 3, «Attuazione»).
2. Ingresso: le Source Identity da confrontare, già filtrate dalla policy per il Governed Context della chiamata (ADD:3059), e il pin del matcher. Uscita: un `CandidateMatchSet@1`.
3. Il port non ha accesso a datastore né a C3: il ruolo interagisce solo attraverso Kernel, Gateway e contratti tipizzati (ADD:3042). Non espone identificativi di backend (LLD:415).
4. Il matcher non scrive membership, non adjudica e non conosce le decisioni (ADD:3059).
5. Prima della decisione su G7 sono esclusi un matcher probabilistico e ogni estrazione da documenti; non si aggiungono dipendenze (decisione, punto 3, «Attuazione»).

### 6.3 Matcher deterministico per le fixture sintetiche

La decisione chiede un matcher deterministico, con versione fissata, per le sole fixture sintetiche (decisione, punto 3) e non ne fissa l'algoritmo: è il quesito `Q-F`. Le proprietà seguenti sono ancorate e valgono qualunque sia la risposta:

1. **Determinismo.** A parità di ingresso e di pin, i record `CandidateMatch` e, in ogni `MatchEvidence`, i campi `candidate_match_ref`, `feature_ref`, `method_ref`, `stance`, `assessor_pin`, `score_semantics` e `content_digest` sono identici byte per byte nella forma canonica (LLD:37). I campi che dipendono dall'esecuzione, cioè `acquired_at`, `acquirer_principal_id`, `chain_of_custody`, `retention_until` e la provenance dell'insieme, sono fuori da questa garanzia: ogni agente ha un'identità distinta per istanza e per run (ADD:3114).
2. **Pin.** Il `matcher_pin` identifica algoritmo, versione e configurazione; ogni `CandidateMatch` e ogni `MatchEvidence` lo riporta (ADD:2010, ADD:2011, ADD:2059).
3. **Ambito.** Si usa solo sul dataset sintetico versionato, la cui ground truth delle identità sta in un oracolo separato e non accessibile al runtime (REG:66).
4. **Semantica dello score.** `score_semantics` è uno dei valori di ADD:1178; `VECTOR_SIMILARITY` e `HYBRID_RANK` non sono disponibili nel profilo del PoC (ADD:1362).

Proposta per `Q-F` (matcher `urn:ocor:matcher:feature-agreement`, versione `1.0.0`):

1. **Ingresso.** Per ogni Source Identity il record chiuso `{source_identity_ref, entity_type_id, features}`, dove `features` associa a ogni `feature_ref` un valore JSON scalare.
2. **Configurazione e pin.** La configurazione è il record chiuso `{matcher_id, version, entity_type_id, feature_refs}`. Nel pin, `resource_id` e `semantic_version` sono `matcher_id` e `version`; `artifact_digest` è il digest della configurazione; `contract_digest` è il digest del record chiuso che elenca i campi dell'ingresso e il nome dell'output.
3. **Confronto.** Per ogni coppia non ordinata di Source Identity con l'`entity_type_id` della configurazione, e per ogni caratteristica, l'esito è `SUPPORTS` se i due valori sono presenti e uguali come valori JSON, `REFUTES` se sono presenti e diversi, `NEUTRAL` se ne manca almeno uno. Nessuna normalizzazione.
4. **Emissione.** Si emette un `CandidateMatch` per la coppia se almeno un esito è `SUPPORTS`; solo per le coppie emesse si emette un `MatchEvidence` per caratteristica, così che ME-1 valga.
5. **Score.** Numero di `SUPPORTS` diviso per la somma di `SUPPORTS` e `REFUTES`; `score_semantics` vale `MATCH_CONFIDENCE`. È una quota di accordo, non una probabilità.
6. **Riferimenti e contenuto.** `candidate_match_ref` è `urn:ocor:candidate-match:` seguito dalle 64 cifre esadecimali dello SHA-256 della forma canonica di `{matcher_pin, source_identity_refs}`. Il `content_digest` di una `MatchEvidence` è il digest del record chiuso `{candidate_match_ref, feature_ref, method_ref, stance, assessor_pin, score_semantics}`.
7. **Incertezza.** `uncertainty` dell'insieme ha `semantics = QUALITATIVE_SCALE` e `value = {scale_id, level}`, con `scale_id` `urn:ocor:scale:match-agreement` e `level` `CONTRADICTED` se almeno un `MatchEvidence` dell'insieme è `REFUTES`, altrimenti `UNCONTRADICTED`.

### 6.4 Conservazione e lettura di Claim e candidati

ADD v1.3 chiede che i `CandidateMatch` non adjudicati restino rappresentabili e interrogabili (ADD:2053) e colloca Claim ed Evidence in record di evidenza e provenance, senza promozione automatica (ADD:148). Non dice quale componente conserva le Claim non ancora ammesse, i `CandidateMatch` e le `MatchEvidence`, da quale registro C3 risolve una Claim, per quale via i candidati arrivano al gateway, né chi verifica ME-1 alla ricezione. È il quesito `Q-H`. Proposta:

1. Claim e insiemi di candidati entrano dal confine di ingestione, come envelope con `semantic_class = CLAIM` (ADD:595); il payload è validato contro il proprio schema, che distingue una Claim da un insieme di candidati, e un fallimento produce una `Violation` e la quarantena (ADD:529). ME-1 e la chiusura dei record si verificano lì.
2. I record ammessi dal confine stanno in un registro di evidenza e provenance. C3 vi risolve Claim ed Evidence e confronta `proposition_ref` e `world_ref` con quelli della Claim; il gateway lo legge attraverso `EvidenceReadPort` (LLD:113).
3. In `NCP-U15` pubblica gli envelope il producer della fixture sintetica. La pubblicazione da parte di un ruolo d'agente in un run governato richiede uno strumento dietro un Tool Contract (ADD:3042) e resta fuori dall'unità.
4. ADD:849 elenca ciò che un payload può creare e non nomina `CandidateMatch`: la proposta chiede al PO di confermare che un insieme di candidati viaggia come payload di classe `CLAIM` con un proprio schema.

## 7. Visibilità in lettura

I contratti delle sei query nominate non cambiano (LLD:28, REG:177). Le identità candidate arrivano nei risultati attraverso campi che il contratto del gateway ha già.

1. **Dove.** `ObjectSnapshot.identity_candidates` è un campo obbligatorio di ogni oggetto servito (ADD:1202, ADD:1225). Ogni elemento è un `IdentityCandidate` con `candidate_ref`, `score`, `score_semantics` e `adjudication_status` (ADD:1173); `candidate_ref` è un `ResourceRef` (ADD:1175, ADD:987).
2. **Che cosa contiene.** Da dove il gateway legge i candidati e come li mette nel campo fa parte di `Q-H`; lo stato che serve fa parte di `Q-L`. Proposta: per ogni `CandidateMatch` che comprende la Source Identity dell'oggetto servito e che il chiamante è autorizzato a vedere, il campo ha un elemento per ciascuna delle altre Source Identity del candidato, con il suo `ResourceRef`, lo `score` e la `score_semantics` del `CandidateMatch` e lo stato della sezione 3.4.
3. **Nessun appiattimento.** Una identità candidata non adjudicata non è fusa nel risultato e non implica appartenenza al cluster canonico (ADD:1171). Conflitti e identità candidate non si appiattiscono (REG:58): due oggetti candidati restano due oggetti, ciascuno con i propri claim ed evidenze.
4. **Stato di verità.** `epistemic_status` distingue ciò che è canonico da ciò che è solo asserito, contestato, non adjudicato o ritirato (ADD:1152). Un oggetto con claim incompatibili li conserva entrambi (ADD:2053).
5. **Provenance.** `GetProvenance` restituisce il lineage filtrato dalla policy (ADD:866): decisioni e membership vi compaiono come nodi, secondo policy.
6. **Policy.** Una lettura non rivela nodi, archi, cardinalità o ragioni di diniego non autorizzati; le redazioni sono dichiarate (ADD:2055, ADD:1141). Un Principal non autorizzato riceve una spiegazione sicura rispetto alla policy, senza fughe di informazione (REG:58).
7. **Tempo.** La vista a un commit preciso si chiede con `EXACT_AT_COMMIT`; se non è servibile la risposta è un errore tipizzato, mai una vista diversa (ADD:3442, LLD:126).

Nota di realizzazione, non normativa. Sul commit letto il gateway restituisce `identity_candidates` sempre vuoto (SRC:c2/gateway.py:591).

## 8. Concorrenza ed errori

### 8.1 Ordine e ripetizione

1. C3 serializza i commit per aggregate e usa la revisione ottimistica (LLD:354). Due decisioni concorrenti sullo stesso aggregate con la stessa `expected_revision`: una è scritta, l'altra riceve `REVISION_CONFLICT` (LLD:132) e la sua azione termina in `INVALIDATED` con `ACT-T31b` (ADD:2903).
2. Un'azione invalidata non si ripresenta con le stesse approvazioni: ogni variazione materiale invalida le Approval, e un cambiamento di stato fa rieseguire il gate (ADD:3334).
3. Lo stesso comando con la stessa chiave di idempotenza restituisce la receipt originale; la stessa chiave con contenuto diverso produce `IDEMPOTENCY_CONFLICT` (LLD:97). Un retry è ammesso solo prima dell'effetto o con idempotenza comprovata (LLD:354).
4. Gli eventi di un aggregate sono consumati in ordine; i watermark sono monotoni; la deduplica è durevole (LLD:355, LLD:148).
5. Timeout del piano di controllo, schema sconosciuto, firma non valida, marking ambiguo o Authority mancante sono un diniego permanente per la singola operazione, non un retry permissivo (LLD:359).
6. Uno stop accettato prima dell'emissione impedisce l'invio a C3 (ADD:2905).

### 8.2 Conflitti fra decisioni sullo stesso insieme

| Situazione | Esito | Ancora |
|---|---|---|
| Split di un merge già invertito | `PRECONDITION_FAILED` | ADD:2569, ADD:2014 |
| Commit che chiude una membership non in vigore | `PRECONDITION_FAILED` | ADD:2569, ADD:2051 |
| Membership la cui decisione generatrice non è il record di decisione aggiunto dallo stesso commit | `INVARIANT_VIOLATION` | ADD:2569, ADD:2059 |
| Due merge concorrenti sulla stessa Canonical Entity | uno scritto, l'altro `REVISION_CONFLICT` | LLD:132 |
| Split che non chiude tutte le membership in vigore del merge invertito, o che ne chiude una di un altro merge | `Q-C`; proposta: `PRECONDITION_FAILED` | ADD:2569 |
| Due merge concorrenti che assegnano la stessa Source Identity a due Canonical Entity diverse | `Q-C`; proposta: uno scritto, l'altro `PRECONDITION_FAILED` | ADD:2569 |
| Riesecuzione del matcher sugli stessi input e con lo stesso pin | `Q-F`; proposta: gli stessi riferimenti, nessun candidato nuovo | sezione 6.3 |

Il secondo caso concorrente riguarda due aggregate diversi, che la revisione ottimistica non mette in ordine (LLD:354): con la proposta di `Q-C` lo risolve una constraint unica nella stessa transazione locale, come per l'idempotenza (LLD:97).

### 8.3 Errori che non sono rifiuti

Un invio a C3 che non riceve né una receipt né un rifiuto non è un successo e non è un fallimento: l'azione resta in `CANONICAL_COMMIT_PENDING` (sezione 1.9, `Q-I`). Il ritiro o il ricalcolo delle derivazioni non fa parte del commit canonico: un projector indisponibile lascia la proiezione indietro rispetto allo split, e le letture che chiedono il commit dello split ricevono `PROJECTION_NOT_READY` o `STALE_CONTEXT` (ADD:3445); il commit canonico resta valido (ADD:272).

## 9. Oracolo di accettazione (allegato non normativo)

Questo allegato descrive, per ciascun criterio del punto 3 della decisione, la fixture e l'esito atteso. Non aggiunge regole: ogni esito atteso rimanda alla sezione che lo fonda. I test stanno in un modulo nuovo, partono rossi, usano i backend reali e non saltano (decisione, punto 3, «Attuazione»). Gli oracoli leggono i dati in modo indipendente dal codice sotto prova. Dove un esito dipende da un quesito, l'atteso indicato è quello dell'opzione raccomandata ed è marcato.

### 9.1 Fixture `ID-FX-1`

Tutti i valori sono inventati. La fixture ha manifest, seed e hash degli artefatti, e la sua ground truth sta in un oracolo che il runtime non legge (REG:66). Tipi di aggregate, riferimenti e revisioni sono dati della release della fixture, non regole.

| Elemento | Valore |
|---|---|
| Contesto | tenant `urn:ocor:tenant:synthetic`; un compartimento, `urn:ocor:compartment:alpha`; world `urn:ocor:world:main` |
| Tipi di entità | `urn:ocor:type:person`, `urn:ocor:type:organisation` |
| Istante di validità `T0` | `2026-01-01T00:00:00Z`; è il `valid_time.from` di asserzioni, decisioni e membership, con `to` uguale a `null` |
| Fonti | `urn:ocor:source:registry-a`, `urn:ocor:source:registry-b` |
| `S1` | persona, `urn:ocor:source-identity:registry-a:p-001`; `name` «Mario Rossi», `birth_date` `1980-01-01` |
| `S2` | persona, `urn:ocor:source-identity:registry-b:p-777`; `name` «Mario Rossi», `birth_date` `1980-01-01` |
| `S3` | persona, `urn:ocor:source-identity:registry-b:p-778`; `name` «Mario Rossi», `birth_date` `1975-06-30` |
| `X`, `Y`, `Z` | organizzazioni, `urn:ocor:source-identity:registry-b:o-9`, `urn:ocor:source-identity:registry-b:o-10`, `urn:ocor:source-identity:registry-b:o-11` |
| Claim | per `n` da 1 a 6, `claim_ref` `urn:ocor:claim:k<n>`, `proposition_ref` `urn:ocor:proposition:k<n>`, evidenza `EV<n>` |
| `K1` | soggetto `S1`, `residence_city` «Roma», fonte `registry-a` |
| `K2` | soggetto `S2`, `residence_city` «Milano», fonte `registry-b` |
| `K3` | soggetto `S3`, `residence_city` «Napoli», fonte `registry-b` |
| `K4` | soggetto `S2`, `linked_to` `X`, fonte `registry-b` |
| `K5` | soggetto `S1`, `linked_to` `Y`, fonte `registry-a` |
| `K6` | soggetto `S2`, `linked_to` `Z`, fonte `registry-b` |
| Evidenza dello split | `EV7`, una rettifica del registro B |
| Persone | proponente `urn:ocor:principal:analyst-1`; approvatore `urn:ocor:principal:steward-1` con il ruolo `urn:ocor:role:identity-steward`; adjudicator `urn:ocor:principal:adjudicator-1` |
| Aggregate delle ammissioni | tipo `urn:ocor:aggregate-type:source-identity-record`, riferimento uguale alla Source Identity soggetto; revisioni attese: `K1` su `S1` da 0, `K2` su `S2` da 0, `K3` su `S3` da 0, `K4` su `S2` da 1, `K5` su `S1` da 1, `K6` su `S2` da 2 |
| Canonical Entity | `E1`, `urn:ocor:canonical-entity:person:e-0001`; `E2`, `urn:ocor:canonical-entity:person:e-0002` |
| Aggregate delle decisioni, con la proposta di `Q-C` | tipo `urn:ocor:aggregate-type:canonical-entity`, riferimento uguale alla Canonical Entity; `E1` nasce con il merge, da revisione 0; lo split parte da revisione 1 |
| Ingresso del matcher | `S1`, `S2`, `S3`; `X`, `Y` e `Z` non sono ingresso |
| Configurazione del matcher, con la proposta di `Q-F` | `entity_type_id` `urn:ocor:type:person`; `feature_refs` `urn:ocor:feature:person:birth-date` e `urn:ocor:feature:person:name` |
| Regola del link | la proiezione attribuisce a una Canonical Entity i link `linked_to` delle Source Identity che ne sono membri |
| `DerivedDefinition` | `urn:ocor:derived:person:residence-cities`: l'insieme ordinato dei valori `residence_city` delle asserzioni canoniche delle Source Identity membri di una Canonical Entity |
| Ground truth dell'oracolo | `S1` e `S2` sono la stessa persona, `S3` è un'altra; dipendono dal merge di `S1` e `S2` in `E1` esattamente `DL`, `DI` e `DL5` |

`S1`, `S2` e `S3` sono omonimi. `K1` e `K2` si contraddicono se `S1` e `S2` sono la stessa persona. Con la proposta di `Q-F` il matcher produce tre `CandidateMatch`: `CM12` fra `S1` e `S2` con score `1.0`; `CM13` fra `S1` e `S3` e `CM23` fra `S2` e `S3` con score `0.5`; sei `MatchEvidence`. I digest del pin li calcola l'unità sugli artefatti che pubblica; il manifest della fixture li riporta e il test li confronta.

### 9.2 Criterio (a): record con insieme chiuso di campi

Per ogni record delle sezioni 1.3 e 2.1-2.6, e per gli output della sezione 6.1 una volta decisa `Q-G`: il test costruisce un'istanza valida e verifica che l'insieme dei campi sia esattamente quello della tabella; poi verifica che un campo in più, un campo in meno e un alias siano rifiutati (sezione 0.3, punto 1).

### 9.3 Criteri (b) e (c): candidati separati, poi merge e split

Passi e attese. Ogni azione è proposta da `analyst-1`, approvata da `steward-1` e decisa da `adjudicator-1`.

1. **Ammissioni.** `K1`, `K2`, `K3` e `K4` sono ammesse con il tipo d'azione di ammissione: nascono quattro Canonical Assertion `A1`, `A2`, `A3`, `A4`, ciascuna con `accepted_from_claim`, `valid_time.from` uguale a `T0` e `system_time.from` uguale all'istante del proprio commit (sezione 1.8).
2. **Prima di ogni adjudication di identità (criterio b).** Il matcher ha prodotto `CM12`, `CM13` e `CM23`. Nello stato canonico non esiste alcuna `ClusterMembershipAssertion` e nessuna proiezione contiene un fatto che unisca due delle tre Source Identity. `A1` e `A2` restano asserzioni su due soggetti distinti, e `K1` e `K2` due Claim distinte. Con la proposta di `Q-L` lo stato di ciascun candidato è `UNADJUDICATED`. Con la proposta di `Q-H`: la lettura di ciascuno dei tre oggetti restituisce un oggetto distinto, con gli altri due in `identity_candidates` e `score_semantics` `MATCH_CONFIDENCE`.
3. **Merge.** Un'azione di merge su `E1`, con `expected_revision` 0, `source_identity_refs` `[S1, S2]`, le membership `M1` (`S1`, `E1`) e `M2` (`S2`, `E1`) valide da `T0` e, come `evidence_refs`, le due `MatchEvidence` di `CM12`, è scritta nel commit `Cm`. Atteso allo stato di `Cm`: un `MergeDecision` `Dm` con `outcome` `MERGE`, `adjudicator_principal_id` `adjudicator-1`, il razionale della `Decision`, `evidence_set_digest` calcolato con IRD-2 e `memberships_created` `[M1, M2]`; `M1` e `M2` in vigore con `generating_decision_ref` `Dm` e `system_time.from` uguale all'istante di `Cm`. Con la proposta di `Q-L`: `CM12` è `ACCEPTED`; `CM13` e `CM23` sono `UNADJUDICATED`.
4. **Derivazioni.** Dopo la proiezione di `Cm` esistono `DL`, il link fra `E1` e `X` ottenuto da `A4` attraverso `M2`, e `DI`, il valore `["Milano", "Roma"]` della `DerivedDefinition` per `E1`, ottenuto da `A1` e `A2` attraverso `M1` e `M2`. La provenance di ciascuna cita le membership usate (sezione 4.2).
5. **Split di una membership inesistente, caso negativo.** Uno split con `reverses_decision_ref` `Dm` e `memberships_ended` `[M1, M2, M9]`, dove `M9` non esiste, è rifiutato da C3 con `PRECONDITION_FAILED` e non scrive nulla (sezione 2.7).
6. **Split parziale, caso negativo.** Con la proposta di `Q-C`: uno split con `reverses_decision_ref` `Dm`, `memberships_ended` `[M2]` e `source_identity_refs` `[S2]` è rifiutato da C3 con `PRECONDITION_FAILED` e non scrive nulla (SD-1).
7. **Proposta dello split e derivazione tardiva.** Si propone uno split con `expected_revision` 1, `reverses_decision_ref` `Dm`, `memberships_ended` `[M1, M2]`, `source_identity_refs` `[S1, S2]`, `evidence_refs` `[EV7]` e `impacted_derivations` che elenca la sola `DL`. Dopo la proposta e prima dell'approvazione si ammette `K5`: nasce `A5` e, nella proiezione, `DL5`, il link fra `E1` e `Y` ottenuto attraverso `M1`.
8. **Split.** Lo split del passo 7 è approvato, deciso `ACCEPT` e scritto nel commit `Cs`. Atteso allo stato di `Cs`: uno `SplitDecision` `Ds` con `outcome` `SPLIT`; `M1` e `M2` con `system_time.to` uguale all'istante di `Cs`; `Dm` ancora presente. Con la proposta di `Q-L`: `CM12` è `SPLIT`.
9. **Due viste bitemporali (criterio c).** Per l'istante di validità `T0`: lo stato registrato da C3 per `Cm` mostra `S1` e `S2` membri di `E1`; lo stato registrato per `Cs` non mostra alcuna membership in vigore. Per un istante di validità precedente a `T0`, nessuno dei due stati mostra membership. Tutte le letture sono possibili dopo `Cs` (sezione 3.5).
10. **Derivazioni dopo lo split (criterio c).** Una lettura con watermark uguale o successivo a `Cs` non mostra in vigore `DL`, `DI` né `DL5`, benché lo split elencasse solo `DL`, e non mostra in vigore alcuna derivazione il cui lineage passi per `M1` o `M2`; le derivazioni attese come dipendenti sono quelle della ground truth (sezione 4.3). `A4` e `A5` restano in vigore: sono asserzioni canoniche, non derivazioni. Con la proposta di `Q-E`: ciascuna delle tre ha un segno di ritiro che cita `Ds` e `Cs`, e una proiezione ricostruita da zero dà lo stesso risultato.
11. **Consegna fuori ordine (criterio c).** Dopo `Cs` si ammette `K6`, nel commit `C6`. Il test consegna a un projector l'evento di `C6` prima di quello di `Cs`. Atteso: a nessun watermark uguale o successivo a `Cs` esiste in vigore un link fra `E1` e `Z` (sezione 4.3, punto 3).

### 9.4 Criterio (d): nessun effetto senza decisione accettata

I casi da 2 a 5 inviano a C3, sul percorso governato e con Decision e Authority validi, comandi che superano ogni passo precedente a quello indicato.

1. `CM13` non ha alcuna decisione. Atteso dopo `Cm`: nessuna membership riguarda `S3`; nessuna proiezione attribuisce a `S1` un'asserzione di `S3` o viceversa; nessuna derivazione ha `CM13` nel proprio lineage (invariante CM-1).
2. Membership generata da un candidato. Prima di `Cm`, un comando di merge su `E2` con `expected_revision` 0 e delta `{decision, memberships}`: la decisione è un `MergeDecision` valido con `source_identity_refs` `[S1, S3]` e `memberships_created` `[M3, M4]`; `M3` (`S1`, `E2`) ha `generating_decision_ref` uguale al riferimento di `CM13`, `M4` (`S3`, `E2`) quello della decisione. Atteso: rifiuto al passo T4 con `INVARIANT_VIOLATION`; revisione, commit, outbox e binding invariati (invariante CMA-1).
3. Membership generata da una decisione vecchia. Dopo `Cm`, un comando di merge su `E1` con `expected_revision` 1: la decisione è un `MergeDecision` valido con `source_identity_refs` `[S3]` e `memberships_created` `[M5]`; `M5` (`S3`, `E1`) ha `generating_decision_ref` `Dm`. Atteso: `INVARIANT_VIOLATION` (invariante CMA-1).
4. Membership senza decisione. Un comando inviato a `CommitAggregate` il cui delta contiene una membership e nessun record di decisione. Atteso: rifiuto al passo V9, con il reason code di `Q-A`, e nessuna scrittura (sezione 2.7).
5. Membership sul port di ammissione. Un comando inviato ad `AdmitClaim` il cui delta contiene una membership. Atteso: come il caso 4.
6. Sonda di mutazione. Tolto il controllo dell'invariante CMA-1, i casi 2 e 3 devono fallire: se il test resta verde, non prova nulla.

### 9.5 Criterio (e): ammissione senza Decision e Authority validi

Per `K1`, un comando di ammissione per ciascuno di questi difetti: Decision non risolvibile; Decision non firmata; Decision con esito diverso da `ACCEPT`; Decision scaduta; Authority non risolvibile; Authority scaduta; Decision o Authority legata a un altro `GatePackage`. Atteso per ogni caso: C3 rifiuta con il reason code della sezione 1.5; nessuna riga nuova in stato canonico, commit, idempotenza, outbox e binding delle fonti; revisione dell'aggregate invariata. Per l'ultimo caso il codice è `GATE_PACKAGE_MISMATCH` e l'azione termina con `ACT-T31b`; per gli altri codice e transizione dipendono da `Q-A`. Il criterio asserisce il codice che C3 restituisce.

### 9.6 Criterio (f): ogni esito è registrato

Sulla stessa fixture si producono: le ammissioni, il merge `Dm` e lo split `Ds` del 9.3; un'azione di merge su `S1` e `S3` che `adjudicator-1` rifiuta; un'azione di merge la cui approvazione è rifiutata da `steward-1`; un'azione di merge la cui approvazione scade; il caso 2 del 9.4, rifiutato da C3. Atteso: per ciascun esito esiste il record indicato nella tabella della sezione 3.6, e da esso si leggono chi ha deciso, o che nessuna persona ha deciso, il razionale o il reason code, e la versione dell'insieme di evidenze. I record `NO_MATCH` e `DEFERRED`, e lo stato `REJECTED` di `CM13`, si verificano quando `Q-B` è decisa e realizzata.

## 10. Tabella di tracciabilità

| Elemento | Sezione | Ancora |
|---|---|---|
| Port `AdmitClaim` e modulo che lo serve | 1.1 | ADD:284 |
| Invocazione solo da C6 in `ACT-T29` | 1.1 | ADD:2900, LLD:302, ADD:342 |
| Un solo comando mutativo | 1.2 | LLD:85, LLD:88-94 |
| Profilo di ammissione: una sola Claim, evidenze obbligatorie | 1.2 | ADD:2048, ADD:2765, ADD:2179, ADD:2565 |
| Record `CanonicalAssertion` e suoi campi | 1.3 | ADD:2003, ADD:2005, ADD:2052 |
| Nessuna promozione implicita | 1.3 | ADD:2048, REG:175 |
| Ordine delle validazioni prima della transazione | 1.4 | LLD:97 |
| Regola su Decision e Authority | 1.4 | ADD:342 |
| Revisione prima e dentro la transazione; ordine nella transazione | 1.4 | LLD:97, LLD:132, REG:186; il resto: `Q-A` |
| Fence di mutazione | 1.4 | ADD:3430, ADD:3443, ADD:3448-3458; che cosa, dove e con quale codice: `Q-A` |
| `REVISION_CONFLICT`, `PRECONDITION_FAILED`, `INVARIANT_VIOLATION`, `GATE_PACKAGE_MISMATCH` | 1.5 | ADD:2569, LLD:132 |
| `IDEMPOTENCY_CONFLICT` | 1.5 | LLD:97 |
| `GOVERNED_CONTEXT_MISMATCH` | 1.5 | LLD:40, ADD:199, ADD:2903 |
| `MARKING_UNRESOLVED` | 1.5 | LLD:67 |
| Altri reason code e transizione | 1.5 | `Q-A` |
| Atomicità, outbox, binding delle fonti | 1.6 | LLD:97, LLD:139, LLD:141, LLD:142, ADD:293, ADD:3432 |
| Rapporto con `CommitAggregate` | 1.7 | ADD:342, LLD:85, LLD:132 |
| Invio senza risposta e retry | 1.9 | `Q-I`; ADD:297, ADD:2851, ADD:2854, ADD:2882, ADD:284, LLD:354 |
| Record `CandidateMatch` | 2.1 | ADD:2010, ADD:1178, ADD:1180 |
| Nessun effetto di un candidato non adjudicato | 2.1 | REG:335, ADD:2059 |
| Record `MatchEvidence` | 2.2 | ADD:2011, ADD:2006, ADD:2007 |
| Record `IdentityResolutionDecision` | 2.3 | ADD:2012, REG:176 |
| Valori di `outcome` e legame di `NO_MATCH` | 2.3, 3.1 | decisione, punto 4 |
| Digest dell'insieme di evidenze | 2.3 | ADD:2056, ADD:2006, LLD:37, LLD:39 |
| Campi derivati dalla `Decision` | 2.3 | ADD:2871, ADD:2850, ADD:197, LLD:41; chi li scrive: `Q-K` |
| Record `MergeDecision` | 2.4 | ADD:2013 |
| Struttura di `reversibility` | 2.4 | `Q-D` |
| Record `SplitDecision` | 2.5 | ADD:2014, ADD:2051 |
| Record `ClusterMembershipAssertion` | 2.6 | ADD:2015, ADD:2051, ADD:2052 |
| Membership solo con la propria decisione, nello stesso commit | 2.6, 2.7 | ADD:2059, REG:335, ADD:2569 |
| Aggregate, esclusività, limiti di merge e split, inversione completa | 2.4, 2.5, 2.6 | `Q-C` |
| Passo e reason code di ogni regola | 2.7 | ADD:2569, LLD:97 |
| Chi scrive merge e split | 3.2 | ADD:342, ADD:2789 |
| Registrazione di `NO_MATCH` e `DEFERRED` | 3.2 | `Q-B`; ADD:2052, ADD:426, ADD:2144-2148, ADD:2059 |
| Delta delle membership in un solo commit | 3.3 | LLD:85, LLD:97, ADD:2013, ADD:2014, REG:335 |
| Binding Claim/source vuoto per merge e split | 3.3 | ADD:2765, ADD:2128, ADD:2565 |
| Stato di adjudication di un candidato | 3.4 | `Q-L`; ADD:1180, ADD:1171, REG:335 |
| Reversibilità | 3.5 | ADD:2051, ADD:2564, REG:120, REG:336, ADD:2745 |
| Registrazione di ogni esito | 3.6 | REG:176, ADD:2862, ADD:2864, ADD:2868, ADD:2869, ADD:2870, ADD:2871, ADD:2874, ADD:2902, ADD:2903 |
| Propagazione dell'incertezza e blocco | 3.7 | REG:65, ADD:3059, ADD:3060, ADD:3110, ADD:3123, ADD:2873 |
| Derivazione dipendente, obbligo di provenance, individuazione | 4.1, 4.2 | REG:333, ADD:2057, ADD:2015, ADD:2017, ADD:2050 |
| Garanzia dopo la chiusura di una membership | 4.3 | ADD:3432, ADD:3433, ADD:3434, ADD:3441, ADD:3445, LLD:148, ADD:848, REG:336 |
| Ritiro o ricalcolo: regola, ambito, forma, lettura | 4.3, 4.4 | `Q-E`; ADD:2051, ADD:2057, ADD:2148 |
| Tre tipi d'azione e classi prodotte | 5.1 | ADD:2144-2148, ADD:2142, ADD:2789 |
| Valori del contratto fissati dalla norma | 5.2 | ADD:2364, ADD:2565, ADD:2376-2377, ADD:2564, ADD:2250, ADD:2563 |
| Valori del contratto lasciati aperti | 5.2 | `Q-J`; ADD:2365, ADD:2368, ADD:2283, ADD:2258, ADD:2249 |
| Precondizioni e invarianti dei tipi | 5.2 | ADD:2159, ADD:2163, ADD:2569 |
| Transizioni percorse | 5.3 | LLD:262-305, ADD:2860-2903 |
| Output del ruolo Fusion/Identity e divieti | 6.1 | ADD:3059, ADD:3116, ADD:3115 |
| Campi dei tre output | 6.1 | `Q-G` |
| Port del matcher | 6.2 | decisione, punto 3; ADD:3042, ADD:3059 |
| Matcher deterministico: determinismo, pin, ambito | 6.3 | decisione, punto 3; LLD:37, ADD:2010, ADD:1412-1417, REG:66 |
| Ingresso, algoritmo, score, incertezza, contenuto delle evidenze | 6.3 | `Q-F` |
| Conservazione e lettura di Claim e candidati | 1.4, 6.4 | `Q-H`; ADD:2053, ADD:148, ADD:849, LLD:113 |
| Identità candidate nelle letture | 7 | ADD:1202, ADD:1225, ADD:1173, ADD:1175, ADD:1171, REG:58 |
| Sei query nominate invariate | 7 | LLD:28, REG:177 |
| Policy e redazioni nelle letture | 7 | ADD:2055, ADD:1141 |
| Concorrenza per aggregate, retry, ordine | 8.1 | LLD:354, LLD:355, LLD:359, LLD:132, LLD:97 |
| Conflitti fra decisioni | 8.2 | ADD:2569, ADD:2051, ADD:2059; il resto: `Q-C` |

## 11. Rinviato a dopo la decisione su G7

Nulla di questa sezione si realizza in `NCP-U15`. È un elenco, senza specifica.

1. **Regola di non riapertura.** Finché una decisione `NO_MATCH` è in vigore, un candidato sullo stesso insieme di Source Identity con lo stesso digest dell'insieme di evidenze non si riapre e resta interrogabile come soppresso, con il riferimento alla decisione; un digest diverso lo riapre. `NCP-U15` definisce il record e gli esiti che la regola userà, non la regola (decisione, punto 4).
2. **Matcher probabilistico.** Un matcher probabilistico è un modulo sostituibile dietro il port della sezione 6.2, con le dipendenze soggette alla politica vigente (decisione, punto 6).
3. **Altre voci del punto 6 della decisione.** Il profilo «integration-ready» e il confine dell'acquisizione a monte non riguardano questo addendum.
