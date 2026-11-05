# NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0052`
(NCP-U05 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, proiezioni C4; branch
`governed/ocor-dev-rem-0052-ncp-u05-c4-projections`, head di lavoro `437852a`, non candidato), voce
`NCR-C4-002`, parte SHACL. Aperta secondo il punto 6 («Stop») di `NORMATIVE-CONFORMANCE-PROGRAMME (2026-10-29)`
e il punto 2 della decisione `NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05)`: l'attuazione dell'opzione scelta
richiede la modifica di un validatore, che l'opzione non descrive. Implementatore: Claude Code (Anthropic),
implementatore di riserva del loop.

## Contesto

- La decisione `NCP-U05-FUSEKI-SHACL-SERVICE (2026-11-05)` ha scelto l'opzione 1 del file
  `reports/development/decision_requests/NCP-U05-FUSEKI-SHACL-SERVICE.md` (commit
  `11c19d1ee4508c7be3ce1a949157c45856ed4494`, sha256
  `48ece35469cb56177faee15d2efce2b8b9c45c20c115b428355bf6c0a1e7a537`): un nuovo file
  `deploy/bootstrap/fuseki/config.ttl`, montato in sola lettura dal servizio `fuseki` di
  `deploy/bootstrap/compose.yaml` con `command: ["--config=/etc/ocor-fuseki/config.ttl"]`.
- L'unità l'ha attuata sul branch di lavoro: RED `7a39c51`, GREEN `437852a`. Il file contiene la
  configurazione di Fuseki (assembler, RDF 1.1 Turtle) con il servizio `ocor` in memoria e gli endpoint
  `sparql`, `query`, `update`, `data` e `shacl`. Sullo stack locale ricreato con quel compose, i 68 casi
  SHACL del modulo `ocor-runtime/tests/tasks/test_ocor_dev_rem_0052.py` passano.
- Il gate `scripts/validate_language_policy.py`, bloccante in CI (`.github/workflows/ocor-rccad.yml` righe 293-294
  e `.github/workflows/ocor-delivery-activation.yml` righe 285-286), rifiuta il file:
  `FAIL: deploy/bootstrap/fuseki/config.ttl: extension '.ttl' has no authorized area for this path in
  OCOR_LANGUAGE_POLICY.md`. La riga 71 di `scripts/validate_language_policy.py` autorizza `.ttl` solo nelle
  sedi dei contratti dichiarativi di `is_declarative_contract_location` (righe 31-39:
  `ocor-runtime/schemas`, `ocor-runtime/docs/governance_dossier/contracts`, `reports/contracts`).
  Lo stesso rifiuto fa fallire `reports/tests/test_validate_language_policy.py`
  (`test_gate_passes_on_the_real_tracked_tree`, righe 78-86).
- La tabella normativa di `docs/development_methodology/OCOR_LANGUAGE_POLICY.md` (`DEC-212`) autorizza
  «RDF 1.1 Turtle» per i grafi RDF (riga 55, riga 14 della tabella) e SHACL Core per la validazione di grafo
  (riga 56, riga 15), senza limitarne la sede. La riga 51 (riga 10 della tabella) copre l'infrastruttura
  dello stack (Compose `deploy/**/compose.yaml`, Dockerfile, Kubernetes) e non nomina file di configurazione
  dei servizi. Il limite di sede di `.ttl` è solo nel validatore.
- Precedente: il task `OCOR-DEV-0081` (commit `8d76829`) ha esteso nello stesso change set le aree autorizzate
  di `scripts/validate_language_policy.py` per un nuovo file di `deploy/bootstrap/fixtures/`, senza modificare
  il documento della policy.
- Nessun ultimo record di evidenza dei task in `completed_evidence_tasks` ha fra gli input
  `scripts/validate_language_policy.py`, `reports/tests/test_validate_language_policy.py` o
  `docs/development_methodology/OCOR_LANGUAGE_POLICY.md` (calcolo con la selezione del record più recente di
  `scripts/validate_evidence_input_drift.py` su `main` `bfb2ca8`). Una modifica di quei file non fa derivare
  alcun record.
- Il `code_paths` di NCP-U05 (`reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`,
  `plan_units.NCP-U05.code_paths`) non comprende il validatore né il suo test; la regola della decisione
  `NCP-UNBINDABLE-REQUALIFICATIONS (2026-11-02)` punto 5 chiede una decision request per modificare un
  validatore.

## Opzioni

1. **Autorizzazione puntuale nel validatore (raccomandata).** NCP-U05 estende il proprio ambito a
   `scripts/validate_language_policy.py` e `reports/tests/test_validate_language_policy.py`. Nel validatore,
   la tupla di `".ttl"` (riga 71) riceve, solo per aggiunta, il predicato
   `lambda p: p == "deploy/bootstrap/fuseki/config.ttl"`: un solo percorso esatto, nessuna nuova area. Nel test,
   solo per aggiunta, `deploy/bootstrap/fuseki/config.ttl` entra in `POSITIVE_CASES` e
   `deploy/bootstrap/fuseki/other.ttl` e `deploy/bootstrap/config.ttl` in `NEGATIVE_CASES`, con RED/GREEN.
   `docs/development_methodology/OCOR_LANGUAGE_POLICY.md` resta invariato, perché la riga 14 della tabella già
   autorizza Turtle per un grafo RDF. Effetto: nessun record deriva, nessuna riqualifica aggiuntiva; il gate
   continua a rifiutare ogni altro `.ttl` fuori dalle sedi dei contratti.
