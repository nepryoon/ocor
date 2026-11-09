# NCP-U11-ADMISSION-QUOTA-COMPOSITION

Status: `DECIDED_BY_PO` (era `OPEN_PO_NORMATIVE_DECISION_REQUIRED`). Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0059`
(NCP-U11 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, memoria governata; branch
`governed/ocor-dev-rem-0059-ncp-u11-governed-memory`, candidato `3425a01a39c11780628ad3df513e9bf21a525427`) e la
voce `NCR-MEMORY-002` di `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Aperta secondo il punto 2 della
decisione `NCP-U11-REM0023-CONSUMER-GUARD (2026-11-09)` («Se l'attuazione richiede di andare oltre quanto le opzioni
scelte descrivono esplicitamente, fermati e apri una decision request»), il punto 1 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` e il punto 5 dello stesso piano («Fuori da questi casi, fermati e apri una
decision request»), e su indicazione esplicita del verdetto. Implementatore: Claude Code (Anthropic),
implementatore di riserva.

## Contesto

- Il verdetto indipendente `OCOR-DEV-REM-0059-3425a01a39c1-0` (Cursor, grok-4.7-high, xAI; creato il
  2026-11-09T10:30:35Z, head `3425a01a39c11780628ad3df513e9bf21a525427`) è `NO_GO` con il finding bloccante `VF-001` (gravità `high`): `docs/OCOR_LLD_v1.1.md` riga 206
  richiede che `admitMemory` verifichi la quota prima della scrittura atomica, ma
  `ocor-runtime/src/ocor_runtime/memory/model.py` righe 1487-1489 (al candidato) appende la versione ammessa e
  restituisce la receipt quando `self._quota is None`. `MemoryAdmissionQuota` è composta soltanto nel modulo
  dell'unità; il mondo di consolidamento sigillato `ocor-runtime/tests/tasks/test_ocor_dev_0054.py` righe 217-225
  costruisce `MemoryAdmissionService` senza quota e `ocor-runtime/src/ocor_runtime/memory/consolidation.py` riga 1544
  chiama `admission.admit`. Correzione richiesta: `admitMemory` fail-closed quando nessuna autorità di quota è
  composta, e `MemoryAdmissionQuota` composta su ogni percorso di ammissione, consolidamento compreso; «where
  NCP-U11-REM0023-CONSUMER-GUARD option 1 forbids the corresponding AST change in the sealed 0054/0055 worlds, stop and
  obtain a PO decision». Il secondo finding, `VF-002` (`medium`, celle N/A senza motivo nella tabella
  dell'autocontrollo), si corregge nel ciclo di riparazione e non richiede decisione.
- È il punto P1 della revisione preventiva `OCOR-DEV-REM-0059-90e47e872c3e-pre`, che l'unità aveva contestato in parte
  (default `quota=None` mantenuto per i mondi sigillati e protetti dal guard) e lasciato al verifier come punto aperto:
  il verifier lo ritiene bloccante.
- Nessun codice di produzione compone oggi `MemoryAdmissionService`: le sole costruzioni sono nei test. Al candidato
  la costruiscono senza quota nove punti di sei moduli sigillati:
  `test_ocor_dev_0050.py` righe 355 e 1013, `test_ocor_dev_0051.py` riga 227, `test_ocor_dev_0052.py` riga 282,
  `test_ocor_dev_0054.py` righe 217 e 402, `test_ocor_dev_0055.py` righe 177 e 1265, `test_ocor_dev_rem_0023.py`
  riga 77. Gli altri consumatori (0053, 0056-0059, 0061, REM-0020, REM-0021, REM-0036, REM-0050, REM-0053) usano questi
  mondi. Con la sola correzione del servizio (fail-closed) tutti questi mondi rifiutano ogni ammissione.
- `MemoryAdmissionQuota` (`operations.py` righe 580-607) richiede un metadata store, il ledger con inventario
  (`records()`), `MemoryOperationsLimits` e una `MemoryQuotaSerialization` (PostgreSQL in
  `test_ocor_dev_0059.py::PostgresSerializedQuota`; un lock locale al processo non qualifica, docstring righe 505-515).
  I mondi di 0051, 0052, 0054 e 0055 hanno metadata store PostgreSQL; quelli di 0050 e REM-0023 (che riusa 0050) sono
  mondi di sola ammissione, senza metadata store né PostgreSQL.
- L'adattamento della costruzione dei mondi rientra nel caso 3 del punto 5 del piano (fixture e precondizioni che
  l'unità cambia per un elemento normativo chiuso, senza RED, con il confronto dell'albero sintattico). Per 0054 e 0055
  però il guard `reports/tests/test_rem0023_consumer_fixture_scope.py`, come esteso dall'opzione 1 di
  `NCP-U11-REM0023-CONSUMER-GUARD`, ammette rispetto a `7cfb60d` soltanto il cablaggio di audit e la differenza della
  scelta del punto 5 sulle cancellazioni: l'argomento `quota=` e le istruzioni che costruiscono la quota sono una
  differenza in più, che il guard rifiuta e che l'opzione decisa non descrive. Inoltre il caso 3 non dice se in un
  mondo senza metadata store (0050, REM-0023) l'adattamento possa aggiungere un backend reale.
- Budget: iterazione 6 di stima 3 (stop a 9, `NCP-THROUGHPUT-RULES (2026-11-05)` punto 2). Il ciclo di riparazione 1
  richiede, dopo la decisione: RED/GREEN e adattamenti, autocontrollo, `PRE-CAMPAIGN-GATE`, revisione preventiva,
  campagna qualificante, verifica indipendente, sigillo e merge, cioè almeno tre iterazioni (7, 8 e 9) senza margine.

## Opzioni

Quesito A: come si compone l'autorità di quota su ogni percorso di ammissione. Quesito B: budget di iterazioni del
ciclo di riparazione.

### Opzioni del quesito A

A1. **Quota obbligatoria, quota reale nei mondi con metadata store, port di test esplicito negli altri
   (raccomandata).** `MemoryAdmissionService` richiede l'autorità di quota: senza di essa, o con un valore che non
   implementa `AdmissionQuotaAuthority`, `admitMemory` rifiuta con `CONTROL_PLANE_UNAVAILABLE`/`QUOTA_UNAVAILABLE`
   prima di qualsiasi scrittura (RED nel modulo dell'unità: ammissione e consolidamento senza quota rifiutano e non
   scrivono nulla). I mondi di 0051, 0052, 0054 e 0055 compongono `MemoryAdmissionQuota` sul proprio metadata store
   PostgreSQL e ledger, con `t59.PostgresSerializedQuota` e `MemoryOperationsLimits` non inferiori alla domanda che il
   mondo produce (nessun esito esistente cambia; il consolidamento di 0054 è contato all'ammissione); i mondi di sola
   ammissione di 0050 e REM-0023 compongono un port di quota di test esplicito che ammette e registra ogni
   `admission_hold`, come i port di policy e di autorità dei moduli G5 sigillati, senza nuovi backend. Adattamenti del
   caso 3 del punto 5: elenco delle funzioni di test, asserzioni, `pytest.raises` e parametrizzazioni invariati,
   registrati nel record con il confronto dell'albero sintattico. Il guard REM-0023 ammette inoltre, per 0054 e 0055,
   soltanto l'argomento `quota=` di ogni chiamata a `MemoryAdmissionService` e le istruzioni di costruzione della quota,
   confrontati byte per byte con testi fissati nel guard; casi negativi in più (quota tolta, limiti cambiati, un altro
   argomento cambiato fanno fallire il guard). Effetto: nessun percorso ammette senza quota; consolidamento coperto con
   la quota reale; guard stretto su tutto il resto.
A2. **Quota obbligatoria, port di test esplicito in tutti i mondi sigillati.** Come l'opzione A1, ma i nove punti
   compongono il port di test che ammette e registra; `MemoryAdmissionQuota` reale resta solo nel modulo dell'unità
   (consolidamento compreso, già provato da
   `test_ncr_memory_002_consolidation_output_is_counted_against_quota_at_admission`). Estensione del guard più piccola
   (un argomento e un'istruzione). Effetto: conformità del servizio identica; i consumatori sigillati non esercitano
   la quota reale.
A3. **Nessuna modifica dei mondi sigillati: quota facoltativa, divergenza residua.** Il default `quota=None` resta;
   `NCR-MEMORY-002` non passa a `IN_REMEDIATION` per il percorso predefinito e si apre una voce nuova `OPEN` del
   registro per la composizione obbligatoria. Effetto: `VF-001` resta aperto, la verifica successiva sarebbe
   prevedibilmente `NO_GO`, `OCOR-DEV-0062` (bloccato dalla voce) resta bloccato.

### Opzioni del quesito B

B1. **Quattro iterazioni oltre la nona (raccomandata).** Per `OCOR-DEV-REM-0059` sono autorizzate fino a quattro iterazioni oltre la nona (dalla
   decima alla tredicesima), solo per il ciclo di riparazione 1 di questo verdetto e, se una verifica `NO_GO` lo
   richiede, per il ciclo di riparazione 2; restano lo stop anticipato per due iterazioni consecutive senza
   avanzamento e il massimo di due cicli di riparazione (stesso modello di `NCP-U08-ITERATION-LIMIT (2026-11-06)`).
B2. **Nessuna estensione.** Nessuna estensione: se il ciclo non si chiude entro la nona iterazione, l'unità si ferma con una decision
   request di livello normativo.

## Raccomandazione

Opzione A1 e opzione B1. A1 chiude `VF-001` come richiesto dal verifier (nessuna ammissione senza quota, quota reale
sul percorso di consolidamento sigillato), usa per i mondi di sola ammissione lo stesso schema di port di test già
accettato nei moduli G5 senza aggiungere backend, e limita la nuova tolleranza del guard a testi fissati con casi
negativi. B1 evita uno stop prevedibile: il ciclo di riparazione richiede tre iterazioni piene dopo la decisione.

## Impatto e lavoro bloccato

- Bloccati in attesa della decisione: il GREEN di `VF-001` (il fail-closed rompe i nove mondi finché non sono
  adattati) e quindi gate, revisione preventiva, campagna e verifica del ciclo di riparazione 1 di
  `OCOR-DEV-REM-0059`; NCP-U12 e i lavori successivi restano in coda all'unità.
- Non bloccati: la correzione di `VF-002` (motivo di ogni cella N/A dell'autocontrollo) e la preparazione del RED.
- Riqualifiche: l'insieme delle undici riqualifiche di sola regressione non cambia (0050, 0051, 0052, 0054, 0055 e
  REM-0023 vi sono già), salvo quanto l'inventario sull'head finale aggiunge.
- Nessun nuovo `DEC-*`; ADD, LLD, contratti, schemi, registri normativi, limiti e claim invariati
  (`E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`).

## Disposition del Product Owner — 2026-11-09

Decisione normativa del PO: `NCP-U11-ADMISSION-QUOTA-COMPOSITION (2026-11-09)`, **opzioni A1 e B1**, come raccomandate e descritte in questo file al commit `f5f18e1581397b37601ee3f8b91cd5f666c56a86` (sha256 `38be32056d58182f7f85f6f74bcd4d56da14ffae91d8fb2ac1e127179fff2a41`, verificata prima dell'attuazione). Il testo integrale della decisione, riportato qui sotto senza modifiche salvo il livello del titolo, è la disposition di questa richiesta. Stato: `DECIDED_BY_PO`. Nessun nuovo `DEC-*`; claim invariati.

### NCP-U11-ADMISSION-QUOTA-COMPOSITION (2026-11-09) — decisione normativa del PO

Decisione **di livello normativo**, presa dal PO con istruzione esplicita il 2026-11-09. Il PO risolve la decision request `NCP-U11-ADMISSION-QUOTA-COMPOSITION` (branch `governed/decision-request-ncp-u11-admission-quota-composition`, commit `f5f18e1581397b37601ee3f8b91cd5f666c56a86`, file `reports/development/decision_requests/NCP-U11-ADMISSION-QUOTA-COMPOSITION.md`, sha256 `38be32056d58182f7f85f6f74bcd4d56da14ffae91d8fb2ac1e127179fff2a41`, draft PR #563) con le **opzioni A1 e B1**, come raccomandate e descritte in quel file a quel commit, senza condizioni aggiuntive. Il commit `f5f18e1581397b37601ee3f8b91cd5f666c56a86` riporta lo stesso contenuto del commit `a62a0d532410371ccec94e607c139212bc708af4` (sha256 `2acc58f2443ce228813329c1d1cd5415ca3961ea92d8983e830f6f5cec95bb48`), con il formato delle opzioni corretto: dove i due testi differiscono vale quello del commit `f5f18e1581397b37601ee3f8b91cd5f666c56a86`.

1. **Opzione A1.** Attua l'opzione A1 esattamente come la descrive il file: `admitMemory` rifiuta prima di qualsiasi scrittura quando l'autorità di quota manca o non è valida; `MemoryAdmissionQuota` reale nei mondi sigillati di 0051, 0052, 0054 e 0055, sul loro metadata store e ledger, con limiti non inferiori alla domanda di ogni mondo e nessun esito esistente cambiato; port di quota di test esplicito nei mondi di sola ammissione di 0050 e REM-0023, senza nuovi backend; adattamenti del caso 3 del punto 5 del piano, registrati con il confronto dell'albero sintattico; estensione del guard REM-0023 per 0054 e 0055 limitata ai testi fissati, con i casi negativi descritti. Dove questo riassunto e il file differiscono, vale il file. Ciò che l'opzione non descrive resta da decidere: fermati e apri una nuova decision request invece di estenderla.
2. **Opzione B1.** Per `OCOR-DEV-REM-0059` (NCP-U11) sono autorizzate fino a quattro iterazioni oltre la nona (dalla decima alla tredicesima), solo per il ciclo di riparazione 1 del verdetto `OCOR-DEV-REM-0059-3425a01a39c1-0` e, se una verifica `NO_GO` lo richiede, per il ciclo di riparazione 2. Restano lo stop anticipato per due iterazioni consecutive senza avanzamento (punto 2 di `NCP-THROUGHPUT-RULES (2026-11-05)`) e il massimo di due cicli di riparazione. Se le iterazioni finiscono senza merge, l'unità si ferma e apre una decision request di livello normativo con lo stato del lavoro.
3. **Registrazione.** Registra la disposition nel file della decision request, nel registro `blockers` di `EXECUTION_STATE.json` (`po_decision` uguale a questa decisione; `evidence` aggiornato al commit `f5f18e1581397b37601ee3f8b91cd5f666c56a86` e al suo sha256, con i valori completi come chiede `STATE-REGISTRY-FULL-COMMIT (2026-11-06)`) e nell'`ITERATION_LOG.md`, secondo la prassi e l'allowlist vigenti; chiudi la draft PR come risolta, come per le decisioni precedenti dell'unità. Negli state sync indica «iterazione N di stima 3, estensione fino alla tredicesima».
4. Nessun nuovo `DEC-*`. Oltre a quanto descrivono le opzioni A1 e B1, nessun test, guard, limite di tempo, soglia, workflow, contratto, schema o registro normativo cambia. Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e Production `NO-GO`.
