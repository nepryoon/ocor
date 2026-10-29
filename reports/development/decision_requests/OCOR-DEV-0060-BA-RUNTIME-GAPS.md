# OCOR-DEV-0060-BA-RUNTIME-GAPS

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Riguarda come qualificare `BA-03`, `BA-04`,
`BA-05` e `BA-06` in `OCOR-DEV-0060`, dato che parte delle proprietà richieste da ADD v1.3
Parte I §2.6 e dagli oracle di LLD v1.1 §7.1 non ha implementazione nel runtime. La scelta
tocca l'attivazione dei fallback di §2.6 (che `OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26)` ha escluso), lo standard di evidenza di `0060` e l'ordine della coda: è una
questione normativa. Autorità corrente: mandato `CC-OCOR-DELIVERY-COMPLETION` §5 e §7,
DEC-210/211, `OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26)`,
`REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION (2026-10-28)` punto 8.

## Contesto

Il 2026-10-29 è iniziata la fase di implementazione di `OCOR-DEV-0060` sul branch
`task/OCOR-DEV-0060-ba-campaign`, da `origin/main` `95257ce`, dopo l'integrazione delle
quattro remediation `REM-0038`–`REM-0041`. Prima della campagna ho scritto, sotto
`ocor-runtime/tests/conformance/ba/` (unica area ammessa dal backlog), un modulo per
ciascun `BA` con casi positivi, negativi e di fault sui backend reali dello stack
`ocor-bootstrap` (15 container), più un modulo strutturale che lega ogni modulo alle righe
normative. Le prove mostrano che il runtime non realizza alcune proprietà. Il task non
può aggiungere codice runtime: `expected_file_areas` contiene solo i test, e il mandato
(§5, punto 1) richiede un change set `governed/` separato per tutto il resto.

Non ho modificato codice runtime, contratti, schemi, harness, workflow, record sigillati o
allowlist. I moduli di test restano sul branch del task come lavoro in corso, non
integrato e non sigillato.

## Fatti

Esecuzione a `95257ce` sullo stack reale da shell pulita (`bootstrap_ci_environment.py
--execute`, Python 3.12.11 del lock). Per ogni lacuna riporto l'obbligo normativo e il
punto del codice che lo dimostra.

**`BA-06` — job ledger di `C7` assente.**

- Obbligo: ADD §2.6 riga `BA-06`, «job ledger con budget, progress e cancellation;
  rilascio risorse entro il target dichiarato», con il «test di cancellazione con verifica
  del rilascio». ADD §2.2 (riga 275): «job ledger PostgreSQL» è `CI` di `C7`. ADD §4.2:
  lifecycle `queued → running → paused | cancelled | completed | failed | expired`, e
  «Budget, quota, progress, cancellation, timeout e backpressure sono obbligatori». ADD
  §4.1.3: «Arresto job causale cancellato | rilascio risorse entro `PT30S`». LLD v1.1
  §6: «C7: job cancellabile con resource release e sealed result».
- Codice: in `ocor-runtime/src/ocor_runtime/c7/` e `c7_emission.py` non esiste alcun job,
  ledger, budget, progress o cancellation; `c7/runtime.py` è sincrono e senza stato.
  `REM-0040-C7-SEALED-RESULT-PORT-DISPOSITION` punto 8 assegna questa parte a
  `OCOR-DEV-0060` «sul PostgreSQL esistente», ma il task non ha codice runtime nel proprio
  perimetro.
- Coperto oggi su SeaweedFS 4.51 reale: immutabilità dopo `sealResult`, digest manomesso
  rifiutato, nuovo sigillo con contenuto diverso rifiutato, lineage e
  identify-or-abstain sigillati.

**`BA-05` — FSM a 44 transizioni non vincolata allo stato corrente.**

- Obbligo: LLD §7.1, «Temporal/PostgreSQL esegue le 44 transizioni, guardie, unknown e
  precedence». ADD §2.6 riga `BA-05`: semantica di `ACT-T14`, `ACT-T18`, `ACT-T19`,
  `ACT-T29`.
- Codice: `c6/fsm.py`, `GovernedActionFSM.apply` cerca la transizione e ne persiste
  l'effetto. Non conosce lo stato corrente dell'azione, non rifiuta una transizione la cui
  sorgente non è quello stato e non valuta le guardie testuali della tabella. Le sole
  guardie valutate dentro Temporal sono quelle di emissione
  (`c6/temporal_workflows.py`, `LeaseStateWorkflow.consume_if_current`: finestra, revoca,
  stop epoch, fencing token, consumo singolo).
