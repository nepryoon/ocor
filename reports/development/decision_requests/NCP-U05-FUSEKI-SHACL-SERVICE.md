# NCP-U05-FUSEKI-SHACL-SERVICE

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0052`
(NCP-U05 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, proiezioni C4; branch
`governed/ocor-dev-rem-0052-ncp-u05-c4-projections`, head di lavoro `5af48a95c91b2783adfcde0a350380394cf49a56`,
non candidato), voce `NCR-C4-002`. Aperta secondo il punto 6 («Stop») di
`NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`: la parte SHACL della voce richiede una modifica fuori dai
`code_paths` dell'unità e riqualifiche che il piano approvato non prevede. Implementatore: Claude Code
(Anthropic), implementatore di riserva del loop.

## Contesto

- Il punto 8 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` (riga 552 di
  `reports/development/decision_requests/NORMATIVE-CONFORMANCE-PLAN.md`) assegna a NCP-U05, per la lacuna
  `BA-04`, la «validazione SHACL delle shape di ADD §3.6 con il servizio SHACL di Fuseki» e l'«export watermark
  correlato al commit canonico» (voce `NCR-C4-002`). Le ancore: ADD v1.3 riga 357 (`BA-04`, «validazione SHACL
  delle shape di §3.6»), righe 1996-2059 (§3.6, shape minime nella riga 2059), LLD v1.1 riga 148 («Jena espone
  RDF/JSON-LD e SHACL con marking conservativo») e riga 370 (oracolo `BA-04`).
- Il `code_paths` di NCP-U05 nel piano approvato (`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json` al
  commit `4781e06de140f770ef0f61d9dab7a6c189cdf97b`, `plan_units.NCP-U05.code_paths`) comprende solo
  `ocor-runtime/src/ocor_runtime/c4/jena_adapter.py`, `rebuild.py` e `typedb_adapter.py`; le riqualifiche
  previste (`plan_units.NCP-U05.requalifications`) sono quelle di `OCOR-DEV-0005`, `0050`, `0082` e i candidati
  `OCOR-DEV-0037`, `0038`, `0039`.
- Fuseki dello stack di sviluppo e di CI parte con `CMD ["--mem", "/ocor"]` (`infra/fuseki/Dockerfile` riga 14;
  servizio `fuseki` di `deploy/bootstrap/compose.yaml` righe 38-50, senza `command`). Un dataset creato da riga
  di comando non espone l'operazione SHACL: sull'head `c392bb8` di `main`, con lo stack `ocor-bootstrap` attivo,
  `POST http://127.0.0.1:3030/ocor/shacl?graph=default` con una shape Turtle risponde `HTTP 405`. `fuseki-server
  --help` (Fuseki 6.2.0) non ha un'opzione che la aggiunga: serve un file di configurazione (`--config`) che
  dichiari l'endpoint `fuseki:shacl`.
- Prova di fattibilità, eseguita in sola lettura sul repository: un container temporaneo della stessa immagine
  `ocor/jena-fuseki:6.2.0` (identità locale invariata), avviato con `--config=<file>` che dichiara il servizio
  `ocor` in memoria con gli endpoint `sparql`, `query`, `update`, `data` (`gsp-rw`) e `shacl`, ha accettato la
  stessa `INSERT DATA` (`HTTP 204`) e ha restituito per `POST /ocor/shacl?graph=default` un `sh:ValidationReport`
  reale (`HTTP 200`, `sh:conforms false`, un `sh:MinCountConstraintComponent`). Il container è stato rimosso.
- Gli ultimi record di evidenza di `OCOR-DEV-0073`, `0074`, `0075`, `0077`, `0078` e `0079`
  (`reports/evidence/G2/OCOR-DEV-00NN.requalified-rem0038.json`) hanno fra gli input
  `deploy/bootstrap/compose.yaml`; quello di `OCOR-DEV-0075` anche `infra/fuseki/Dockerfile`; quelli di `0070`,
  `0073`-`0079`, `REM-0018`, `REM-0022` e `REM-0023` anche `infra/services.lock.json`. Una modifica di quei file
  fa derivare quei record (`scripts/validate_evidence_input_drift.py`) e richiede riqualifiche non previste dal
  piano.
- Il resto di `NCR-C4-002` (quarantena durevole consultata in lettura, rebuild dallo store canonico TerminusDB con
  checkpoint firmato e replay bounded, watermark Jena correlato al commit canonico, oggetto `marking` canonico al
  posto di `ocor_runtime.c4_marking` nel componente corrente, errori Jena tipizzati) non dipende da questa
  decisione e prosegue.

## Opzioni