2. **Autorizzazione puntuale nel validatore e nella tabella della policy.** Come l'opzione 1; in più la riga 10
   della tabella di `docs/development_methodology/OCOR_LANGUAGE_POLICY.md` (riga 51) nomina anche «configurazione
   dei servizi dello stack in RDF 1.1 Turtle (`deploy/bootstrap/fuseki/config.ttl`)». Effetto: tracciabilità
   esplicita nel documento di `DEC-212`, al prezzo di una modifica del testo normativo di quella decisione, che
   nessun'altra estensione di area ha finora richiesto; nessun record deriva.
3. **Configurazione nel Compose, senza file Turtle.** La configurazione entra in `deploy/bootstrap/compose.yaml`
   come `configs` di primo livello con `content` in linea, montata nel servizio `fuseki` allo stesso percorso;
   nessun `deploy/bootstrap/fuseki/config.ttl`. Cambia l'elemento «nuovo file» dell'opzione scelta in
   `NCP-U05-FUSEKI-SHACL-SERVICE`, richiede `configs.content` (Compose 2.23 o successivo) anche sui runner
   della CI, e porta un documento Turtle dentro un file YAML, fuori dal controllo per estensione del gate.
   Effetto: nessuna modifica del validatore; le stesse riqualifiche di sola regressione di `OCOR-DEV-0073`,
   `0074`, `0075`, `0077`, `0078` e `0079` già previste.

**Raccomandazione**: opzione 1. Mantiene esattamente l'opzione scelta in `NCP-U05-FUSEKI-SHACL-SERVICE`,
segue il precedente di `OCOR-DEV-0081`, è coerente con la riga 14 della tabella della policy, autorizza un solo
percorso e non fa derivare alcun record.

## Impatto e task bloccati

- Bloccati la candidatura di `OCOR-DEV-REM-0052` (PRE-CAMPAIGN-GATE, campagna, record, verifica, sigillo,
  merge) e, di conseguenza, le unità successive di `plan_order`, che attendono NCP-U05. Il resto del lavoro
  dell'unità (inventario dei consumer, lista delle riqualifiche, bozza del record, indice di tracciabilità
  inversa) prosegue.
- Nessun test esistente, limite, soglia, workflow, guard, contratto, schema o registro normativo cambia con le
  opzioni 1 e 3; con l'opzione 2 cambia solo il testo della riga 10 della tabella della policy. Claim
  invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.

## Disposition del Product Owner — 2026-11-05

Decisione del PO, su delega completa (`DELEGA-COMPLETA (2026-11-02)`), modello `claude-opus-5-5`, effort `xhigh`: `NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY (2026-11-05)`, **opzione 1** (autorizzazione puntuale nel validatore). Vale come decisione del PO a ogni effetto, di livello normativo. Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. La richiesta decisa è il file al commit `486d0603f02ea68db890d62225736bd7ff50fa6e`, sha256 `5afab32b9d908d3688c2e76df143532114333604d4d4c86461168be40f91d692` (verificata prima dell'attuazione). Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY (2026-11-05) — decisione del PO, su delega completa

Decisa su delega completa del PO secondo `DELEGA-COMPLETA (2026-11-02)`, con il modello `claude-opus-5-5` ed effort `xhigh` (scelta di `claude-opus-5-5` con effort `medium`, delicatezza ALTA). Il PO risolve la decision request `NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY` (branch `governed/decision-request-ncp-u05-fuseki-config-language-policy`, commit `486d0603f02ea68db890d62225736bd7ff50fa6e`, file `reports/development/decision_requests/NCP-U05-FUSEKI-CONFIG-LANGUAGE-POLICY.md`, sha256 `5afab32b9d908d3688c2e76df143532114333604d4d4c86461168be40f91d692`) adottando l'**opzione 1**.

1. Applica le opzioni scelte esattamente come descritte nel file indicato, a quel commit. Se il file che leggi a quel commit non ha quello sha256, non applicarle e apri una decision request.
2. Se l'attuazione richiede di andare oltre quanto le opzioni scelte descrivono esplicitamente, fermati e apri una decision request: la deciderà la stessa delega.
3. Registra la disposition nel file della decision request, nel registro `blockers` di `EXECUTION_STATE.json` (`po_decision` uguale a questa decisione, con la nota «decisa su delega completa del PO, modello claude-opus-5-5, effort xhigh») e nell'`ITERATION_LOG.md`, con lo stesso trattamento di una decisione del PO. Vale come decisione del PO a ogni effetto, anche dove una regola chiede una decisione del PO non presa su delega.
4. Le altre decisioni e regole vigenti restano invariate, salvo quanto le opzioni scelte cambiano esplicitamente.