- Coperto oggi su Temporal 1.32.1 reale: le 44 transizioni eseguite e persistite (tabella
  ricostruita dal server uguale al digest sigillato), rivalidazione all'emissione,
  precedenza dello stop, `EXECUTION_UNKNOWN` su timeout ambiguo senza cancellazione
  presunta, fencing del worker stale, consegna duplicata consumata una volta.

**`BA-03` — nessuna sandbox `EXACT_AT_COMMIT(Cn)` e nessun `UNSUPPORTED_CAPABILITY`.**

- Obbligo: ADD §2.6 riga `BA-03`, «Sandbox disposable per servire `EXACT_AT_COMMIT(Cn)`
  su query logiche nominate», con «Benchmark di creazione sandbox; test di esaurimento
  risorse; test negativo con emulazione indisponibile». ADD §3.3: con emulazione
  indisponibile il Gateway restituisce `UNSUPPORTED_CAPABILITY` e non degrada a
  `AT_LEAST_COMMIT`.
- Codice: `c4/typedb_adapter.py` serve solo il commit proiettato in quel momento; nessun
  file di `c2/` o `c4/` produce `UNSUPPORTED_CAPABILITY`. Una richiesta esatta per un
  commit precedente è rifiutata con `PROJECTION_NOT_READY` o `CONSISTENCY_DOWNGRADE`, mai
  servita con dati più recenti: l'oracle di LLD §7.1 («exact-at-commit o
  `PROJECTION_NOT_READY`, mai downgrade») è osservato, la sandbox e il reason code ADD no.
- Difetto collegato: `c2/ports.py`, `ConsistencyRequirement.verify_served`, rifiuta
  `AT_LEAST_COMMIT(Cn)` quando il watermark è oltre `Cn`, perché confronta per uguaglianza.
  ADD §3.3 e i criteri di `FR-057` prevedono che una proiezione oltre `Cn` serva
  at-least. Non è dichiarato né provato da alcun caso di `0060`.

**`BA-04` — nessuna validazione SHACL delle shape di §3.6 e nessun export watermark.**

- Obbligo: ADD §2.6 riga `BA-04`, round-trip RDF/JSON-LD/SHACL «ed export watermark
  correlabile al commit canonico», con «validazione SHACL delle shape di §3.6».
- Codice: `c4/jena_adapter.py` dichiara un controllo «SHACL-equivalent» (proprietà
  richieste e predicati chiusi) perché «no general SHACL» è disponibile; né `pyshacl` né
  un servizio SHACL di Fuseki sono configurati; nessun export watermark.
- Coperto oggi su Fuseki 6.2.0 reale: round-trip RDF/JSON-LD delle fixture canoniche,
  pubblicazione fuori profilo rifiutata senza scritture, marking join senza leakage di
  contenuto, conteggio o esistenza.

**Difetto osservato, fuori dai casi.** `c4/typedb_adapter.py`, `_write`: un `URLError` a
livello di connessione non chiude la transazione di scrittura; un payload di 16 MiB ha
lasciato una transazione aperta e TypeDB ha rifiutato la cancellazione del database fino
al timeout.

**Gli altri BA.** `BA-01` (TerminusDB 12.0.7: cinque crash window, writer stale, fork senza
`DeliveryAttempt`) e `BA-02` (TypeDB 3.12.3: lettori concorrenti, rollback atomico di
facts e watermark) sono coperti dai moduli senza lacune runtime. `BA-07` (Kafka 7.6.0: replay dalla
retention configurata con ordine per partizione e dedup, schema incompatibile in DLQ,
evento poison in quarantena, backpressure, broker fermato e riavviato) e `BA-08` (OPA,
Keycloak, SPIRE, OpenBao: decisione entro `policy_authority_timeout`, drill di stop con
ultimo command accettato prima dello stop e rifiuti fino a 10,75 s dopo, revoca e stop
epoch come meccanismi indipendenti, scadenza locale del lease con OPA in pausa, secret
isolation) sono coperti senza lacune runtime. Limiti da dichiarare nell'evidenza: per
`BA-07` broker singolo senza Strimzi né schema registry esterno (accettato dal PO) e
`NFR-073` legato a `OI-028`; per `BA-08` il gate che unisce decisione OPA e lease è
composto nel test con le parti sigillate, perché nessun componente runtime le unisce.

I moduli sono sul branch `task/OCOR-DEV-0060-ba-campaign`, commit WIP `43d9616`: 48 casi,
48 PASS sullo stack reale in 157 s, zero skip; RED a `95257ce` (cartella assente, pytest
exit 4).

