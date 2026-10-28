# REM-0040-C7-SEALED-RESULT-PORT

Status: `OPEN_PO_DECISION_REQUIRED`. Riguarda il perimetro di `OCOR-DEV-REM-0040`
(change set c della decisione normativa del PO `OCOR-DEV-0060-BA-SELECTED-COMPONENTS
(2026-10-26)`: adapter SeaweedFS di `C7` «dietro i port esistenti»). Nel runtime non
esiste un port di `C7` dietro cui collocare l'adapter. Nessuna variazione di limiti,
timeout, soglie, partizioni, casi, gate, contratti o schemi. Autorità corrente:
`OCOR-DEV-0060-BA-SELECTED-COMPONENTS (2026-10-26)`, punto 4 («Contratti, port, schemi e
semantica restano invariati. Se un adapter richiede di cambiarli, fermati e apri una
decision request»); `CC-OCOR-DELIVERY-COMPLETION` §7; DEC-210/211.

## Contesto

Il 2026-10-28, all'avvio di `OCOR-DEV-REM-0040` su `origin/main`
`d9fb92ce600d95e79c48d625ca0ce88ed53a6304`, l'inventario in sola lettura dei port di `C7`
ha dato il risultato descritto sotto. Non è stato scritto codice, né creato un branch di
change set, né eseguita una campagna. L'ID `OCOR-DEV-REM-0040` resta libero per il change
set: compare su tutti i ref soltanto come prossima azione pianificata.

Il precedente di `OCOR-DEV-REM-0039` (Temporal per `C6`) ha trovato port esistenti nel
codice (`kernel.governance.LeaseStatePort`, `c6.fsm.EffectSink`) e vi ha collocato
l'adapter senza cambiarli. Per `C7` questo non è possibile.

## Fatti

Baseline normativa:

- ADD v1.3 §4.2 (riga 2936 di `OCOR_ADD_v1.3_APPROVED_BASELINE.md`, sha256
  `dca9e218914a310ac53f92cded61ae29a40323b98daacb51028077d6c15cd2fb`) definisce il port
  vendor-neutral `ScenarioOverlayStore` con sei operazioni: `openSnapshot`,
  `forkScenario`, `appendOverlay`, `readAt`, `sealResult`, `discard`.
- ADD v1.3 riga 307: i branch di scenario di `VersionedAssertedState` (TerminusDB) sono
  scritti soltanto dall'adapter `ScenarioOverlayStore` di `C7`. Le operazioni di overlay
  (`openSnapshot`, `forkScenario`, `appendOverlay`, `readAt`, `discard`) appartengono
  quindi al backend dello stato asserito, cioè al change set d (`OCOR-DEV-REM-0041`,
  TerminusDB).
- ADD v1.3 riga 275: per `C7` lo «store S3-compatible content-addressed» e il «job ledger
  PostgreSQL» sono `CI` distinti. Riga 359, `BA-06`: «Content-addressing immutabile per
  `sealResult`; job ledger con budget, progress e cancellation»; test «di immutabilità
  post-`sealResult`» e «di cancellazione con verifica del rilascio».
- LLD v1.1 (sha256 `bd464bfef50dc5a5e1b7ffac389fdf12be57a3b545225a92cf1564dc6a01d219`):
  §2.7 elenca il package `ocor.c7.result`; riga 357 «C7: job cancellabile con resource
  release e sealed result»; riga 372, oracle `BA-06`: «S3/PostgreSQL sigilla causal
  result, lineage, identify-or-abstain e isolation».

Codice su `origin/main`:

- `ocor-runtime/src/ocor_runtime/c7/runtime.py` (sha256
  `618296ae3e490cb2170f1f330a7cc1e3a821795791203d5bfc88c194b32ce118`, task sigillato
  `OCOR-DEV-0045`) calcola `CausalOutcome` con `reproducibility_digest` in processo. Non
  dichiara alcun `Protocol` e non persiste nulla. Il suo unico consumer è
  `ocor-runtime/tests/tasks/test_ocor_dev_0045.py`.
- Nessun `ScenarioOverlayStore`, `sealResult` o equivalente esiste in
  `ocor-runtime/src/`.
- L'unico `Protocol` di `C7` è `c7_emission.EventSink` (`emit(event, idempotency_key)`),
  il confine dell'`EMISSION-FENCE` per gli eventi dell'outbox. Non riguarda i risultati
  causali, e collocarvi l'object store non realizzerebbe l'oracle di `BA-06`.
- `memory.stores.MemoryContentStore` (riga 579) è un port content-addressed di `C8`, non
  di `C7`. Espone `delete` (riga 588), incompatibile con un oggetto sigillato immutabile.
- Nessun port di job ledger di `C7` esiste. Il job ledger PostgreSQL di `BA-06` non è nel
  perimetro di `OCOR-DEV-REM-0040` (adapter SeaweedFS): in `OCOR-DEV-0060` resta da
  qualificare sul PostgreSQL esistente.
