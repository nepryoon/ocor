# NCP-U11-ADMISSION-QUOTA-COMPOSITION

Status: `OPEN_PO_NORMATIVE_DECISION_REQUIRED`. Livello: normativo. Riguarda l'unità `OCOR-DEV-REM-0059`
(NCP-U11 di `NORMATIVE-CONFORMANCE-PLAN (2026-10-30)`, memoria governata; branch
`governed/ocor-dev-rem-0059-ncp-u11-governed-memory`, candidato `3425a01a39c11780628ad3df513e9bf21a525427`) e la
voce `NCR-MEMORY-002` di `reports/development/NORMATIVE_CONFORMANCE_REGISTER.json`. Aperta secondo il punto 2 della
decisione `NCP-U11-REM0023-CONSUMER-GUARD (2026-11-09)` («Se l'attuazione richiede di andare oltre quanto le opzioni
scelte descrivono esplicitamente, fermati e apri una decision request»), il punto 1 di
`NORMATIVE-CONFORMANCE-PLAN (2026-10-30)` e il punto 5 dello stesso piano («Fuori da questi casi, fermati e apri una
decision request»), e su indicazione esplicita del verdetto. Implementatore: Claude Code (Anthropic),
implementatore di riserva del loop.

## Contesto

- Il verdetto indipendente `OCOR-DEV-REM-0059-3425a01a39c1-0` (Cursor, grok-4.7-high, xAI; `~/.ocor-codex/verdicts/`,
  2026-11-09T10:30:35Z) è `NO_GO` con il finding bloccante `VF-001` (gravità `high`): `docs/OCOR_LLD_v1.1.md` riga 206
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

## Quesito A — composizione della quota

1. **Quota obbligatoria, quota reale nei mondi con metadata store, port di test esplicito negli altri
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
2. **Quota obbligatoria, port di test esplicito in tutti i mondi sigillati.** Come l'opzione 1, ma i nove punti
   compongono il port di test che ammette e registra; `MemoryAdmissionQuota` reale resta solo nel modulo dell'unità
   (consolidamento compreso, già provato da
   `test_ncr_memory_002_consolidation_output_is_counted_against_quota_at_admission`). Estensione del guard più piccola
   (un argomento e un'istruzione). Effetto: conformità del servizio identica; i consumatori sigillati non esercitano
   la quota reale.
3. **Nessuna modifica dei mondi sigillati: quota facoltativa, divergenza residua.** Il default `quota=None` resta;
   `NCR-MEMORY-002` non passa a `IN_REMEDIATION` per il percorso predefinito e si apre una voce nuova `OPEN` del
   registro per la composizione obbligatoria. Effetto: `VF-001` resta aperto, la verifica successiva sarebbe
   prevedibilmente `NO_GO`, `OCOR-DEV-0062` (bloccato dalla voce) resta bloccato.

## Quesito B — iterazioni

1. **B1 (raccomandata).** Per `OCOR-DEV-REM-0059` sono autorizzate fino a quattro iterazioni oltre la nona (dalla
   decima alla tredicesima), solo per il ciclo di riparazione 1 di questo verdetto e, se una verifica `NO_GO` lo
   richiede, per il ciclo di riparazione 2; restano lo stop anticipato per due iterazioni consecutive senza
   avanzamento e il massimo di due cicli di riparazione (stesso modello di `NCP-U08-ITERATION-LIMIT (2026-11-06)`).
2. **B2.** Nessuna estensione: se il ciclo non si chiude entro la nona iterazione, l'unità si ferma con una decision
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