## Opzioni

1. **Remediation governate del runtime previsto dal design approvato, poi la campagna `0060` completa.**
   - Change set `governed/` separati, ciascuno col primo `OCOR-DEV-REM-*` libero (oggi
     `REM-0043`), ciclo completo (inventario, RED sul backend reale, GREEN, riqualifiche,
     suite completa, verifica esterna, sigillo, merge), nell'ordine:
     - a. job ledger di `C7` su PostgreSQL: lifecycle di ADD §4.2, budget, quota, progress,
       cancellation, timeout e backpressure, rilascio delle risorse entro `PT30S`
       (ADD §4.1.3), dietro un port nuovo di `C7`, senza cambiare `c7/runtime.py`,
       `CausalOutcome`, contratti o schemi;
     - b. FSM di `C6` con stato corrente e guardie: rifiuto delle transizioni la cui
       sorgente non è lo stato corrente e valutazione delle guardie di LLD §3.2,
       eseguite e persistite nel workflow Temporal di `REM-0039`;
     - c. sandbox `EXACT_AT_COMMIT(Cn)` su TypeDB (database disposable ricostruito da `C3`
       al commit `Cn`) con `UNSUPPORTED_CAPABILITY` quando non è disponibile, correzione
       di `AT_LEAST_COMMIT` e chiusura della transazione di `_write`;
     - d. validazione SHACL delle shape di §3.6 su Jena (servizio SHACL di Fuseki 6.2.0,
       nessuna nuova dipendenza Python) ed export watermark correlato al commit canonico.
   - Poi `0060` qualifica gli otto `BA` senza fallback, riusando i moduli già scritti.
   - Impatto: quattro cicli completi prima di `0060`; nessuna nuova tecnologia; i port nuovi
     di a e b sono interni (nessun contratto pubblico). `0062`–`0064` proseguono intanto.
2. **Fallback di §2.6 dove la baseline li prevede, e remediation solo per il resto.**
   - `BA-03`: si attiva il fallback «Restringere `EXACT_AT_COMMIT` al solo
     `VersionedAssertedState` e restituire `UNSUPPORTED_CAPABILITY` sulle query logiche».
   - `BA-04`: si attiva il fallback «Boundary W3C come export batch offline non correlato a
     watermark, con staleness dichiarata e ruolo non interrogabile in linea».
   - `BA-05` e `BA-06`: remediation a e b dell'opzione 1 (per questi `BA` il fallback non
     copre la lacuna).
   - Impatto: due remediation invece di quattro; supersede in modo circoscritto
     «Nessun fallback di §2.6 è attivato» di `OCOR-DEV-0060-BA-SELECTED-COMPONENTS`;
     capacità ridotta per `EXACT_AT_COMMIT` sulle query logiche e per il boundary W3C.
3. **Campagna `0060` parziale ora, decisione rinviata.**
   - `0060` esegue e sigilla i casi coperti; le proprietà mancanti si registrano
     `NOT_EXECUTED`. Il task non entra in `completed_evidence_tasks` e `0065`–`0069`
     restano bloccati fino a una decisione successiva.
   - Impatto: una seconda campagna e una seconda verifica di `0060`.

## Raccomandazione

Opzione 1. Tutte le proprietà mancanti sono già specificate dal design approvato (ADD
§2.2, §3.3, §4.1.3, §4.2, §2.6; LLD v1.1 §3.2, §6, §7.1), quindi le remediation
completano il runtime senza nuove decisioni architetturali e senza ridurre capacità.
L'opzione 1 mantiene inoltre la decisione del 2026-10-26 di non attivare fallback e
qualifica `0060` in una sola campagna.

## Impatto e prossima azione

- Task bloccati da questa richiesta: `OCOR-DEV-0060` e, per dipendenza, `0065`–`0069`.
- Non bloccati: `OCOR-DEV-0062`, `0063`, `0064`. Il loop prosegue con `OCOR-DEV-0062`,
  il numero più basso del ready set.
- Il branch `task/OCOR-DEV-0060-ba-campaign` (commit `43d9616`) conserva i moduli scritti
  (WIP, non integrato, non sigillato, nessuna PR). Nessun codice runtime, contratto, schema, harness, workflow,
  record di evidenza o allowlist modificato. Nessun nuovo `DEC-*`. `E1=0`, `E2=0`,
  `Verified=0`, runtime `NOT_ESTABLISHED`, PoC/Production `NO-GO` invariati.
- Implementatori che hanno toccato `0060`: Claude Code (Anthropic, claude-opus-5-5).