- Stack: SeaweedFS è già nello stack di bootstrap a 15 container (`OCOR-DEV-REM-0038`,
  immagine `chrislusf/seaweedfs@sha256:f7a49e3f3972ebed5be2ed4befa4a0c68eb7bdddba6e692d42729ceb545134b8`),
  con il probe Object Lock in modalità `COMPLIANCE` di
  `deploy/bootstrap/services/seaweedfs/qualify.py`, che firma le richieste SigV4 con la sola
  libreria standard.
- `ocor-runtime/uv.lock` non contiene client S3.

Conseguenza: qualunque adapter SeaweedFS di `C7` richiede di introdurre nel codice un port
che oggi non esiste. Il punto 4 della decisione lo vieta senza una decisione del PO.

## Opzioni

1. **Sotto-port `sealResult` di `ScenarioOverlayStore`, con l'adapter SeaweedFS dietro.**
   - In `ocor-runtime/src/ocor_runtime/c7/` si aggiunge un `Protocol` che riproduce la sola
     operazione `sealResult` di ADD v1.3 §4.2, più la lettura del risultato sigillato per
     digest (la parte di `readAt` che riguarda i risultati). Ha nomi e docstring che citano
     §4.2. Le operazioni di overlay restano fuori, per il change set d (TerminusDB).
   - L'adapter SeaweedFS scrive il `CausalOutcome` canonico sotto una chiave derivata dal
     `reproducibility_digest`, in un bucket con Object Lock e versioning attivi, con
     retention `COMPLIANCE` come nel probe di REM-0038. A ogni lettura ricalcola e verifica
     il digest. Sul percorso applicativo non esistono `DeleteObject` né l'header di bypass
     della retention. Un secondo sigillo con lo stesso digest e contenuto identico è
     idempotente; con contenuto diverso è rifiutato.
   - `c7/runtime.py`, `CausalOutcome`, i reason code, i contratti e gli schemi restano
     invariati. Riqualifiche attese dall'inventario: nessuna sostanziale, soltanto quelle di
     sola regressione per l'allowlist del piano (`OCOR-DEV-0005`, `0050`, `0082`).
   - Client S3 con firma SigV4 sulla sola libreria standard, come `qualify.py`: nessuna
     nuova dipendenza Python e `uv.lock` invariato.
   - RED e GREEN su SeaweedFS reale, compresi i casi negativi (cancellazione e
     sovrascrittura negate, digest manomesso rifiutato, bucket senza Object Lock rifiutato
     all'avvio).
2. **Port completo `ScenarioOverlayStore` in `C7`.** Si introduce il `Protocol` con tutte e
   sei le operazioni di §4.2. In REM-0040 l'adapter SeaweedFS implementa `sealResult` e la
   lettura dei risultati. Le operazioni di overlay restano senza implementazione reale fino
   a REM-0041, oppure vengono realizzate su object store in REM-0040. Nel primo caso il port
   resta parzialmente non implementato. Nel secondo, l'overlay va su un backend diverso da
   quello indicato alla riga 307 dell'ADD.
3. **Nessun port nuovo: REM-0040 sospesa.** `BA-06` resta `NOT_EXECUTED` per componente
   senza adapter. `OCOR-DEV-0060` non può entrare in `completed_evidence_tasks` finché il PO
   non decide un'altra strada. Si prosegue con `OCOR-DEV-REM-0041` e con
   `OCOR-DEV-0062`–`0064`.

## Raccomandazione

Opzione 1. Realizza nel codice l'operazione già approvata in ADD v1.3 §4.2 che `BA-06`
esercita, senza cambiare `c7/runtime.py`, contratti, schemi o semantica. Lascia le
operazioni di overlay al backend che l'ADD assegna loro (TerminusDB, change set d) e non
aggiunge dipendenze né riqualifiche sostanziali.

## Impatto

- Bloccato fino alla decisione: `OCOR-DEV-REM-0040`. Resta bloccato anche
  `OCOR-DEV-0060`, che attende comunque l'integrazione di REM-0038–0041.
- Non bloccati: `OCOR-DEV-REM-0041` (adapter TerminusDB di `C3`, prossima unità
  nell'ordine vigente), `OCOR-DEV-0062`, `0063`, `0064`.
- Con l'opzione 1 la suite completa, la CI e il verifier restano invariati, salvo i casi
  nuovi del modulo del task.
- SeaweedFS resta `Candidate Implementation` fino alla qualifica di `OCOR-DEV-0060`.
- Claim invariati: `E1=0`, `E2=0`, `Verified=0`, runtime `NOT_ESTABLISHED`, PoC e
  Production `NO-GO`. Nessun nuovo `DEC-*`.