1. **Configurazione Fuseki montata dallo stack (raccomandata).** NCP-U05 estende il proprio ambito a un nuovo
   file `deploy/bootstrap/fuseki/config.ttl` (servizio `ocor` in memoria con gli endpoint `sparql`, `query`,
   `update`, `data` e `shacl`, gli stessi nomi di oggi più `shacl`) e al servizio `fuseki` di
   `deploy/bootstrap/compose.yaml`, che lo monta in sola lettura e aggiunge
   `command: ["--config=/etc/ocor-fuseki/config.ttl"]`. Immagine, `infra/fuseki/Dockerfile`,
   `infra/services.lock.json` e controllo d'identità restano invariati; CI e stack locale usano lo stesso
   `compose.yaml`. L'adapter Jena valida con quell'endpoint le shape di ADD v1.3 riga 2059 prima di rendere
   visibile una pubblicazione. Effetto: riqualifiche di sola regressione, nella classe non qualificante di
   `REM-0046-REGRESSION-REQUALIFICATION-RECORDS (2026-10-30)`, di `OCOR-DEV-0073`, `0074`, `0075`, `0077`,
   `0078` e `0079` (input `deploy/bootstrap/compose.yaml`), con test invariati; una iterazione in più circa.
2. **Configurazione nell'immagine.** Il file di configurazione entra in `infra/fuseki/` e `infra/fuseki/Dockerfile`
   riga 14 passa a `CMD ["--config=/etc/ocor-fuseki/config.ttl"]`. Cambia l'identità dell'immagine: servono la
   riacquisizione governata dell'identità locale (`infra/fuseki/local_identity.lock.json`) e il nuovo
   `build.output_sha256` dell'entry `fuseki` di `infra/services.lock.json`, con le condizioni delle decisioni
   sull'identità dell'immagine Fuseki. Effetto: riqualifiche di sola regressione degli 11 task con
   `infra/services.lock.json` o `infra/fuseki/Dockerfile` fra gli input (`OCOR-DEV-0070`, `0073`-`0079`,
   `REM-0018`, `REM-0022`, `REM-0023`); più passi di supply chain dell'opzione 1 per lo stesso risultato.
3. **Validazione SHACL fuori da Fuseki.** Una libreria SHACL di processo (per esempio pySHACL) nell'adapter.
   Richiede una nuova dipendenza di runtime e una modifica di `uv.lock`, non ammesse dal punto 7 di
   `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, e non realizza il «servizio SHACL di Fuseki» del punto 8. Effetto:
   cambio della decisione sul piano.

**Raccomandazione**: opzione 1. Realizza esattamente il punto 8 della decisione sul piano con il servizio di
Fuseki già presente nell'immagine approvata, senza toccare immagine, lock dei servizi e controllo d'identità, e
con il numero minimo di riqualifiche, tutte di sola regressione.

## Impatto e task bloccati

- Bloccata solo la parte SHACL di `NCR-C4-002` e, di conseguenza, la chiusura di `OCOR-DEV-REM-0052` (record,
  candidato, verifica, sigillo, merge) e le unità successive di `plan_order`, che attendono NCP-U05.
- Nessun test, limite, soglia, gate, workflow, guard, contratto, schema o registro normativo cambia con una
  qualsiasi delle opzioni 1 e 2. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`,
  PoC e Production `NO-GO`.

## Disposition del Product Owner — 2026-11-05

Decisione del PO, su delega completa (`DELEGA-COMPLETA (2026-11-02)`), modello `claude-opus-5-5`, effort `xhigh`: `NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05)`, **opzione 1** (configurazione Fuseki montata dallo stack). Vale come decisione del PO a ogni effetto, di livello normativo. Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. La richiesta decisa è il file al commit `11c19d1ee4508c7be3ce1a949157c45856ed4494`, sha256 `48ece35469cb56177faee15d2efce2b8b9c45c20c115b428355bf6c0a1e7a537` (verificata prima dell'attuazione). Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05) — decisione del PO, su delega completa

Decisa su delega completa del PO secondo `DELEGA-COMPLETA (2026-11-02)`, con il modello `claude-opus-5-5` ed effort `xhigh` (scelta di `claude-opus-5-5` con effort `medium`, delicatezza ALTA). Il PO risolve la decision request `NCP-U05-FUSEKI-SHACL-SERVICE` (branch `governed/decision-request-ncp-u05-fuseki-shacl-service`, commit `11c19d1ee4508c7be3ce1a949157c45856ed4494`, file `reports/development/decision_requests/NCP-U05-FUSEKI-SHACL-SERVICE.md`, sha256 `48ece35469cb56177faee15d2efce2b8b9c45c20c115b428355bf6c0a1e7a537`) adottando l'**opzione 1**.

1. Applica le opzioni scelte esattamente come descritte nel file indicato, a quel commit. Se il file che leggi a quel commit non ha quello sha256, non applicarle e apri una decision request.
2. Se l'attuazione richiede di andare oltre quanto le opzioni scelte descrivono esplicitamente, fermati e apri una decision request: la deciderà la stessa delega.
3. Registra la disposition nel file della decision request, nel registro `blockers` di `EXECUTION_STATE.json` (`po_decision` uguale a questa decisione, con la nota «decisa su delega completa del PO, modello claude-opus-5-5, effort xhigh») e nell'`ITERATION_LOG.md`, con lo stesso trattamento di una decisione del PO. Vale come decisione del PO a ogni effetto, anche dove una regola chiede una decisione del PO non presa su delega.
4. Le altre decisioni e regole vigenti restano invariate, salvo quanto le opzioni scelte cambiano esplicitamente.
